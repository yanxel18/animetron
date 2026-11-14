import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.database import create_database_engine
from app.services.reviews.scope import ReviewDestination, ReviewScope
from app.services.reviews.store import (
    DecisionOutcome,
    DeliveryOutcome,
    ReviewConflict,
    ReviewNotFound,
    ReviewState,
    create_review_request,
    decide_review,
    deliver_review_request,
    expire_review_request,
    get_review_decision,
    get_review_request,
    review_decisions,
    review_requests,
)
from app.services.workflows.runs import create_run


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_database_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_request_retry_is_idempotent_and_changed_reuse_conflicts(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        original = create_review_request(
            connection, request_id, scope, expires_at=expires_at
        )
        assert (
            create_review_request(
                connection, request_id, scope, expires_at=expires_at
            )
            == original
        )
        with pytest.raises(ReviewConflict):
            create_review_request(
                connection,
                request_id,
                ReviewScope(
                    run_id=scope.run_id,
                    artifact_revision=scope.artifact_revision,
                    artifact_sha256=scope.artifact_sha256,
                    caption_sha256="c" * 64,
                    destinations=scope.destinations,
                ),
                expires_at=expires_at,
            )

    with engine.connect() as connection:
        assert get_review_request(connection, request_id) == original


def test_delivery_failure_unknown_and_confirmation_transitions(engine):
    failed_scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    unknown_scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    failed_id, unknown_id = uuid4(), uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    with engine.begin() as connection:
        create_run(connection, failed_scope.run_id)
        create_run(connection, unknown_scope.run_id)
        create_review_request(
            connection, failed_id, failed_scope, expires_at=expires_at
        )
        create_review_request(
            connection, unknown_id, unknown_scope, expires_at=expires_at
        )
        failure = deliver_review_request(
            connection,
            failed_id,
            outcome=DeliveryOutcome.FAILED,
            error_code="provider_rejected",
        )
        assert failure.state is ReviewState.DELIVERY_FAILED
        assert failure.delivery_error_code == "provider_rejected"
        assert (
            deliver_review_request(
                connection,
                failed_id,
                outcome=DeliveryOutcome.FAILED,
                error_code="provider_rejected",
            )
            == failure
        )
        with pytest.raises(ReviewConflict):
            deliver_review_request(
                connection, failed_id, outcome=DeliveryOutcome.DELIVERED
            )
        unknown = deliver_review_request(
            connection, unknown_id, outcome=DeliveryOutcome.UNKNOWN
        )
        assert unknown.state is ReviewState.DELIVERY_UNKNOWN
        delivered = deliver_review_request(
            connection, unknown_id, outcome=DeliveryOutcome.DELIVERED
        )
        assert delivered.state is ReviewState.AWAITING_DECISION


def test_expiry_requires_aware_future_time_and_transitions_after_deadline(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        with pytest.raises(ValueError, match="aware"):
            create_review_request(
                connection, request_id, scope, expires_at=datetime.now()
            )
        with pytest.raises(ValueError, match="future"):
            create_review_request(
                connection,
                request_id,
                scope,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        expires_at = datetime.now(UTC) + timedelta(milliseconds=250)
        create_review_request(
            connection, request_id, scope, expires_at=expires_at
        )
        deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )

    time.sleep(0.35)
    with engine.begin() as connection:
        expired = expire_review_request(connection, request_id)
        assert expired.state is ReviewState.EXPIRED
        assert (
            create_review_request(
                connection, request_id, scope, expires_at=expires_at
            )
            == expired
        )
        with pytest.raises(ReviewConflict):
            decide_review(
                connection,
                request_id,
                DecisionOutcome.APPROVED,
                reviewer_id="reviewer-1",
            )


def test_changed_scope_supersedes_approval_without_changing_decision(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        original = create_review_request(
            connection, request_id, scope, expires_at=expires_at
        )
        deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )
        decision = decide_review(
            connection,
            request_id,
            DecisionOutcome.APPROVED,
            reviewer_id="reviewer-1",
        )
        changed_scope = ReviewScope(
            run_id=scope.run_id,
            artifact_revision="render-2",
            artifact_sha256="c" * 64,
            caption_sha256=scope.caption_sha256,
            destinations=scope.destinations,
        )
        changed = create_review_request(
            connection,
            uuid4(),
            changed_scope,
            expires_at=expires_at,
        )
        assert changed.scope == changed_scope

    with engine.connect() as connection:
        superseded = get_review_request(connection, request_id)
        assert superseded.state is ReviewState.SUPERSEDED
        assert superseded.scope == original.scope
        assert get_review_decision(connection, request_id) == decision
        assert decision.outcome is DecisionOutcome.APPROVED


def test_decision_is_idempotent_immutable_and_rejects_conflicting_replay(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        create_review_request(
            connection,
            request_id,
            scope,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )
        decision = decide_review(
            connection,
            request_id,
            DecisionOutcome.APPROVED,
            reviewer_id="reviewer-1",
        )
        assert (
            decide_review(
                connection,
                request_id,
                DecisionOutcome.APPROVED,
                reviewer_id="reviewer-1",
            )
            == decision
        )
        with pytest.raises(ReviewConflict):
            decide_review(
                connection,
                request_id,
                DecisionOutcome.REJECTED,
                reviewer_id="reviewer-1",
            )

    with engine.begin() as connection:
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                update(review_decisions)
                .where(review_decisions.c.review_id == request_id)
                .values(outcome=DecisionOutcome.REJECTED.value)
            )
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                review_decisions.delete().where(
                    review_decisions.c.review_id == request_id
                )
            )
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                update(review_requests)
                .where(review_requests.c.id == request_id)
                .values(artifact_sha256="c" * 64)
            )
    with engine.connect() as connection:
        assert get_review_decision(connection, request_id) == decision


def test_concurrent_opposite_decisions_commit_one_immutable_winner(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        create_review_request(
            connection,
            request_id,
            scope,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )

    barrier = Barrier(2)

    def decide(outcome):
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                barrier.wait(timeout=5)
                return decide_review(
                    connection,
                    request_id,
                    outcome,
                    reviewer_id=f"reviewer-{outcome.value.lower()}",
                ).outcome
        except ReviewConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                decide,
                (DecisionOutcome.APPROVED, DecisionOutcome.REJECTED),
            )
        )
    assert outcomes.count("conflict") == 1
    assert sum(isinstance(outcome, DecisionOutcome) for outcome in outcomes) == 1
    with engine.connect() as connection:
        decisions = connection.execute(
            select(review_decisions).where(
                review_decisions.c.review_id == request_id
            )
        ).all()
        assert len(decisions) == 1


def test_review_request_delivery_and_decision_share_caller_rollback(engine):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    with engine.begin() as connection:
        create_run(connection, scope.run_id)

    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        create_review_request(
            connection,
            request_id,
            scope,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )
        decide_review(
            connection,
            request_id,
            DecisionOutcome.REJECTED,
            reviewer_id="reviewer-1",
        )
        connection.execute(text("CREATE TABLE review_rollback_probe (id integer)"))
        raise RuntimeError("abort")

    with engine.connect() as connection:
        with pytest.raises(ReviewNotFound):
            get_review_request(connection, request_id)
        with pytest.raises(ReviewNotFound):
            get_review_decision(connection, request_id)
        assert (
            connection.scalar(text("SELECT to_regclass('review_rollback_probe')"))
            is None
        )


@pytest.mark.parametrize("state", ["APPROVED", "REJECTED"])
def test_raw_insert_cannot_start_with_decided_state(engine, state):
    run_id, request_id = uuid4(), uuid4()
    with engine.begin() as connection:
        create_run(connection, run_id)
        with (
            pytest.raises(DBAPIError, match="must start pending delivery"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    "INSERT INTO review_requests "
                    "(id, run_id, artifact_revision, artifact_sha256, "
                    "caption_sha256, destinations, expires_at, state) "
                    "VALUES (:id, :run_id, 'render-1', :artifact, :caption, "
                    """'[{"provider":"facebook","account_id":"page-1"}]'::jsonb, """
                    "clock_timestamp() + interval '1 hour', :state)"
                ),
                {
                    "id": request_id,
                    "run_id": run_id,
                    "artifact": "a" * 64,
                    "caption": "b" * 64,
                    "state": state,
                },
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert connection.scalar(text("SELECT 1")) == 1
        with pytest.raises(ReviewNotFound):
            get_review_request(connection, request_id)


@pytest.mark.parametrize("reviewer_id", ["reviewer id", "", "-reviewer", "a" * 129])
def test_invalid_reviewer_id_preserves_caller_transaction(engine, reviewer_id):
    scope = ReviewScope(
        run_id=uuid4(),
        artifact_revision="render-1",
        artifact_sha256="a" * 64,
        caption_sha256="b" * 64,
        destinations=(ReviewDestination("facebook", "page-1"),),
    )
    request_id = uuid4()
    with engine.begin() as connection:
        create_run(connection, scope.run_id)
        create_review_request(
            connection,
            request_id,
            scope,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        delivered = deliver_review_request(
            connection, request_id, outcome=DeliveryOutcome.DELIVERED
        )
        # No savepoint masks a database error or partially written decision.
        with pytest.raises(ValueError, match="reviewer identifier"):
            decide_review(
                connection,
                request_id,
                DecisionOutcome.APPROVED,
                reviewer_id=reviewer_id,
            )
        assert connection.scalar(text("SELECT 1")) == 1
        assert get_review_request(connection, request_id) == delivered
        with pytest.raises(ReviewNotFound):
            get_review_decision(connection, request_id)
        decision = decide_review(
            connection,
            request_id,
            DecisionOutcome.APPROVED,
            reviewer_id="Reviewer_1.:@-",
        )
    with engine.connect() as connection:
        assert get_review_decision(connection, request_id) == decision


def test_raw_expired_request_cannot_transition_to_awaiting_decision(engine):
    run_id, request_id = uuid4(), uuid4()
    with engine.begin() as connection:
        create_run(connection, run_id)
        # Past timestamps avoid relying on a sleep or the application expiry guard.
        connection.execute(
            text(
                "INSERT INTO review_requests "
                "(id, run_id, artifact_revision, artifact_sha256, caption_sha256, "
                "destinations, created_at, expires_at) "
                "VALUES (:id, :run_id, 'render-1', :artifact, :caption, "
                """'[{"provider":"facebook","account_id":"page-1"}]'::jsonb, """
                "clock_timestamp() - interval '2 hours', "
                "clock_timestamp() - interval '1 hour')"
            ),
            {
                "id": request_id,
                "run_id": run_id,
                "artifact": "a" * 64,
                "caption": "b" * 64,
            },
        )
        with (
            pytest.raises(DBAPIError, match="review request has expired"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    "UPDATE review_requests SET state = 'AWAITING_DECISION' "
                    "WHERE id = :id"
                ),
                {"id": request_id},
            )
        assert (
            get_review_request(connection, request_id).state
            is ReviewState.PENDING_DELIVERY
        )
        assert expire_review_request(connection, request_id).state is ReviewState.EXPIRED
