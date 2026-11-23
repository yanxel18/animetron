"""Authenticated artifact upload and owner-only metadata/content reads."""

import re
from functools import partial
from tempfile import SpooledTemporaryFile
from threading import BoundedSemaphore
from typing import Annotated, BinaryIO, cast
from uuid import RFC_4122, UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.api.auth import ErrorResponse
from app.api.dependencies import auth_dependencies
from app.core.artifact_bytes import (
    ArtifactByteStore,
    StoredBytes,
    UnsupportedStorageError,
)
from app.core.artifact_media import ArtifactMediaError, validate_png
from app.core.artifacts import (
    ArtifactMetadata,
    ArtifactNotFound,
    get_artifact,
    save_artifact,
)
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
_INLINE_MEDIA_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "video/webm",
    }
)
_DOCUMENTED_CONTENT_TYPES = (
    "application/octet-stream",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
)
_MAX_CONCURRENT_CONTENT_READS = 2
_MAX_CONCURRENT_UPLOADS = 2
_MAX_UPLOAD_CHUNKS = 8192
_UPLOAD_SPOOL_MEMORY_BYTES = 2 * 1024 * 1024


class _ContentResponse(Response):
    def __init__(
        self,
        *,
        content: bytes,
        status_code: int,
        media_type: str,
        headers: dict[str, str],
        read_slots: BoundedSemaphore,
    ) -> None:
        super().__init__(
            content=content,
            status_code=status_code,
            media_type=media_type,
            headers=headers,
        )
        self._read_slots = read_slots

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._read_slots.release()


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
    content_read_slots = BoundedSemaphore(_MAX_CONCURRENT_CONTENT_READS)
    upload_slots = BoundedSemaphore(_MAX_CONCURRENT_UPLOADS)

    def persistence() -> AuthStore:
        if config is None or store is None:
            raise AuthDenied("AUTH_UNAVAILABLE", 503)
        return store

    def byte_store_dependency() -> ArtifactByteStore:
        if byte_store is None:
            raise AuthDenied("ARTIFACT_UNAVAILABLE", 503)
        return byte_store

    @router.post(
        "",
        response_model=ArtifactMetadataOutput,
        status_code=201,
        responses={
            413: {
                "model": ErrorResponse,
                "description": "Upload exceeds the byte limit",
            },
            415: {"model": ErrorResponse, "description": "Media type is unsupported"},
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "image/png": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def upload_png(
        request: Request,
        principal: Annotated[Principal, Depends(owner)],
    ) -> ArtifactMetadataOutput:
        """Stream, validate and store one bounded PNG using a generated ID."""
        if request.query_params:
            raise AuthDenied("INVALID_REQUEST", 422)
        media_types = request.headers.getlist("content-type")
        if len(media_types) != 1 or media_types[0].strip().lower() != "image/png":
            raise AuthDenied("ARTIFACT_MEDIA_UNSUPPORTED", 415)
        revisions = request.headers.getlist("x-artifact-revision")
        lengths = request.headers.getlist("content-length")
        encodings = request.headers.getlist("content-encoding")
        if (
            len(revisions) != 1
            or len(lengths) > 1
            or (lengths and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is None)
            or len(encodings) > 1
            or (encodings and encodings[0].lower() != "identity")
        ):
            raise AuthDenied("INVALID_REQUEST", 422)
        declared_size = int(lengths[0]) if lengths else None
        if declared_size is not None and declared_size > MAX_ARTIFACT_CONTENT_BYTES:
            raise AuthDenied("ARTIFACT_TOO_LARGE", 413)
        if not upload_slots.acquire(blocking=False):
            raise AuthDenied("ARTIFACT_BUSY", 503)

        try:
            byte_store = byte_store_dependency()
            database = persistence()
            artifact_id = uuid4()
            try:
                ArtifactMetadata(
                    artifact_id,
                    principal.id,
                    revisions[0],
                    "0" * 64,
                    0,
                    "image/png",
                )
            except (TypeError, ValueError):
                raise AuthDenied("INVALID_REQUEST", 422) from None

            with SpooledTemporaryFile(
                max_size=_UPLOAD_SPOOL_MEMORY_BYTES, mode="w+b"
            ) as raw_source:
                source = cast(BinaryIO, raw_source)
                byte_count = 0
                chunk_count = 0
                async for chunk in request.stream():
                    chunk_count += 1
                    if chunk_count > _MAX_UPLOAD_CHUNKS:
                        raise AuthDenied("ARTIFACT_TOO_LARGE", 413)
                    byte_count += len(chunk)
                    if byte_count > MAX_ARTIFACT_CONTENT_BYTES:
                        raise AuthDenied("ARTIFACT_TOO_LARGE", 413)
                    await run_in_threadpool(source.write, chunk)
                if declared_size is not None and byte_count != declared_size:
                    raise AuthDenied("INVALID_REQUEST", 422)
                source.seek(0)
                try:
                    await run_in_threadpool(
                        validate_png,
                        source,
                        max_bytes=MAX_ARTIFACT_CONTENT_BYTES,
                    )
                except ArtifactMediaError:
                    raise AuthDenied("ARTIFACT_CONTENT_INVALID", 422) from None
                source.seek(0)
                try:
                    stored = await run_in_threadpool(
                        partial(
                            byte_store.put,
                            artifact_id,
                            source,
                            max_bytes=MAX_ARTIFACT_CONTENT_BYTES,
                        )
                    )
                except (UnsupportedStorageError, OSError, ValueError):
                    raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None

            record = ArtifactMetadata(
                artifact_id,
                principal.id,
                revisions[0],
                stored.sha256,
                stored.byte_size,
                "image/png",
            )

            def persist() -> ArtifactMetadata:
                with database.transaction() as connection:
                    return save_artifact(connection, record)

            try:
                record = await run_in_threadpool(persist)
            except IntegrityError:
                # A constraint rejection proves that this insert did not commit.
                # Other database errors need readback before deciding their outcome.
                try:
                    await run_in_threadpool(
                        partial(byte_store.remove_if_matches, stored)
                    )
                except (OSError, RuntimeError):
                    raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None
                raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None
            except DBAPIError:
                def reconcile() -> ArtifactMetadata | None:
                    with database.transaction() as connection:
                        try:
                            return get_artifact(connection, artifact_id)
                        except ArtifactNotFound:
                            return None

                try:
                    existing = await run_in_threadpool(reconcile)
                except DBAPIError:
                    # Keep the uploaded bytes when the commit outcome remains unknown.
                    raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None
                if existing != record:
                    raise AuthDenied("ARTIFACT_UNAVAILABLE", 503) from None
                # A matching row confirms that the original commit succeeded.
                record = existing
            return ArtifactMetadataOutput(
                id=record.id,
                ownerId=record.owner_id,
                revision=record.revision,
                sha256=record.sha256,
                byteSize=record.byte_size,
                mediaType=record.media_type,
            )
        finally:
            upload_slots.release()

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
        if not content_read_slots.acquire(blocking=False):
            raise AuthDenied("ARTIFACT_BUSY", 503)
        slot_held = True
        try:
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
            use_range = range_header is not None and (
                if_range is None or if_range == etag
            )
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
            disposition = (
                "inline" if record.media_type in _INLINE_MEDIA_TYPES else "attachment"
            )
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'{disposition}; filename="artifact-{id.hex}"',
                "ETag": etag,
                "X-Content-Type-Options": "nosniff",
            }
            if status_code == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
            content = body if status_code == 200 else body[start : end + 1]
            response = _ContentResponse(
                content=content,
                status_code=status_code,
                media_type=media_type,
                headers=headers,
                read_slots=content_read_slots,
            )
            slot_held = False
            return response
        finally:
            if slot_held:
                content_read_slots.release()

    return router
