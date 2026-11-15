"""Internal immutable execution bindings, not runtime loading or authorization."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.services.workflows.document import validate_revision_identifier
from app.services.workflows.execution_snapshot import (
    ExecutionNodeDefinition,
    create_execution_snapshot,
)
from app.services.workflows.revisions import get_revision, revisions
from app.services.workflows.validation import GraphLimits

metadata = MetaData()
bindings = Table(
    "workflow_execution_bindings", metadata,
    Column("workflow_id", Uuid, primary_key=True),
    Column("revision", String(128), primary_key=True),
    Column("source_sha256", String(64), nullable=False),
    Column("execution_bytes", LargeBinary, nullable=False),
    Column("execution_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workflow_id", "revision"], [revisions.c.workflow_id, revisions.c.revision],
    ),
    CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_execution_binding_source_sha256"),
    CheckConstraint(
        "execution_sha256 ~ '^[0-9a-f]{64}$'", name="ck_execution_binding_execution_sha256",
    ),
)


@dataclass(frozen=True)
class ExecutionBinding:
    workflow_id: UUID
    revision: str
    source_sha256: str
    execution_bytes: bytes
    execution_sha256: str
    created_at: datetime


class ExecutionBindingNotFound(LookupError):
    pass


class ExecutionBindingConflict(Exception):
    pass


class ExecutionBindingCorrupt(Exception):
    pass


def _guard(connection: Connection, workflow_id: UUID, revision: str) -> None:
    from psycopg import Connection as PsycopgConnection

    driver = connection.connection.driver_connection
    if not connection.in_transaction() or not isinstance(driver, PsycopgConnection) or driver.autocommit:
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    if not isinstance(workflow_id, UUID):
        raise TypeError("Workflow identifier must be a UUID")
    if not isinstance(revision, str):
        raise TypeError("Workflow revision must be a string")
    validate_revision_identifier(revision)


def _load(connection: Connection, workflow_id: UUID, revision: str) -> ExecutionBinding:
    row = connection.execute(
        select(bindings).where(bindings.c.workflow_id == workflow_id, bindings.c.revision == revision)
    ).one_or_none()
    if row is None:
        raise ExecutionBindingNotFound("Execution binding not found")
    source = get_revision(connection, workflow_id, revision)
    data = bytes(row.execution_bytes)
    if source.sha256 != row.source_sha256 or hashlib.sha256(data).hexdigest() != row.execution_sha256:
        raise ExecutionBindingCorrupt("Execution binding failed its integrity check")
    try:
        payload = json.loads(data)
    except (ValueError, RecursionError):
        raise ExecutionBindingCorrupt("Execution binding document is invalid") from None
    if (
        not isinstance(payload, dict) or payload.get("kind") != "internal.workflow-execution"
        or payload.get("revision") != revision or type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != 1
    ):
        raise ExecutionBindingCorrupt("Execution binding association is invalid")
    return ExecutionBinding(
        row.workflow_id, row.revision, row.source_sha256, data, row.execution_sha256, row.created_at,
    )


def get_execution_binding(connection: Connection, workflow_id: UUID, revision: str) -> ExecutionBinding:
    """Load retained bytes with integrity checks, independently of the current catalog."""
    _guard(connection, workflow_id, revision)
    with connection.begin_nested():
        return _load(connection, workflow_id, revision)


def bind_execution_snapshot(
    connection: Connection,
    workflow_id: UUID,
    revision: str,
    expected_sha256: str,
    catalog: Mapping[str, ExecutionNodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> ExecutionBinding:
    """Bind the checked stored source once; the caller owns transaction and authorization."""
    _guard(connection, workflow_id, revision)
    if not isinstance(expected_sha256, str):
        raise TypeError("Expected SHA-256 must be a string")
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("Expected SHA-256 must be 64 lowercase hex characters")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Byte limit must be a positive integer")
    with connection.begin_nested():
        source = get_revision(connection, workflow_id, revision)
        if source.sha256 != expected_sha256:
            raise ExecutionBindingConflict("Expected SHA-256 does not match stored revision")
        execution = create_execution_snapshot(source.canonical_json, catalog, limits, max_bytes=max_bytes)
        connection.execute(
            insert(bindings).values(
                workflow_id=workflow_id, revision=revision, source_sha256=source.sha256,
                execution_bytes=execution.canonical_json, execution_sha256=execution.sha256,
            ).on_conflict_do_nothing(index_elements=[bindings.c.workflow_id, bindings.c.revision])
        )
        record = _load(connection, workflow_id, revision)
        if record.source_sha256 != source.sha256 or record.execution_bytes != execution.canonical_json:
            raise ExecutionBindingConflict("Revision already has a different execution binding")
        return record
