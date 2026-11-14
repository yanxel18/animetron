"""Authenticated metadata queue and exact-scope human decision endpoints."""

import base64
import binascii
import re
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import Response

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.core.outbox import OutboxConflict
from app.services.reviews.decisions import record_decision
from app.services.reviews.scope import ReviewDestination, ReviewScope
from app.services.reviews.store import (
    DecisionOutcome,
    ReviewConflict,
    ReviewDecision,
    ReviewNotFound,
    ReviewRequest,
    ReviewState,
    list_review_requests,
)

_MAX_DECISION_BODY_BYTES = 4096
_CURSOR_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class BoundedJSONRoute(APIRoute):
    """Cap review mutation bodies before FastAPI/Pydantic parses JSON."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            if request.method != "POST":
                return await handler(request)

            lengths = request.headers.getlist("content-length")
            media_types = request.headers.getlist("content-type")
            encodings = request.headers.getlist("content-encoding")
            if (
                len(lengths) > 1
                or len(media_types) != 1
                or media_types[0].split(";", 1)[0].strip().lower() != "application/json"
                or len(encodings) > 1
                or encodings and encodings[0].lower() != "identity"
            ):
                raise AuthDenied("INVALID_REVIEW_HEADERS", 422)
            if lengths:
                declared = lengths[0]
                if not declared.isascii() or not declared.isdigit():
                    raise AuthDenied("INVALID_CONTENT_LENGTH", 422)
                # Compare canonical decimals without converting attacker-sized
                # integers; leading zeros retain their existing numeric meaning.
                canonical = declared.lstrip("0") or "0"
                maximum = str(_MAX_DECISION_BODY_BYTES)
                if len(canonical) > len(maximum) or (
                    len(canonical) == len(maximum) and canonical > maximum
                ):
                    raise AuthDenied("REVIEW_BODY_TOO_LARGE", 422)

            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > _MAX_DECISION_BODY_BYTES:
                    raise AuthDenied("REVIEW_BODY_TOO_LARGE", 422)
                body.extend(chunk)
            # FastAPI reads Request.body() for its typed JSON model. The stream
            # has been bounded above; cache only those bounded bytes for parsing.
            request.__dict__["_body"] = bytes(body)
            return await handler(request)

        return bounded


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StrictInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReviewDestinationInput(StrictInputModel):
    provider: str
    account_id: str = Field(alias="accountId")


class ReviewScopeInput(StrictInputModel):
    run_id: UUID = Field(alias="runId")
    artifact_revision: str = Field(alias="artifactRevision")
    artifact_sha256: str = Field(alias="artifactSha256")
    caption_sha256: str = Field(alias="captionSha256")
    destinations: list[ReviewDestinationInput]

    @field_validator("run_id", mode="before")
    @classmethod
    def parse_run_id(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                return value
        return value

    def to_scope(self) -> ReviewScope:
        return ReviewScope(
            run_id=self.run_id,
            artifact_revision=self.artifact_revision,
            artifact_sha256=self.artifact_sha256,
            caption_sha256=self.caption_sha256,
            destinations=tuple(
                ReviewDestination(item.provider, item.account_id)
                for item in self.destinations
            ),
        )


class ReviewDecisionInput(StrictInputModel):
    expected_scope: ReviewScopeInput = Field(alias="expectedScope")
    outcome: Literal["APPROVED", "REJECTED"]


class ReviewDestinationResponse(PublicModel):
    provider: str
    account_id: str = Field(alias="accountId")


class ReviewMetadataResponse(PublicModel):
    id: UUID
    run_id: UUID = Field(alias="runId")
    artifact_revision: str = Field(alias="artifactRevision")
    artifact_sha256: str = Field(alias="artifactSha256")
    caption_sha256: str = Field(alias="captionSha256")
    destinations: list[ReviewDestinationResponse]
    expires_at: datetime = Field(alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")
    state: ReviewState
    state_changed_at: datetime = Field(alias="stateChangedAt")
    delivery_error_code: str | None = Field(alias="deliveryErrorCode")


class ReviewPageResponse(PublicModel):
    data: list[ReviewMetadataResponse]
    next_cursor: str | None = Field(alias="nextCursor")


class ReviewDecisionResponse(PublicModel):
    review_id: UUID = Field(alias="reviewId")
    outcome: Literal["APPROVED", "REJECTED"]
    decided_at: datetime = Field(alias="decidedAt")


def _encode_cursor(request: ReviewRequest) -> str:
    value = (
        request.created_at.astimezone(UTC).isoformat(timespec="microseconds")
        + "|"
        + str(request.id)
    )
    return base64.urlsafe_b64encode(value.encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    if _CURSOR_PATTERN.fullmatch(value) is None:
        raise AuthDenied("INVALID_REQUEST", 422)
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True,
        ).decode("ascii")
        timestamp, raw_id = decoded.split("|", 1)
        created_at = datetime.fromisoformat(timestamp)
        review_id = UUID(raw_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise AuthDenied("INVALID_REQUEST", 422) from None
    offset = created_at.utcoffset()
    if (
        created_at.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
        or review_id.version != 4
        or review_id.variant != RFC_4122
        or str(review_id) != raw_id
    ):
        raise AuthDenied("INVALID_REQUEST", 422)
    return created_at, review_id


def _metadata(request: ReviewRequest) -> ReviewMetadataResponse:
    return ReviewMetadataResponse(
        id=request.id,
        runId=request.scope.run_id,
        artifactRevision=request.scope.artifact_revision,
        artifactSha256=request.scope.artifact_sha256,
        captionSha256=request.scope.caption_sha256,
        destinations=[
            ReviewDestinationResponse(provider=item.provider, accountId=item.account_id)
            for item in request.scope.destinations
        ],
        expiresAt=request.expires_at,
        createdAt=request.created_at,
        state=request.state,
        stateChangedAt=request.state_changed_at,
        deliveryErrorCode=request.delivery_error_code,
    )


def _decision_response(decision: ReviewDecision) -> ReviewDecisionResponse:
    return ReviewDecisionResponse(
        reviewId=decision.review_id,
        outcome=decision.outcome.value,
        decidedAt=decision.decided_at,
    )


def reviews_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/reviews",
        route_class=BoundedJSONRoute,
        responses={
            status: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            }
            for status in (401, 403, 404, 409, 422, 503)
        },
    )
    _, owner = auth_dependencies(config, store)

    def persistence() -> AuthStore:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return store

    @router.get("", response_model=ReviewPageResponse)
    def queue(
        request: Request,
        _: Annotated[Principal, Depends(owner)],
        cursor: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> ReviewPageResponse:
        parameters = request.query_params.multi_items()
        names = [name for name, _value in parameters]
        if set(names) - {"cursor", "limit"} or len(names) != len(set(names)):
            raise AuthDenied("INVALID_REQUEST", 422)
        position = _decode_cursor(cursor) if cursor is not None else None
        with persistence().transaction() as connection:
            rows = list_review_requests(connection, position, limit + 1)
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1]) if len(rows) > limit else None
        return ReviewPageResponse(
            data=[_metadata(item) for item in page],
            nextCursor=next_cursor,
        )

    @router.post(
        "/{id}/decisions",
        response_model=ReviewDecisionResponse,
    )
    def decide(
        id: UUID,
        body: ReviewDecisionInput,
        user: Annotated[Principal, Depends(owner)],
    ) -> ReviewDecisionResponse:
        if id.version != 4 or id.variant != RFC_4122:
            raise AuthDenied("INVALID_REVIEW_ID", 422)
        try:
            expected_scope = body.expected_scope.to_scope()
        except (TypeError, ValueError):
            raise AuthDenied("INVALID_REVIEW_SCOPE", 422) from None
        outcome = DecisionOutcome(body.outcome)
        try:
            with persistence().transaction() as connection:
                decision = record_decision(
                    connection, user, expected_scope, id, outcome,
                )
        except ReviewNotFound:
            raise AuthDenied("REVIEW_NOT_FOUND", 404) from None
        except (ReviewConflict, OutboxConflict):
            raise AuthDenied("REVIEW_CONFLICT", 409) from None
        return _decision_response(decision)

    return router
