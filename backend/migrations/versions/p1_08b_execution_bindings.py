"""Retain immutable execution snapshots for workflow revisions."""

import sqlalchemy as sa
from alembic import op

revision = "p1_08b_execution_bindings"
down_revision = "p1_09a_run_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_execution_bindings",
        sa.Column("workflow_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.String(128), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("execution_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("execution_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["workflow_id", "revision"], ["workflow_revisions.workflow_id", "workflow_revisions.revision"],
        ),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_execution_binding_source_sha256"),
        sa.CheckConstraint(
            "execution_sha256 ~ '^[0-9a-f]{64}$'", name="ck_execution_binding_execution_sha256",
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_workflow_execution_binding() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Execution bindings cannot be changed or deleted'
                USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER workflow_execution_binding_immutable
        BEFORE UPDATE OR DELETE ON workflow_execution_bindings
        FOR EACH ROW EXECUTE FUNCTION guard_workflow_execution_binding()
    """)


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization and recovery required.
    op.drop_table("workflow_execution_bindings")
    op.execute("DROP FUNCTION guard_workflow_execution_binding()")
