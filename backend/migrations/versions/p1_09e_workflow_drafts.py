"""Persist mutable workflow drafts separately from immutable revisions."""

import sqlalchemy as sa
from alembic import op

revision = "p1_09e_workflow_drafts"
down_revision = "p6_02d_due_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_drafts",
        sa.Column("workflow_id", sa.Uuid(), primary_key=True),
        sa.Column("document", sa.LargeBinary(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_workflow_draft_version"),
    )


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization/recovery required.
    op.drop_table("workflow_drafts")
