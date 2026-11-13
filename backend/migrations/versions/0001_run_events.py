"""Create durable workflow runs and ordered events."""

import sqlalchemy as sa
from alembic import op

revision = "0001_run_events"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_workflow_run_sequence_positive"),
    )
    op.create_table(
        "workflow_run_events",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("workflow_runs.id"), primary_key=True
        ),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("sequence > 0", name="ck_workflow_event_sequence_positive"),
    )


def downgrade() -> None:
    op.drop_table("workflow_run_events")
    op.drop_table("workflow_runs")
