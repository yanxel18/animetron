import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, insert, select, text
from test_execution_readiness import _binding, _manifest
from test_run_dispatch import AllHandlers, ReadyModels
from test_run_revisions import save

from app.core.database import create_database_engine
from app.core.outbox import enqueue, outbox
from app.services.workflows import (
    execution_readiness,
    node_admission,
    run_cancellations,
    run_dispatch,
    run_requests,
)
from app.services.workflows.runs import (
    RunConflict,
    RunState,
    create_run,
    get_run_status,
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
