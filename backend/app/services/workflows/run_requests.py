"""Internal run-request persistence, never execution or authorization."""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import RFC_4122, UUID, uuid4

from psycopg import Connection as PsycopgConnection
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.core.outbox import enqueue, outbox
from app.services.workflows.document import validate_revision_identifier
from app.services.workflows.revisions import get_revision, revisions
from app.services.workflows.run_revisions import create_run_with_revision, run_revisions
from app.services.workflows.runs import events, runs

INTERNAL_TOPIC = "internal.workflow-run-requested.v1"

metadata = MetaData()
run_requests = Table(
    "workflow_run_requests",
    metadata,
    Column("request_id", Uuid, primary_key=True),
    Column(
        "run_id", Uuid,
        ForeignKey(runs.c.id, deferrable=True, initially="DEFERRED"),
        nullable=False, unique=True,
    ),
    Column("workflow_id", Uuid, nullable=False),
    Column("revision", String(128), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workflow_id", "revision"], [revisions.c.workflow_id, revisions.c.revision],
        deferrable=True, initially="DEFERRED",
    ),
    CheckConstraint(
        "substr(request_id::text, 15, 1) = '4' AND "
        "substr(request_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_run_request_uuid4",
    ),
    CheckConstraint(
        "substr(run_id::text, 15, 1) = '4' AND "
        "substr(run_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_run_request_run_uuid4",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_run_request_sha256"),
)


@dataclass(frozen=True)
class RunRequest:
    request_id: UUID
    run_id: UUID
    workflow_id: UUID
    revision: str
    sha256: str
    created_at: datetime


class RunRequestConflict(Exception):
    pass


class RunRequestCorrupt(Exception):
    pass


def _uuid4(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError("Request and run identifiers must be UUIDs")
    if value.version != 4 or value.variant != RFC_4122:
        raise ValueError("Request and run identifiers must be RFC-variant UUID4")


def _check_evidence(connection: Connection, record: RunRequest) -> None:
    _uuid4(record.run_id)
    run = connection.scalar(select(runs.c.id).where(runs.c.id == record.run_id))
    binding = connection.execute(
        select(run_revisions.c.workflow_id, run_revisions.c.revision)
        .where(run_revisions.c.run_id == record.run_id)
    ).one_or_none()
    initial = connection.execute(
        select(events.c.state, events.c.message)
        .where(events.c.run_id == record.run_id, events.c.sequence == 1)
    ).one_or_none()
    intent = connection.execute(
        select(outbox.c.topic, outbox.c.resource_id)
        .where(outbox.c.id == record.request_id)
    ).one_or_none()
    if (
        run is None
        or binding is None
        or tuple(binding) != (record.workflow_id, record.revision)
        or initial is None
        or tuple(initial) != ("QUEUED", "Queued")
        or intent is None
        or tuple(intent) != (INTERNAL_TOPIC, record.run_id)
    ):
        raise RunRequestCorrupt("Run request is missing or has inconsistent service evidence")


def request_run(
    connection: Connection,
    request_id: UUID,
    workflow_id: UUID,
    revision: str,
    expected_sha256: str,
) -> RunRequest:
    """Persist/replay one internal request; caller owns transaction and authorization."""
    driver = connection.connection.driver_connection
    if (
        not connection.in_transaction()
        or not isinstance(driver, PsycopgConnection)
        or driver.autocommit
    ):
        raise RuntimeError("An explicit non-autocommit psycopg transaction is required")
    _uuid4(request_id)
    if not isinstance(workflow_id, UUID):
        raise TypeError("Workflow identifier must be a UUID")
    if not isinstance(revision, str):
        raise TypeError("Workflow revision must be a string")
    validate_revision_identifier(revision)
    if not isinstance(expected_sha256, str):
        raise TypeError("Expected SHA-256 must be a string")
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("Expected SHA-256 must be 64 lowercase hex characters")

    with connection.begin_nested():
        # Claim before creating anything. The unique key waits for a concurrent
        # winner; deferred FKs allow the canonical run/binding path to follow.
        inserted = connection.execute(
            insert(run_requests)
            .values(
                request_id=request_id, run_id=uuid4(), workflow_id=workflow_id,
                revision=revision, sha256=expected_sha256,
            )
            .on_conflict_do_nothing(index_elements=[run_requests.c.request_id])
            .returning(run_requests.c.request_id)
        ).scalar_one_or_none()
        row = connection.execute(
            select(run_requests).where(run_requests.c.request_id == request_id)
            .with_for_update()
        ).one()
        record = RunRequest(
            row.request_id, row.run_id, row.workflow_id,
            row.revision, row.sha256, row.created_at,
        )
        if (record.workflow_id, record.revision, record.sha256) != (
            workflow_id, revision, expected_sha256,
        ):
            raise RunRequestConflict("Request identity already has a different payload")
        snapshot = get_revision(connection, workflow_id, revision)
        if snapshot.sha256 != expected_sha256:
            raise RunRequestConflict("Expected SHA-256 does not match stored snapshot")
        if inserted is not None:
            create_run_with_revision(connection, record.run_id, workflow_id, revision)
            enqueue(connection, request_id, INTERNAL_TOPIC, record.run_id)
        _check_evidence(connection, record)
        return record
