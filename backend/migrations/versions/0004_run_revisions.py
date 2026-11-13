"""Bind workflow runs to stored revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_run_revisions"
down_revision = "0003_workflow_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_revisions",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("workflow_runs.id"), primary_key=True
        ),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id", "revision"],
            ["workflow_revisions.workflow_id", "workflow_revisions.revision"],
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_run_revisions")
