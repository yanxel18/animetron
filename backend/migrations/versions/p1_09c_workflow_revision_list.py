"""Index stable workflow revision-list pagination."""

from alembic import op

revision = "p1_09c_workflow_revision_list"
down_revision = "p1_08b_execution_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_workflow_revisions_list_cursor",
        "workflow_revisions",
        ["workflow_id", "created_at", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_revisions_list_cursor", table_name="workflow_revisions")
