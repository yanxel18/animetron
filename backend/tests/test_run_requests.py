import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from queue import Queue
from uuid import uuid1, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from test_run_revisions import save

from app.core.outbox import enqueue, outbox
from app.services.workflows import run_requests as requests
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    revisions,
)
from app.services.workflows.run_revisions import (
    create_run_with_revision,
    get_run_snapshot,
    run_revisions,
)
from app.services.workflows.runs import (
    RunState,
    events,
    list_events,
    runs,
    transition_run,
)


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_request_and_identical_retry_create_one_checked_association(engine):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        first = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
    with engine.begin() as conn:
        retry = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        assert retry == first
        assert first.request_id == request_id
        assert first.workflow_id == workflow_id
        assert first.revision == "rev1"
        assert first.sha256 == snapshot.sha256
        assert first.run_id.version == 4
        assert first.run_id != request_id
        assert first.created_at.utcoffset().total_seconds() == 0
        with pytest.raises(FrozenInstanceError):
            first.run_id = uuid4()
        assert get_run_snapshot(conn, first.run_id) == snapshot
        assert [event.state for event in list_events(conn, first.run_id, 0)] == [RunState.QUEUED]
        for table, condition in (
            (requests.run_requests, requests.run_requests.c.request_id == request_id),
            (runs, runs.c.id == first.run_id),
            (events, events.c.run_id == first.run_id),
            (run_revisions, run_revisions.c.run_id == first.run_id),
            (outbox, outbox.c.resource_id == first.run_id),
        ):
            assert conn.scalar(select(func.count()).select_from(table).where(condition)) == 1
        intent = conn.execute(select(outbox).where(outbox.c.id == request_id)).one()
        assert intent.topic == "internal.workflow-run-requested.v1"
        assert intent.resource_id == first.run_id


def counts(conn):
    return tuple(
        conn.scalar(select(func.count()).select_from(table))
        for table in (requests.run_requests, runs, run_revisions, events, outbox)
    )


@pytest.mark.parametrize("changed", ["workflow", "revision", "digest"])
def test_changed_payload_conflicts_without_writes(engine, changed):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        first = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        before = counts(conn)
        with pytest.raises(requests.RunRequestConflict):
            requests.request_run(
                conn, request_id,
                uuid4() if changed == "workflow" else workflow_id,
                "other" if changed == "revision" else "rev1",
                "0" * 64 if changed == "digest" else snapshot.sha256,
            )
        assert counts(conn) == before
        assert requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256) == first


@pytest.mark.parametrize("failure", ["missing", "digest", "corrupt"])
def test_invalid_snapshot_leaves_no_claim_and_outer_work_can_commit(engine, failure):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        if failure == "corrupt":
            conn.execute(
                update(revisions).where(revisions.c.workflow_id == workflow_id)
                .values(document=b"corrupt")
            )
        before = counts(conn)
        error = {
            "missing": RevisionNotFound,
            "digest": requests.RunRequestConflict,
            "corrupt": RevisionCorrupt,
        }[failure]
        with pytest.raises(error):
            requests.request_run(
                conn, request_id, workflow_id,
                "missing" if failure == "missing" else "rev1",
                "0" * 64 if failure == "digest" else snapshot.sha256,
            )
        assert counts(conn) == before
        assert conn.scalar(text("SELECT 1")) == 1
    with engine.connect() as conn:
        assert conn.scalar(
            select(revisions.c.workflow_id).where(revisions.c.workflow_id == workflow_id)
        ) == workflow_id
        assert conn.scalar(
            select(requests.run_requests.c.request_id)
            .where(requests.run_requests.c.request_id == request_id)
        ) is None


def test_actual_late_database_collision_rolls_back_savepoint_not_outer_work(engine):
    workflow_id, request_id, low_level_run = uuid4(), uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        create_run_with_revision(conn, low_level_run, workflow_id, "rev1")
        # Even a superficially valid pre-existing INTERNAL intent is not adopted.
        enqueue(conn, request_id, requests.INTERNAL_TOPIC, low_level_run)
        before = counts(conn)
        with pytest.raises(IntegrityError) as failure:
            requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        assert failure.value.orig.sqlstate == "23505"
        assert counts(conn) == before
        assert conn.scalar(
            select(outbox.c.resource_id).where(outbox.c.id == request_id)
        ) == low_level_run
    with engine.begin() as conn:
        assert get_run_snapshot(conn, low_level_run) == snapshot
        assert conn.scalar(
            select(requests.run_requests.c.request_id)
            .where(requests.run_requests.c.request_id == request_id)
        ) is None


def test_actual_outer_database_failure_rolls_back_successful_request(engine):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        before = counts(conn)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        record = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        enqueue(conn, request_id, requests.INTERNAL_TOPIC, record.run_id)
    with engine.begin() as conn:
        assert counts(conn) == before
        assert conn.scalar(select(runs.c.id).where(runs.c.id == record.run_id)) is None
        # Rolled-back claim can be retried as a fresh request.
        retry = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        assert retry.run_id != record.run_id


@pytest.mark.parametrize(
    "evidence,change",
    [
        ("binding", "missing"), ("binding", "wrong"),
        ("intent", "missing"), ("intent", "topic"), ("intent", "resource"),
        ("event", "missing"), ("event", "state"),
    ],
)
def test_replay_rejects_missing_or_mismatched_evidence_without_repair(engine, evidence, change):
    workflow_id, request_id, other_workflow = uuid4(), uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        save(conn, other_workflow)
        first = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        if evidence == "binding":
            statement = (
                delete(run_revisions) if change == "missing"
                else update(run_revisions).values(workflow_id=other_workflow)
            ).where(run_revisions.c.run_id == first.run_id)
        elif evidence == "intent":
            statement = (
                delete(outbox) if change == "missing"
                else update(outbox).values(
                    **({"topic": "other.internal"} if change == "topic"
                       else {"resource_id": uuid4()})
                )
            ).where(outbox.c.id == request_id)
        else:
            statement = (
                delete(events) if change == "missing"
                else update(events).values(state="RUNNING")
            ).where(events.c.run_id == first.run_id, events.c.sequence == 1)
        conn.execute(statement)
        before = counts(conn)
        with pytest.raises(requests.RunRequestCorrupt):
            requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        assert counts(conn) == before
        # No repair, including for fields whose mutation leaves row counts unchanged.
        with pytest.raises(requests.RunRequestCorrupt):
            requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)


def test_unverified_claim_with_missing_run_is_not_promoted(engine):
    workflow_id, request_id, absent_run = uuid4(), uuid4(), uuid4()
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            snapshot = save(conn, workflow_id)
            # Deferred FK lets us inspect an incomplete raw claim before commit.
            conn.execute(insert(requests.run_requests).values(
                request_id=request_id, run_id=absent_run, workflow_id=workflow_id,
                revision="rev1", sha256=snapshot.sha256,
            ))
            before = counts(conn)
            with pytest.raises(requests.RunRequestCorrupt):
                requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
            assert counts(conn) == before
            assert conn.scalar(select(runs.c.id).where(runs.c.id == absent_run)) is None
        finally:
            transaction.rollback()


def test_replay_checks_snapshot_and_allows_later_run_and_delivery_state(engine):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        first = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        transition_run(conn, first.run_id, 1, RunState.RUNNING, "Started")
        conn.execute(update(outbox).where(outbox.c.id == request_id).values(delivered_at=func.now()))
        assert requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256) == first
        assert len(list_events(conn, first.run_id, 0)) == 2
        conn.execute(
            update(revisions).where(revisions.c.workflow_id == workflow_id)
            .values(document=b"corrupt")
        )
        with pytest.raises(RevisionCorrupt):
            requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)


def test_request_mutation_and_deletion_are_database_guarded(engine):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        first = requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256)
        for statement in (
            update(requests.run_requests).values(run_id=uuid4()),
            update(requests.run_requests).values(sha256="0" * 64),
            delete(requests.run_requests),
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(statement.where(requests.run_requests.c.request_id == request_id))
        assert requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256) == first


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("request_id", "not-a-uuid", TypeError),
        ("request_id", uuid1(), ValueError),
        ("workflow_id", "not-a-uuid", TypeError),
        ("revision", 1, TypeError),
        ("revision", " ", ValueError),
        ("revision", "x" * 129, ValueError),
        ("revision", "\x00", ValueError),
        ("expected_sha256", 1, TypeError),
        ("expected_sha256", "F" * 64, ValueError),
        ("expected_sha256", "0" * 63, ValueError),
    ],
)
def test_type_and_format_guards_leave_outer_transaction_usable(engine, field, value, error):
    values = {
        "request_id": uuid4(), "workflow_id": uuid4(),
        "revision": "rev1", "expected_sha256": "0" * 64,
    }
    values[field] = value
    with engine.begin() as conn:
        before = counts(conn)
        with pytest.raises(error):
            requests.request_run(conn, **values)
        assert counts(conn) == before


def test_requires_transaction_and_rejects_autocommit_and_non_psycopg(engine):
    args = (uuid4(), uuid4(), "rev1", "0" * 64)
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        requests.request_run(conn, *args)
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(),
        pytest.raises(RuntimeError, match="non-autocommit"),
    ):
        requests.request_run(conn, *args)
    sqlite = create_engine("sqlite://")
    try:
        with sqlite.begin() as conn, pytest.raises(RuntimeError, match="psycopg"):
            requests.request_run(conn, *args)
    finally:
        sqlite.dispose()


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_duplicate_waits_for_real_database_winner(engine, different):
    workflow_id, request_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        before = counts(conn)
    contender_pid = Queue()

    def contender():
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            contender_pid.put(conn.scalar(text("SELECT pg_backend_pid()")))
            try:
                return requests.request_run(
                    conn, request_id, workflow_id, "rev1",
                    "0" * 64 if different else snapshot.sha256,
                )
            except requests.RunRequestConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
        transaction = winner.begin()
        try:
            winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
            first = requests.request_run(winner, request_id, workflow_id, "rev1", snapshot.sha256)
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
                    pytest.fail("Contender never waited on the database winner")
            assert not future.done()
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        result = future.result(timeout=10)
    assert result == ("conflict" if different else first)
    with engine.begin() as conn:
        assert requests.request_run(conn, request_id, workflow_id, "rev1", snapshot.sha256) == first
        assert counts(conn) == tuple(value + 1 for value in before)
        assert len(list_events(conn, first.run_id, 0)) == 1
        for table, condition in (
            (requests.run_requests, requests.run_requests.c.request_id == request_id),
            (run_revisions, run_revisions.c.run_id == first.run_id),
            (outbox, outbox.c.resource_id == first.run_id),
        ):
            assert conn.scalar(select(func.count()).select_from(table).where(condition)) == 1
