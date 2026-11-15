import importlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from queue import Queue
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from test_schedule_store import save

from app.core.outbox import outbox
from app.services.scheduling.preview import preview_occurrences
from app.services.scheduling.store import create_schedule, get_schedule, update_schedule
from app.services.workflows.revisions import RevisionCorrupt, revisions
from app.services.workflows.runs import events, runs


@pytest.fixture
def ledger():
    return importlib.import_module("app.services.scheduling.due_slots")


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def seed(conn, *, expression="30 1 * * *", zone="America/New_York"):
    workflow_id, schedule_id = uuid4(), uuid4()
    cursor = datetime(2026, 11, 1, 4, tzinfo=UTC)
    save(conn, workflow_id, "v1")
    schedule = create_schedule(
        conn, schedule_id, workflow_id, "v1", expression=expression,
        time_zone=zone, enabled=True, cursor=cursor,
    )
    return schedule, preview_occurrences(expression, zone, cursor)[0]


@pytest.mark.parametrize("expression,zone,cursor", [
    ("30 1 * * *", "America/New_York", datetime(2026, 11, 1, 4, tzinfo=UTC)),
    ("30 2 * * *", "America/New_York", datetime(2026, 3, 8, 5, tzinfo=UTC)),
    ("0 0 1 * mon", "UTC", datetime(2026, 1, 2, tzinfo=UTC)),
])
def test_occurrence_validation_reuses_preview(ledger, expression, zone, cursor):
    occurrence = preview_occurrences(expression, zone, cursor)[0]
    assert ledger.validate_occurrence(expression, zone, occurrence) is None


@pytest.mark.parametrize("change", [
    {"slot_key": "UTC:2026-11-01T01:30"},
    {"due_at": datetime(2026, 11, 1, 6, 30, tzinfo=UTC)},
    {"due_at": datetime(2026, 11, 1, 5, 30)},
    {"slot_key": "x" * 300},
    {"local_time": datetime(2026, 11, 1, 1, 30)},
])
def test_forged_occurrence_rejected(ledger, change):
    occurrence = preview_occurrences(
        "30 1 * * *", "America/New_York", datetime(2026, 11, 1, 4, tzinfo=UTC),
    )[0]
    with pytest.raises(ValueError):
        ledger.validate_occurrence("30 1 * * *", "America/New_York", replace(occurrence, **change))


def test_due_instant_accepts_equivalent_fold_offset(ledger):
    occurrence = preview_occurrences(
        "30 1 * * *", "America/New_York", datetime(2026, 11, 1, 4, tzinfo=UTC),
    )[0]
    ledger.validate_occurrence(
        "30 1 * * *", "America/New_York", replace(occurrence, due_at=occurrence.local_time),
    )


def test_gap_is_not_an_occurrence(ledger):
    from zoneinfo import ZoneInfo

    from app.services.scheduling.preview import ScheduleOccurrence

    local = datetime(2026, 3, 8, 2, 30, tzinfo=ZoneInfo("America/New_York"))
    with pytest.raises(ValueError):
        ledger.validate_occurrence("30 2 * * *", "America/New_York", ScheduleOccurrence(
            local, local.astimezone(UTC), "America/New_York:2026-03-08T02:30",
        ))


def test_binding_replay_namespace_and_no_effects(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
        before = tuple(conn.scalar(select(func.count()).select_from(t)) for t in (runs, events, outbox))
        first = ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
        assert first.schedule_id == schedule.id
        assert first.slot_key == occurrence.slot_key
        assert first.due_at == occurrence.due_at
        assert (first.workflow_id, first.revision, first.schedule_version) == (
            schedule.workflow_id, "v1", 1,
        )
        assert first.created_at.tzinfo is not None
        assert ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence) == first
        assert ledger.record_due_slot(
            conn, schedule.id, expected_version=1,
            occurrence=replace(occurrence, due_at=occurrence.local_time),
        ) == first
        assert ledger.get_due_slot(conn, schedule.id, occurrence.slot_key) == first
        other, _ = seed(conn)
        second = ledger.record_due_slot(conn, other.id, expected_version=1, occurrence=occurrence)
        assert second.schedule_id != first.schedule_id
        assert conn.scalar(select(func.count()).select_from(ledger.due_slots).where(
            ledger.due_slots.c.slot_key == occurrence.slot_key,
        )) == 2
        assert get_schedule(conn, schedule.id) == schedule
        assert tuple(conn.scalar(select(func.count()).select_from(t)) for t in (runs, events, outbox)) == before


def test_replay_after_edit_preserves_binding_and_conflicts_survive(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
        first = ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
        save(conn, schedule.workflow_id, "v2")
        update_schedule(
            conn, schedule.id, expected_version=1, workflow_id=schedule.workflow_id,
            revision="v2", expression="30 1 * * *", time_zone="America/New_York",
            enabled=False, cursor=occurrence.due_at,
        )
        assert ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence) == first
        with pytest.raises(ledger.DueSlotConflict):
            ledger.record_due_slot(conn, schedule.id, expected_version=2, occurrence=occurrence)
        with pytest.raises(ledger.DueSlotConflict):
            ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=replace(
                occurrence, due_at=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            ))
        next_slot = preview_occurrences("30 1 * * *", "America/New_York", occurrence.due_at)[0]
        with pytest.raises(ledger.DueSlotConflict):
            ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=next_slot)
        assert conn.scalar(text("SELECT 1")) == 1
        assert ledger.get_due_slot(conn, schedule.id, occurrence.slot_key) == first


def test_database_uniqueness_immutability_and_foreign_keys(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
        ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
        row = dict(conn.execute(select(ledger.due_slots).where(
            ledger.due_slots.c.schedule_id == schedule.id,
        )).one()._mapping)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(ledger.due_slots.insert().values(**row))
        for change in [{"due_at": datetime(2026, 11, 2, tzinfo=UTC)}, {"revision": "v2"}]:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(update(ledger.due_slots).where(
                    ledger.due_slots.c.schedule_id == schedule.id,
                ).values(**change))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(ledger.due_slots.delete().where(ledger.due_slots.c.schedule_id == schedule.id))
        for change in [{"schedule_id": uuid4()}, {"slot_key": "other", "revision": "missing"}]:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(ledger.due_slots.insert().values(**(row | change)))


def test_outer_rollback_and_transaction_guards(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
        raise RuntimeError("abort")
    with engine.connect() as conn, pytest.raises(ledger.DueSlotNotFound):
        ledger.get_due_slot(conn, schedule.id, occurrence.slot_key)
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(), pytest.raises(RuntimeError, match="non-autocommit"),
    ):
        ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)


def test_invalid_input_and_corrupt_revision_do_not_claim(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
        for version in [True, 0, 2147483648]:
            with pytest.raises(ValueError):
                ledger.record_due_slot(conn, schedule.id, expected_version=version, occurrence=occurrence)
        for invalid in [
            replace(occurrence, slot_key="UTC:\x00"),
            replace(occurrence, due_at=occurrence.due_at.replace(tzinfo=None)),
        ]:
            with pytest.raises(ValueError):
                ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=invalid)
        conn.execute(update(revisions).where(
            revisions.c.workflow_id == schedule.workflow_id,
        ).values(document=b"corrupt"))
        with pytest.raises(RevisionCorrupt):
            ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
        assert conn.scalar(select(func.count()).select_from(ledger.due_slots).where(
            ledger.due_slots.c.schedule_id == schedule.id,
        )) == 0
        assert conn.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_observers_replay_or_conflict(engine, ledger, different):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
    barrier = Barrier(2)

    def record(version):
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            barrier.wait(timeout=10)
            try:
                return ledger.record_due_slot(conn, schedule.id, expected_version=version, occurrence=occurrence)
            except ledger.DueSlotConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, [1, 2 if different else 1]))
    if different:
        assert results.count("conflict") == 1
    else:
        assert results[0] == results[1]
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(ledger.due_slots).where(
            ledger.due_slots.c.schedule_id == schedule.id,
        )) == 1


def wait_blocked(engine, pid):
    deadline = time.monotonic() + 4
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            waiting = observer.scalar(text(
                "SELECT wait_event FROM pg_stat_activity WHERE pid = :pid"
            ), {"pid": pid})
            observer.commit()
            if waiting == "transactionid":
                return
            time.sleep(0.02)
    pytest.fail("Contender did not wait on the owned transaction")


@pytest.mark.parametrize("rollback", [False, True])
def test_unique_constraint_arbitrates_real_inflight_inserts(engine, ledger, rollback):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
    values = {
        "schedule_id": schedule.id, "slot_key": occurrence.slot_key,
        "schedule_version": 1, "workflow_id": schedule.workflow_id, "revision": "v1",
        "due_at": occurrence.due_at,
    }
    pids = Queue()

    def contend():
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
                conn.execute(ledger.due_slots.insert().values(**values))
            return "inserted"
        except IntegrityError:
            return "duplicate"

    with engine.connect() as first, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = first.begin()
        first.execute(ledger.due_slots.insert().values(**values))
        future = pool.submit(contend)
        try:
            wait_blocked(engine, pids.get(timeout=10))
        finally:
            if rollback:
                transaction.rollback()
            else:
                transaction.commit()
        assert future.result(timeout=10) == ("inserted" if rollback else "duplicate")
    with engine.connect() as conn:
        assert ledger.get_due_slot(conn, schedule.id, occurrence.slot_key).revision == "v1"


def test_descriptor_edit_cannot_race_revision_binding(engine, ledger):
    with engine.begin() as conn:
        schedule, occurrence = seed(conn)
        save(conn, schedule.workflow_id, "v2")
    pids = Queue()

    def observe():
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
            with pytest.raises(ledger.DueSlotConflict):
                ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)

    with engine.connect() as editor, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = editor.begin()
        update_schedule(
            editor, schedule.id, expected_version=1, workflow_id=schedule.workflow_id,
            revision="v2", expression="30 1 * * *", time_zone="America/New_York",
            enabled=True, cursor=occurrence.due_at,
        )
        future = pool.submit(observe)
        try:
            wait_blocked(engine, pids.get(timeout=10))
        finally:
            transaction.commit()
        future.result(timeout=10)
    with engine.begin() as conn:
        with pytest.raises(ledger.DueSlotNotFound):
            ledger.get_due_slot(conn, schedule.id, occurrence.slot_key)
        recorded = ledger.record_due_slot(conn, schedule.id, expected_version=2, occurrence=occurrence)
        assert (recorded.workflow_id, recorded.revision, recorded.schedule_version) == (
            schedule.workflow_id, "v2", 2,
        )


def test_migration_roundtrip_and_metadata_consistency(engine, ledger):
    migration = importlib.import_module("migrations.versions.p6_02d_due_slots")
    with engine.begin() as conn:
        # Transactional DDL/savepoint restores pre-test observations on rollback.
        savepoint = conn.begin_nested()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
                assert not inspect(conn).has_table("schedule_due_slots")
                migration.upgrade()
            db = inspect(conn)
            assert db.get_pk_constraint("schedule_due_slots")["constrained_columns"] == [
                "schedule_id", "slot_key",
            ]
            actual = {c["name"]: c for c in db.get_columns("schedule_due_slots")}
            assert set(actual) == set(ledger.due_slots.c.keys())
            for column in ledger.due_slots.c:
                assert actual[column.name]["nullable"] == column.nullable
                assert str(actual[column.name]["type"].compile(dialect=conn.dialect)) == str(
                    column.type.compile(dialect=conn.dialect),
                )
            assert {fk["name"] for fk in db.get_foreign_keys("schedule_due_slots")} == {
                "fk_due_slot_schedule", "fk_due_slot_revision",
            }
            assert {c["name"] for c in db.get_check_constraints("schedule_due_slots")} == {
                "ck_due_slot_key", "ck_due_slot_version",
            }
            schedule, occurrence = seed(conn)
            ledger.record_due_slot(conn, schedule.id, expected_version=1, occurrence=occurrence)
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(ledger.due_slots.delete().where(ledger.due_slots.c.schedule_id == schedule.id))
        finally:
            savepoint.rollback()
