import os
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL

from app.core.database import create_database_engine
from app.core.outbox import metadata as outbox_metadata
from app.core.outbox import outbox
from app.services.workflows import run_cancellations
from app.services.workflows.runs import (
    RunConflict,
    RunState,
    create_run,
    get_run_status,
    list_events,
    runs,
    transition_run,
)

pytest_plugins = ("test_execution_readiness",)


@pytest.fixture
def cancellation_run(queued_run):
    engine, run_id, workflow_id, revision = queued_run
    outbox_metadata.create_all(engine)
    return engine, run_id, workflow_id, revision


def test_cancellation_request_transitions_once_and_deduplicates_outbox(
    cancellation_run,
):
    engine, run_id, *_ = cancellation_run

    with engine.begin() as connection:
        first = run_cancellations.request_run_cancellation(connection, run_id)

    assert first.outcome is run_cancellations.CancellationOutcome.REQUESTED
    assert first.state is RunState.CANCELLING
    assert first.last_sequence == 2
    with engine.begin() as connection:
        intent_count = connection.scalar(
            select(func.count())
            .select_from(outbox)
            .where(outbox.c.resource_id == run_id)
        )
        intents = connection.execute(
            select(outbox.c.topic, outbox.c.resource_id).where(
                outbox.c.resource_id == run_id
            )
        ).all()
        second = run_cancellations.request_run_cancellation(connection, run_id)

    assert intent_count == 1
    assert [tuple(intent) for intent in intents] == [
        (run_cancellations.CANCELLATION_TOPIC, run_id)
    ]
    assert second.outcome is run_cancellations.CancellationOutcome.ALREADY_REQUESTED
    assert second.state is RunState.CANCELLING
    assert second.last_sequence == 2
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.CANCELLING


def test_concurrent_cancellation_waits_and_reuses_committed_intent():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    run_id = uuid4()
    contender_pid = Queue()
    try:
        with engine.begin() as connection:
            create_run(connection, run_id)

        def contender():
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                contender_pid.put(connection.scalar(text("SELECT pg_backend_pid()")))
                return run_cancellations.request_run_cancellation(connection, run_id)

        with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
            transaction = winner.begin()
            try:
                winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
                first = run_cancellations.request_run_cancellation(winner, run_id)
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
                        pytest.fail("Cancellation contender never waited on the winner")
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
    finally:
        engine.dispose()

    assert first.outcome is run_cancellations.CancellationOutcome.REQUESTED
    assert second.outcome is run_cancellations.CancellationOutcome.ALREADY_REQUESTED
    assert first.last_sequence == second.last_sequence == 2
    assert status.state is RunState.CANCELLING
    assert status.last_sequence == 2
    assert [event.state for event in events] == [RunState.QUEUED, RunState.CANCELLING]
    assert topics == [run_cancellations.CANCELLATION_TOPIC]


@pytest.mark.parametrize(
    ("initial_state", "sequence_before_cancel"),
    [
        (RunState.QUEUED, 1),
        (RunState.RUNNING, 2),
        (RunState.WAITING_REVIEW, 3),
    ],
)
def test_active_run_states_accept_a_cancellation_request(
    cancellation_run,
    initial_state,
    sequence_before_cancel,
):
    engine, run_id, *_ = cancellation_run

    with engine.begin() as connection:
        if initial_state is not RunState.QUEUED:
            transition_run(connection, run_id, 1, RunState.RUNNING, "Started")
        if initial_state is RunState.WAITING_REVIEW:
            transition_run(connection, run_id, 2, initial_state, "Waiting")
        result = run_cancellations.request_run_cancellation(connection, run_id)

    assert result.outcome is run_cancellations.CancellationOutcome.REQUESTED
    assert result.state is RunState.CANCELLING
    assert result.last_sequence == sequence_before_cancel + 1


@pytest.mark.parametrize(
    "terminal_state",
    [RunState.SUCCEEDED, RunState.PARTIAL_FAILURE, RunState.FAILED],
)
def test_terminal_runs_reject_cancellation_without_creating_intents(
    cancellation_run,
    terminal_state,
):
    engine, run_id, *_ = cancellation_run
    with engine.begin() as connection:
        transition_run(connection, run_id, 1, RunState.RUNNING, "Started")
        transition_run(connection, run_id, 2, terminal_state, "Finished")

    with engine.begin() as connection, pytest.raises(RunConflict):
        run_cancellations.request_run_cancellation(connection, run_id)

    with engine.begin() as connection:
        assert connection.scalar(
            select(func.count()).select_from(outbox).where(
                outbox.c.resource_id == run_id
            )
        ) == 0
        assert get_run_status(connection, run_id).state is terminal_state


def test_cancelled_run_retries_are_idempotent(cancellation_run):
    engine, run_id, *_ = cancellation_run
    with engine.begin() as connection:
        result = run_cancellations.request_run_cancellation(connection, run_id)
        transition_run(
            connection,
            run_id,
            result.last_sequence,
            RunState.CANCELLED,
            "Cancellation completed",
        )

    with engine.begin() as connection:
        retry = run_cancellations.request_run_cancellation(connection, run_id)
        intent_count = connection.scalar(
            select(func.count()).select_from(outbox).where(
                outbox.c.resource_id == run_id
            )
        )

    assert retry.outcome is run_cancellations.CancellationOutcome.ALREADY_CANCELLED
    assert retry.state is RunState.CANCELLED
    assert retry.last_sequence == 3
    assert intent_count == 1


def test_inconsistent_cancelling_state_fails_closed(cancellation_run):
    engine, run_id, *_ = cancellation_run
    with engine.begin() as connection:
        transition_run(connection, run_id, 1, RunState.CANCELLING, "Cancel")

    with engine.begin() as connection, pytest.raises(
        run_cancellations.RunCancellationCorrupt
    ):
        run_cancellations.request_run_cancellation(connection, run_id)


def test_outer_rollback_removes_cancellation_state_and_intent(
    cancellation_run,
):
    engine, run_id, *_ = cancellation_run
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        result = run_cancellations.request_run_cancellation(connection, run_id)
        assert result.state is RunState.CANCELLING
        raise RuntimeError("abort")

    with engine.begin() as connection:
        assert get_run_status(connection, run_id).state is RunState.QUEUED
        assert connection.scalar(
            select(func.count()).select_from(outbox).where(
                outbox.c.resource_id == run_id
            )
        ) == 0


def test_cancellation_requires_a_caller_owned_transaction(cancellation_run):
    engine, run_id, *_ = cancellation_run
    with engine.connect() as connection, pytest.raises(
        RuntimeError, match="explicit transaction"
    ):
        run_cancellations.request_run_cancellation(connection, run_id)


def test_cancellation_intent_survives_database_reconnect(tmp_path):
    database_url = URL.create(
        "sqlite+pysqlite",
        database=str(tmp_path / "workflow.db"),
    )
    run_id = uuid4()
    engine = create_engine(database_url)
    try:
        runs.metadata.create_all(engine)
        outbox_metadata.create_all(engine)
        with engine.begin() as connection:
            create_run(connection, run_id)
            first = run_cancellations.request_run_cancellation(connection, run_id)
    finally:
        engine.dispose()

    reconnected_engine = create_engine(database_url)
    try:
        with reconnected_engine.begin() as connection:
            status = get_run_status(connection, run_id)
            events = list_events(connection, run_id, after_sequence=0)
            retry = run_cancellations.request_run_cancellation(connection, run_id)
            intent_count = connection.scalar(
                select(func.count()).select_from(outbox).where(
                    outbox.c.resource_id == run_id,
                    outbox.c.topic == run_cancellations.CANCELLATION_TOPIC,
                )
            )
    finally:
        reconnected_engine.dispose()

    assert first.outcome is run_cancellations.CancellationOutcome.REQUESTED
    assert status.state is RunState.CANCELLING
    assert status.last_sequence == 2
    assert [event.state for event in events] == [
        RunState.QUEUED,
        RunState.CANCELLING,
    ]
    assert retry.outcome is run_cancellations.CancellationOutcome.ALREADY_REQUESTED
    assert retry.last_sequence == status.last_sequence
    assert intent_count == 1
