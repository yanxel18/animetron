from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection


class RunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_REVIEW = "WAITING_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    RunState.QUEUED: {RunState.RUNNING, RunState.CANCELLING, RunState.FAILED},
    RunState.RUNNING: {
        RunState.WAITING_REVIEW,
        RunState.SUCCEEDED,
        RunState.PARTIAL_FAILURE,
        RunState.FAILED,
        RunState.CANCELLING,
    },
    RunState.WAITING_REVIEW: {
        RunState.RUNNING,
        RunState.FAILED,
        RunState.CANCELLING,
    },
    RunState.CANCELLING: {RunState.CANCELLED, RunState.FAILED},
}

metadata = MetaData()
runs = Table(
    "workflow_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("state", String(20), nullable=False),
    Column("sequence", Integer, nullable=False),
    CheckConstraint("sequence > 0", name="ck_workflow_run_sequence_positive"),
)
events = Table(
    "workflow_run_events",
    metadata,
    Column("run_id", Uuid, ForeignKey("workflow_runs.id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("state", String(20), nullable=False),
    Column("message", String(1000), nullable=False),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("sequence > 0", name="ck_workflow_event_sequence_positive"),
)


class RunNotFound(LookupError):
    pass


class RunConflict(Exception):
    pass


class InvalidRunTransition(ValueError):
    pass


@dataclass(frozen=True)
class RunEvent:
    run_id: UUID
    sequence: int
    state: RunState
    message: str
    occurred_at: datetime


@dataclass(frozen=True)
class RunStatus:
    run_id: UUID
    state: RunState
    last_sequence: int


def get_run_status(connection: Connection, run_id: UUID) -> RunStatus:
    row = connection.execute(
        select(runs.c.id, runs.c.state, runs.c.sequence).where(runs.c.id == run_id)
    ).one_or_none()
    if row is None:
        raise RunNotFound("Run not found")
    return RunStatus(row.id, RunState(row.state), row.sequence)


def create_run(connection: Connection, run_id: UUID) -> None:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    connection.execute(
        insert(runs).values(id=run_id, state=RunState.QUEUED.value, sequence=1)
    )
    connection.execute(
        insert(events).values(
            run_id=run_id, sequence=1, state=RunState.QUEUED.value, message="Queued"
        )
    )


def transition_run(
    connection: Connection,
    run_id: UUID,
    expected_sequence: int,
    state: RunState,
    message: str,
) -> None:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    if not message.strip() or len(message) > 1000:
        raise ValueError("Event message must contain 1 to 1000 characters")
    row = connection.execute(
        select(runs.c.state, runs.c.sequence)
        .where(runs.c.id == run_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise RunNotFound("Run not found")
    if row.sequence != expected_sequence:
        raise RunConflict("Run sequence has changed")
    if state not in TRANSITIONS.get(RunState(row.state), set()):
        raise InvalidRunTransition("Run state transition is not allowed")
    sequence = row.sequence + 1
    connection.execute(
        update(runs)
        .where(runs.c.id == run_id)
        .values(state=state.value, sequence=sequence)
    )
    connection.execute(
        insert(events).values(
            run_id=run_id, sequence=sequence, state=state.value, message=message
        )
    )


def list_events(
    connection: Connection, run_id: UUID, after_sequence: int, limit: int = 100
) -> list[RunEvent]:
    if after_sequence < 0 or not 1 <= limit <= 500:
        raise ValueError("Replay cursor or limit is invalid")
    if connection.scalar(select(runs.c.id).where(runs.c.id == run_id)) is None:
        raise RunNotFound("Run not found")
    rows = connection.execute(
        select(events)
        .where(events.c.run_id == run_id, events.c.sequence > after_sequence)
        .order_by(events.c.sequence)
        .limit(limit)
    )
    return [
        RunEvent(
            row.run_id, row.sequence, RunState(row.state), row.message, row.occurred_at
        )
        for row in rows
    ]
