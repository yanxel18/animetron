"""Persist verified node plans before exposing runs to execution workers."""

import sqlalchemy as sa
from alembic import op

revision = "p1_10c_dispatch_intents"
down_revision = "p1_09e_workflow_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_intents",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(node_id) BETWEEN 1 AND 128",
            name="ck_workflow_node_intent_id_length",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("run_id", "node_id"),
    )


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization/recovery required.
    op.drop_table("workflow_node_intents")
