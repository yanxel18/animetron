"""Create a sample revision from a locked, versioned draft."""

from uuid import UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy.engine import Connection

from app.services.workflows.drafts import WorkflowDraftConflict, get_draft
from app.services.workflows.revisions import save_revision
from app.services.workflows.sample_evaluator import (
    MAX_SAMPLE_DOCUMENT_BYTES,
    SAMPLE_DEFINITIONS,
    SAMPLE_GRAPH_LIMITS,
)
from app.services.workflows.snapshot import WorkflowSnapshot, create_snapshot


class RevisionCanonicalTooLarge(Exception):
    pass


def create_sample_revision(
    connection: Connection, workflow_id: UUID, expected_version: int
) -> WorkflowSnapshot:
    if not connection.in_transaction():
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    driver = connection.connection.driver_connection
    if not isinstance(driver, PsycopgConnection) or driver.autocommit:
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    draft = get_draft(connection, workflow_id, for_update=True)
    if draft.version != expected_version:
        raise WorkflowDraftConflict("Workflow draft changed before revision creation")
    snapshot = create_snapshot(
        draft.document, SAMPLE_DEFINITIONS, SAMPLE_GRAPH_LIMITS,
        max_bytes=MAX_SAMPLE_DOCUMENT_BYTES,
    )
    if len(snapshot.canonical_json) > MAX_SAMPLE_DOCUMENT_BYTES:
        raise RevisionCanonicalTooLarge("Canonical workflow revision exceeds byte limit")
    return save_revision(
        connection, workflow_id, draft.document, SAMPLE_DEFINITIONS,
        SAMPLE_GRAPH_LIMITS, max_bytes=MAX_SAMPLE_DOCUMENT_BYTES,
    )
