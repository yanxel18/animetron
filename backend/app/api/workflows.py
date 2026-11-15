"""Authenticated, owner-only reads of persisted immutable workflow revisions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.services.workflows.document import validate_revision_identifier
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    get_revision,
)


class RevisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workflow_id: UUID = Field(alias="workflowId")
    revision: str
    canonical_json: str = Field(alias="canonicalJson")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def workflows_router(config: AuthConfig | None, store: AuthStore | None) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/workflows",
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

    @router.get("/{id}/revisions/{revision}", response_model=RevisionOutput)
    def read_revision(
        id: UUID,
        revision: Annotated[str, Path(min_length=1, max_length=128)],
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> RevisionOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
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

    return router
