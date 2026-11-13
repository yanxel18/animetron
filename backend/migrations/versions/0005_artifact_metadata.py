"""Add internal immutable artifact metadata storage."""

import sqlalchemy as sa
from alembic import op

revision = "0005_artifact_metadata"
down_revision = "0004_run_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_metadata",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("storage_locator", sa.String(42), nullable=False),
        sa.CheckConstraint(
            "substr(id::text, 15, 1) = '4' AND "
            "substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_artifact_uuid4",
        ),
        sa.CheckConstraint(
            "owner_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
            name="ck_artifact_owner",
        ),
        sa.CheckConstraint(
            "revision ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
            name="ck_artifact_revision",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_sha256"
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_artifact_byte_size"),
        sa.CheckConstraint(
            "media_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]*/"
            "[a-z0-9][a-z0-9!#$&^_.+-]*$'",
            name="ck_artifact_media_type",
        ),
        sa.CheckConstraint(
            "storage_locator = 'artifacts/' || replace(id::text, '-', '')",
            name="ck_artifact_locator",
        ),
    )


def downgrade() -> None:
    op.drop_table("artifact_metadata")
