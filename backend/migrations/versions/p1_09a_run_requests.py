"""Retain internal idempotent run-request associations."""

import sqlalchemy as sa
from alembic import op

revision = "p1_09a_run_requests"
down_revision = "p4_04a_review_queue_20261114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workflow_runs.id"], deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "revision"],
            ["workflow_revisions.workflow_id", "workflow_revisions.revision"],
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "substr(request_id::text, 15, 1) = '4' AND "
            "substr(request_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_run_request_uuid4",
        ),
        sa.CheckConstraint(
            "substr(run_id::text, 15, 1) = '4' AND "
            "substr(run_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_run_request_run_uuid4",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_run_request_sha256"),
    )
    op.execute("""
        CREATE FUNCTION guard_workflow_run_request() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Run request records cannot be changed or deleted'
                USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER workflow_run_request_immutable
        BEFORE UPDATE OR DELETE ON workflow_run_requests
        FOR EACH ROW EXECUTE FUNCTION guard_workflow_run_request()
    """)


def downgrade() -> None:
    op.drop_table("workflow_run_requests")
    op.execute("DROP FUNCTION guard_workflow_run_request()")
