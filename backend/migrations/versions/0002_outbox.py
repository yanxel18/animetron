"""Create transactional outbox intents."""

import sqlalchemy as sa
from alembic import op

revision = "0002_outbox"
down_revision = "0001_run_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_intents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)", name="ck_outbox_lease_pair"
        ),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_intents",
        ["topic", "created_at", "id"],
        postgresql_where=sa.text("delivered_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox_intents")
    op.drop_table("outbox_intents")
