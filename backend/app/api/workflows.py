"""Owner-authorized workflow discovery, draft access and validation APIs."""

import base64
import binascii
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import ErrorResponse
from app.api.bounded_json import BoundedJSONRoute
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.services.workflows.document import (
    InvalidWorkflowDocument,
    validate_revision_identifier,
)
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
from app.services.workflows.run_requests import (
    RunRequestConflict,
    RunRequestCorrupt,
    request_run,
)
from app.services.workflows.sample_evaluator import validate_sample_document

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
_MAX_WORKFLOW_BODY_BYTES = 262_144


class WorkflowJSONRoute(BoundedJSONRoute):
    max_body_bytes = _MAX_WORKFLOW_BODY_BYTES
    methods_with_body = frozenset({"POST", "PUT"})
    invalid_headers_code = "INVALID_WORKFLOW_HEADERS"
    too_large_code = "WORKFLOW_BODY_TOO_LARGE"


class WorkflowRunJSONRoute(WorkflowJSONRoute):
    max_body_bytes = 4096
    methods_with_body = frozenset({"POST"})


class RunCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: str = Field(min_length=1, max_length=128)


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


class RunCreateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: UUID = Field(alias="runId")


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


class WorkflowValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(
        alias="expectedVersion",
        ge=1,
        lt=2_147_483_647,
    )


class WorkflowValidationIssueOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: str
    message: str
    node_id: str | None = Field(default=None, alias="nodeId")
    edge_id: str | None = Field(default=None, alias="edgeId")
    source_port: str | None = Field(default=None, alias="sourcePort")
    target_port: str | None = Field(default=None, alias="targetPort")


class WorkflowValidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")
    draft_version: int = Field(alias="draftVersion", ge=1)
    is_valid: bool = Field(alias="isValid")
    issues: list[WorkflowValidationIssueOutput]


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


def _parse_idempotency_key(value: str, request: Request) -> UUID:
    headers = request.headers.getlist("idempotency-key")
    if len(headers) != 1 or headers[0] != value:
        raise AuthDenied("INVALID_REQUEST", 422)
    try:
        request_id = UUID(value)
    except ValueError:
        raise AuthDenied("INVALID_REQUEST", 422) from None
    if (
        str(request_id) != value
        or request_id.version != 4
        or request_id.variant != RFC_4122
    ):
        raise AuthDenied("INVALID_REQUEST", 422)
    return request_id


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

    run_router = APIRouter(route_class=WorkflowRunJSONRoute)

    @run_router.post(
        "/{id}/runs",
        response_model=RunCreateOutput,
        status_code=202,
        responses={
            202: {
                "headers": {
                    "Location": {
                        "description": "URL for reading persisted run status.",
                        "schema": {"type": "string"},
                    }
                }
            },
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
    def create_run(
        id: UUID,
        request: Request,
        response: Response,
        body: RunCreateInput,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=36,
                max_length=36,
                description=(
                    "Canonical lowercase RFC-variant UUID4, reused for retries "
                    "of this run intent."
                ),
            ),
        ],
        _: Annotated[Principal, Depends(owner)],
    ) -> RunCreateOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        request_id = _parse_idempotency_key(idempotency_key, request)
        try:
            validate_revision_identifier(body.revision)
        except ValueError:
            raise AuthDenied("INVALID_REQUEST", 422) from None

        try:
            with persistence().transaction() as connection:
                snapshot = get_revision(connection, id, body.revision)
                run_request = request_run(
                    connection,
                    request_id,
                    id,
                    body.revision,
                    snapshot.sha256,
                )
        except RevisionNotFound:
            raise AuthDenied("REVISION_NOT_FOUND", 404) from None
        except RunRequestConflict:
            raise AuthDenied("WORKFLOW_RUN_CONFLICT", 409) from None
        except (RevisionCorrupt, RunRequestCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None

        response.headers["Location"] = f"/api/v1/runs/{run_request.run_id}"
        return RunCreateOutput(runId=run_request.run_id)

    router.include_router(run_router)

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

    @router.post(
        "/{id}/validations",
        response_model=WorkflowValidationOutput,
        response_model_exclude_none=True,
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
    def validate_workflow_draft(
        id: UUID,
        request: Request,
        body: WorkflowValidationInput,
        _: Annotated[Principal, Depends(owner)],
    ) -> WorkflowValidationOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        try:
            with persistence().transaction() as connection:
                draft = get_draft(connection, id)
        except WorkflowDraftNotFound:
            raise AuthDenied("WORKFLOW_DRAFT_NOT_FOUND", 404) from None
        except (WorkflowDraftCorrupt, RuntimeError, SQLAlchemyError):
            raise AuthDenied("DEPENDENCY_UNAVAILABLE", 503) from None
        if draft.version != body.expected_version:
            raise AuthDenied("WORKFLOW_DRAFT_CONFLICT", 409)

        try:
            parsed = validate_sample_document(draft.document)
        except InvalidWorkflowDocument:
            issues = [
                WorkflowValidationIssueOutput(
                    code="INVALID_DOCUMENT",
                    message="Workflow document is invalid",
                )
            ]
        else:
            issues = [
                WorkflowValidationIssueOutput(
                    code=issue.code,
                    message=issue.message,
                    nodeId=issue.node_id,
                    edgeId=issue.edge_id,
                    sourcePort=issue.source_port,
                    targetPort=issue.target_port,
                )
                for issue in parsed.issues
            ]
        return WorkflowValidationOutput(
            workflowId=id,
            draftVersion=draft.version,
            isValid=not issues,
            issues=issues,
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
