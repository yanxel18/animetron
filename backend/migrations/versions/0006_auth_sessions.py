"""Add opaque sessions, single-use login challenges and minimal security audit."""

import sqlalchemy as sa
from alembic import op

revision = "0006_auth_sessions"
down_revision = "0005_artifact_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_login_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("verifier", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_login_states_expires_at", "auth_login_states", ["expires_at"])
    op.create_table(
        "auth_sessions",
        sa.Column("handle_hash", sa.String(64), primary_key=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("principal_id", sa.String(64), nullable=False, unique=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("csrf", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("principal_id", sa.String(64)),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_audit_events_occurred_at", "auth_audit_events", ["occurred_at"])
    op.create_table(
        "auth_rate",
        sa.Column("bucket", sa.BigInteger(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    for table in ("auth_rate", "auth_audit_events", "auth_sessions", "auth_login_states"):
        op.drop_table(table)
