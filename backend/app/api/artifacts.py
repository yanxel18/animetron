"""Authenticated, owner-only reads of artifact metadata."""

from typing import Annotated
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.artifacts import ArtifactNotFound, get_artifact
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal


class ArtifactMetadataOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: UUID
    owner_id: str = Field(alias="ownerId")
    revision: str
    sha256: str
    byte_size: int = Field(alias="byteSize")
    media_type: str = Field(alias="mediaType")


def artifacts_router(
    config: AuthConfig | None, store: AuthStore | None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/artifacts",
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

    @router.get("/{id}", response_model=ArtifactMetadataOutput)
    def read_metadata(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> ArtifactMetadataOutput:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        if id.version != 4 or id.variant != RFC_4122:
            raise AuthDenied("ARTIFACT_NOT_FOUND", 404)
        try:
            with persistence().transaction() as connection:
                record = get_artifact(connection, id)
        except ArtifactNotFound:
            raise AuthDenied("ARTIFACT_NOT_FOUND", 404) from None
        return ArtifactMetadataOutput(
            id=record.id,
            ownerId=record.owner_id,
            revision=record.revision,
            sha256=record.sha256,
            byteSize=record.byte_size,
            mediaType=record.media_type,
        )

    return router
