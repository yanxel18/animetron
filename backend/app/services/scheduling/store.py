"""Internal schedule descriptors; no scheduler or dispatch is provided."""

from dataclasses import dataclass
from datetime import datetime
from uuid import RFC_4122, UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import (
    Boolean,
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
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, RowMapping

from app.services.scheduling.preview import preview_occurrences
from app.services.workflows.revisions import get_revision, revisions

metadata = MetaData()
schedules = Table(
    "schedule_descriptors",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workflow_id", Uuid, nullable=False),
    Column("revision", String(128), nullable=False),
    Column("expression", String(256), nullable=False),
    Column("time_zone", String(255), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("next_due_at", DateTime(timezone=True), nullable=True),
    Column("overlap_policy", String(4), nullable=False),
    Column("missed_run_policy", String(4), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workflow_id", "revision"],
        [revisions.c.workflow_id, revisions.c.revision],
        name="fk_schedule_workflow_revision",
    ),
    CheckConstraint(
        "substr(id::text, 15, 1) = '4' AND "
        "substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_schedule_uuid4",
    ),
    CheckConstraint("length(expression) BETWEEN 1 AND 256", name="ck_schedule_expression"),
    CheckConstraint("length(time_zone) BETWEEN 1 AND 255", name="ck_schedule_time_zone"),
    CheckConstraint(
        "(enabled AND next_due_at IS NOT NULL) OR "
        "(NOT enabled AND next_due_at IS NULL)",
        name="ck_schedule_next_due",
    ),
    CheckConstraint("overlap_policy = 'skip'", name="ck_schedule_overlap_policy"),
    CheckConstraint("missed_run_policy = 'skip'", name="ck_schedule_missed_policy"),
    CheckConstraint("version > 0", name="ck_schedule_version"),
)


@dataclass(frozen=True)
class Schedule:
    id: UUID
    workflow_id: UUID
    revision: str
    expression: str
    time_zone: str
    enabled: bool
    next_due_at: datetime | None
    overlap_policy: str
    missed_run_policy: str
    version: int
    created_at: datetime
    updated_at: datetime


class ScheduleNotFound(LookupError):
    pass


class ScheduleConflict(Exception):
    pass


def _transaction(connection: Connection) -> None:
    driver = connection.connection.driver_connection
    if (
        not connection.in_transaction()
        or not isinstance(driver, PsycopgConnection)
        or driver.autocommit
    ):
        raise RuntimeError("An explicit non-autocommit transaction is required")


def _id(schedule_id: UUID) -> None:
    if not isinstance(schedule_id, UUID):
        raise TypeError("Invalid schedule identifier")
    if schedule_id.version != 4 or schedule_id.variant != RFC_4122:
        raise ValueError("Schedule identifier must be an RFC-variant UUID4")


def _values(
    connection: Connection,
    workflow_id: UUID,
    revision: str,
    expression: str,
    time_zone: str,
    enabled: bool,
    cursor: datetime,
) -> dict[str, object]:
    if not isinstance(workflow_id, UUID):
        raise TypeError("Invalid workflow identifier")
    if not isinstance(revision, str):
        raise TypeError("Invalid workflow revision")
    if not isinstance(expression, str) or not 1 <= len(expression) <= 256:
        raise ValueError("Invalid schedule expression length")
    if not isinstance(time_zone, str) or not 1 <= len(time_zone) <= 255:
        raise ValueError("Invalid schedule time zone length")
    if type(enabled) is not bool:
        raise TypeError("Schedule enabled must be a boolean")
    if not isinstance(cursor, datetime) or cursor.tzinfo is None or cursor.utcoffset() is None:
        raise ValueError("Schedule cursor must be timezone-aware")
    occurrences = preview_occurrences(expression, time_zone, cursor)
    get_revision(connection, workflow_id, revision)
    return {
        "workflow_id": workflow_id,
        "revision": revision,
        "expression": expression,
        "time_zone": time_zone,
        "enabled": enabled,
        "next_due_at": occurrences[0].due_at if enabled else None,
    }


def _schedule(row: RowMapping) -> Schedule:
    return Schedule(
        id=row["id"],
        workflow_id=row["workflow_id"],
        revision=row["revision"],
        expression=row["expression"],
        time_zone=row["time_zone"],
        enabled=row["enabled"],
        next_due_at=row["next_due_at"],
        overlap_policy=row["overlap_policy"],
        missed_run_policy=row["missed_run_policy"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_schedule(connection: Connection, schedule_id: UUID) -> Schedule:
    _id(schedule_id)
    row = connection.execute(
        select(schedules).where(schedules.c.id == schedule_id)
    ).one_or_none()
    if row is None:
        raise ScheduleNotFound("Schedule not found")
    return _schedule(row._mapping)


def list_schedules(
    connection: Connection, *, limit: int, after: UUID | None = None
) -> tuple[Schedule, ...]:
    """Return at most 100 records in ascending UUID order, exclusive of after."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Schedule list limit must be between 1 and 100")
    query = select(schedules).order_by(schedules.c.id).limit(limit)
    if after is not None:
        _id(after)
        query = query.where(schedules.c.id > after)
    return tuple(_schedule(row._mapping) for row in connection.execute(query))


def create_schedule(
    connection: Connection,
    schedule_id: UUID,
    workflow_id: UUID,
    revision: str,
    *,
    expression: str,
    time_zone: str,
    enabled: bool,
    cursor: datetime,
) -> Schedule:
    """Create a descriptor in the caller's transaction."""
    _transaction(connection)
    _id(schedule_id)
    values = _values(connection, workflow_id, revision, expression, time_zone, enabled, cursor)
    row = connection.execute(
        insert(schedules)
        .values(id=schedule_id, **values, overlap_policy="skip", missed_run_policy="skip", version=1)
        .on_conflict_do_nothing(index_elements=[schedules.c.id])
        .returning(schedules)
    ).one_or_none()
    if row is None:
        raise ScheduleConflict("Schedule identifier already exists")
    return _schedule(row._mapping)


def update_schedule(
    connection: Connection,
    schedule_id: UUID,
    *,
    expected_version: int,
    workflow_id: UUID,
    revision: str,
    expression: str,
    time_zone: str,
    enabled: bool,
    cursor: datetime,
) -> Schedule:
    """Replace descriptor fields iff version matches; paused next due is null."""
    _transaction(connection)
    _id(schedule_id)
    if type(expected_version) is not int or not 1 <= expected_version < 2147483647:
        raise ValueError("Invalid expected schedule version")
    values = _values(connection, workflow_id, revision, expression, time_zone, enabled, cursor)
    row = connection.execute(
        update(schedules)
        .where(schedules.c.id == schedule_id, schedules.c.version == expected_version)
        .values(**values, version=schedules.c.version + 1, updated_at=func.now())
        .returning(schedules)
    ).one_or_none()
    if row is None:
        get_schedule(connection, schedule_id)
        raise ScheduleConflict("Schedule changed before update")
    return _schedule(row._mapping)
