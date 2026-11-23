"""Authenticated, owner-only reads of artifact metadata and content."""

import re
from typing import Annotated
from uuid import RFC_4122, UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.artifact_bytes import (
    ArtifactByteStore,
    StoredBytes,
    UnsupportedStorageError,
)
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


MAX_ARTIFACT_CONTENT_BYTES = 128 * 1024 * 1024
_INLINE_MEDIA_TYPES = frozenset({
    "image/gif", "image/jpeg", "image/png", "image/webp",
    "video/mp4", "video/webm",
})
_DOCUMENTED_CONTENT_TYPES = (
    "application/octet-stream",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
)


def _binary_content_schema() -> dict[str, object]:
    return {
        media_type: {"schema": {"type": "string", "format": "binary"}}
        for media_type in _DOCUMENTED_CONTENT_TYPES
    }


def _byte_range(value: str, size: int) -> tuple[int, int]:
    """Parse one RFC-style byte range; multipart responses are not supported."""
    if len(value) > 128 or "," in value:
        raise ValueError("Invalid byte range")
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if match is None or (not match.group(1) and not match.group(2)) or size == 0:
        raise ValueError("Invalid byte range")
    first, last = match.groups()
    if not first:
        suffix = int(last)
        if suffix == 0:
            raise ValueError("Invalid byte range")
        return max(0, size - suffix), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Invalid byte range")
    return start, min(end, size - 1)


def artifacts_router(
    config: AuthConfig | None,
    store: AuthStore | None,
    byte_store: ArtifactByteStore | None = None,
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

    @router.get(
        "/{id}/content",
        response_class=Response,
        responses={
            200: {
                "description": "Full artifact content",
                "content": _binary_content_schema(),
            },
            206: {
                "description": "Partial artifact content",
                "content": _binary_content_schema(),
            },
            413: {
                "model": ErrorResponse,
                "description": "Artifact exceeds the delivery limit",
            },
            416: {"description": "The requested byte range is invalid"},
        },
    )
    def read_content(
        id: UUID,
        request: Request,
        _: Annotated[Principal, Depends(owner)],
    ) -> Response:
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        if id.version != 4 or id.variant != RFC_4122:
            raise AuthDenied("ARTIFACT_NOT_FOUND", 404)
        if byte_store is None:
            raise AuthDenied("ARTIFACT_UNAVAILABLE", 503)
        try:
            with persistence().transaction() as connection:
                record = get_artifact(connection, id)
            if record.byte_size > MAX_ARTIFACT_CONTENT_BYTES:
                raise AuthDenied("ARTIFACT_TOO_LARGE", 413)
            body = byte_store.read_verified(
                StoredBytes(record.id, record.sha256, record.byte_size),
                max_bytes=MAX_ARTIFACT_CONTENT_BYTES,
            )
        except ArtifactNotFound:
            raise AuthDenied("ARTIFACT_NOT_FOUND", 404) from None
        except (UnsupportedStorageError, OSError):
            raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None

        etag = f'"{record.sha256}"'
        range_values = request.headers.getlist("range")
        if_range_values = request.headers.getlist("if-range")
        if len(range_values) > 1 or (range_values and len(if_range_values) > 1):
            return Response(
                status_code=416,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes */{len(body)}",
                    "ETag": etag,
                },
            )
        range_header = range_values[0] if range_values else None
        if_range = if_range_values[0] if if_range_values else None
        use_range = range_header is not None and (if_range is None or if_range == etag)
        status_code = 200
        start, end = 0, len(body) - 1
        if use_range:
            assert range_header is not None
            try:
                start, end = _byte_range(range_header, len(body))
            except ValueError:
                return Response(
                    status_code=416,
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Range": f"bytes */{len(body)}",
                        "ETag": etag,
                    },
                )
            status_code = 206

        media_type = (
            record.media_type
            if record.media_type in _INLINE_MEDIA_TYPES
            else "application/octet-stream"
        )
        disposition = "inline" if record.media_type in _INLINE_MEDIA_TYPES else "attachment"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'{disposition}; filename="artifact-{id.hex}"',
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
        content = body if status_code == 200 else body[start:end + 1]
        return Response(
            content=content,
            status_code=status_code,
            media_type=media_type,
            headers=headers,
        )

    return router
