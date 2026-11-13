from uuid import UUID

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    Uuid,
    insert,
    select,
)
from sqlalchemy.engine import Connection

from app.services.workflows.revisions import get_revision, revisions
from app.services.workflows.runs import create_run, runs
from app.services.workflows.snapshot import WorkflowSnapshot

metadata = MetaData()
run_revisions = Table(
    "workflow_run_revisions",
    metadata,
    Column("run_id", Uuid, ForeignKey(runs.c.id), primary_key=True),
    Column("workflow_id", Uuid, nullable=False),
    Column("revision", String(128), nullable=False),
    ForeignKeyConstraint(
        ["workflow_id", "revision"], [revisions.c.workflow_id, revisions.c.revision]
    ),
)


class RunRevisionNotFound(LookupError):
    pass


def create_run_with_revision(
    connection: Connection, run_id: UUID, workflow_id: UUID, revision: str
) -> None:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    get_revision(connection, workflow_id, revision)
    create_run(connection, run_id)
    connection.execute(
        insert(run_revisions).values(
            run_id=run_id, workflow_id=workflow_id, revision=revision
        )
    )


def get_run_snapshot(connection: Connection, run_id: UUID) -> WorkflowSnapshot:
    row = connection.execute(
        select(run_revisions.c.workflow_id, run_revisions.c.revision).where(
            run_revisions.c.run_id == run_id
        )
    ).one_or_none()
    if row is None:
        raise RunRevisionNotFound("Run has no bound workflow revision")
    return get_revision(connection, row.workflow_id, row.revision)
