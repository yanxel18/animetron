"""Authenticated, owner-only HTTP reads of durable workflow run state."""

import re
from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.services.workflows import run_cancellations
from app.services.workflows import runs as run_store
from app.services.workflows.run_cancellations import (
    CancellationOutcome,
    RunCancellationCorrupt,
)
from app.services.workflows.runs import (
    RunConflict,
    RunEvent,
    RunNotFound,
    RunState,
    RunStatus,
)

_ASCII_DECIMAL = re.compile(r"[0-9]+\Z")
_MAX_SEQUENCE = 2_147_483_647
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunStatusOutput(Output):
    run_id: UUID = Field(alias="runId")
    state: RunState
    last_sequence: int = Field(alias="lastSequence")


class RunEventOutput(Output):
    run_id: UUID = Field(alias="runId")
    sequence: int
    state: RunState
    message: str
    occurred_at: AwareDatetime = Field(alias="occurredAt")


class RunEventPageOutput(Output):
    data: list[RunEventOutput]
    next_after_sequence: int = Field(alias="nextAfterSequence")
    has_more: bool = Field(alias="hasMore")


class RunCancellationOutput(Output):
    run_id: UUID = Field(alias="runId")
    state: RunState
    last_sequence: int = Field(alias="lastSequence")
    outcome: CancellationOutcome


def _validate_query_parameters(request: Request, allowed: set[str]) -> None:
    names = [name for name, _value in request.query_params.multi_items()]
    if set(names) - allowed or len(names) != len(set(names)):
        raise AuthDenied("INVALID_REQUEST", 422)


def _parse_decimal(
    value: str | None,
    *,
    default: int,
    max_digits: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if len(value) > max_digits or _ASCII_DECIMAL.fullmatch(value) is None:
        raise AuthDenied("INVALID_REQUEST", 422)
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise AuthDenied("INVALID_REQUEST", 422)
    return parsed


def _event_output(event: RunEvent) -> RunEventOutput:
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise RuntimeError("Stored run event timestamp is not timezone-aware")
    return RunEventOutput(
        runId=event.run_id,
        sequence=event.sequence,
        state=event.state,
        message=event.message,
        occurredAt=occurred_at.astimezone(UTC),
    )


def runs_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/runs",
        responses={
            status: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            }
            for status in (401, 403, 404, 422, 503)
        },
    )
    _, owner = auth_dependencies(config, store)

    def persistence() -> AuthStore:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return store

    @router.get("/{id}", response_model=RunStatusOutput)
    def read_status(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> RunStatusOutput:
        _validate_query_parameters(request, set())
        try:
            with persistence().transaction() as connection:
                status: RunStatus = run_store.get_run_status(connection, id)
        except RunNotFound:
            raise AuthDenied("RUN_NOT_FOUND", 404) from None
        return RunStatusOutput(
            runId=status.run_id,
            state=status.state,
            lastSequence=status.last_sequence,
        )

    @router.get("/{id}/events", response_model=RunEventPageOutput)
    def read_events(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> RunEventPageOutput:
        _validate_query_parameters(request, {"afterSequence", "limit"})
        after_sequence = _parse_decimal(
            request.query_params.get("afterSequence"),
            default=0,
            max_digits=10,
            minimum=0,
            maximum=_MAX_SEQUENCE,
        )
        limit = _parse_decimal(
            request.query_params.get("limit"),
            default=_DEFAULT_LIMIT,
            max_digits=3,
            minimum=1,
            maximum=_MAX_LIMIT,
        )
        try:
            with persistence().transaction() as connection:
                events = run_store.list_events(
                    connection, id, after_sequence, limit=limit + 1,
                )
        except RunNotFound:
            raise AuthDenied("RUN_NOT_FOUND", 404) from None

        page = events[:limit]
        return RunEventPageOutput(
            data=[_event_output(event) for event in page],
            nextAfterSequence=page[-1].sequence if page else after_sequence,
            hasMore=len(events) > limit,
        )

    @router.post(
        "/{id}/cancellations",
        response_model=RunCancellationOutput,
        status_code=202,
        responses={
            409: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            }
        },
    )
    def request_cancellation(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> RunCancellationOutput:
        _validate_query_parameters(request, set())
        try:
            with persistence().transaction() as connection:
                result = run_cancellations.request_run_cancellation(connection, id)
        except RunNotFound:
            raise AuthDenied("RUN_NOT_FOUND", 404) from None
        except RunConflict:
            raise AuthDenied("RUN_CANCELLATION_CONFLICT", 409) from None
        except (RunCancellationCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None
        return RunCancellationOutput(
            runId=result.run_id,
            state=result.state,
            lastSequence=result.last_sequence,
            outcome=result.outcome,
        )

    return router
