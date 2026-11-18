import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from test_execution_bindings import bind
from test_execution_bindings import save as save_execution
from test_execution_readiness import HandlerCatalog, ModelRegistry, _binding, _manifest
from test_execution_snapshot import LIMITS, MANIFEST
from test_run_dispatch import AllHandlers, ReadyModels
from test_run_revisions import save

from app.core.database import create_database_engine
from app.core.outbox import enqueue, outbox
from app.services.workflows import (
    execution_bindings,
    execution_readiness,
    node_admission,
    node_outcomes,
    node_revalidation,
    run_cancellations,
    run_dispatch,
    run_requests,
)
from app.services.workflows.runs import (
    RunConflict,
    RunState,
    create_run,
    get_run_status,
    list_events,
    transition_run,
)
from app.services.workflows.validation import GraphLimits


@pytest.fixture
def prepared_run(monkeypatch):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable PostgreSQL harness")
    engine = create_database_engine(url)
    workflow_id = uuid4()
    try:
        with engine.begin() as connection:
            snapshot = save(connection, workflow_id)
            request = run_requests.request_run(
                connection, uuid4(), workflow_id, "rev1", snapshot.sha256,
            )
        binding = replace(
            _binding(
                workflow_id, "rev1", _manifest(), ("node-1", "node-2"),
                (("node-1", "node-2"),),
            ),
            source_sha256=snapshot.sha256,
        )
        monkeypatch.setattr(execution_readiness, "get_execution_binding", lambda *_: binding)
        with engine.begin() as connection:
            run_dispatch.prepare_run_dispatch(
                connection, request.run_id, AllHandlers(), ReadyModels(),
                GraphLimits(max_nodes=8, max_edges=8), max_bytes=4096,
            )
        yield engine, request.run_id
    finally:
        engine.dispose()


def claim(connection, claim_id, run_id, node_id="node-1"):
    return node_admission.claim_node(connection, claim_id, run_id, node_id)


def count_claims(connection, run_id):
    return connection.scalar(
        select(func.count()).select_from(node_admission.claims).where(
            node_admission.claims.c.run_id == run_id,
        )
    )


@pytest.mark.parametrize(
    ("claim_id", "node_id"),
    [(UUID(int=0), "node-1"), (uuid4(), ""), (uuid4(), "n" * 129), (uuid4(), "n\0")],
)
def test_invalid_claim_inputs_do_not_write(prepared_run, claim_id, node_id):
    engine, run_id = prepared_run
    with engine.begin() as connection:
        with pytest.raises(ValueError):
            claim(connection, claim_id, run_id, node_id)
        assert count_claims(connection, run_id) == 0


def test_claim_requires_caller_owned_transaction(prepared_run):
    engine, run_id = prepared_run
    with engine.connect() as connection, pytest.raises(RuntimeError, match="transaction"):
        claim(connection, uuid4(), run_id)


def test_claim_replay_and_conflicting_identity(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        first = claim(connection, claim_id, run_id)
        replay = claim(connection, claim_id, run_id)
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, claim_id, run_id, "node-2")
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, uuid4(), run_id)
        assert count_claims(connection, run_id) == 1
    assert first.outcome is node_admission.AdmissionOutcome.CLAIMED
    assert replay.outcome is node_admission.AdmissionOutcome.ALREADY_CLAIMED
    assert (replay.claim_id, replay.run_id, replay.node_id) == (claim_id, run_id, "node-1")


def test_only_planned_root_nodes_are_eligible(prepared_run):
    engine, run_id = prepared_run
    with engine.begin() as connection:
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, uuid4(), run_id, "node-2")
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, uuid4(), run_id, "missing")
        assert count_claims(connection, run_id) == 0


def test_missing_run_ready_evidence_fails_closed(prepared_run):
    engine, run_id = prepared_run
    with engine.begin() as connection:
        connection.execute(delete(outbox).where(outbox.c.id == run_dispatch._outbox_id(run_id)))
        with pytest.raises(run_dispatch.RunDispatchCorrupt):
            claim(connection, uuid4(), run_id)
        assert count_claims(connection, run_id) == 0


def test_failed_insert_is_rolled_back_when_caller_commits(prepared_run):
    engine, run_id = prepared_run
    with engine.begin() as connection:
        def fail_after_insert(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("INSERT INTO workflow_node_claims"):
                raise RuntimeError("injected failure")

        event.listen(connection, "after_cursor_execute", fail_after_insert)
        try:
            with pytest.raises(RuntimeError, match="injected failure"):
                claim(connection, uuid4(), run_id)
        finally:
            event.remove(connection, "after_cursor_execute", fail_after_insert)
        assert connection.scalar(text("SELECT 1")) == 1
        assert count_claims(connection, run_id) == 0
    with engine.connect() as connection:
        assert count_claims(connection, run_id) == 0


def test_outer_rollback_and_caught_failure_leave_no_partial_claim(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        claim(connection, claim_id, run_id)
        raise RuntimeError("abort")
    with engine.begin() as connection:
        assert count_claims(connection, run_id) == 0
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, uuid4(), run_id, "node-2")
        assert connection.scalar(text("SELECT 1")) == 1
    with engine.begin() as connection:
        assert count_claims(connection, run_id) == 0
        assert claim(connection, claim_id, run_id).outcome is node_admission.AdmissionOutcome.CLAIMED


def test_replay_survives_cancellation_without_allowing_new_claim(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        run_cancellations.request_run_cancellation(connection, run_id)
    with engine.begin() as connection:
        assert claim(connection, claim_id, run_id).outcome is node_admission.AdmissionOutcome.ALREADY_CLAIMED
        with pytest.raises(RunConflict):
            claim(connection, uuid4(), run_id, "node-2")
        assert count_claims(connection, run_id) == 1


@pytest.mark.parametrize("same_identity", [True, False])
def test_concurrent_claims_serialize_and_cannot_double_admit(prepared_run, same_identity):
    engine, run_id = prepared_run
    first_id = uuid4()
    second_id = first_id if same_identity else uuid4()
    contender_pid = Queue()

    def contender():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
            try:
                return claim(connection, second_id, run_id)
            except node_admission.AdmissionConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
        transaction = winner.begin()
        try:
            winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
            first = claim(winner, first_id, run_id)
            future = pool.submit(contender)
            pid = contender_pid.get(timeout=5)
            deadline = time.monotonic() + 5
            with engine.connect() as observer:
                while time.monotonic() < deadline:
                    if winner_pid in observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                    ):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Claim contender never waited on the first transaction")
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        second = future.result(timeout=10)

    assert first.outcome is node_admission.AdmissionOutcome.CLAIMED
    if same_identity:
        assert second.outcome is node_admission.AdmissionOutcome.ALREADY_CLAIMED
    else:
        assert second == "conflict"
    with engine.connect() as connection:
        assert count_claims(connection, run_id) == 1


def test_same_identity_concurrently_used_for_different_runs_conflicts(prepared_run):
    engine, run_id = prepared_run
    other_run, claim_id = uuid4(), uuid4()
    contender_pid = Queue()
    with engine.begin() as connection:
        create_run(connection, other_run)
        connection.execute(insert(run_dispatch.node_intents).values(
            run_id=other_run, node_id="node-1", dependencies=[],
        ))
        enqueue(connection, run_dispatch._outbox_id(other_run), run_dispatch.RUN_READY_TOPIC, other_run)
        transition_run(connection, other_run, 1, RunState.RUNNING, "Prepared")

    def contender():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
            with pytest.raises(node_admission.AdmissionConflict):
                claim(connection, claim_id, other_run)
            assert connection.scalar(text("SELECT 1")) == 1

    with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
        transaction = winner.begin()
        try:
            winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
            claim(winner, claim_id, run_id)
            future = pool.submit(contender)
            pid = contender_pid.get(timeout=5)
            deadline = time.monotonic() + 5
            with engine.connect() as observer:
                while time.monotonic() < deadline:
                    if winner_pid in observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                    ):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Conflicting identity never waited on the first transaction")
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        future.result(timeout=10)
    with engine.connect() as connection:
        assert count_claims(connection, run_id) == 1
        assert count_claims(connection, other_run) == 0


@pytest.mark.parametrize("first_operation", ["cancel", "claim"])
def test_cancellation_and_claim_serialize(prepared_run, first_operation):
    engine, run_id = prepared_run
    claim_id = uuid4()
    contender_pid = Queue()

    def execute(connection, operation):
        if operation == "cancel":
            return run_cancellations.request_run_cancellation(connection, run_id)
        return claim(connection, claim_id, run_id)

    def contender():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
            try:
                return execute(connection, "claim" if first_operation == "cancel" else "cancel")
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
                    if winner_pid in observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                    ):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Cancellation contender never waited on the winner")
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        second = future.result(timeout=10)

    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.CANCELLING
        assert count_claims(connection, run_id) == (0 if first_operation == "cancel" else 1)
    if first_operation == "cancel":
        assert first.outcome is run_cancellations.CancellationOutcome.REQUESTED
        assert second == "conflict"
    else:
        assert first.outcome is node_admission.AdmissionOutcome.CLAIMED
        assert second.outcome is run_cancellations.CancellationOutcome.REQUESTED


def test_confirmed_outcome_replay_and_conflicts(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        first = node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
        replay = node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
        assert first.recorded is True
        assert replay.recorded is False
        with pytest.raises(node_outcomes.OutcomeConflict):
            node_outcomes.record_outcome(
                connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.FAILED,
                node_outcomes.FailureCode.EXECUTION_FAILED,
            )
        with pytest.raises(node_outcomes.OutcomeConflict):
            node_outcomes.record_outcome(
                connection, claim_id, run_id, "node-2", node_outcomes.NodeStatus.SUCCEEDED,
            )
        with pytest.raises(node_outcomes.OutcomeConflict):
            node_outcomes.record_outcome(
                connection, uuid4(), run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
            )
        assert connection.scalar(
            select(func.count()).select_from(node_outcomes.outcomes)
            .where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == 1
        assert get_run_status(connection, run_id).state is RunState.RUNNING
        with pytest.raises(node_admission.AdmissionConflict):
            claim(connection, uuid4(), run_id, "node-2")


def test_outcome_input_validation_and_transaction(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.connect() as connection, pytest.raises(RuntimeError, match="transaction"):
        node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        for status, code in [
            (node_outcomes.NodeStatus.FAILED, None),
            (node_outcomes.NodeStatus.SUCCEEDED, node_outcomes.FailureCode.EXECUTION_FAILED),
            (node_outcomes.NodeStatus.FAILED, "arbitrary sensitive error"),
            ("UNKNOWN", None),
        ]:
            with pytest.raises(ValueError):
                node_outcomes.record_outcome(connection, claim_id, run_id, "node-1", status, code)
        assert connection.scalar(
            select(func.count()).select_from(node_outcomes.outcomes)
            .where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == 0


def test_confirmed_failure_replay(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        first = node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.FAILED,
            node_outcomes.FailureCode.EXECUTION_FAILED,
        )
        replay = node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.FAILED,
            node_outcomes.FailureCode.EXECUTION_FAILED,
        )
        assert first.recorded is True
        assert replay.recorded is False
        assert replay.error_code is node_outcomes.FailureCode.EXECUTION_FAILED


def test_outcome_failure_savepoint_and_outer_rollback(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
    with engine.begin() as connection:
        def fail_after_insert(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("INSERT INTO workflow_node_outcomes"):
                raise RuntimeError("injected failure")

        event.listen(connection, "after_cursor_execute", fail_after_insert)
        try:
            with pytest.raises(RuntimeError, match="injected failure"):
                node_outcomes.record_outcome(
                    connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
                )
        finally:
            event.remove(connection, "after_cursor_execute", fail_after_insert)
        assert connection.scalar(text("SELECT 1")) == 1
        assert connection.scalar(
            select(func.count()).select_from(node_outcomes.outcomes)
            .where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == 0
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
        raise RuntimeError("abort")
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(node_outcomes.outcomes)
            .where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == 0


@pytest.mark.parametrize("first_operation", ["cancel", "outcome", "competing"])
def test_outcome_serialization_and_late_recording(prepared_run, first_operation):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
    contender_pid = Queue()

    def execute(connection, operation):
        if operation == "cancel":
            return run_cancellations.request_run_cancellation(connection, run_id)
        if operation == "competing":
            return node_outcomes.record_outcome(
                connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.FAILED,
                node_outcomes.FailureCode.EXECUTION_FAILED,
            )
        return node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )

    def contender():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
            try:
                return execute(connection, "cancel" if first_operation == "outcome" else "outcome")
            except node_outcomes.OutcomeConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
        transaction = winner.begin()
        try:
            winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
            execute(winner, first_operation)
            future = pool.submit(contender)
            pid = contender_pid.get(timeout=5)
            deadline = time.monotonic() + 5
            with engine.connect() as observer:
                while time.monotonic() < deadline:
                    if winner_pid in observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                    ):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Outcome contender never waited on the first transaction")
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        result = future.result(timeout=10)

    with engine.connect() as connection:
        row = connection.execute(
            select(node_outcomes.outcomes).where(node_outcomes.outcomes.c.claim_id == claim_id)
        ).one()
        assert row.status == ("FAILED" if first_operation == "competing" else "SUCCEEDED")
        assert get_run_status(connection, run_id).state is (
            RunState.RUNNING if first_operation == "competing" else RunState.CANCELLING
        )
    if first_operation == "competing":
        assert result == "conflict"
    elif first_operation == "cancel":
        assert result.recorded is True


def test_outcome_database_rejects_mutation_and_invalid_codes(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(node_outcomes.outcomes.insert().values(
                claim_id=claim_id, status="FAILED", error_code="raw exception",
            ))
        node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
        for statement in (
            node_outcomes.outcomes.update().where(node_outcomes.outcomes.c.claim_id == claim_id)
            .values(status="FAILED", error_code="EXECUTION_FAILED"),
            node_outcomes.outcomes.delete().where(node_outcomes.outcomes.c.claim_id == claim_id),
        ):
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(statement)
        assert connection.scalar(
            select(node_outcomes.outcomes.c.status).where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == "SUCCEEDED"


def revalidate(connection, claim_id, run_id, handlers=None, models=None):
    return node_revalidation.revalidate_admitted_node(
        connection, claim_id, run_id, "node-1",
        handlers if handlers is not None else AllHandlers(),
        models if models is not None else ReadyModels(),
        GraphLimits(max_nodes=8, max_edges=8), max_bytes=4096,
    )


def test_revalidation_uses_persisted_execution_binding():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable PostgreSQL harness")
    engine = create_database_engine(url)
    workflow_id, claim_id = uuid4(), uuid4()
    handler_handle, model_handle = object(), object()
    handlers = HandlerCatalog(execution_readiness.ResolvedHandler("story-handler", "c" * 64, handler_handle))
    models = ModelRegistry(execution_readiness.ReadyModel(MANIFEST, model_handle))
    try:
        with engine.begin() as connection:
            snapshot = save_execution(connection, workflow_id)
            bind(execution_bindings, connection, workflow_id, snapshot.sha256)
            request = run_requests.request_run(connection, uuid4(), workflow_id, "r1", snapshot.sha256)
            run_dispatch.prepare_run_dispatch(
                connection, request.run_id, handlers, models, LIMITS, max_bytes=100_000,
            )
            claim(connection, claim_id, request.run_id, "a")
        with engine.begin() as connection:
            result = node_revalidation.revalidate_admitted_node(
                connection, claim_id, request.run_id, "a", handlers, models, LIMITS,
                max_bytes=100_000,
            )
            assert result.ready
            assert result.handlers[0][1].handle is handler_handle
            assert result.models[0][2].handle is model_handle
    finally:
        engine.dispose()


def test_revalidation_is_read_only_and_returns_verified_whole_graph(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        before = (
            get_run_status(connection, run_id), list_events(connection, run_id, 0),
            connection.execute(select(outbox).where(outbox.c.resource_id == run_id)).all(),
            connection.execute(select(run_dispatch.node_intents).where(
                run_dispatch.node_intents.c.run_id == run_id,
            )).all(),
        )
        result = revalidate(connection, claim_id, run_id)
        assert result.ready
        assert [node_id for node_id, _ in result.handlers] == ["node-1", "node-2"]
        assert len(result.models) == 2
        assert (
            get_run_status(connection, run_id), list_events(connection, run_id, 0),
            connection.execute(select(outbox).where(outbox.c.resource_id == run_id)).all(),
            connection.execute(select(run_dispatch.node_intents).where(
                run_dispatch.node_intents.c.run_id == run_id,
            )).all(),
        ) == before
        assert connection.scalar(
            select(func.count()).select_from(node_outcomes.outcomes)
            .where(node_outcomes.outcomes.c.claim_id == claim_id)
        ) == 0


@pytest.mark.parametrize("damage", ["missing", "extra", "altered"])
def test_revalidation_rejects_corrupted_persisted_plan(prepared_run, damage):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        if damage == "missing":
            connection.execute(delete(run_dispatch.node_intents).where(
                run_dispatch.node_intents.c.run_id == run_id,
                run_dispatch.node_intents.c.node_id == "node-2",
            ))
        elif damage == "extra":
            connection.execute(insert(run_dispatch.node_intents).values(
                run_id=run_id, node_id="extra", dependencies=[],
            ))
        else:
            connection.execute(run_dispatch.node_intents.update().where(
                run_dispatch.node_intents.c.run_id == run_id,
                run_dispatch.node_intents.c.node_id == "node-2",
            ).values(dependencies=[]))
        with pytest.raises(node_revalidation.RevalidationConflict):
            revalidate(connection, claim_id, run_id)
        assert get_run_status(connection, run_id).state is RunState.RUNNING


def test_revalidation_rejects_missing_mismatched_and_completed_claims(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        with pytest.raises(node_revalidation.RevalidationConflict):
            revalidate(connection, uuid4(), run_id)
        with pytest.raises(node_revalidation.RevalidationConflict):
            node_revalidation.revalidate_admitted_node(
                connection, claim_id, run_id, "node-2", AllHandlers(), ReadyModels(),
                GraphLimits(max_nodes=8, max_edges=8), max_bytes=4096,
            )
        node_outcomes.record_outcome(
            connection, claim_id, run_id, "node-1", node_outcomes.NodeStatus.SUCCEEDED,
        )
        with pytest.raises(node_revalidation.RevalidationConflict):
            revalidate(connection, claim_id, run_id)


@pytest.mark.parametrize("bad_resource", ["handler", "model"])
def test_revalidation_unready_pin_does_not_transition_run(prepared_run, bad_resource):
    engine, run_id = prepared_run
    claim_id = uuid4()

    class Missing:
        def resolve(self, _):
            return None

    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        before = get_run_status(connection, run_id), list_events(connection, run_id, 0)
        result = revalidate(
            connection, claim_id, run_id,
            handlers=Missing() if bad_resource == "handler" else AllHandlers(),
            models=Missing() if bad_resource == "model" else ReadyModels(),
        )
        assert not result.ready
        assert result.failure_code is (
            execution_readiness.ReadinessFailureCode.HANDLER_NOT_READY
            if bad_resource == "handler" else execution_readiness.ReadinessFailureCode.MODEL_NOT_READY
        )
        assert (get_run_status(connection, run_id), list_events(connection, run_id, 0)) == before


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("missing", execution_readiness.ReadinessFailureCode.EXECUTION_BINDING_NOT_FOUND),
        ("corrupt", execution_readiness.ReadinessFailureCode.EXECUTION_BINDING_CORRUPT),
        ("source", execution_readiness.ReadinessFailureCode.RUN_BINDING_INVALID),
        ("document", execution_readiness.ReadinessFailureCode.EXECUTION_DOCUMENT_INVALID),
    ],
)
def test_revalidation_binding_failures_do_not_transition_run(prepared_run, monkeypatch, damage, expected):
    engine, run_id = prepared_run
    claim_id = uuid4()
    original = execution_readiness.get_execution_binding

    def broken_binding(*args):
        if damage == "missing":
            raise execution_bindings.ExecutionBindingNotFound()
        if damage == "corrupt":
            raise execution_bindings.ExecutionBindingCorrupt()
        binding = original(*args)
        if damage == "source":
            return replace(binding, source_sha256="e" * 64)
        return replace(binding, execution_bytes=b"{}")

    monkeypatch.setattr(execution_readiness, "get_execution_binding", broken_binding)
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        before = get_run_status(connection, run_id), list_events(connection, run_id, 0)
        result = revalidate(connection, claim_id, run_id)
        assert result.failure_code is expected
        assert not result.ready
        assert (get_run_status(connection, run_id), list_events(connection, run_id, 0)) == before


@pytest.mark.parametrize("bad_resource", ["handler", "model"])
def test_revalidation_rejects_mismatched_pin(prepared_run, bad_resource):
    engine, run_id = prepared_run
    claim_id = uuid4()

    class WrongHandler:
        def resolve(self, artifact_id):
            return execution_readiness.ResolvedHandler(artifact_id, "a" * 64, object())

    class WrongModel:
        def resolve(self, manifest):
            return execution_readiness.ReadyModel(replace(manifest, estimated_bytes=5), object())

    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        result = revalidate(
            connection, claim_id, run_id,
            handlers=WrongHandler() if bad_resource == "handler" else AllHandlers(),
            models=WrongModel() if bad_resource == "model" else ReadyModels(),
        )
        assert not result.ready
        assert result.failure_code is (
            execution_readiness.ReadinessFailureCode.HANDLER_PIN_MISMATCH
            if bad_resource == "handler" else execution_readiness.ReadinessFailureCode.MODEL_PIN_MISMATCH
        )
        assert get_run_status(connection, run_id).state is RunState.RUNNING


def test_revalidation_requires_transaction_and_run_ready_evidence(prepared_run):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.connect() as connection, pytest.raises(RuntimeError, match="transaction"):
        revalidate(connection, claim_id, run_id)
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
        connection.execute(delete(outbox).where(outbox.c.id == run_dispatch._outbox_id(run_id)))
        with pytest.raises(run_dispatch.RunDispatchCorrupt):
            revalidate(connection, claim_id, run_id)
        assert connection.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("first_operation", ["cancel", "revalidate"])
def test_revalidation_and_cancellation_lock_order(prepared_run, first_operation):
    engine, run_id = prepared_run
    claim_id = uuid4()
    with engine.begin() as connection:
        claim(connection, claim_id, run_id)
    contender_pid = Queue()

    def execute(connection, operation):
        if operation == "cancel":
            return run_cancellations.request_run_cancellation(connection, run_id)
        return revalidate(connection, claim_id, run_id)

    def contender():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
            try:
                return execute(connection, "revalidate" if first_operation == "cancel" else "cancel")
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
                    if winner_pid in observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                    ):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Revalidation contender never waited on the first transaction")
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        second = future.result(timeout=10)

    if first_operation == "cancel":
        assert second == "conflict"
    else:
        assert first.ready
        assert second.outcome is run_cancellations.CancellationOutcome.REQUESTED
    with engine.begin() as connection:
        assert get_run_status(connection, run_id).state is RunState.CANCELLING
        with pytest.raises(RunConflict):
            revalidate(connection, claim_id, run_id)
