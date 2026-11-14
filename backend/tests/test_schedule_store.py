import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine

from app.services.scheduling.preview import preview_occurrences
from app.services.scheduling.store import (
    ScheduleConflict,
    ScheduleNotFound,
    create_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from app.services.workflows.revisions import RevisionNotFound, save_revision
from app.services.workflows.run_revisions import (
    create_run_with_revision,
    get_run_snapshot,
)
from app.services.workflows.validation import GraphLimits, NodeDefinition


class Story(BaseModel):
    prompt: str


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def save(conn, workflow_id, revision):
    document = json.dumps(
        {
            "schemaVersion": 1,
            "revision": revision,
            "nodes": [{"id": "a", "type": "story", "config": {"prompt": "x"}}],
            "edges": [],
        }
    ).encode()
    return save_revision(
        conn,
        workflow_id,
        document,
        {"story": NodeDefinition(config_model=Story)},
        GraphLimits(max_nodes=10, max_edges=10),
        max_bytes=4096,
    )


def test_persistence_pagination_rollback_and_validation(engine):
    workflow_id, schedule_id = uuid4(), uuid4()
    cursor = datetime(2026, 3, 8, 5, tzinfo=UTC)
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        schedule = create_schedule(
            conn, schedule_id, workflow_id, "v1",
            expression="30 2 * * *", time_zone="America/New_York",
            enabled=True, cursor=cursor,
        )
        assert schedule.next_due_at == preview_occurrences(
            "30 2 * * *", "America/New_York", cursor
        )[0].due_at
        assert schedule.version == 1
        assert schedule.overlap_policy == "skip"
        assert schedule.missed_run_policy == "skip"
        assert get_schedule(conn, schedule_id) == schedule
        assert schedule in list_schedules(conn, limit=100)
        with pytest.raises(ValueError):
            create_schedule(
                conn, uuid4(), workflow_id, "v1", expression="* * * * *",
                time_zone="UTC", enabled=True, cursor=datetime(2026, 1, 1),
            )
        with pytest.raises(RevisionNotFound):
            create_schedule(
                conn, uuid4(), workflow_id, "missing", expression="* * * * *",
                time_zone="UTC", enabled=True, cursor=cursor,
            )
        with pytest.raises(ValueError):
            list_schedules(conn, limit=0)
    rolled_back = uuid4()
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        create_schedule(
            conn, rolled_back, workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=False, cursor=cursor,
        )
        raise RuntimeError("abort")
    with engine.connect() as conn, pytest.raises(ScheduleNotFound):
        get_schedule(conn, rolled_back)


def test_pause_resume_and_stale_edits(engine):
    workflow_id, schedule_id = uuid4(), uuid4()
    early = datetime(2026, 11, 1, 4, tzinfo=UTC)
    later = datetime(2026, 11, 3, 8, tzinfo=UTC)
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        original = create_schedule(
            conn, schedule_id, workflow_id, "v1", expression="30 1 * * *",
            time_zone="America/New_York", enabled=True, cursor=early,
        )
        assert original.next_due_at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
        paused = update_schedule(
            conn, schedule_id, expected_version=1, workflow_id=workflow_id,
            revision="v1", expression="30 1 * * *", time_zone="America/New_York",
            enabled=False, cursor=early,
        )
        assert paused.next_due_at is None
        resumed = update_schedule(
            conn, schedule_id, expected_version=2, workflow_id=workflow_id,
            revision="v1", expression="30 1 * * *", time_zone="America/New_York",
            enabled=True, cursor=later,
        )
        assert resumed.next_due_at == preview_occurrences(
            "30 1 * * *", "America/New_York", later
        )[0].due_at
        assert resumed.next_due_at > later
        with pytest.raises(ScheduleConflict):
            update_schedule(
                conn, schedule_id, expected_version=2, workflow_id=workflow_id,
                revision="v1", expression="* * * * *", time_zone="UTC",
                enabled=True, cursor=later,
            )


def test_concurrent_edits_have_one_winner(engine):
    workflow_id, schedule_id = uuid4(), uuid4()
    cursor = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        create_schedule(
            conn, schedule_id, workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=True, cursor=cursor,
        )
    barrier = Barrier(2)

    def edit(expression):
        with engine.begin() as conn:
            barrier.wait(timeout=10)
            try:
                update_schedule(
                    conn, schedule_id, expected_version=1, workflow_id=workflow_id,
                    revision="v1", expression=expression, time_zone="UTC",
                    enabled=True, cursor=cursor,
                )
                return "won"
            except ScheduleConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ["0 * * * *", "30 * * * *"])) == [
            "conflict", "won"
        ]


def test_edit_does_not_change_bound_run_snapshot(engine):
    workflow_id, schedule_id, run_id = uuid4(), uuid4(), uuid4()
    cursor = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        original = save(conn, workflow_id, "v1")
        save(conn, workflow_id, "v2")
        create_run_with_revision(conn, run_id, workflow_id, "v1")
        create_schedule(
            conn, schedule_id, workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=True, cursor=cursor,
        )
        changed = update_schedule(
            conn, schedule_id, expected_version=1, workflow_id=workflow_id,
            revision="v2", expression="0 * * * *", time_zone="UTC",
            enabled=True, cursor=cursor,
        )
        assert changed.revision == "v2"
        assert get_run_snapshot(conn, run_id) == original


@pytest.mark.parametrize(
    "expression,time_zone,enabled,cursor,error",
    [
        ("* " * 130, "UTC", True, datetime(2026, 1, 1, tzinfo=UTC), ValueError),
        ("* * * * *", "a" * 256, True, datetime(2026, 1, 1, tzinfo=UTC), ValueError),
        ("* * * * *", "UTC", 1, datetime(2026, 1, 1, tzinfo=UTC), TypeError),
        ("* * * * * *", "UTC", True, datetime(2026, 1, 1, tzinfo=UTC), ValueError),
        ("* * * * *", "../UTC", True, datetime(2026, 1, 1, tzinfo=UTC), ValueError),
    ],
)
def test_bad_inputs_do_not_abort_transaction(engine, expression, time_zone, enabled, cursor, error):
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        with pytest.raises(error):
            create_schedule(
                conn, uuid4(), workflow_id, "v1", expression=expression,
                time_zone=time_zone, enabled=enabled, cursor=cursor,
            )
        valid = create_schedule(
            conn, uuid4(), workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=True, cursor=cursor,
        )
        assert get_schedule(conn, valid.id) == valid


def test_pagination_and_requires_explicit_transaction(engine):
    workflow_id = uuid4()
    ids = sorted([uuid4(), uuid4(), uuid4()])
    cursor = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        create_schedule(
            conn, ids[0], workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=False, cursor=cursor,
        )
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        for schedule_id in ids:
            create_schedule(
                conn, schedule_id, workflow_id, "v1", expression="* * * * *",
                time_zone="UTC", enabled=False, cursor=cursor,
            )
        page = list_schedules(conn, limit=1, after=ids[0])
        assert len(page) == 1
        assert ids[0] < page[0].id <= ids[1]
        assert all(item.id > page[0].id for item in list_schedules(conn, limit=100, after=page[0].id))


def test_update_rollback_and_autocommit_rejection(engine):
    workflow_id, schedule_id = uuid4(), uuid4()
    cursor = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        original = create_schedule(
            conn, schedule_id, workflow_id, "v1", expression="* * * * *",
            time_zone="UTC", enabled=True, cursor=cursor,
        )
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        update_schedule(
            conn, schedule_id, expected_version=1, workflow_id=workflow_id,
            revision="v1", expression="0 * * * *", time_zone="UTC",
            enabled=False, cursor=cursor,
        )
        raise RuntimeError("abort")
    with engine.connect() as conn:
        assert get_schedule(conn, schedule_id) == original
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(),
        pytest.raises(RuntimeError, match="non-autocommit"),
    ):
        update_schedule(
            conn, schedule_id, expected_version=1, workflow_id=workflow_id,
            revision="v1", expression="0 * * * *", time_zone="UTC",
            enabled=False, cursor=cursor,
        )
