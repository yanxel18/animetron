"""Persist internal schedule descriptors."""

import sqlalchemy as sa
from alembic import op

revision = "p6_02b_schedule_records"
down_revision = "0008_auth_review_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_descriptors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("expression", sa.String(256), nullable=False),
        sa.Column("time_zone", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overlap_policy", sa.String(4), nullable=False),
        sa.Column("missed_run_policy", sa.String(4), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["workflow_id", "revision"], ["workflow_revisions.workflow_id", "workflow_revisions.revision"],
            name="fk_schedule_workflow_revision",
        ),
        sa.CheckConstraint(
            "substr(id::text, 15, 1) = '4' AND substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_schedule_uuid4",
        ),
        sa.CheckConstraint("length(expression) BETWEEN 1 AND 256", name="ck_schedule_expression"),
        sa.CheckConstraint("length(time_zone) BETWEEN 1 AND 255", name="ck_schedule_time_zone"),
        sa.CheckConstraint(
            "(enabled AND next_due_at IS NOT NULL) OR (NOT enabled AND next_due_at IS NULL)",
            name="ck_schedule_next_due",
        ),
        sa.CheckConstraint("overlap_policy = 'skip'", name="ck_schedule_overlap_policy"),
        sa.CheckConstraint("missed_run_policy = 'skip'", name="ck_schedule_missed_policy"),
        sa.CheckConstraint("version > 0", name="ck_schedule_version"),
    )


def downgrade() -> None:
    op.drop_table("schedule_descriptors")
