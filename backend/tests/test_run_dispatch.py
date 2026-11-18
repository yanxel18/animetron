import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from test_execution_readiness import _binding, _manifest
from test_run_revisions import save

from app.core.database import create_database_engine
from app.core.outbox import metadata as outbox_metadata
from app.core.outbox import outbox
from app.services.models.manifest import ModelManifest
from app.services.workflows import (
    execution_readiness,
    run_cancellations,
    run_dispatch,
    run_requests,
)
from app.services.workflows.execution_readiness import ReadyModel, ResolvedHandler
from app.services.workflows.runs import (
    RunConflict,
    RunState,
    get_run_status,
    list_events,
)
from app.services.workflows.validation import GraphLimits

pytest_plugins = ("test_execution_readiness",)


@pytest.fixture
def dispatchable_run(queued_run):
    engine, run_id, workflow_id, revision = queued_run
    outbox_metadata.create_all(engine)
    run_dispatch.metadata.create_all(engine)
    return engine, run_id, workflow_id, revision


class AllHandlers:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, artifact_id: str) -> ResolvedHandler:
        self.calls.append(artifact_id)
        return ResolvedHandler(artifact_id, "d" * 64, object())


class ReadyModels:
    def resolve(self, manifest: ModelManifest) -> ReadyModel:
        return ReadyModel(manifest, object())


def _counts(connection, run_id):
    return (
        connection.scalar(
            select(func.count())
            .select_from(run_dispatch.node_intents)
            .where(run_dispatch.node_intents.c.run_id == run_id)
        ),
        connection.scalar(
            select(func.count())
            .select_from(outbox)
            .where(outbox.c.resource_id == run_id)
        ),
    )


def test_ready_run_persists_node_intents_and_one_dispatch_outbox_atomically(
    dispatchable_run, monkeypatch
):
    engine, run_id, workflow_id, revision = dispatchable_run
    binding = _binding(
        workflow_id,
        revision,
        _manifest(),
        ("node-1", "node-2", "node-3"),
        (("node-2", "node-3"), ("node-1", "node-3")),
    )
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )
    handlers = AllHandlers()

    with engine.begin() as connection:
        result = run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            handlers,
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.outcome is run_dispatch.DispatchOutcome.PREPARED
    assert result.readiness is not None and result.readiness.ready
    assert result.node_count == 3
    assert [node_id for node_id, _ in result.readiness.node_dependencies] == [
        "node-1",
        "node-2",
        "node-3",
    ]
    with engine.begin() as connection:
        nodes = connection.execute(
            select(
                run_dispatch.node_intents.c.node_id,
                run_dispatch.node_intents.c.dependencies,
            )
            .where(run_dispatch.node_intents.c.run_id == run_id)
            .order_by(run_dispatch.node_intents.c.node_id)
        ).all()
        assert [(row.node_id, row.dependencies) for row in nodes] == [
            ("node-1", []),
            ("node-2", []),
            ("node-3", ["node-1", "node-2"]),
        ]
        intents = connection.execute(
            select(outbox.c.topic, outbox.c.resource_id)
            .where(outbox.c.resource_id == run_id)
        ).all()
        assert [tuple(intent) for intent in intents] == [
            (run_dispatch.RUN_READY_TOPIC, run_id)
        ]
        assert get_run_status(connection, run_id).state is RunState.RUNNING

        before = _counts(connection, run_id)
        replay = run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            handlers,
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )
        assert replay.outcome is run_dispatch.DispatchOutcome.ALREADY_PREPARED
        assert replay.readiness is None
        assert _counts(connection, run_id) == before

    assert len(handlers.calls) == 3


def test_unready_later_node_fails_before_persisting_any_dispatch_intents(
    dispatchable_run, monkeypatch
):
    engine, run_id, workflow_id, revision = dispatchable_run
    binding = _binding(
        workflow_id, revision, _manifest(), ("node-1", "node-2")
    )
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )

    class FirstHandlerOnly:
        def resolve(self, artifact_id: str) -> ResolvedHandler | None:
            if artifact_id == "handler-v1":
                return ResolvedHandler(artifact_id, "d" * 64, object())
            return None

    with engine.begin() as connection:
        result = run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            FirstHandlerOnly(),
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.outcome is run_dispatch.DispatchOutcome.FAILED
    assert result.readiness is not None
    assert (
        result.readiness.failure_code
        is execution_readiness.ReadinessFailureCode.HANDLER_NOT_READY
    )
    with engine.begin() as connection:
        assert _counts(connection, run_id) == (0, 0)
        assert get_run_status(connection, run_id).state is RunState.FAILED


def test_outer_rollback_removes_node_intents_and_dispatch_outbox(
    dispatchable_run, monkeypatch
):
    engine, run_id, workflow_id, revision = dispatchable_run
    binding = _binding(workflow_id, revision, _manifest())
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        result = run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            AllHandlers(),
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )
        assert result.outcome is run_dispatch.DispatchOutcome.PREPARED
        raise RuntimeError("abort")

    with engine.begin() as connection:
        assert _counts(connection, run_id) == (0, 0)
        assert get_run_status(connection, run_id).state is RunState.QUEUED


def test_committed_cancellation_prevents_later_dispatch_preparation(
    dispatchable_run, monkeypatch
):
    engine, run_id, workflow_id, revision = dispatchable_run
    binding = _binding(workflow_id, revision, _manifest())
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
    )
    handlers = AllHandlers()

    with engine.begin() as connection:
        cancellation = run_cancellations.request_run_cancellation(connection, run_id)

    with pytest.raises(RunConflict), engine.begin() as connection:
        run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            handlers,
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    with engine.begin() as connection:
        retry = run_cancellations.request_run_cancellation(connection, run_id)
        status = get_run_status(connection, run_id)
        events = list_events(connection, run_id, 0)
        topics = connection.execute(
            select(outbox.c.topic).where(outbox.c.resource_id == run_id)
        ).scalars().all()
        node_count = connection.scalar(
            select(func.count()).select_from(run_dispatch.node_intents).where(
                run_dispatch.node_intents.c.run_id == run_id
            )
        )

    assert cancellation.outcome is run_cancellations.CancellationOutcome.REQUESTED
    assert retry.outcome is run_cancellations.CancellationOutcome.ALREADY_REQUESTED
    assert status.state is RunState.CANCELLING
    assert status.last_sequence == 2
    assert [event.state for event in events] == [RunState.QUEUED, RunState.CANCELLING]
    assert topics == [run_cancellations.CANCELLATION_TOPIC]
    assert node_count == 0
    assert handlers.calls == []


@pytest.mark.parametrize("first_operation", ["cancel", "dispatch"])
def test_dispatch_and_cancellation_serialize_on_postgresql(first_operation, monkeypatch):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    workflow_id = uuid4()
    contender_pid = Queue()
    handlers = AllHandlers()
    try:
        with engine.begin() as connection:
            snapshot = save(connection, workflow_id)
            request = run_requests.request_run(
                connection, uuid4(), workflow_id, "rev1", snapshot.sha256,
            )
        run_id = request.run_id
        binding = replace(
            _binding(workflow_id, "rev1", _manifest()), source_sha256=snapshot.sha256,
        )
        monkeypatch.setattr(
            execution_readiness, "get_execution_binding", lambda *_args: binding,
        )

        def execute(connection, operation):
            if operation == "cancel":
                return run_cancellations.request_run_cancellation(connection, run_id)
            return run_dispatch.prepare_run_dispatch(
                connection, run_id, handlers, ReadyModels(),
                GraphLimits(max_nodes=8, max_edges=8), max_bytes=4096,
            )

        def contender():
            try:
                with engine.begin() as connection:
                    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                    contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
                    operation = "dispatch" if first_operation == "cancel" else "cancel"
                    return execute(connection, operation)
            except RunConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
            transaction = winner.begin()
            try:
                winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
                first = execute(winner, first_operation)
                future = pool.submit(contender)
                pid = contender_pid.get(timeout=5)
                deadline = time.monotonic() + 5
                with engine.connect() as observer:
                    while time.monotonic() < deadline:
                        blockers = observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                        )
                        if winner_pid in blockers:
                            break
                        time.sleep(0.02)
                    else:
                        pytest.fail("Contender never waited on the first transaction")
                assert not future.done()
                transaction.commit()
            finally:
                if transaction.is_active:
                    transaction.rollback()
            second = future.result(timeout=10)

        with engine.begin() as connection:
            status = get_run_status(connection, run_id)
            events = list_events(connection, run_id, 0)
            topics = connection.execute(
                select(outbox.c.topic).where(outbox.c.resource_id == run_id)
            ).scalars().all()
            node_count = connection.scalar(
                select(func.count()).select_from(run_dispatch.node_intents).where(
                    run_dispatch.node_intents.c.run_id == run_id
                )
            )
    finally:
        engine.dispose()

    assert status.state is RunState.CANCELLING
    assert topics.count(run_requests.INTERNAL_TOPIC) == 1
    assert topics.count(run_cancellations.CANCELLATION_TOPIC) == 1
    if first_operation == "cancel":
        assert first.outcome is run_cancellations.CancellationOutcome.REQUESTED
        assert second == "conflict"
        assert [event.state for event in events] == [RunState.QUEUED, RunState.CANCELLING]
        assert topics.count(run_dispatch.RUN_READY_TOPIC) == 0
        assert node_count == 0
        assert handlers.calls == []
        assert len(topics) == 2
    else:
        assert first.outcome is run_dispatch.DispatchOutcome.PREPARED
        assert second.outcome is run_cancellations.CancellationOutcome.REQUESTED
        assert [event.state for event in events] == [
            RunState.QUEUED, RunState.RUNNING, RunState.CANCELLING,
        ]
        assert topics.count(run_dispatch.RUN_READY_TOPIC) == 1
        assert node_count == 1
        assert len(topics) == 3


def test_dispatch_topic_is_distinct_from_non_executable_run_request():
    assert run_dispatch.RUN_READY_TOPIC != "internal.workflow-run-requested.v1"


def test_dispatch_requires_a_caller_owned_transaction(dispatchable_run):
    engine, run_id, *_ = dispatchable_run
    with engine.connect() as connection, pytest.raises(
        RuntimeError, match="explicit transaction"
    ):
        run_dispatch.prepare_run_dispatch(
            connection,
            run_id,
            AllHandlers(),
            ReadyModels(),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )
