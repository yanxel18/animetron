"""Authenticated, owner-only reads of persisted immutable workflow revisions."""

import base64
import binascii
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import ErrorResponse
from app.api.bounded_json import BoundedJSONRoute
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.services.workflows.document import validate_revision_identifier
from app.services.workflows.drafts import (
    WorkflowDraftConflict,
    WorkflowDraftCorrupt,
    WorkflowDraftNotFound,
    get_draft,
    save_draft,
)
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionCursor,
    RevisionNotFound,
    get_revision,
    list_revisions,
    list_workflow_ids,
)

_ASCII_DECIMAL = re.compile(r"[0-9]+\Z")
_CURSOR_CHARS = re.compile(r"[A-Za-z0-9_-]+\Z")
_CURSOR_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_DEFAULT_REVISION_LIMIT = 50
_MAX_REVISION_LIMIT = 100
_MAX_CURSOR_LENGTH = 2304
_MAX_WORKFLOW_CURSOR_LENGTH = 128
_MAX_DRAFT_DOCUMENT_BYTES = 32_768
_MAX_DRAFT_BODY_BYTES = 262_144


class WorkflowJSONRoute(BoundedJSONRoute):
    max_body_bytes = _MAX_DRAFT_BODY_BYTES
    methods_with_body = frozenset({"PUT"})
    invalid_headers_code = "INVALID_WORKFLOW_HEADERS"
    too_large_code = "WORKFLOW_DRAFT_BODY_TOO_LARGE"


class RevisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")
    revision: str
    canonical_json: str = Field(alias="canonicalJson")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RevisionSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")
    revision: str = Field(min_length=1, max_length=128)
    created_at: AwareDatetime = Field(alias="createdAt")


class RevisionListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: list[RevisionSummaryOutput]
    next_cursor: str | None = Field(alias="nextCursor")


class WorkflowIdOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")


class WorkflowIdListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: list[WorkflowIdOutput]
    next_cursor: str | None = Field(alias="nextCursor")


class WorkflowDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")
    document: str
    version: int = Field(ge=1)


class WorkflowDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    document: str
    expected_version: int | None = Field(
        alias="expectedVersion",
        ge=1,
        lt=2_147_483_647,
    )


def _encode_workflow_cursor(workflow_id: UUID) -> str:
    payload = json.dumps(
        {"after": str(workflow_id), "version": 1}, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _parse_workflow_cursor(value: str | None) -> UUID | None:
    if value is None:
        return None
    if (
        not value
        or len(value) > _MAX_WORKFLOW_CURSOR_LENGTH
        or _CURSOR_CHARS.fullmatch(value) is None
    ):
        raise AuthDenied("INVALID_REQUEST", 422)
    try:
        data = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(data.decode("ascii"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"after", "version"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or not isinstance(payload["after"], str)
        ):
            raise ValueError("Invalid cursor")
        workflow_id = UUID(payload["after"])
        if _encode_workflow_cursor(workflow_id) != value:
            raise ValueError("Non-canonical cursor")
    except (binascii.Error, UnicodeDecodeError, ValueError, RecursionError):
        raise AuthDenied("INVALID_REQUEST", 422) from None
    return workflow_id


def _parse_revision_limit(value: str | None) -> int:
    if value is None:
        return _DEFAULT_REVISION_LIMIT
    if (
        len(value) > 3
        or _ASCII_DECIMAL.fullmatch(value) is None
        or not 1 <= int(value) <= _MAX_REVISION_LIMIT
    ):
        raise AuthDenied("INVALID_REQUEST", 422)
    return int(value)


def _encode_revision_cursor(
    workflow_id: UUID, created_at: datetime, revision: str
) -> str:
    payload = {
        "createdAt": created_at.astimezone(UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
        "revision": revision,
        "version": 1,
        "workflowId": str(workflow_id),
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _parse_revision_cursor(value: str | None, workflow_id: UUID) -> RevisionCursor | None:
    if value is None:
        return None
    if (
        not value
        or len(value) > _MAX_CURSOR_LENGTH
        or _CURSOR_CHARS.fullmatch(value) is None
    ):
        raise AuthDenied("INVALID_REQUEST", 422)
    try:
        encoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(encoded.decode("ascii"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"createdAt", "revision", "version", "workflowId"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or payload["workflowId"] != str(workflow_id)
            or not isinstance(payload["createdAt"], str)
            or _CURSOR_TIMESTAMP.fullmatch(payload["createdAt"]) is None
            or not isinstance(payload["revision"], str)
        ):
            raise ValueError("Invalid cursor")
        created_at = datetime.strptime(
            payload["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=UTC)
        validate_revision_identifier(payload["revision"])
        if _encode_revision_cursor(
            workflow_id, created_at, payload["revision"]
        ) != value:
            raise ValueError("Non-canonical cursor")
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        RecursionError,
        json.JSONDecodeError,
    ):
        raise AuthDenied("INVALID_REQUEST", 422) from None
    return RevisionCursor(created_at=created_at, revision=payload["revision"])


def workflows_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/workflows",
        route_class=WorkflowJSONRoute,
        responses={
            status: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            }
            for status in (401, 403, 422, 503)
        },
    )
    _, owner = auth_dependencies(config, store)

    def persistence() -> AuthStore:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return store

    @router.get("", response_model=WorkflowIdListOutput)
    def discover_workflows(
        request: Request,
        _: Annotated[Principal, Depends(owner)],
        cursor: Annotated[
            str | None,
            Query(
                description="Opaque exclusive continuation cursor from a prior page.",
                min_length=1,
                max_length=_MAX_WORKFLOW_CURSOR_LENGTH,
                pattern=r"^[A-Za-z0-9_-]+$",
            ),
        ] = None,
        limit: Annotated[
            str | None,
            Query(
                description="ASCII decimal page size, default 50 and bounded to 1..100.",
                min_length=1,
                max_length=3,
                pattern=r"^[0-9]+$",
            ),
        ] = None,
    ) -> WorkflowIdListOutput:
        names = [name for name, _value in request.query_params.multi_items()]
        if set(names) - {"cursor", "limit"} or len(names) != len(set(names)):
            raise AuthDenied("INVALID_REQUEST", 422)
        page_size = _parse_revision_limit(limit)
        position = _parse_workflow_cursor(cursor)
        try:
            with persistence().transaction() as connection:
                ids = list_workflow_ids(connection, after=position, limit=page_size + 1)
        except (RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None
        page = ids[:page_size]
        return WorkflowIdListOutput(
            data=[WorkflowIdOutput(workflowId=workflow_id) for workflow_id in page],
            nextCursor=_encode_workflow_cursor(page[-1]) if len(ids) > page_size else None,
        )

    @router.get(
        "/{id}/draft",
        response_model=WorkflowDraftOutput,
        responses={
            404: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            }
        },
    )
    def read_workflow_draft(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> WorkflowDraftOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        try:
            with persistence().transaction() as connection:
                draft = get_draft(connection, id)
        except WorkflowDraftNotFound:
            raise AuthDenied("WORKFLOW_DRAFT_NOT_FOUND", 404) from None
        except (WorkflowDraftCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None
        return WorkflowDraftOutput(
            workflowId=draft.workflow_id,
            document=draft.document.decode("utf-8"),
            version=draft.version,
        )

    @router.put(
        "/{id}/draft",
        response_model=WorkflowDraftOutput,
        responses={
            404: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            },
            409: {
                "model": ErrorResponse,
                "description": "Request could not be completed",
            },
        },
    )
    def write_workflow_draft(
        id: UUID,
        request: Request,
        body: WorkflowDraftInput,
        _: Annotated[Principal, Depends(owner)],
    ) -> WorkflowDraftOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        try:
            document = body.document.encode("utf-8")
        except UnicodeEncodeError:
            raise AuthDenied("INVALID_REQUEST", 422) from None
        try:
            with persistence().transaction() as connection:
                draft = save_draft(
                    connection,
                    id,
                    document,
                    expected_version=body.expected_version,
                    max_bytes=_MAX_DRAFT_DOCUMENT_BYTES,
                )
        except WorkflowDraftNotFound:
            raise AuthDenied("WORKFLOW_DRAFT_NOT_FOUND", 404) from None
        except WorkflowDraftConflict:
            raise AuthDenied("WORKFLOW_DRAFT_CONFLICT", 409) from None
        except ValueError:
            raise AuthDenied("INVALID_REQUEST", 422) from None
        except (WorkflowDraftCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None
        return WorkflowDraftOutput(
            workflowId=draft.workflow_id,
            document=draft.document.decode("utf-8"),
            version=draft.version,
        )

    @router.get("/{id}/revisions", response_model=RevisionListOutput)
    def list_workflow_revisions(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
        cursor: Annotated[
            str | None,
            Query(
                description="Opaque continuation cursor from a prior page for this workflow.",
                min_length=1,
                max_length=_MAX_CURSOR_LENGTH,
                pattern=r"^[A-Za-z0-9_-]+$",
            ),
        ] = None,
        limit: Annotated[
            str | None,
            Query(
                description="ASCII decimal page size, default 50 and bounded to 1..100.",
                min_length=1,
                max_length=3,
                pattern=r"^[0-9]+$",
            ),
        ] = None,
    ) -> RevisionListOutput:
        names = [name for name, _value in request.query_params.multi_items()]
        if set(names) - {"cursor", "limit"} or len(names) != len(set(names)):
            raise AuthDenied("INVALID_REQUEST", 422)
        page_size = _parse_revision_limit(limit)
        position = _parse_revision_cursor(cursor, id)
        try:
            with persistence().transaction() as connection:
                revisions = list_revisions(
                    connection,
                    id,
                    after=position,
                    limit=page_size + 1,
                )
        except (RevisionCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None

        page = revisions[:page_size]
        next_cursor = (
            _encode_revision_cursor(id, page[-1].created_at, page[-1].revision)
            if len(revisions) > page_size
            else None
        )
        return RevisionListOutput(
            data=[
                RevisionSummaryOutput(
                    workflowId=id,
                    revision=revision.revision,
                    createdAt=revision.created_at.astimezone(UTC),
                )
                for revision in page
            ],
            nextCursor=next_cursor,
        )

    def load_revision(id: UUID, revision: str) -> RevisionOutput:
        try:
            validate_revision_identifier(revision)
        except ValueError:
            raise AuthDenied("INVALID_REQUEST", 422) from None
        try:
            with persistence().transaction() as connection:
                snapshot = get_revision(connection, id, revision)
        except RevisionNotFound:
            raise AuthDenied("REVISION_NOT_FOUND", 404) from None
        except RevisionCorrupt:
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None

        return RevisionOutput(
            workflowId=id,
            revision=snapshot.revision,
            canonicalJson=snapshot.canonical_json.decode("ascii"),
            sha256=snapshot.sha256,
        )

    not_found: dict[int | str, dict[str, Any]] = {
        404: {
            "model": ErrorResponse,
            "description": "Request could not be completed",
        }
    }

    @router.get("/{id}/revision", response_model=RevisionOutput, responses=not_found)
    def read_revision_by_query(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
        revision: Annotated[str, Query(min_length=1, max_length=128)],
    ) -> RevisionOutput:
        if [name for name, _ in request.query_params.multi_items()] != ["revision"]:
            raise AuthDenied("INVALID_REQUEST", 422)
        return load_revision(id, revision)

    @router.get(
        "/{id}/revisions/{revision}", response_model=RevisionOutput, responses=not_found
    )
    def read_revision(
        id: UUID,
        revision: Annotated[str, Path(min_length=1, max_length=128)],
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> RevisionOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        return load_revision(id, revision)

    return router
