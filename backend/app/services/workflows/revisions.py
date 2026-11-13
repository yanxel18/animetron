import hashlib
import json
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
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
from app.services.workflows.snapshot import WorkflowSnapshot, create_snapshot
from app.services.workflows.validation import GraphLimits, NodeDefinition

metadata = MetaData()
revisions = Table(
    "workflow_revisions",
    metadata,
    Column("workflow_id", Uuid, primary_key=True),
    Column("revision", String(128), primary_key=True),
    Column("document", LargeBinary, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)


class RevisionNotFound(LookupError):
    pass


class RevisionConflict(Exception):
    pass


class RevisionCorrupt(Exception):
    pass


def get_revision(
    connection: Connection, workflow_id: UUID, revision: str
) -> WorkflowSnapshot:
    validate_revision_identifier(revision)
    row = connection.execute(
        select(revisions.c.document, revisions.c.sha256).where(
            revisions.c.workflow_id == workflow_id, revisions.c.revision == revision
        )
    ).one_or_none()
    if row is None:
        raise RevisionNotFound("Workflow revision not found")
    document = bytes(row.document)
    if hashlib.sha256(document).hexdigest() != row.sha256:
        raise RevisionCorrupt("Workflow revision failed its integrity check")
    try:
        payload = json.loads(document)
    except (ValueError, RecursionError):
        raise RevisionCorrupt("Workflow revision document is invalid") from None
    if not isinstance(payload, dict) or payload.get("revision") != revision:
        raise RevisionCorrupt("Workflow revision identifier does not match document")
    return WorkflowSnapshot(
        revision=revision, canonical_json=document, sha256=row.sha256
    )


def save_revision(
    connection: Connection,
    workflow_id: UUID,
    data: bytes,
    definitions: Mapping[str, NodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> WorkflowSnapshot:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    snapshot = create_snapshot(data, definitions, limits, max_bytes=max_bytes)
    result = connection.execute(
        insert(revisions)
        .values(
            workflow_id=workflow_id,
            revision=snapshot.revision,
            document=snapshot.canonical_json,
            sha256=snapshot.sha256,
        )
        .on_conflict_do_nothing(
            index_elements=[revisions.c.workflow_id, revisions.c.revision]
        )
        .returning(revisions.c.workflow_id)
    )
    if result.scalar_one_or_none() is not None:
        return snapshot
    existing = get_revision(connection, workflow_id, snapshot.revision)
    if existing != snapshot:
        raise RevisionConflict("Workflow revision already contains different content")
    return existing
