"""Caller-transactional persistence for internal human-review records.

These records preserve scope and history; they are not authorization proofs.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import RFC_4122, UUID

from psycopg import Connection as PsycopgConnection
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Connection, RowMapping

from app.services.reviews.scope import ReviewDestination, ReviewScope
from app.services.workflows.document import validate_revision_identifier
from app.services.workflows.runs import runs as workflow_runs

metadata = MetaData()
review_requests = Table(
    "review_requests",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "run_id",
        Uuid,
        ForeignKey(workflow_runs.c.id),
        nullable=False,
    ),
    Column("artifact_revision", String(128), nullable=False),
    Column("artifact_sha256", String(64), nullable=False),
    Column("caption_sha256", String(64), nullable=False),
    Column("destinations", JSONB, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "state",
        String(24),
        nullable=False,
        server_default="PENDING_DELIVERY",
    ),
    Column(
        "state_changed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("delivery_error_code", String(80), nullable=True),
    CheckConstraint(
        "substr(id::text, 15, 1) = '4' AND "
        "substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_review_request_uuid4",
    ),
    CheckConstraint(
        "artifact_revision ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
        name="ck_review_artifact_revision",
    ),
    CheckConstraint(
        "artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_review_artifact_sha256"
    ),
    CheckConstraint("caption_sha256 ~ '^[0-9a-f]{64}$'", name="ck_review_caption_sha256"),
    CheckConstraint(
        "jsonb_typeof(destinations) = 'array' AND "
        "jsonb_array_length(destinations) > 0",
        name="ck_review_destinations",
    ),
    CheckConstraint(
        "state IN ('PENDING_DELIVERY', 'AWAITING_DECISION', 'APPROVED', "
        "'REJECTED', 'EXPIRED', 'SUPERSEDED', 'DELIVERY_FAILED', "
        "'DELIVERY_UNKNOWN')",
        name="ck_review_request_state",
    ),
    CheckConstraint(
        "delivery_error_code IS NULL OR "
        "(state IN ('DELIVERY_FAILED', 'DELIVERY_UNKNOWN') AND "
        "delivery_error_code ~ '^[a-z][a-z0-9._-]{0,79}$')",
        name="ck_review_delivery_error_code",
    ),
    CheckConstraint("expires_at > created_at", name="ck_review_expiry"),
)
Index(
    "uq_review_active_run",
    review_requests.c.run_id,
    unique=True,
    postgresql_where=text(
        "state IN ('PENDING_DELIVERY', 'AWAITING_DECISION', 'APPROVED', "
        "'REJECTED', 'DELIVERY_UNKNOWN')"
    ),
)
review_decisions = Table(
    "review_decisions",
    metadata,
    Column(
        "review_id",
        Uuid,
        ForeignKey("review_requests.id"),
        primary_key=True,
    ),
    Column("outcome", String(8), nullable=False),
    Column("reviewer_id", String(128), nullable=False),
    Column(
        "decided_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(
        "outcome IN ('APPROVED', 'REJECTED')", name="ck_review_decision_outcome"
    ),
    CheckConstraint(
        "reviewer_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
        name="ck_review_reviewer_id",
    ),
)

_ACTIVE_STATES = (
    "PENDING_DELIVERY",
    "AWAITING_DECISION",
    "APPROVED",
    "REJECTED",
    "DELIVERY_UNKNOWN",
)


class ReviewState(StrEnum):
    PENDING_DELIVERY = "PENDING_DELIVERY"
    AWAITING_DECISION = "AWAITING_DECISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DecisionOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ReviewRequest:
    id: UUID
    scope: ReviewScope
    expires_at: datetime
    created_at: datetime
    state: ReviewState
    state_changed_at: datetime
    delivery_error_code: str | None


@dataclass(frozen=True)
class ReviewDecision:
    review_id: UUID
    outcome: DecisionOutcome
    reviewer_id: str
    decided_at: datetime


class ReviewNotFound(LookupError):
    pass


class ReviewConflict(Exception):
    pass


class ReviewCorrupt(Exception):
    pass


class ReviewRunNotFound(LookupError):
    pass


class _ReviewIdCollision(Exception):
    pass


def _require_transaction(connection: Connection) -> None:
    driver = connection.connection.driver_connection
    if (
        not connection.in_transaction()
        or not isinstance(driver, PsycopgConnection)
        or driver.autocommit
    ):
        raise RuntimeError("An explicit non-autocommit transaction is required")


def _validate_request_id(review_id: UUID) -> None:
    if not isinstance(review_id, UUID):
        raise TypeError("Invalid review identifier")
    if review_id.version != 4 or review_id.variant != RFC_4122:
        raise ValueError("Review identifier must be an RFC-variant UUID4")


def _validate_expiry(expires_at: datetime) -> None:
    if (
        not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
    ):
        raise ValueError("Review expiry must be timezone-aware")


def _scope_values(scope: ReviewScope) -> dict[str, object]:
    if type(scope) is not ReviewScope:
        raise TypeError("Invalid review scope")
    return {
        "run_id": scope.run_id,
        "artifact_revision": scope.artifact_revision,
        "artifact_sha256": scope.artifact_sha256,
        "caption_sha256": scope.caption_sha256,
        "destinations": [
            {"provider": item.provider, "account_id": item.account_id}
            for item in scope.destinations
        ],
    }


def _scope_from_row(row: RowMapping) -> ReviewScope:
    raw_destinations = row["destinations"]
    if type(raw_destinations) is not list:
        raise ReviewCorrupt("Stored review scope is invalid")
    destinations = []
    for item in raw_destinations:
        if (
            type(item) is not dict
            or set(item) != {"provider", "account_id"}
            or type(item["provider"]) is not str
            or type(item["account_id"]) is not str
        ):
            raise ReviewCorrupt("Stored review scope is invalid")
        destinations.append(ReviewDestination(item["provider"], item["account_id"]))
    try:
        return ReviewScope(
            run_id=row["run_id"],
            artifact_revision=row["artifact_revision"],
            artifact_sha256=row["artifact_sha256"],
            caption_sha256=row["caption_sha256"],
            destinations=tuple(destinations),
        )
    except (TypeError, ValueError):
        raise ReviewCorrupt("Stored review scope is invalid") from None


def _request_from_row(row: RowMapping) -> ReviewRequest:
    try:
        state = ReviewState(row["state"])
    except ValueError:
        raise ReviewCorrupt("Stored review state is invalid") from None
    return ReviewRequest(
        id=row["id"],
        scope=_scope_from_row(row),
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        state=state,
        state_changed_at=row["state_changed_at"],
        delivery_error_code=row["delivery_error_code"],
    )


def get_review_request(connection: Connection, review_id: UUID) -> ReviewRequest:
    row = connection.execute(
        select(review_requests).where(review_requests.c.id == review_id)
    ).one_or_none()
    if row is None:
        raise ReviewNotFound("Review request not found")
    return _request_from_row(row._mapping)


def create_review_request(
    connection: Connection,
    review_id: UUID,
    scope: ReviewScope,
    *,
    expires_at: datetime,
) -> ReviewRequest:
    """Create or replay one immutable-scope request in the caller's transaction."""
    _require_transaction(connection)
    _validate_request_id(review_id)
    scope_values = _scope_values(scope)
    _validate_expiry(expires_at)
    run_id = scope.run_id
    run = connection.execute(
        select(workflow_runs.c.id)
        .where(workflow_runs.c.id == run_id)
        .with_for_update()
    ).scalar_one_or_none()
    if run is None:
        raise ReviewRunNotFound("Review run not found")

    existing_row = connection.execute(
        select(review_requests).where(review_requests.c.id == review_id)
    ).one_or_none()
    if existing_row is not None:
        existing = _request_from_row(existing_row._mapping)
        if existing.scope != scope or existing.expires_at != expires_at:
            raise ReviewConflict("Review ID already contains different request data")
        return existing

    database_now = connection.scalar(select(func.clock_timestamp()))
    if database_now is None or expires_at <= database_now:
        raise ValueError("Review expiry must be in the future")

    active_rows = connection.execute(
        select(review_requests)
        .where(
            review_requests.c.run_id == run_id,
            review_requests.c.state.in_(_ACTIVE_STATES),
        )
        .with_for_update()
    ).all()
    if any(_scope_from_row(row._mapping) == scope for row in active_rows):
        raise ReviewConflict("A current request already exists for this review scope")

    try:
        with connection.begin_nested():
            for row in active_rows:
                connection.execute(
                    update(review_requests)
                    .where(review_requests.c.id == row.id)
                    .values(state=ReviewState.SUPERSEDED.value)
                )
            result = connection.execute(
                insert(review_requests)
                .values(
                    id=review_id,
                    **scope_values,
                    expires_at=expires_at,
                )
                .on_conflict_do_nothing(index_elements=[review_requests.c.id])
                .returning(review_requests.c.id)
            )
            if result.scalar_one_or_none() is None:
                raise _ReviewIdCollision
    except _ReviewIdCollision:
        existing = get_review_request(connection, review_id)
        if existing.scope == scope and existing.expires_at == expires_at:
            return existing
        raise ReviewConflict(
            "Review ID already contains different request data"
        ) from None
    return get_review_request(connection, review_id)


def _expire_if_due(connection: Connection, review_id: UUID) -> bool:
    result = connection.execute(
        update(review_requests)
        .where(
            review_requests.c.id == review_id,
            review_requests.c.state.in_(
                (
                    ReviewState.PENDING_DELIVERY.value,
                    ReviewState.AWAITING_DECISION.value,
                    ReviewState.DELIVERY_UNKNOWN.value,
                )
            ),
            review_requests.c.expires_at <= func.clock_timestamp(),
        )
        .values(state=ReviewState.EXPIRED.value)
        .returning(review_requests.c.id)
    )
    return result.scalar_one_or_none() is not None


def deliver_review_request(
    connection: Connection,
    review_id: UUID,
    *,
    outcome: DeliveryOutcome,
    error_code: str | None = None,
) -> ReviewRequest:
    """Persist a trusted delivery outcome; this function sends no content."""
    _require_transaction(connection)
    if type(outcome) is not DeliveryOutcome:
        raise TypeError("Invalid review delivery outcome")
    if outcome is DeliveryOutcome.FAILED:
        if (
            not isinstance(error_code, str)
            or re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", error_code) is None
        ):
            raise ValueError("A valid delivery error code is required")
    elif outcome is DeliveryOutcome.DELIVERED and error_code is not None:
        raise ValueError("A successful delivery cannot have an error code")
    elif error_code is not None and (
        not isinstance(error_code, str)
        or re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", error_code) is None
    ):
        raise ValueError("Invalid delivery error code")

    target = {
        DeliveryOutcome.DELIVERED: ReviewState.AWAITING_DECISION,
        DeliveryOutcome.FAILED: ReviewState.DELIVERY_FAILED,
        DeliveryOutcome.UNKNOWN: ReviewState.DELIVERY_UNKNOWN,
    }[outcome]
    request = get_review_request(connection, review_id)
    if request.state is target:
        if request.delivery_error_code == error_code:
            return request
        raise ReviewConflict("Review request already has a different delivery result")
    if request.state not in (
        ReviewState.PENDING_DELIVERY,
        ReviewState.DELIVERY_UNKNOWN,
    ):
        raise ReviewConflict("Review request cannot accept this delivery outcome")

    result = connection.execute(
        update(review_requests)
        .where(
            review_requests.c.id == review_id,
            review_requests.c.state == request.state.value,
            review_requests.c.expires_at > func.clock_timestamp(),
        )
        .values(state=target.value, delivery_error_code=error_code)
        .returning(review_requests.c.id)
    )
    if result.scalar_one_or_none() is not None:
        return get_review_request(connection, review_id)
    if _expire_if_due(connection, review_id):
        raise ReviewConflict("Expired review requests cannot receive outcomes")
    raise ReviewConflict("Review request changed before delivery outcome was recorded")


def expire_review_request(connection: Connection, review_id: UUID) -> ReviewRequest:
    """Mark a due, undecided request expired using the PostgreSQL clock."""
    _require_transaction(connection)
    request = get_review_request(connection, review_id)
    if request.state is ReviewState.EXPIRED:
        return request
    if _expire_if_due(connection, review_id):
        return get_review_request(connection, review_id)
    raise ReviewConflict("Review request is not eligible for expiry")


def _decision_from_row(row: RowMapping) -> ReviewDecision:
    try:
        outcome = DecisionOutcome(row["outcome"])
    except ValueError:
        raise ReviewCorrupt("Stored review decision is invalid") from None
    return ReviewDecision(
        review_id=row["review_id"],
        outcome=outcome,
        reviewer_id=row["reviewer_id"],
        decided_at=row["decided_at"],
    )


def get_review_decision(connection: Connection, review_id: UUID) -> ReviewDecision:
    row = connection.execute(
        select(review_decisions).where(review_decisions.c.review_id == review_id)
    ).one_or_none()
    if row is None:
        raise ReviewNotFound("Review decision not found")
    return _decision_from_row(row._mapping)


def decide_review(
    connection: Connection,
    review_id: UUID,
    outcome: DecisionOutcome,
    *,
    reviewer_id: str,
) -> ReviewDecision:
    """Persist one immutable decision from a trusted caller in its transaction."""
    _require_transaction(connection)
    _validate_request_id(review_id)
    if type(outcome) is not DecisionOutcome:
        raise TypeError("Invalid review decision")
    if not isinstance(reviewer_id, str):
        raise TypeError("Invalid reviewer identifier")
    try:
        validate_revision_identifier(reviewer_id)
    except ValueError:
        raise ValueError("Invalid reviewer identifier") from None

    existing_row = connection.execute(
        select(review_decisions).where(review_decisions.c.review_id == review_id)
    ).one_or_none()
    if existing_row is not None:
        existing = _decision_from_row(existing_row._mapping)
        if existing.outcome is outcome and existing.reviewer_id == reviewer_id:
            return existing
        raise ReviewConflict("Review request already has a different decision")

    request = get_review_request(connection, review_id)
    if request.state is not ReviewState.AWAITING_DECISION:
        raise ReviewConflict("Review request is not awaiting a decision")

    result = connection.execute(
        update(review_requests)
        .where(
            review_requests.c.id == review_id,
            review_requests.c.state == ReviewState.AWAITING_DECISION.value,
            review_requests.c.expires_at > func.clock_timestamp(),
        )
        .values(state=outcome.value)
        .returning(review_requests.c.id)
    )
    if result.scalar_one_or_none() is None:
        if _expire_if_due(connection, review_id):
            raise ReviewConflict("Expired review requests cannot be decided")
        committed_row = connection.execute(
            select(review_decisions).where(review_decisions.c.review_id == review_id)
        ).one_or_none()
        if committed_row is not None:
            committed = _decision_from_row(committed_row._mapping)
            if committed.outcome is outcome and committed.reviewer_id == reviewer_id:
                return committed
        raise ReviewConflict("Review request changed before decision was recorded")

    connection.execute(
        insert(review_decisions).values(
            review_id=review_id,
            outcome=outcome.value,
            reviewer_id=reviewer_id,
        )
    )
    return get_review_decision(connection, review_id)
