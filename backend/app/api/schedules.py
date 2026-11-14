"""Owner-only schedule descriptors and read-only previews."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import RFC_4122, UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.api.auth import ErrorResponse
from app.api.bounded_json import BoundedJSONRoute
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.services.scheduling.preview import preview_occurrences
from app.services.scheduling.store import (
    Schedule,
    ScheduleConflict,
    ScheduleNotFound,
    create_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from app.services.workflows.revisions import RevisionNotFound


class ScheduleJSONRoute(BoundedJSONRoute):
    methods_with_body = frozenset({"POST", "PUT"})
    invalid_headers_code = "INVALID_SCHEDULE_HEADERS"
    too_large_code = "SCHEDULE_BODY_TOO_LARGE"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DescriptorInput(Input):
    workflow_id: UUID = Field(alias="workflowId")
    revision: str = Field(min_length=1, max_length=128)
    expression: str = Field(min_length=1, max_length=256)
    time_zone: str = Field(alias="timeZone", min_length=1, max_length=255)
    enabled: bool
    overlap_policy: Literal["skip"] = Field(alias="overlapPolicy")
    missed_run_policy: Literal["skip"] = Field(alias="missedRunPolicy")

    @field_validator("workflow_id", mode="before")
    @classmethod
    def parse_workflow_id(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                pass
        return value


class UpdateInput(DescriptorInput):
    expected_version: int = Field(alias="expectedVersion", ge=1, lt=2147483647)


class PreviewInput(Input):
    after: AwareDatetime | None = None

    @field_validator("after", mode="before")
    @classmethod
    def parse_after(cls, value: object) -> object:
        if value is None:
            raise ValueError("An explicit preview cursor must be timezone-aware")
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return value


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)


class DescriptorOutput(Output):
    id: UUID
    workflow_id: UUID = Field(alias="workflowId")
    revision: str
    expression: str
    time_zone: str = Field(alias="timeZone")
    enabled: bool
    next_due_at: datetime | None = Field(alias="nextDueAt")
    overlap_policy: Literal["skip"] = Field(alias="overlapPolicy")
    missed_run_policy: Literal["skip"] = Field(alias="missedRunPolicy")
    version: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PageOutput(Output):
    data: list[DescriptorOutput]
    next_cursor: str | None = Field(alias="nextCursor")


class OccurrenceOutput(Output):
    local_time: datetime = Field(alias="localTime")
    due_at: datetime = Field(alias="dueAt")
    slot_key: str = Field(alias="slotKey")


class PreviewOutput(Output):
    occurrences: list[OccurrenceOutput]


def _id(value: UUID) -> UUID:
    if value.version != 4 or value.variant != RFC_4122:
        raise AuthDenied("INVALID_REQUEST", 422)
    return value


def _clock(connection: Connection) -> datetime:
    value: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
    return value


def _output(value: Schedule) -> DescriptorOutput:
    return DescriptorOutput.model_validate(value)


def _no_query(request: Request) -> None:
    if request.query_params:
        raise AuthDenied("INVALID_REQUEST", 422)


def schedules_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/schedules",
        route_class=ScheduleJSONRoute,
        responses={
            status: {"model": ErrorResponse, "description": "Request could not be completed"}
            for status in (401, 403, 404, 409, 422, 503)
        },
    )
    _, owner = auth_dependencies(config, store)

    def persistence() -> AuthStore:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return store

    @router.get("", response_model=PageOutput)
    def page(
        request: Request,
        _: Annotated[Principal, Depends(owner)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=36)] = None,
    ) -> PageOutput:
        names = [name for name, _ in request.query_params.multi_items()]
        if set(names) - {"limit", "cursor"} or len(names) != len(set(names)):
            raise AuthDenied("INVALID_REQUEST", 422)
        position = None
        if cursor is not None:
            try:
                position = _id(UUID(cursor))
            except ValueError:
                raise AuthDenied("INVALID_REQUEST", 422) from None
            if str(position) != cursor:
                raise AuthDenied("INVALID_REQUEST", 422)
        with persistence().transaction() as connection:
            rows = list_schedules(connection, limit=limit, after=position)
        return PageOutput(
            data=[_output(row) for row in rows],
            nextCursor=str(rows[-1].id) if len(rows) == limit else None,
        )

    @router.post("", response_model=DescriptorOutput, status_code=201)
    def create(
        request: Request, body: DescriptorInput, _: Annotated[Principal, Depends(owner)],
    ) -> DescriptorOutput:
        _no_query(request)
        try:
            with persistence().transaction() as connection:
                cursor = _clock(connection)
                try:
                    value = create_schedule(
                        connection, uuid4(), body.workflow_id, body.revision,
                        expression=body.expression, time_zone=body.time_zone,
                        enabled=body.enabled, cursor=cursor,
                    )
                except ValueError:
                    raise AuthDenied("INVALID_REQUEST", 422) from None
        except RevisionNotFound:
            raise AuthDenied("REVISION_NOT_FOUND", 404) from None
        except ScheduleConflict:
            raise AuthDenied("SCHEDULE_CONFLICT", 409) from None
        return _output(value)

    @router.get("/{id}", response_model=DescriptorOutput)
    def read(
        id: UUID, request: Request, _: Annotated[Principal, Depends(owner)],
    ) -> DescriptorOutput:
        _no_query(request)
        _id(id)
        try:
            with persistence().transaction() as connection:
                value = get_schedule(connection, id)
        except ScheduleNotFound:
            raise AuthDenied("SCHEDULE_NOT_FOUND", 404) from None
        return _output(value)

    @router.put("/{id}", response_model=DescriptorOutput)
    def replace(
        id: UUID, request: Request, body: UpdateInput, _: Annotated[Principal, Depends(owner)],
    ) -> DescriptorOutput:
        _no_query(request)
        _id(id)
        try:
            with persistence().transaction() as connection:
                cursor = _clock(connection)
                try:
                    value = update_schedule(
                        connection, id, expected_version=body.expected_version,
                        workflow_id=body.workflow_id, revision=body.revision,
                        expression=body.expression, time_zone=body.time_zone,
                        enabled=body.enabled, cursor=cursor,
                    )
                except ValueError:
                    raise AuthDenied("INVALID_REQUEST", 422) from None
        except (ScheduleNotFound, RevisionNotFound):
            raise AuthDenied("SCHEDULE_NOT_FOUND", 404) from None
        except ScheduleConflict:
            raise AuthDenied("SCHEDULE_CONFLICT", 409) from None
        return _output(value)

    @router.post("/{id}/previews", response_model=PreviewOutput)
    def preview(
        id: UUID, request: Request, body: PreviewInput, _: Annotated[Principal, Depends(owner)],
    ) -> PreviewOutput:
        _no_query(request)
        _id(id)
        try:
            with persistence().transaction() as connection:
                value = get_schedule(connection, id)
                cursor = body.after if body.after is not None else _clock(connection)
        except ScheduleNotFound:
            raise AuthDenied("SCHEDULE_NOT_FOUND", 404) from None
        try:
            occurrences = preview_occurrences(value.expression, value.time_zone, cursor)
        except (ValueError, OverflowError):
            raise AuthDenied("INVALID_REQUEST", 422) from None
        return PreviewOutput(occurrences=[
            OccurrenceOutput.model_validate(occurrence) for occurrence in occurrences
        ])

    return router
