"""Internal immutable occurrence observations, not dispatch/skip decisions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, RowMapping

from app.services.scheduling.preview import ScheduleOccurrence, preview_occurrences
from app.services.scheduling.store import (
    ScheduleNotFound,
    _id,
    _schedule,
    _transaction,
    schedules,
)
from app.services.workflows.revisions import get_revision, revisions

metadata = MetaData()
due_slots = Table(
    "schedule_due_slots", metadata,
    Column("schedule_id", Uuid, primary_key=True),
    Column("slot_key", String(272), primary_key=True),
    Column("schedule_version", Integer, nullable=False),
    Column("workflow_id", Uuid, nullable=False),
    Column("revision", String(128), nullable=False),
    Column("due_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["schedule_id"], [schedules.c.id], name="fk_due_slot_schedule"),
    ForeignKeyConstraint(
        ["workflow_id", "revision"], [revisions.c.workflow_id, revisions.c.revision],
        name="fk_due_slot_revision",
    ),
    CheckConstraint("length(slot_key) BETWEEN 1 AND 272", name="ck_due_slot_key"),
    CheckConstraint("schedule_version > 0", name="ck_due_slot_version"),
)


@dataclass(frozen=True)
class DueSlot:
    schedule_id: UUID
    slot_key: str
    schedule_version: int
    workflow_id: UUID
    revision: str
    due_at: datetime
    created_at: datetime


class DueSlotConflict(Exception):
    pass


class DueSlotNotFound(LookupError):
    pass


def _slot_key(slot_key: str) -> None:
    if not isinstance(slot_key, str) or not 1 <= len(slot_key) <= 272 or "\x00" in slot_key:
        raise ValueError("Invalid local slot key")


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Occurrence times must be timezone-aware")


def validate_occurrence(
    expression: str, time_zone: str, occurrence: ScheduleOccurrence,
) -> None:
    """Require the exact zone/wall key and earlier-fold instant from preview."""
    _slot_key(occurrence.slot_key)
    _aware(occurrence.local_time)
    _aware(occurrence.due_at)
    try:
        expected = preview_occurrences(
            expression, time_zone, occurrence.due_at.astimezone(UTC) - timedelta(microseconds=1),
        )[0]
    except (OverflowError, ValueError):
        raise ValueError("Invalid schedule occurrence") from None
    if (
        occurrence.slot_key != expected.slot_key
        or occurrence.due_at.astimezone(UTC) != expected.due_at
        or occurrence.local_time.isoformat() != expected.local_time.isoformat()
    ):
        raise ValueError("Occurrence does not match schedule preview")


def _record(row: RowMapping) -> DueSlot:
    return DueSlot(
        schedule_id=row["schedule_id"], slot_key=row["slot_key"],
        schedule_version=row["schedule_version"], workflow_id=row["workflow_id"],
        revision=row["revision"], due_at=row["due_at"], created_at=row["created_at"],
    )


def get_due_slot(connection: Connection, schedule_id: UUID, slot_key: str) -> DueSlot:
    """Read one committed/caller-visible observation, without execution claims."""
    _id(schedule_id)
    _slot_key(slot_key)
    row = connection.execute(select(due_slots).where(
        due_slots.c.schedule_id == schedule_id, due_slots.c.slot_key == slot_key,
    )).one_or_none()
    if row is None:
        raise DueSlotNotFound("Due slot not found")
    return _record(row._mapping)


def _replay(record: DueSlot, version: int, occurrence: ScheduleOccurrence) -> DueSlot:
    if record.schedule_version != version or record.due_at != occurrence.due_at.astimezone(UTC):
        raise DueSlotConflict("Slot identity is already bound to a different observation")
    local = record.due_at.astimezone(ZoneInfo(record.slot_key.split(":", 1)[0]))
    if occurrence.local_time.isoformat() != local.isoformat():
        raise ValueError("Occurrence local time does not match binding")
    return record


def record_due_slot(
    connection: Connection, schedule_id: UUID, *,
    expected_version: int, occurrence: ScheduleOccurrence,
) -> DueSlot:
    """Observe a candidate in the caller's transaction; never decide its outcome."""
    _transaction(connection)
    _id(schedule_id)
    if type(expected_version) is not int or not 1 <= expected_version <= 2147483647:
        raise ValueError("Invalid expected schedule version")
    _slot_key(occurrence.slot_key)
    _aware(occurrence.local_time)
    _aware(occurrence.due_at)
    # Serialize descriptor binding with existing version-checked edits. This
    # lock is not a dispatch claim; the unique PK remains the identity guard.
    row = connection.execute(
        select(schedules).where(schedules.c.id == schedule_id).with_for_update(),
    ).one_or_none()
    if row is None:
        raise ScheduleNotFound("Schedule not found")
    schedule = _schedule(row._mapping)
    try:
        existing = get_due_slot(connection, schedule_id, occurrence.slot_key)
    except DueSlotNotFound:
        existing = None
    if existing is not None:
        return _replay(existing, expected_version, occurrence)
    if schedule.version != expected_version:
        raise DueSlotConflict("Schedule changed before observation")
    validate_occurrence(schedule.expression, schedule.time_zone, occurrence)
    get_revision(connection, schedule.workflow_id, schedule.revision)
    row = connection.execute(
        insert(due_slots).values(
            schedule_id=schedule_id, slot_key=occurrence.slot_key,
            schedule_version=expected_version, workflow_id=schedule.workflow_id,
            revision=schedule.revision, due_at=occurrence.due_at.astimezone(UTC),
        ).on_conflict_do_nothing(
            index_elements=[due_slots.c.schedule_id, due_slots.c.slot_key],
        ).returning(due_slots),
    ).one_or_none()
    if row is not None:
        return _record(row._mapping)
    return _replay(
        get_due_slot(connection, schedule_id, occurrence.slot_key), expected_version, occurrence,
    )
