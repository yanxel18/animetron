"""Persist a verified node plan before exposing a run-ready outbox intent."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Uuid,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Connection

from app.core.outbox import enqueue, outbox
from app.services.workflows.execution_readiness import (
    ExecutionReadiness,
    HandlerCatalog,
    ModelRegistry,
    preflight_run,
)
from app.services.workflows.runs import (
    RunConflict,
    RunNotFound,
    RunState,
    runs,
    transition_run,
)
from app.services.workflows.validation import GraphLimits

RUN_READY_TOPIC = "internal.workflow-run-ready.v1"

metadata = runs.metadata
node_intents = Table(
    "workflow_node_intents",
    metadata,
    Column("run_id", Uuid, ForeignKey(runs.c.id), primary_key=True),
    Column("node_id", String(128), primary_key=True),
    Column("dependencies", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("length(node_id) BETWEEN 1 AND 128", name="ck_workflow_node_intent_id_length"),
)


class DispatchOutcome(StrEnum):
    PREPARED = "PREPARED"
    FAILED = "FAILED"
    ALREADY_PREPARED = "ALREADY_PREPARED"


class RunDispatchCorrupt(Exception):
    pass


@dataclass(frozen=True)
class RunDispatchPreparation:
    outcome: DispatchOutcome
    readiness: ExecutionReadiness | None
    node_count: int


def _outbox_id(run_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"urn:animetron:workflow-run-ready:v1:{run_id}")


def _existing_dispatch(
    connection: Connection,
    run_id: UUID,
) -> RunDispatchPreparation:
    intent_id = _outbox_id(run_id)
    row = connection.execute(
        select(outbox.c.topic, outbox.c.resource_id).where(outbox.c.id == intent_id)
    ).one_or_none()
    if row is None or tuple(row) != (RUN_READY_TOPIC, run_id):
        raise RunDispatchCorrupt("Running workflow has no matching dispatch intent")
    node_count = connection.scalar(
        select(func.count())
        .select_from(node_intents)
        .where(node_intents.c.run_id == run_id)
    )
    return RunDispatchPreparation(
        DispatchOutcome.ALREADY_PREPARED,
        None,
        int(node_count or 0),
    )


def prepare_run_dispatch(
    connection: Connection,
    run_id: UUID,
    handler_catalog: HandlerCatalog,
    model_registry: ModelRegistry,
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> RunDispatchPreparation:
    """Preflight every pin, then atomically persist node intents and a run-ready event."""
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
    if state is RunState.RUNNING:
        return _existing_dispatch(connection, run_id)
    if state is not RunState.QUEUED:
        raise RunConflict("Only queued runs can be prepared for dispatch")

    readiness = preflight_run(
        connection,
        run_id,
        handler_catalog,
        model_registry,
        limits,
        max_bytes=max_bytes,
    )
    if not readiness.ready:
        return RunDispatchPreparation(
            DispatchOutcome.FAILED,
            readiness,
            0,
        )

    for node_id, dependencies in readiness.node_dependencies:
        connection.execute(
            insert(node_intents).values(
                run_id=run_id,
                node_id=node_id,
                dependencies=list(dependencies),
            )
        )
    enqueue(connection, _outbox_id(run_id), RUN_READY_TOPIC, run_id)
    transition_run(
        connection,
        run_id,
        row.sequence,
        RunState.RUNNING,
        "Execution dispatch prepared",
    )
    return RunDispatchPreparation(
        DispatchOutcome.PREPARED,
        readiness,
        len(readiness.node_dependencies),
    )
