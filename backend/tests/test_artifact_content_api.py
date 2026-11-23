import contextlib
import hashlib
import struct
import zlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api import artifacts
from app.core.artifact_bytes import ByteIntegrityError, StoredBytes
from app.core.artifacts import ArtifactMetadata, ArtifactNotFound
from app.core.auth import AuthDenied
from app.main import create_api


class MemoryStore:
    @contextlib.contextmanager
    def transaction(self):
        yield object()


class MemoryBytes:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[StoredBytes, int]] = []
        self.uploads: list[tuple[StoredBytes, bytes, int]] = []
        self.error: Exception | None = None

    def put(self, artifact_id, source, *, max_bytes: int) -> StoredBytes:
        content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Artifact exceeds byte limit")
        stored = StoredBytes(
            artifact_id, hashlib.sha256(content).hexdigest(), len(content)
        )
        self.uploads.append((stored, content, max_bytes))
        return stored

    def read_verified(self, expected: StoredBytes, *, max_bytes: int) -> bytes:
        self.calls.append((expected, max_bytes))
        if self.error is not None:
            raise self.error
        return self.content


class CloseableBytes:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def record_for(
    content: bytes = b"synthetic", media_type: str = "video/mp4"
) -> ArtifactMetadata:
    return ArtifactMetadata(
        id=uuid4(),
        owner_id="creator-1",
        revision="render-1",
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        media_type=media_type,
    )


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def valid_png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x10\x20\x30\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", pixels)
        + png_chunk(b"IEND", b"")
    )


def assert_upload_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def client_for(monkeypatch, record: ArtifactMetadata, byte_store: MemoryBytes | None):
    def dependencies(_config, _store):
        def principal(_request: Request):
            if _request.headers.get("x-test-owner") != "yes":
                raise AuthDenied("FORBIDDEN", 403)
            return SimpleNamespace(id="artifact-owner")

        return principal, principal

    def get_record(_connection, artifact_id):
        if artifact_id != record.id:
            raise ArtifactNotFound("Artifact metadata not found")
        return record

    monkeypatch.setattr(artifacts, "auth_dependencies", dependencies)
    monkeypatch.setattr(artifacts, "get_artifact", get_record)
    app = FastAPI()
    app.include_router(artifacts.artifacts_router(object(), MemoryStore(), byte_store))

    @app.exception_handler(AuthDenied)
    async def auth_error(_request: Request, error: AuthDenied):
        return JSONResponse(
            status_code=error.status, content={"error": {"code": error.code}}
        )

    return TestClient(app)


def test_owner_gets_verified_bytes_and_safe_inline_headers(monkeypatch):
    content = b"synthetic"
    record = record_for(content)
    byte_store = MemoryBytes(content)
    client = client_for(monkeypatch, record, byte_store)

    response = client.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes"},
    )

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "video/mp4"
    assert (
        response.headers["content-disposition"]
        == f'inline; filename="artifact-{record.id.hex}"'
    )
    assert response.headers["etag"] == f'"{record.sha256}"'
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(content))
    assert byte_store.calls == [
        (
            StoredBytes(record.id, record.sha256, len(content)),
            artifacts.MAX_ARTIFACT_CONTENT_BYTES,
        )
    ]


@pytest.mark.parametrize(
    ("range_header", "if_range", "status", "expected", "content_range"),
    [
        ("bytes=2-4", None, 206, b"nth", "bytes 2-4/9"),
        ("bytes=-3", None, 206, b"tic", "bytes 6-8/9"),
        ("bytes=2-4", '"stale"', 200, b"synthetic", None),
    ],
)
def test_single_byte_ranges_and_if_range(
    monkeypatch, range_header, if_range, status, expected, content_range
):
    content = b"synthetic"
    record = record_for(content)
    client = client_for(monkeypatch, record, MemoryBytes(content))
    headers = {"x-test-owner": "yes", "range": range_header}
    if if_range is not None:
        headers["if-range"] = if_range

    response = client.get(f"/api/v1/artifacts/{record.id}/content", headers=headers)

    assert response.status_code == status
    assert response.content == expected
    if content_range is None:
        assert "content-range" not in response.headers
    else:
        assert response.headers["content-range"] == content_range


@pytest.mark.parametrize("range_header", ["bytes=0-1,3-4", "bytes=-0", "bytes=99-100"])
def test_invalid_ranges_return_416_without_content(monkeypatch, range_header):
    record = record_for()
    client = client_for(monkeypatch, record, MemoryBytes(b"synthetic"))

    response = client.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes", "range": range_header},
    )

    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["content-range"] == "bytes */9"
    assert response.headers["accept-ranges"] == "bytes"


def test_non_inline_media_is_downloaded_as_opaque_binary(monkeypatch):
    content = b"<script>alert(1)</script>"
    record = record_for(content, "text/html")
    client = client_for(monkeypatch, record, MemoryBytes(content))

    response = client.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes"},
    )

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_owner_is_required_and_unconfigured_store_fails_closed(monkeypatch):
    record = record_for()
    byte_store = MemoryBytes(b"synthetic")
    client = client_for(monkeypatch, record, byte_store)

    denied = client.get(f"/api/v1/artifacts/{record.id}/content")
    assert denied.status_code == 403
    assert byte_store.calls == []

    unconfigured = client_for(monkeypatch, record, None)
    unavailable = unconfigured.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"


def test_integrity_failure_is_hidden_as_unavailable(monkeypatch):
    record = record_for()
    byte_store = MemoryBytes(b"synthetic")
    byte_store.error = ByteIntegrityError("private storage detail")
    client = client_for(monkeypatch, record, byte_store)

    response = client.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes"},
    )

    assert response.status_code == 503
    assert "private storage detail" not in response.text


def test_oversized_artifact_is_rejected_before_byte_read(monkeypatch):
    record = ArtifactMetadata(
        id=uuid4(),
        owner_id="creator-1",
        revision="render-1",
        sha256="0" * 64,
        byte_size=artifacts.MAX_ARTIFACT_CONTENT_BYTES + 1,
        media_type="video/mp4",
    )
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record, byte_store)

    response = client.get(
        f"/api/v1/artifacts/{record.id}/content",
        headers={"x-test-owner": "yes"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "ARTIFACT_TOO_LARGE"
    assert byte_store.calls == []


def test_owner_uploads_a_valid_png_with_server_generated_metadata(monkeypatch):
    content = valid_png()
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)
    saved = []
    monkeypatch.setattr(
        artifacts,
        "save_artifact",
        lambda _connection, record: saved.append(record) or record,
    )

    response = client.post(
        "/api/v1/artifacts",
        content=content,
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-2",
            "x-test-owner": "yes",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": str(saved[0].id),
        "ownerId": "artifact-owner",
        "revision": "render-2",
        "sha256": hashlib.sha256(content).hexdigest(),
        "byteSize": len(content),
        "mediaType": "image/png",
    }
    assert len(byte_store.uploads) == 1
    stored, uploaded, limit = byte_store.uploads[0]
    assert uploaded == content
    assert stored.id == saved[0].id
    assert limit == artifacts.MAX_ARTIFACT_CONTENT_BYTES


def test_owner_upload_rejects_invalid_content_before_storage(monkeypatch):
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)

    response = client.post(
        "/api/v1/artifacts",
        content=b"not a PNG",
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-2",
            "x-test-owner": "yes",
        },
    )

    assert_upload_error(response, 422, "ARTIFACT_CONTENT_INVALID")
    assert byte_store.uploads == []


def test_owner_upload_rejects_unsupported_media_before_storage(monkeypatch):
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)

    response = client.post(
        "/api/v1/artifacts",
        content=b"opaque",
        headers={
            "content-type": "application/octet-stream",
            "x-artifact-revision": "render-2",
            "x-test-owner": "yes",
        },
    )

    assert_upload_error(response, 415, "ARTIFACT_MEDIA_UNSUPPORTED")
    assert byte_store.uploads == []


def test_upload_requires_owner_before_storage(monkeypatch):
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)

    response = client.post(
        "/api/v1/artifacts",
        content=valid_png(),
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-2",
        },
    )

    assert_upload_error(response, 403, "FORBIDDEN")
    assert byte_store.uploads == []


def test_upload_fails_closed_without_byte_store(monkeypatch):
    client = client_for(monkeypatch, record_for(), None)

    response = client.post(
        "/api/v1/artifacts",
        content=valid_png(),
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-2",
            "x-test-owner": "yes",
        },
    )

    assert_upload_error(response, 503, "ARTIFACT_UNAVAILABLE")


def test_upload_rejects_invalid_revision_before_storage(monkeypatch):
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)

    response = client.post(
        "/api/v1/artifacts",
        content=valid_png(),
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "../secret",
            "x-test-owner": "yes",
        },
    )

    assert_upload_error(response, 422, "INVALID_REQUEST")
    assert byte_store.uploads == []


def test_owner_upload_enforces_streamed_byte_limit(monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_ARTIFACT_CONTENT_BYTES", 8)
    byte_store = MemoryBytes(b"")
    client = client_for(monkeypatch, record_for(), byte_store)

    response = client.post(
        "/api/v1/artifacts",
        content=valid_png(),
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-2",
            "x-test-owner": "yes",
        },
    )

    assert_upload_error(response, 413, "ARTIFACT_TOO_LARGE")
    assert byte_store.uploads == []


def test_api_closes_injected_byte_store_on_shutdown():
    byte_store = CloseableBytes()

    with TestClient(create_api(artifact_byte_store=byte_store)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert not byte_store.closed

    assert byte_store.closed
