"""Create stored workflow revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_workflow_revisions"
down_revision = "0002_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_revisions",
        sa.Column("workflow_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.String(128), primary_key=True),
        sa.Column("document", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_revisions")
