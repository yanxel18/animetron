import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.auth import AuthDenied, Principal
from app.core.database import create_database_engine
from app.core.outbox import OutboxConflict, enqueue, outbox
from app.services.reviews import decisions as service
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
    get_review_decision,
    get_review_request,
)
from app.services.workflows.runs import create_run


@pytest.fixture
def engine():
    engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def owner():
    # Test substitute for the trusted server's freshly authenticated Principal.
    return Principal("owner-1", "owner", "test-csrf", datetime.now(UTC) + timedelta(hours=1))


def ready(engine, *, seconds=3600, delivered=True):
    scope = ReviewScope(
        uuid4(), "render-1", "a" * 64, "b" * 64,
        (ReviewDestination("facebook", "page-1"),),
    )
    review_id = uuid4()
    with engine.begin() as conn:
        create_run(conn, scope.run_id)
        create_review_request(
            conn, review_id, scope,
            expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        )
        if delivered:
            deliver_review_request(conn, review_id, outcome=DeliveryOutcome.DELIVERED)
    return review_id, scope


def intents(conn, review_id):
    return conn.execute(select(outbox).where(outbox.c.resource_id == review_id)).all()


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
@pytest.mark.parametrize("outcome", list(DecisionOutcome))
def test_only_owner_can_decide_and_valid_replay_has_no_effect(engine, owner, role, outcome):
    review_id, scope = ready(engine)
    principal = replace(owner, role=role)
    with engine.begin() as conn:
        if role != "owner":
            with pytest.raises(AuthDenied) as denied:
                service.record_decision(conn, principal, scope, review_id, outcome)
            assert (denied.value.code, denied.value.status) == ("FORBIDDEN", 403)
            assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION
            with pytest.raises(ReviewNotFound):
                get_review_decision(conn, review_id)
            assert intents(conn, review_id) == []
        else:
            decision = service.record_decision(conn, principal, scope, review_id, outcome)
            assert decision.reviewer_id == owner.id
    if role == "owner":
        with engine.begin() as conn:
            assert service.record_decision(conn, owner, scope, review_id, outcome) == decision
            rows = intents(conn, review_id)
            assert len(rows) == (1 if outcome is DecisionOutcome.APPROVED else 0)
            if rows:
                assert rows[0].topic == service.APPROVED_TOPIC
                assert rows[0].id == service.approval_intent_id(review_id)
            for changed_owner, changed_outcome in (
                (replace(owner, id="owner-2"), outcome),
                (owner, DecisionOutcome.REJECTED if outcome is DecisionOutcome.APPROVED
                 else DecisionOutcome.APPROVED),
            ):
                with pytest.raises(ReviewConflict):
                    service.record_decision(conn, changed_owner, scope, review_id, changed_outcome)


@pytest.mark.parametrize("expiry", [datetime(2000, 1, 1, tzinfo=UTC), datetime(2099, 1, 1)])
@pytest.mark.parametrize("replay", [False, True])
def test_stale_or_naive_principal_is_denied_even_on_replay(engine, owner, expiry, replay):
    review_id, scope = ready(engine)
    with engine.begin() as conn:
        if replay:
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        before = intents(conn, review_id)
        with pytest.raises(AuthDenied):
            service.record_decision(
                conn, replace(owner, expires_at=expiry), scope, review_id, DecisionOutcome.APPROVED,
            )
        assert intents(conn, review_id) == before
        if not replay:
            assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION


@pytest.mark.parametrize("field,value", [
    ("run_id", uuid4()), ("artifact_revision", "render-2"),
    ("artifact_sha256", "c" * 64), ("caption_sha256", "c" * 64),
    ("destinations", (ReviewDestination("facebook", "page-2"),)),
])
@pytest.mark.parametrize("replay", [False, True])
def test_exact_scope_is_required_before_effects_and_replay(engine, owner, field, value, replay):
    review_id, scope = ready(engine)
    with engine.begin() as conn:
        if replay:
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        before = intents(conn, review_id)
        with pytest.raises(ReviewConflict):
            service.record_decision(
                conn, owner, replace(scope, **{field: value}), review_id, DecisionOutcome.APPROVED,
            )
        assert intents(conn, review_id) == before
        if not replay:
            assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION


@pytest.mark.parametrize("invalid", ["expired", "superseded", "undelivered"])
@pytest.mark.parametrize("replay", [False, True])
def test_invalid_current_state_never_returns_approval(engine, owner, invalid, replay):
    review_id, scope = ready(
        engine, seconds=1 if invalid == "expired" else 3600,
        delivered=invalid != "undelivered",
    )
    with engine.begin() as conn:
        if replay and invalid != "undelivered":
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        if invalid == "superseded":
            create_review_request(
                conn, uuid4(), replace(scope, artifact_revision="render-2"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
    if invalid == "expired":
        time.sleep(1.1)
    with engine.begin() as conn:
        before = intents(conn, review_id)
        with pytest.raises(ReviewConflict):
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        assert intents(conn, review_id) == before


@pytest.mark.parametrize("collision", ["none", "topic", "resource"])
def test_low_level_approval_is_not_promoted_or_repaired(engine, owner, collision):
    review_id, scope = ready(engine)
    with engine.begin() as conn:
        decide_review(conn, review_id, DecisionOutcome.APPROVED, reviewer_id=owner.id)
        if collision != "none":
            enqueue(
                conn, service.approval_intent_id(review_id),
                "other.topic" if collision == "topic" else service.APPROVED_TOPIC,
                uuid4() if collision == "resource" else review_id,
            )
        with pytest.raises((ReviewConflict, OutboxConflict)):
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)


@pytest.mark.parametrize("topic,resource_changed", [
    ("other.topic", False), ("internal.review-approved.v1", True),
    ("internal.review-approved.v1", False),
])
def test_pending_intent_collision_cannot_authorize(engine, owner, topic, resource_changed):
    review_id, scope = ready(engine)
    with engine.begin() as conn:
        enqueue(conn, service.approval_intent_id(review_id), topic,
                uuid4() if resource_changed else review_id)
        with pytest.raises(OutboxConflict):
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION


@pytest.mark.parametrize("failure", ["database", "python"])
def test_enqueue_error_rolls_back_even_when_caller_catches(engine, owner, monkeypatch, failure):
    review_id, scope = ready(engine)

    def broken_enqueue(conn, intent_id, topic, resource_id):
        enqueue(conn, intent_id, topic, resource_id)
        if failure == "database":
            conn.execute(text("SELECT 1 / 0"))
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(service, "enqueue", broken_enqueue)
    with engine.begin() as conn:
        with pytest.raises(DBAPIError if failure == "database" else RuntimeError):
            service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        assert conn.scalar(select(func.count()).select_from(outbox).where(
            outbox.c.resource_id == review_id,
        )) == 0
        assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION
        with pytest.raises(ReviewNotFound):
            get_review_decision(conn, review_id)
        conn.execute(text("SELECT 1"))  # Caller can still commit unrelated work.
    with engine.connect() as conn:
        assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION
        assert intents(conn, review_id) == []


def test_outer_rollback_removes_decision_and_intent(engine, owner):
    review_id, scope = ready(engine)
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        raise RuntimeError("abort")
    with engine.connect() as conn:
        assert get_review_request(conn, review_id).state is ReviewState.AWAITING_DECISION
        assert intents(conn, review_id) == []


def test_real_concurrent_opposite_decisions_have_single_winner(engine, owner):
    review_id, scope = ready(engine)
    barrier = Barrier(2)

    def decide(outcome):
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            conn.execute(text("SET LOCAL statement_timeout = '10s'"))
            barrier.wait(timeout=5)
            try:
                return service.record_decision(conn, owner, scope, review_id, outcome).outcome
            except ReviewConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, list(DecisionOutcome)))
    assert results.count("conflict") == 1
    with engine.connect() as conn:
        winner = get_review_decision(conn, review_id).outcome
        assert winner in results
        assert get_review_request(conn, review_id).state.value == winner.value
        assert len(intents(conn, review_id)) == (1 if winner is DecisionOutcome.APPROVED else 0)


def test_explicit_transaction_and_typed_identifier_required(engine, owner):
    review_id, scope = ready(engine)
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(),
        pytest.raises(RuntimeError, match="transaction"),
    ):
        service.record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="UUID4"):
            service.record_decision(conn, owner, scope, uuid5(NAMESPACE_URL, "test"), DecisionOutcome.APPROVED)
        with pytest.raises(TypeError):
            service.record_decision(conn, owner, scope, review_id, "APPROVED")
