import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import event, func, select, text, update
from test_review_decision_service import intents, ready

from app.core.auth import AuthConfig, AuthStore, Principal, digest, sessions
from app.core.database import create_database_engine
from app.core.outbox import OutboxConflict, enqueue, outbox
from app.services.reviews.decisions import (
    APPROVED_TOPIC,
    approval_intent_id,
    record_decision,
)
from app.services.reviews.scope import ReviewDestination
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
    review_requests,
)


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def config():
    return AuthConfig(
        "https://identity.example/realm", "control", "test-only-placeholder",
        "https://control.example", "owner-subject",
    )


@pytest.fixture
def lookup(engine):
    # Import at execution time so absent DB infrastructure keeps the usual skip.
    from app.services.reviews.approvals import require_valid_approval

    return require_valid_approval


def approved(engine, config, *, seconds=3600, reviewer_id=None):
    review_id, scope = ready(engine, seconds=seconds)
    principal = Principal(
        reviewer_id or digest(config.issuer + "\0" + config.owner_subject),
        "owner", "test-csrf", datetime.now(UTC) + timedelta(hours=1),
    )
    with engine.begin() as conn:
        record_decision(conn, principal, scope, review_id, DecisionOutcome.APPROVED)
    return review_id, scope


def test_checked_metadata_is_frozen_read_only_and_needs_no_active_session(
    engine, config, lookup,
):
    review_id, scope = ready(engine)
    _, owner = AuthStore(engine, config).create_session(config.owner_subject, "lookup-test")
    with engine.begin() as conn:
        decision = record_decision(conn, owner, scope, review_id, DecisionOutcome.APPROVED)
        conn.execute(sessions.delete().where(sessions.c.principal_id == owner.id))
    with engine.begin() as conn:
        request = get_review_request(conn, review_id)
        before = intents(conn, review_id)
        transaction = conn.get_transaction()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(conn, "before_cursor_execute", capture)
        try:
            checked = lookup(conn, review_id, scope, auth_config=config)
        finally:
            event.remove(conn, "before_cursor_execute", capture)
        assert statements and all(sql.lstrip().startswith("SELECT") for sql in statements)
        assert conn.get_transaction() is transaction
        assert checked.scope == scope
        assert checked.decision == decision
        assert checked.review_id == review_id
        assert checked.expires_at == request.expires_at
        with pytest.raises(FrozenInstanceError):
            checked.expires_at = datetime.now(UTC)
        assert get_review_request(conn, review_id) == request
        assert get_review_decision(conn, review_id) == decision
        assert intents(conn, review_id) == before
    # Lookup does not commit unrelated caller work.
    with engine.connect() as conn:
        transaction = conn.begin()
        lookup(conn, review_id, scope, auth_config=config)
        conn.execute(update(outbox).where(outbox.c.id == approval_intent_id(review_id))
                     .values(topic="caller.uncommitted"))
        transaction.rollback()
    with engine.connect() as conn:
        assert intents(conn, review_id) == before


@pytest.mark.parametrize("state", [s for s in ReviewState if s is not ReviewState.APPROVED])
def test_every_nonapproved_current_state_is_rejected(engine, config, lookup, state):
    review_id, scope = ready(
        engine, delivered=state not in (
            ReviewState.PENDING_DELIVERY, ReviewState.DELIVERY_FAILED,
            ReviewState.DELIVERY_UNKNOWN,
        ), seconds=0.2 if state is ReviewState.EXPIRED else 3600,
    )
    with engine.begin() as conn:
        if state in (ReviewState.DELIVERY_FAILED, ReviewState.DELIVERY_UNKNOWN):
            deliver_review_request(
                conn, review_id,
                outcome=DeliveryOutcome.FAILED if state is ReviewState.DELIVERY_FAILED
                else DeliveryOutcome.UNKNOWN,
                error_code="test.failure" if state is ReviewState.DELIVERY_FAILED else None,
            )
        elif state is ReviewState.REJECTED:
            decide_review(conn, review_id, DecisionOutcome.REJECTED,
                          reviewer_id=digest(config.issuer + "\0" + config.owner_subject))
        elif state is ReviewState.SUPERSEDED:
            record_decision(
                conn, Principal(digest(config.issuer + "\0" + config.owner_subject),
                                "owner", "csrf", datetime.now(UTC) + timedelta(hours=1)),
                scope, review_id, DecisionOutcome.APPROVED,
            )
            create_review_request(
                conn, uuid4(), replace(scope, artifact_revision="render-2"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        elif state is ReviewState.EXPIRED:
            expiry = get_review_request(conn, review_id).expires_at
            while conn.scalar(select(func.clock_timestamp())) <= expiry:
                time.sleep(0.05)
            expire_review_request(conn, review_id)
        before = get_review_request(conn, review_id)
        assert before.state is state
        with pytest.raises(ReviewConflict):
            lookup(conn, review_id, scope, auth_config=config)
        assert get_review_request(conn, review_id) == before


@pytest.mark.parametrize("field,value", [
    ("run_id", uuid4()), ("artifact_revision", "render-2"),
    ("artifact_sha256", "c" * 64), ("caption_sha256", "c" * 64),
    ("destinations", (ReviewDestination("facebook", "page-2"),)),
])
def test_every_exact_scope_field_is_checked(engine, config, lookup, field, value):
    review_id, scope = approved(engine, config)
    with engine.begin() as conn, pytest.raises(ReviewConflict):
        lookup(conn, review_id, replace(scope, **{field: value}), auth_config=config)


@pytest.mark.parametrize("evidence", [
    "missing-review", "missing-decision",
    "low-level", "wrong-id", "wrong-topic", "wrong-resource",
])
def test_unverified_or_colliding_approval_is_not_repaired(engine, config, lookup, evidence):
    review_id, scope = ready(engine)
    with engine.connect() as conn, conn.begin() as transaction:
        if evidence != "missing-review":
            if evidence == "missing-decision":
                conn.execute(update(review_requests).where(review_requests.c.id == review_id)
                             .values(state=ReviewState.APPROVED.value))
            else:
                decide_review(
                    conn, review_id, DecisionOutcome.APPROVED,
                    reviewer_id=digest(config.issuer + "\0" + config.owner_subject),
                )
            if evidence != "low-level":
                enqueue(
                    conn, uuid4() if evidence == "wrong-id" else approval_intent_id(review_id),
                    "wrong.topic" if evidence == "wrong-topic" else APPROVED_TOPIC,
                    uuid4() if evidence == "wrong-resource" else review_id,
                )
        before = intents(conn, review_id)
        expected_error = (
            ReviewNotFound if evidence in ("missing-review", "missing-decision")
            else OutboxConflict if evidence in ("wrong-topic", "wrong-resource")
            else ReviewConflict
        )
        with pytest.raises(expected_error):
            lookup(conn, uuid4() if evidence == "missing-review" else review_id,
                   scope, auth_config=config)
        assert intents(conn, review_id) == before
        # Missing-decision intermediate state must not pass deferred commit guards.
        transaction.rollback()


@pytest.mark.parametrize("field,value", [
    ("outcome", DecisionOutcome.REJECTED), ("review_id", uuid4()),
])
def test_mismatched_decision_read_is_rejected(engine, config, lookup, monkeypatch, field, value):
    from app.services.reviews import approvals

    review_id, scope = approved(engine, config)
    with engine.begin() as conn:
        decision = get_review_decision(conn, review_id)
        # DB triggers prohibit committed mismatched decisions; exercise the read guard.
        monkeypatch.setattr(
            approvals, "get_review_decision",
            lambda connection, review_id: replace(decision, **{field: value}),
        )
        with pytest.raises(ReviewConflict):
            lookup(conn, review_id, scope, auth_config=config)


@pytest.mark.parametrize("changed", ["issuer", "subject", "grant", "raw-subject", "no-separator"])
def test_only_exact_current_configured_owner_matches(engine, config, lookup, changed):
    reviewer_id = (
        config.owner_subject if changed == "raw-subject"
        else digest(config.issuer + config.owner_subject) if changed == "no-separator"
        else None
    )
    review_id, scope = approved(engine, config, reviewer_id=reviewer_id)
    current = (
        replace(config, issuer="https://other.example/realm") if changed == "issuer"
        else replace(config, owner_subject="new-owner") if changed in ("subject", "grant")
        else config
    )
    if changed == "grant":
        current = replace(current, grants={config.owner_subject: "operator"})
    with engine.begin() as conn, pytest.raises(ReviewConflict):
        lookup(conn, review_id, scope, auth_config=current)


def test_explicit_transaction_and_existing_type_contracts(engine, config, lookup):
    review_id, scope = approved(engine, config)
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        lookup(conn, review_id, scope, auth_config=config)
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(), pytest.raises(RuntimeError, match="transaction"),
    ):
        lookup(conn, review_id, scope, auth_config=config)
    with engine.begin() as conn:
        for invalid_id, error in [(str(review_id), TypeError), (uuid5(NAMESPACE_URL, "x"), ValueError)]:
            with pytest.raises(error):
                lookup(conn, invalid_id, scope, auth_config=config)
        with pytest.raises(TypeError):
            lookup(conn, review_id, object(), auth_config=config)
        with pytest.raises(TypeError):
            lookup(conn, review_id, scope, auth_config=object())


def test_expiry_is_rechecked_after_actual_final_intent_lock_wait(engine, config, lookup):
    review_id, scope = approved(engine, config, seconds=4)
    started = Event()
    pid = []
    with engine.connect() as blocker:
        blocker.begin()
        blocker.execute(select(outbox.c.id).where(
            outbox.c.id == approval_intent_id(review_id),
        ).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            def inspect():
                with engine.begin() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '15s'"))
                    conn.execute(text("SET LOCAL statement_timeout = '20s'"))
                    pid.append(conn.scalar(text("SELECT pg_backend_pid()")))
                    started.set()
                    return lookup(conn, review_id, scope, auth_config=config)

            future = pool.submit(inspect)
            try:
                assert started.wait(timeout=5)
                with engine.connect() as observer:
                    waiting = False
                    for _ in range(100):
                        waiting = observer.scalar(text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                        ), {"pid": pid[0]}) == "Lock"
                        if waiting:
                            break
                        time.sleep(0.05)
                    assert waiting, "lookup never waited on the held final intent lock"
                    expiry = get_review_request(observer, review_id).expires_at
                    while observer.scalar(select(func.clock_timestamp())) <= expiry:
                        time.sleep(0.05)
                    assert not future.done()
            finally:
                blocker.commit()  # Release before waiting for the worker, even on failure.
            with pytest.raises(ReviewConflict, match="expired"):
                future.result(timeout=20)
    with engine.connect() as conn:
        assert get_review_request(conn, review_id).state is ReviewState.APPROVED
        assert len(intents(conn, review_id)) == 1
