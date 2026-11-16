"""Internal mutable workflow draft persistence; no validation or execution."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Uuid,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
drafts = Table(
    "workflow_drafts",
    metadata,
    Column("workflow_id", Uuid, primary_key=True),
    Column("document", LargeBinary, nullable=False),
    Column("version", Integer, nullable=False),
    CheckConstraint("version > 0", name="ck_workflow_draft_version"),
)


@dataclass(frozen=True)
class WorkflowDraft:
    workflow_id: UUID
    document: bytes
    version: int


class WorkflowDraftNotFound(LookupError):
    pass


class WorkflowDraftConflict(Exception):
    pass


class WorkflowDraftCorrupt(Exception):
    pass


def _workflow_id(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError("Workflow identifier must be a UUID")


def _draft(row: RowMapping) -> WorkflowDraft:
    if (
        not isinstance(row["workflow_id"], UUID)
        or not isinstance(row["document"], bytes)
        or type(row["version"]) is not int
        or row["version"] < 1
    ):
        raise WorkflowDraftCorrupt("Workflow draft metadata is invalid")
    try:
        row["document"].decode("utf-8")
    except UnicodeDecodeError:
        raise WorkflowDraftCorrupt("Workflow draft is not valid UTF-8") from None
    return WorkflowDraft(row["workflow_id"], row["document"], row["version"])


def get_draft(connection: Connection, workflow_id: UUID) -> WorkflowDraft:
    _workflow_id(workflow_id)
    row = connection.execute(
        select(drafts).where(drafts.c.workflow_id == workflow_id)
    ).one_or_none()
    if row is None:
        raise WorkflowDraftNotFound("Workflow draft not found")
    return _draft(row._mapping)


def save_draft(
    connection: Connection,
    workflow_id: UUID,
    document: bytes,
    *,
    expected_version: int | None,
    max_bytes: int,
) -> WorkflowDraft:
    """Create or compare-and-swap a draft in the caller's transaction."""
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    _workflow_id(workflow_id)
    if not isinstance(document, bytes):
        raise TypeError("Workflow draft must be bytes")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Draft byte limit must be a positive integer")
    if len(document) > max_bytes:
        raise ValueError("Workflow draft exceeds byte limit")
    try:
        document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Workflow draft must be valid UTF-8") from None
    if expected_version is not None and (
        type(expected_version) is not int or not 1 <= expected_version < 2_147_483_647
    ):
        raise ValueError("Expected draft version is invalid")

    if expected_version is None:
        try:
            with connection.begin_nested():
                inserted = connection.execute(
                    insert(drafts)
                    .values(workflow_id=workflow_id, document=document, version=1)
                    .returning(drafts)
                ).one()
        except IntegrityError:
            existing = connection.execute(
                select(drafts.c.workflow_id).where(drafts.c.workflow_id == workflow_id)
            ).one_or_none()
            if existing is not None:
                raise WorkflowDraftConflict("Workflow draft already exists") from None
            raise
        return _draft(inserted._mapping)

    updated = connection.execute(
        update(drafts)
        .where(
            drafts.c.workflow_id == workflow_id,
            drafts.c.version == expected_version,
        )
        .values(document=document, version=drafts.c.version + 1)
        .returning(drafts)
    ).one_or_none()
    if updated is not None:
        return _draft(updated._mapping)
    existing = connection.execute(
        select(drafts.c.workflow_id).where(drafts.c.workflow_id == workflow_id)
    ).one_or_none()
    if existing is None:
        raise WorkflowDraftNotFound("Workflow draft not found")
    raise WorkflowDraftConflict("Workflow draft changed before update")
