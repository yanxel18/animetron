"""Persist durable workflow node admission claims."""

import sqlalchemy as sa
from alembic import op

revision = "p1_10d_node_admission"
down_revision = "p1_10c_dispatch_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_claims",
        sa.Column("claim_id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "node_id"],
            ["workflow_node_intents.run_id", "workflow_node_intents.node_id"],
        ),
        sa.UniqueConstraint("run_id", "node_id", name="uq_workflow_node_claim"),
        sa.CheckConstraint(
            "substr(claim_id::text, 15, 1) = '4' AND "
            "substr(claim_id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_workflow_node_claim_uuid4",
        ),
    )


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization/recovery required.
    op.drop_table("workflow_node_claims")
