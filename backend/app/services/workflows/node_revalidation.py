"""Point-in-time revalidation of an admitted node, not authority to execute."""

from uuid import RFC_4122, UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.services.workflows.execution_readiness import (
    ExecutionReadiness,
    HandlerCatalog,
    ModelRegistry,
    ReadinessFailureCode,
    _load_run_pins,
    _resolve_pins,
)
from app.services.workflows.node_admission import claims
from app.services.workflows.node_outcomes import outcomes
from app.services.workflows.run_dispatch import _existing_dispatch, node_intents
from app.services.workflows.runs import RunConflict, RunNotFound, RunState, runs
from app.services.workflows.validation import GraphLimits


class RevalidationConflict(Exception):
    pass


def revalidate_admitted_node(
    connection: Connection,
    claim_id: UUID,
    run_id: UUID,
    node_id: str,
    handler_catalog: HandlerCatalog,
    model_registry: ModelRegistry,
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> ExecutionReadiness:
    """Check current evidence; returned handles are not permission to invoke."""
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
        state = connection.scalar(select(runs.c.state).where(runs.c.id == run_id).with_for_update())
        if state is None:
            raise RunNotFound("Run not found")
        if RunState(state) is not RunState.RUNNING:
            raise RunConflict("Only running workflows can be revalidated")
        association = connection.execute(
            select(claims.c.run_id, claims.c.node_id)
            .where(claims.c.claim_id == claim_id)
            .with_for_update()
        ).one_or_none()
        if association is None or tuple(association) != (run_id, node_id):
            raise RevalidationConflict("Claim not found or association does not match")
        if connection.scalar(select(outcomes.c.claim_id).where(outcomes.c.claim_id == claim_id)):
            raise RevalidationConflict("Claim already has a confirmed outcome")
        _existing_dispatch(connection, run_id)
        pins = _load_run_pins(connection, run_id, limits, max_bytes=max_bytes)
        if isinstance(pins, ReadinessFailureCode):
            return ExecutionReadiness(False, pins)
        actual = connection.execute(
            select(node_intents.c.node_id, node_intents.c.dependencies)
            .where(node_intents.c.run_id == run_id)
            .limit(limits.max_nodes + 1)
        ).all()
        expected = {node.node_id: list(node.dependencies) for node in pins}
        if (
            len(actual) != len(expected)
            or {row.node_id: row.dependencies for row in actual} != expected
            or node_id not in expected
            or expected[node_id] != []
        ):
            raise RevalidationConflict("Persisted node plan does not match execution snapshot")
        return _resolve_pins(pins, handler_catalog, model_registry)
