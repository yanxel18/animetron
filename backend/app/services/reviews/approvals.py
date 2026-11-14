"""Current internal approval inspection, never a reusable publication capability."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.core.auth import AuthConfig, digest
from app.core.outbox import OutboxConflict, outbox
from app.services.reviews.decisions import APPROVED_TOPIC, approval_intent_id
from app.services.reviews.scope import ReviewScope
from app.services.reviews.store import (
    DecisionOutcome,
    ReviewConflict,
    ReviewDecision,
    ReviewState,
    _require_transaction,
    _validate_request_id,
    get_review_decision,
    lock_review_request,
)


@dataclass(frozen=True)
class CheckedApproval:
    """Metadata checked at this transaction/settings, not proof or byte verification."""

    review_id: UUID
    scope: ReviewScope
    decision: ReviewDecision
    expires_at: datetime


def require_valid_approval(
    connection: Connection,
    review_id: UUID,
    expected_scope: ReviewScope,
    *,
    auth_config: AuthConfig,
) -> CheckedApproval:
    """Inspect only; caller owns transaction, timeouts and fresh caller authorization.

    auth_config MUST be current trusted-server settings, never client supplied.
    No active human-owner session is needed to inspect an existing decision.
    A trusted publisher must call/recheck on every attempt and before effects;
    returned metadata is not a cached permission or cryptographic capability.
    Privileged arbitrary DB writers are outside the storage integrity guarantee.
    """
    _require_transaction(connection)
    _validate_request_id(review_id)
    if type(expected_scope) is not ReviewScope:
        raise TypeError("Invalid expected review scope")
    if type(auth_config) is not AuthConfig:
        raise TypeError("Invalid trusted auth configuration")

    request = lock_review_request(connection, review_id)
    if request.state is not ReviewState.APPROVED:
        raise ReviewConflict("Review request is not currently approved")
    if request.scope != expected_scope:
        raise ReviewConflict("Review scope does not match expected scope")
    decision = get_review_decision(connection, review_id)
    owner_id = digest(auth_config.issuer + "\0" + auth_config.owner_subject)
    if (
        decision.review_id != request.id
        or decision.outcome is not DecisionOutcome.APPROVED
        or decision.reviewer_id != owner_id
    ):
        raise ReviewConflict("Approval does not match the current configured owner")

    intent = connection.execute(
        select(outbox).where(outbox.c.id == approval_intent_id(review_id)).with_for_update()
    ).one_or_none()
    if intent is None:
        raise ReviewConflict("Approval lacks authorized service intent evidence")
    if intent.topic != APPROVED_TOPIC or intent.resource_id != review_id:
        raise OutboxConflict("Reserved review intent has different topic or resource")
    # Final potentially blocking lock is above. now()/transaction time is unsafe.
    database_now = connection.scalar(select(func.clock_timestamp()))
    if not isinstance(database_now, datetime):
        raise TypeError("Database clock unavailable")
    if request.expires_at <= database_now:
        raise ReviewConflict("Review request has expired")
    return CheckedApproval(request.id, request.scope, decision, request.expires_at)
