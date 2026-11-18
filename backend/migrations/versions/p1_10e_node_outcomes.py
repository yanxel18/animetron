"""Persist immutable confirmed workflow node outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "p1_10e_node_outcomes"
down_revision = "p1_10d_node_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_outcomes",
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("workflow_node_claims.claim_id"), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND error_code IS NULL) OR "
            "(status = 'FAILED' AND error_code IS NOT NULL AND error_code = 'EXECUTION_FAILED')",
            name="ck_workflow_node_outcome_result",
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_workflow_node_outcome() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'workflow node outcomes are immutable';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER workflow_node_outcome_immutable
        BEFORE UPDATE OR DELETE ON workflow_node_outcomes
        FOR EACH ROW EXECUTE FUNCTION guard_workflow_node_outcome()
    """)


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization/recovery required.
    op.drop_table("workflow_node_outcomes")
    op.execute("DROP FUNCTION guard_workflow_node_outcome()")
