"""Bound shared denial auditing independently of login traffic."""

import sqlalchemy as sa
from alembic import op

revision = "0007_auth_denial_counters"
down_revision = "0006_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_denial_counters",
        sa.Column("event", sa.String(32), primary_key=True),
        sa.Column("slot", sa.Integer(), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrences", sa.BigInteger(), nullable=False),
        sa.Column("last_request_id", sa.String(36), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event IN ('access_denied', 'login_failed')", name="ck_denial_event"),
        sa.CheckConstraint("slot >= 0 AND slot < 96", name="ck_denial_slot"),
        sa.CheckConstraint("occurrences > 0", name="ck_denial_occurrences"),
    )


def downgrade() -> None:
    op.drop_table("auth_denial_counters")
