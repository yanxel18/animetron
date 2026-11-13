import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from app.services.workflows.runs import (
    InvalidRunTransition,
    RunConflict,
    RunNotFound,
    RunState,
    create_run,
    list_events,
    transition_run,
)


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_create_and_replay_after_commit(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        transition_run(conn, run_id, 1, RunState.RUNNING, "Started")
        transition_run(conn, run_id, 2, RunState.SUCCEEDED, "Finished")
    with engine.connect() as conn:
        events = list_events(conn, run_id, after_sequence=1)
        assert [(e.sequence, e.state, e.message) for e in events] == [
            (2, RunState.RUNNING, "Started"),
            (3, RunState.SUCCEEDED, "Finished"),
        ]
        assert all(e.run_id == run_id and e.occurred_at.tzinfo for e in events)


def test_outer_transaction_rollback_removes_run_and_event(engine) -> None:
    run_id = uuid4()
    with pytest.raises(RuntimeError), engine.begin() as conn:
        create_run(conn, run_id)
        raise RuntimeError("abort")
    with engine.connect() as conn, pytest.raises(RunNotFound):
        list_events(conn, run_id, after_sequence=0)


def test_invalid_transition_does_not_append_event(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        with pytest.raises(InvalidRunTransition):
            transition_run(conn, run_id, 1, RunState.SUCCEEDED, "Invalid")
        assert len(list_events(conn, run_id, after_sequence=0)) == 1


def test_stale_sequence_and_missing_run_are_explicit(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        transition_run(conn, run_id, 1, RunState.RUNNING, "Started")
        with pytest.raises(RunConflict):
            transition_run(conn, run_id, 1, RunState.CANCELLING, "Cancel")
        with pytest.raises(RunNotFound):
            transition_run(conn, uuid4(), 1, RunState.RUNNING, "Absent")


def test_two_writers_with_same_sequence_have_one_winner(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)

    def write(state: RunState) -> str:
        try:
            with engine.begin() as conn:
                transition_run(conn, run_id, 1, state, "Concurrent")
            return "ok"
        except RunConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [RunState.RUNNING, RunState.CANCELLING]))
    assert sorted(results) == ["conflict", "ok"]
    with engine.connect() as conn:
        assert [e.sequence for e in list_events(conn, run_id, after_sequence=0)] == [
            1,
            2,
        ]


def test_negative_replay_cursor_is_rejected(engine) -> None:
    with engine.connect() as conn, pytest.raises(ValueError):
        list_events(conn, uuid4(), after_sequence=-1)


def test_replay_is_bounded_and_resumable(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        transition_run(conn, run_id, 1, RunState.RUNNING, "Started")
        transition_run(conn, run_id, 2, RunState.SUCCEEDED, "Finished")
        first = list_events(conn, run_id, after_sequence=0, limit=2)
        second = list_events(conn, run_id, after_sequence=first[-1].sequence, limit=2)
        assert [event.sequence for event in first + second] == [1, 2, 3]
        with pytest.raises(ValueError):
            list_events(conn, run_id, after_sequence=0, limit=501)


def test_cancellation_prevents_success_and_terminal_states_are_final(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        transition_run(conn, run_id, 1, RunState.CANCELLING, "Cancel requested")
        with pytest.raises(InvalidRunTransition):
            transition_run(conn, run_id, 2, RunState.SUCCEEDED, "Cannot succeed")
        transition_run(conn, run_id, 2, RunState.CANCELLED, "Cancelled")
        with pytest.raises(InvalidRunTransition):
            transition_run(conn, run_id, 3, RunState.RUNNING, "Cannot restart")


def test_waiting_review_cannot_directly_succeed(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
        transition_run(conn, run_id, 1, RunState.RUNNING, "Started")
        transition_run(conn, run_id, 2, RunState.WAITING_REVIEW, "Waiting")
        with pytest.raises(InvalidRunTransition):
            transition_run(conn, run_id, 3, RunState.SUCCEEDED, "Not approved")


def test_transition_and_event_roll_back_together(engine) -> None:
    run_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, run_id)
    with pytest.raises(RuntimeError), engine.begin() as conn:
        transition_run(conn, run_id, 1, RunState.RUNNING, "Started")
        raise RuntimeError("abort")
    with engine.begin() as conn:
        assert [e.sequence for e in list_events(conn, run_id, 0)] == [1]
        transition_run(conn, run_id, 1, RunState.RUNNING, "Retried")


def test_writes_require_explicit_transaction(engine) -> None:
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        create_run(conn, uuid4())
