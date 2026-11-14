"""Index stable review queue keyset ordering."""

from alembic import op

revision = "p4_04a_review_queue_20261114"
down_revision = "p6_02b_schedule_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_review_queue_created_id",
        "review_requests",
        ["created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_queue_created_id", table_name="review_requests")
