"""Owner-only internal decisions; neither results nor intents are approval proofs."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.core.auth import AuthDenied, Principal
from app.core.outbox import OutboxConflict, enqueue, outbox
from app.services.reviews.scope import ReviewScope
from app.services.reviews.store import (
    DecisionOutcome,
    ReviewConflict,
    ReviewDecision,
    ReviewState,
    _require_transaction,
    _validate_request_id,
    decide_review,
    get_review_decision,
    get_review_request,
    review_requests,
)
from app.services.workflows.runs import runs

# Reserved for this service's trusted writers, not a publication topic.
APPROVED_TOPIC = "internal.review-approved.v1"
_INTENT_NAMESPACE = UUID("fd3e1bf7-f2a6-51b9-bdaa-2299c3124a19")


def approval_intent_id(review_id: UUID) -> UUID:
    """Stable namespaced internal notification identity, not authorization."""
    _validate_request_id(review_id)
    return uuid5(_INTENT_NAMESPACE, str(review_id))


def record_decision(
    connection: Connection,
    principal: Principal,
    expected_scope: ReviewScope,
    review_id: UUID,
    outcome: DecisionOutcome,
) -> ReviewDecision:
    """Record a decision in the caller's explicit psycopg transaction.

    Callers MUST freshly authenticate through the trusted server before every
    call, including retries. Never deserialize Principal from client input.
    This function checks role and expiry, not session revocation/authentication.
    The caller owns commit/rollback and transaction-local lock/statement budgets.
    """
    _require_transaction(connection)
    _validate_request_id(review_id)
    if type(outcome) is not DecisionOutcome:
        raise TypeError("Invalid review decision")
    if type(expected_scope) is not ReviewScope:
        raise TypeError("Invalid expected review scope")
    if type(principal) is not Principal or principal.role != "owner":
        raise AuthDenied("FORBIDDEN", 403)
    expiry = principal.expires_at
    if (
        not isinstance(expiry, datetime)
        or expiry.tzinfo is None
        or expiry.utcoffset() is None
    ):
        raise AuthDenied("UNAUTHENTICATED", 401)

    # Savepoint also undoes the store transition if enqueue fails and the caller
    # catches the exception then commits unrelated work in the outer transaction.
    with connection.begin_nested():
        request = get_review_request(connection, review_id)
        # The stored run (not caller-supplied scope) determines lock ownership.
        connection.execute(
            select(runs.c.id).where(runs.c.id == request.scope.run_id).with_for_update()
        ).scalar_one()
        connection.execute(
            select(review_requests.c.id)
            .where(review_requests.c.id == review_id)
            .with_for_update()
        ).scalar_one()
        request = get_review_request(connection, review_id)
        _require_unexpired(connection, expiry, request.expires_at)
        if request.scope != expected_scope:
            raise ReviewConflict("Review scope does not match expected scope")
        if request.state not in (
            ReviewState.AWAITING_DECISION, ReviewState.APPROVED, ReviewState.REJECTED,
        ):
            raise ReviewConflict("Review request is not current and decidable")

        intent_id = approval_intent_id(review_id)
        intent = connection.execute(
            select(outbox).where(outbox.c.id == intent_id).with_for_update()
        ).one_or_none()
        if intent is not None and (
            intent.topic != APPROVED_TOPIC or intent.resource_id != review_id
        ):
            raise OutboxConflict("Reserved review intent has different topic or resource")

        if request.state in (ReviewState.APPROVED, ReviewState.REJECTED):
            existing = get_review_decision(connection, review_id)
            if (
                existing.outcome is not outcome
                or existing.reviewer_id != principal.id
                or request.state.value != existing.outcome.value
            ):
                raise ReviewConflict("Review request already has a different decision")
            if outcome is DecisionOutcome.APPROVED and intent is None:
                raise ReviewConflict("Approval lacks authorized service intent evidence")
            if outcome is DecisionOutcome.REJECTED and intent is not None:
                raise OutboxConflict("Rejected review has an approval intent")
            # Delegate identical replay to the existing immutable state machine.
            decision = decide_review(connection, review_id, outcome, reviewer_id=principal.id)
            # Recheck after the intent lock wait, the last potentially blocking step.
            _require_unexpired(connection, expiry, request.expires_at)
            return decision

        if intent is not None:
            raise OutboxConflict("Undecided review already has a reserved approval intent")
        decision = decide_review(
            connection, review_id, outcome, reviewer_id=principal.id,
        )
        if outcome is DecisionOutcome.APPROVED:
            enqueue(connection, intent_id, APPROVED_TOPIC, review_id)
        # The savepoint undoes both effects if time passed during lock/insert waits.
        _require_unexpired(connection, expiry, request.expires_at)
        return decision


def _require_unexpired(
    connection: Connection, principal_expiry: datetime, request_expiry: datetime,
) -> None:
    # clock_timestamp advances even during long transactions and lock waits.
    database_now = connection.scalar(select(func.clock_timestamp()))
    if not isinstance(database_now, datetime):
        raise TypeError("Database clock unavailable")
    if principal_expiry <= database_now:
        raise AuthDenied("UNAUTHENTICATED", 401)
    if request_expiry <= database_now:
        raise ReviewConflict("Review request has expired")
