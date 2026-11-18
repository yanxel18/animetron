"""Record independently confirmed node outcomes without dispatching work."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import RFC_4122, UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Uuid,
    func,
    select,
)
from sqlalchemy.engine import Connection

from app.services.workflows.node_admission import claims, metadata
from app.services.workflows.runs import RunNotFound, runs

outcomes = Table(
    "workflow_node_outcomes",
    metadata,
    Column("claim_id", Uuid, ForeignKey(claims.c.claim_id), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("error_code", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "(status = 'SUCCEEDED' AND error_code IS NULL) OR "
        "(status = 'FAILED' AND error_code IS NOT NULL AND error_code = 'EXECUTION_FAILED')",
        name="ck_workflow_node_outcome_result",
    ),
)


class NodeStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class FailureCode(StrEnum):
    EXECUTION_FAILED = "EXECUTION_FAILED"


class OutcomeConflict(Exception):
    pass


@dataclass(frozen=True)
class ConfirmedOutcome:
    claim_id: UUID
    run_id: UUID
    node_id: str
    status: NodeStatus
    error_code: FailureCode | None
    recorded: bool


def record_outcome(
    connection: Connection,
    claim_id: UUID,
    run_id: UUID,
    node_id: str,
    status: NodeStatus,
    error_code: FailureCode | None = None,
) -> ConfirmedOutcome:
    """Persist trusted evidence; the claim identifier is not authentication."""
    if not connection.in_transaction():
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    driver = connection.connection.driver_connection
    if not isinstance(driver, PsycopgConnection) or driver.autocommit:
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    if not isinstance(claim_id, UUID) or claim_id.version != 4 or claim_id.variant != RFC_4122:
        raise ValueError("Claim identifier must be an RFC-variant UUID4")
    if not isinstance(run_id, UUID):
        raise TypeError("Run identifier must be a UUID")
    if not isinstance(node_id, str) or not 1 <= len(node_id) <= 128 or "\0" in node_id:
        raise ValueError("Invalid node identifier")
    if not isinstance(status, NodeStatus) or (
        status is NodeStatus.SUCCEEDED and error_code is not None
    ) or (
        status is NodeStatus.FAILED and not isinstance(error_code, FailureCode)
    ):
        raise ValueError("Invalid confirmed outcome")

    with connection.begin_nested():
        state = connection.scalar(select(runs.c.state).where(runs.c.id == run_id).with_for_update())
        if state is None:
            raise RunNotFound("Run not found")
        association = connection.execute(
            select(claims.c.run_id, claims.c.node_id)
            .where(claims.c.claim_id == claim_id)
            .with_for_update()
        ).one_or_none()
        if association is None or tuple(association) != (run_id, node_id):
            raise OutcomeConflict("Claim not found or association does not match")
        existing = connection.execute(
            select(outcomes.c.status, outcomes.c.error_code).where(outcomes.c.claim_id == claim_id)
        ).one_or_none()
        if existing is not None:
            if tuple(existing) != (status.value, error_code.value if error_code else None):
                raise OutcomeConflict("Claim already has a different outcome")
            return ConfirmedOutcome(claim_id, run_id, node_id, status, error_code, False)
        connection.execute(outcomes.insert().values(
            claim_id=claim_id, status=status.value, error_code=error_code.value if error_code else None,
        ))
        return ConfirmedOutcome(claim_id, run_id, node_id, status, error_code, True)
