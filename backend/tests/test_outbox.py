import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.outbox import (
    OutboxConflict,
    acknowledge,
    claim,
    enqueue,
    outbox,
)
from app.services.workflows.runs import RunNotFound, create_run, list_events


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


def test_run_and_outbox_intent_commit_and_roll_back_together(engine) -> None:
    committed_run, rolled_back_run = uuid4(), uuid4()
    committed_event, rolled_back_event = uuid4(), uuid4()
    with engine.begin() as conn:
        create_run(conn, committed_run)
        enqueue(conn, committed_event, "workflow.run", committed_run)
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        create_run(conn, rolled_back_run)
        enqueue(conn, rolled_back_event, "workflow.run", rolled_back_run)
        raise RuntimeError("abort")
    with engine.connect() as conn:
        assert len(list_events(conn, committed_run, 0)) == 1
        assert conn.scalar(select(outbox.c.id).where(outbox.c.id == committed_event))
        assert (
            conn.scalar(select(outbox.c.id).where(outbox.c.id == rolled_back_event))
            is None
        )
        with pytest.raises(RunNotFound):
            list_events(conn, rolled_back_run, 0)


def test_duplicate_intent_id_is_rejected(engine) -> None:
    event_id = uuid4()
    with engine.begin() as conn:
        enqueue(conn, event_id, "workflow.run", uuid4())
    with pytest.raises(IntegrityError), engine.begin() as conn:
        enqueue(conn, event_id, "workflow.run", uuid4())


def test_claim_acknowledge_and_expired_lease_fencing(engine) -> None:
    event_id = uuid4()
    topic = f"test.{uuid4().hex}"
    with engine.begin() as conn:
        enqueue(conn, event_id, topic, uuid4())
    with engine.begin() as conn:
        first = claim(conn, limit=1, lease_seconds=60, topic=topic)[0]
        assert first.id == event_id
    with engine.begin() as conn:
        assert claim(conn, limit=1, lease_seconds=60, topic=topic) == []
        conn.execute(
            update(outbox)
            .where(outbox.c.id == event_id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1))
        )
    with engine.begin() as conn:
        with pytest.raises(OutboxConflict):
            acknowledge(conn, event_id, first.lease_token)
        second = claim(conn, limit=1, lease_seconds=60, topic=topic)[0]
        assert second.id == event_id and second.lease_token != first.lease_token
        with pytest.raises(OutboxConflict):
            acknowledge(conn, event_id, first.lease_token)
        acknowledge(conn, event_id, second.lease_token)
    with engine.begin() as conn:
        assert claim(conn, limit=1, lease_seconds=60, topic=topic) == []


def test_concurrent_claimers_never_receive_same_intent(engine) -> None:
    topic = f"test.{uuid4().hex}"
    ids = {uuid4(), uuid4()}
    with engine.begin() as conn:
        for event_id in ids:
            enqueue(conn, event_id, topic, uuid4())

    def take_one():
        with engine.begin() as conn:
            return claim(conn, limit=1, lease_seconds=60, topic=topic)

    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(lambda _: take_one(), range(2)))
    assert {item.id for batch in batches for item in batch} == ids


def test_locked_intent_is_skipped_by_another_claimer(engine) -> None:
    topic = f"test.{uuid4().hex}"
    ids = {uuid4(), uuid4()}
    with engine.begin() as conn:
        for event_id in ids:
            enqueue(conn, event_id, topic, uuid4())
    with engine.begin() as first_conn:
        first = claim(first_conn, limit=1, lease_seconds=60, topic=topic)[0]
        with engine.begin() as second_conn:
            second_conn.execute(text("SET LOCAL lock_timeout = '2s'"))
            second = claim(second_conn, limit=1, lease_seconds=60, topic=topic)[0]
            assert {first.id, second.id} == ids


def test_invalid_arguments_and_missing_transactions_are_rejected(engine) -> None:
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        enqueue(conn, uuid4(), "workflow.run", uuid4())
    with engine.begin() as conn:
        for topic in ("", "with spaces", "x" * 81):
            with pytest.raises(ValueError):
                enqueue(conn, uuid4(), topic, uuid4())
        for limit, seconds in ((0, 60), (501, 60), (1, 0)):
            with pytest.raises(ValueError):
                claim(conn, limit=limit, lease_seconds=seconds, topic="workflow.run")
