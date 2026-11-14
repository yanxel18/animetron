"""Persist internal review requests and immutable decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p4_02_review_records_20261114"
down_revision = "0005_artifact_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("artifact_revision", sa.String(128), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("caption_sha256", sa.String(64), nullable=False),
        sa.Column("destinations", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "state",
            sa.String(24),
            nullable=False,
            server_default="PENDING_DELIVERY",
        ),
        sa.Column(
            "state_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivery_error_code", sa.String(80), nullable=True),
        sa.CheckConstraint(
            "substr(id::text, 15, 1) = '4' AND "
            "substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_review_request_uuid4",
        ),
        sa.CheckConstraint(
            "artifact_revision ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
            name="ck_review_artifact_revision",
        ),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_review_artifact_sha256",
        ),
        sa.CheckConstraint(
            "caption_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_review_caption_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(destinations) = 'array' AND "
            "jsonb_array_length(destinations) > 0",
            name="ck_review_destinations",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING_DELIVERY', 'AWAITING_DECISION', 'APPROVED', "
            "'REJECTED', 'EXPIRED', 'SUPERSEDED', 'DELIVERY_FAILED', "
            "'DELIVERY_UNKNOWN')",
            name="ck_review_request_state",
        ),
        sa.CheckConstraint(
            "delivery_error_code IS NULL OR "
            "(state IN ('DELIVERY_FAILED', 'DELIVERY_UNKNOWN') AND "
            "delivery_error_code ~ '^[a-z][a-z0-9._-]{0,79}$')",
            name="ck_review_delivery_error_code",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_review_expiry"),
    )
    op.create_index(
        "uq_review_active_run",
        "review_requests",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('PENDING_DELIVERY', 'AWAITING_DECISION', 'APPROVED', "
            "'REJECTED', 'DELIVERY_UNKNOWN')"
        ),
    )
    op.create_table(
        "review_decisions",
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("review_requests.id"),
            primary_key=True,
        ),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "outcome IN ('APPROVED', 'REJECTED')",
            name="ck_review_decision_outcome",
        ),
        sa.CheckConstraint(
            "reviewer_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
            name="ck_review_reviewer_id",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION guard_review_request_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(
                NEW.id, NEW.run_id, NEW.artifact_revision, NEW.artifact_sha256,
                NEW.caption_sha256, NEW.destinations, NEW.expires_at, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.run_id, OLD.artifact_revision, OLD.artifact_sha256,
                OLD.caption_sha256, OLD.destinations, OLD.expires_at, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'review request scope is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.state = OLD.state THEN
                IF NEW.state_changed_at IS DISTINCT FROM OLD.state_changed_at
                   OR NEW.delivery_error_code IS DISTINCT FROM OLD.delivery_error_code
                THEN
                    RAISE EXCEPTION 'review request metadata requires a state transition'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NOT (
                (OLD.state = 'PENDING_DELIVERY' AND NEW.state IN (
                    'AWAITING_DECISION', 'DELIVERY_FAILED', 'DELIVERY_UNKNOWN',
                    'EXPIRED', 'SUPERSEDED'
                ))
                OR (OLD.state = 'DELIVERY_UNKNOWN' AND NEW.state IN (
                    'AWAITING_DECISION', 'DELIVERY_FAILED', 'EXPIRED', 'SUPERSEDED'
                ))
                OR (OLD.state = 'AWAITING_DECISION' AND NEW.state IN (
                    'APPROVED', 'REJECTED', 'EXPIRED', 'SUPERSEDED'
                ))
                OR (OLD.state IN ('APPROVED', 'REJECTED') AND NEW.state = 'SUPERSEDED')
            ) THEN
                RAISE EXCEPTION 'illegal review request state transition'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.state = 'EXPIRED' AND OLD.expires_at > clock_timestamp() THEN
                RAISE EXCEPTION 'review request has not expired'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.state IN ('AWAITING_DECISION', 'APPROVED', 'REJECTED')
               AND OLD.expires_at <= clock_timestamp()
            THEN
                RAISE EXCEPTION 'review request has expired'
                    USING ERRCODE = '23514';
            END IF;
            NEW.state_changed_at := clock_timestamp();
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER review_request_update_guard
            BEFORE UPDATE ON review_requests
            FOR EACH ROW EXECUTE FUNCTION guard_review_request_update();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_review_request_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'review request history is immutable'
                USING ERRCODE = '23514';
        END;
        $$;
        CREATE TRIGGER review_request_delete_guard
            BEFORE DELETE ON review_requests
            FOR EACH ROW EXECUTE FUNCTION reject_review_request_delete();
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_review_decision_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE request_state text;
        BEGIN
            SELECT state INTO request_state FROM review_requests
                WHERE id = NEW.review_id FOR UPDATE;
            IF request_state IS DISTINCT FROM NEW.outcome THEN
                RAISE EXCEPTION 'decision does not match request state'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER review_decision_insert_guard
            BEFORE INSERT ON review_decisions
            FOR EACH ROW EXECUTE FUNCTION guard_review_decision_insert();
        CREATE FUNCTION reject_review_decision_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'review decisions are immutable'
                USING ERRCODE = '23514';
        END;
        $$;
        CREATE TRIGGER review_decision_update_guard
            BEFORE UPDATE OR DELETE ON review_decisions
            FOR EACH ROW EXECUTE FUNCTION reject_review_decision_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION check_review_decision_state() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE stored_outcome text;
        BEGIN
            IF NEW.state IN ('APPROVED', 'REJECTED') THEN
                SELECT outcome INTO stored_outcome FROM review_decisions
                    WHERE review_id = NEW.id;
                IF stored_outcome IS DISTINCT FROM NEW.state THEN
                    RAISE EXCEPTION 'review state requires its immutable decision'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;
        CREATE CONSTRAINT TRIGGER review_decision_state_guard
            AFTER UPDATE OF state ON review_requests
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION check_review_decision_state();
        """
    )


def downgrade() -> None:
    op.drop_table("review_decisions")
    op.drop_index("uq_review_active_run", table_name="review_requests")
    op.drop_table("review_requests")
    op.execute("DROP FUNCTION check_review_decision_state()")
    op.execute("DROP FUNCTION reject_review_decision_mutation()")
    op.execute("DROP FUNCTION guard_review_decision_insert()")
    op.execute("DROP FUNCTION reject_review_request_delete()")
    op.execute("DROP FUNCTION guard_review_request_update()")
