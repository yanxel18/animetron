"""Durable node admission without executing or retrying work."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import RFC_4122, UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.services.workflows.run_dispatch import (
    _existing_dispatch,
    node_intents,
)
from app.services.workflows.runs import RunConflict, RunNotFound, RunState, runs

metadata = MetaData()
claims = Table(
    "workflow_node_claims",
    metadata,
    Column("claim_id", Uuid, primary_key=True),
    Column("run_id", Uuid, nullable=False),
    Column("node_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["run_id", "node_id"], [node_intents.c.run_id, node_intents.c.node_id],
    ),
    UniqueConstraint("run_id", "node_id", name="uq_workflow_node_claim"),
    CheckConstraint(
        "substr(claim_id::text, 15, 1) = '4' AND "
        "substr(claim_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_workflow_node_claim_uuid4",
    ),
)


class AdmissionConflict(Exception):
    pass


class AdmissionOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"


@dataclass(frozen=True)
class NodeAdmission:
    claim_id: UUID
    run_id: UUID
    node_id: str
    outcome: AdmissionOutcome


def claim_node(
    connection: Connection, claim_id: UUID, run_id: UUID, node_id: str,
) -> NodeAdmission:
    """Claim a prepared root node; a replay does not authorize execution."""
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

    with connection.begin_nested():
        state = connection.scalar(
            select(runs.c.state).where(runs.c.id == run_id).with_for_update()
        )
        if state is None:
            raise RunNotFound("Run not found")
        existing = connection.execute(
            select(claims.c.run_id, claims.c.node_id).where(claims.c.claim_id == claim_id)
        ).one_or_none()
        if existing is not None:
            if tuple(existing) != (run_id, node_id):
                raise AdmissionConflict("Claim identity has a different association")
            return NodeAdmission(claim_id, run_id, node_id, AdmissionOutcome.ALREADY_CLAIMED)
        if RunState(state) is not RunState.RUNNING:
            raise RunConflict("Only running workflows can admit nodes")
        _existing_dispatch(connection, run_id)
        dependencies = connection.execute(
            select(node_intents.c.dependencies).where(
                node_intents.c.run_id == run_id, node_intents.c.node_id == node_id,
            )
        ).one_or_none()
        if dependencies is None or dependencies.dependencies != []:
            raise AdmissionConflict("Node is missing or not eligible for admission")
        inserted = connection.execute(
            insert(claims)
            .values(claim_id=claim_id, run_id=run_id, node_id=node_id)
            .on_conflict_do_nothing()
            .returning(claims.c.claim_id)
        ).scalar_one_or_none()
        if inserted is None:
            existing = connection.execute(
                select(claims.c.run_id, claims.c.node_id).where(claims.c.claim_id == claim_id)
            ).one_or_none()
            if existing is not None and tuple(existing) == (run_id, node_id):
                return NodeAdmission(
                    claim_id, run_id, node_id, AdmissionOutcome.ALREADY_CLAIMED,
                )
            raise AdmissionConflict("Node or claim identity is already claimed")
        return NodeAdmission(claim_id, run_id, node_id, AdmissionOutcome.CLAIMED)
