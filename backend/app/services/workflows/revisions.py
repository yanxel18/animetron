import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    literal,
    select,
    tuple_,
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
Index(
    "ix_workflow_revisions_list_cursor",
    revisions.c.workflow_id,
    revisions.c.created_at,
    revisions.c.revision,
)


@dataclass(frozen=True)
class RevisionCursor:
    created_at: datetime
    revision: str


@dataclass(frozen=True)
class WorkflowRevisionSummary:
    revision: str
    created_at: datetime


class RevisionNotFound(LookupError):
    pass


class RevisionConflict(Exception):
    pass


class RevisionCorrupt(Exception):
    pass


def list_revisions(
    connection: Connection,
    workflow_id: UUID,
    *,
    after: RevisionCursor | None,
    limit: int,
) -> list[WorkflowRevisionSummary]:
    if type(limit) is not int or not 1 <= limit <= 101:
        raise ValueError("Revision page limit is invalid")
    if after is not None:
        if (
            after.created_at.tzinfo is None
            or after.created_at.utcoffset() is None
        ):
            raise ValueError("Revision cursor timestamp must be timezone-aware")
        validate_revision_identifier(after.revision)
        position = tuple_(
            revisions.c.created_at,
            revisions.c.revision,
        ) < tuple_(
            literal(after.created_at, type_=DateTime(timezone=True)),
            literal(after.revision, type_=String(128)),
        )
    else:
        position = None

    statement = select(
        revisions.c.revision,
        revisions.c.created_at,
    ).where(revisions.c.workflow_id == workflow_id)
    if position is not None:
        statement = statement.where(position)
    rows = connection.execute(
        statement.order_by(
            revisions.c.created_at.desc(),
            revisions.c.revision.desc(),
        ).limit(limit)
    )

    summaries: list[WorkflowRevisionSummary] = []
    for row in rows:
        if (
            not isinstance(row.revision, str)
            or not isinstance(row.created_at, datetime)
            or row.created_at.tzinfo is None
            or row.created_at.utcoffset() is None
        ):
            raise RevisionCorrupt("Workflow revision metadata is invalid")
        try:
            validate_revision_identifier(row.revision)
        except ValueError:
            raise RevisionCorrupt("Workflow revision metadata is invalid") from None
        summaries.append(
            WorkflowRevisionSummary(
                revision=row.revision,
                created_at=row.created_at.astimezone(UTC),
            )
        )
    return summaries


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
