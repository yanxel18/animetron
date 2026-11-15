"""Retain immutable schedule occurrence observations; no dispatch outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "p6_02d_due_slots"
down_revision = "p1_09c_workflow_revision_list"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_due_slots",
        sa.Column("schedule_id", sa.Uuid(), primary_key=True),
        sa.Column("slot_key", sa.String(272), primary_key=True),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["schedule_descriptors.id"], name="fk_due_slot_schedule",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "revision"], ["workflow_revisions.workflow_id", "workflow_revisions.revision"],
            name="fk_due_slot_revision",
        ),
        sa.CheckConstraint("length(slot_key) BETWEEN 1 AND 272", name="ck_due_slot_key"),
        sa.CheckConstraint("schedule_version > 0", name="ck_due_slot_version"),
    )
    op.execute("""
        CREATE FUNCTION guard_schedule_due_slot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Due slot observations cannot be changed or deleted'
                USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER schedule_due_slot_immutable
        BEFORE UPDATE OR DELETE ON schedule_due_slots
        FOR EACH ROW EXECUTE FUNCTION guard_schedule_due_slot()
    """)


def downgrade() -> None:
    # Destructive for populated databases: explicit authorization/recovery required.
    op.drop_table("schedule_due_slots")
    op.execute("DROP FUNCTION guard_schedule_due_slot()")
