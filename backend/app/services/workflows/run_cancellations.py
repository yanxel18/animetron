"""Persist cooperative run-cancellation intents."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.core.outbox import enqueue, outbox
from app.services.workflows.runs import (
    RunConflict,
    RunNotFound,
    RunState,
    runs,
    transition_run,
)

CANCELLATION_TOPIC = "internal.workflow-run-cancellation-requested.v1"


class CancellationOutcome(StrEnum):
    REQUESTED = "REQUESTED"
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    ALREADY_CANCELLED = "ALREADY_CANCELLED"


class RunCancellationCorrupt(Exception):
    pass


@dataclass(frozen=True)
class RunCancellationResult:
    run_id: UUID
    state: RunState
    last_sequence: int
    outcome: CancellationOutcome


def _intent_id(run_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"urn:animetron:workflow-run-cancellation-requested:v1:{run_id}",
    )


def _verify_intent(connection: Connection, run_id: UUID) -> None:
    row = connection.execute(
        select(outbox.c.topic, outbox.c.resource_id).where(
            outbox.c.id == _intent_id(run_id)
        )
    ).one_or_none()
    if row is None or tuple(row) != (CANCELLATION_TOPIC, run_id):
        raise RunCancellationCorrupt("Run cancellation state has no matching intent")


def request_run_cancellation(
    connection: Connection,
    run_id: UUID,
) -> RunCancellationResult:
    """Request cancellation without claiming the worker has stopped."""
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    row = connection.execute(
        select(runs.c.state, runs.c.sequence)
        .where(runs.c.id == run_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise RunNotFound("Run not found")
    state = RunState(row.state)

    if state in {RunState.QUEUED, RunState.RUNNING, RunState.WAITING_REVIEW}:
        enqueue(connection, _intent_id(run_id), CANCELLATION_TOPIC, run_id)
        transition_run(
            connection,
            run_id,
            row.sequence,
            RunState.CANCELLING,
            "Cancellation requested",
        )
        return RunCancellationResult(
            run_id,
            RunState.CANCELLING,
            row.sequence + 1,
            CancellationOutcome.REQUESTED,
        )

    if state in {RunState.CANCELLING, RunState.CANCELLED}:
        _verify_intent(connection, run_id)
        outcome = (
            CancellationOutcome.ALREADY_CANCELLED
            if state is RunState.CANCELLED
            else CancellationOutcome.ALREADY_REQUESTED
        )
        return RunCancellationResult(run_id, state, row.sequence, outcome)

    raise RunConflict("Only active runs can be cancelled")
