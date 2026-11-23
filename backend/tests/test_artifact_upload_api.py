import hashlib
import os
import secrets
import struct
import zlib
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import artifacts as artifact_api
from app.core.artifact_bytes import StoredBytes
from app.core.artifacts import artifacts, get_artifact
from app.core.auth import AuthConfig, AuthStore
from app.core.database import create_database_engine
from app.main import SecurityHeaders, create_api


class MemoryUploadBytes:
    def __init__(self) -> None:
        self.uploads: dict[object, bytes] = {}

    def put(self, artifact_id, source, *, max_bytes: int) -> StoredBytes:
        content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Artifact exceeds byte limit")
        self.uploads[artifact_id] = content
        return StoredBytes(
            artifact_id, hashlib.sha256(content).hexdigest(), len(content)
        )

    def close(self) -> None:
        pass


@pytest.fixture
def upload_context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/artifacts",
        client_id="animetron-artifacts",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="artifact-owner",
    )
    auth_store = AuthStore(engine, config)
    byte_store = MemoryUploadBytes()
    with TestClient(
        SecurityHeaders(create_api(config, engine, byte_store)),
        base_url=config.origin,
    ) as client:
        handle, principal = auth_store.create_session("artifact-owner", "test-upload")
        client.cookies.set("__Host-animetron_session", handle)
        yield client, engine, byte_store, config, principal
    engine.dispose()


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x20\x40\x60\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", pixels)
        + _chunk(b"IEND", b"")
    )


def test_owner_upload_commits_verified_bytes_metadata_and_csrf(upload_context) -> None:
    client, engine, byte_store, config, principal = upload_context
    content = _png()

    response = client.post(
        "/api/v1/artifacts",
        content=content,
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-1",
            "origin": config.origin,
            "x-csrf-token": principal.csrf,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {
        "id",
        "ownerId",
        "revision",
        "sha256",
        "byteSize",
        "mediaType",
    }
    assert payload["ownerId"] == principal.id
    assert payload["revision"] == "render-1"
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["byteSize"] == len(content)
    assert payload["mediaType"] == "image/png"
    with engine.begin() as connection:
        record = get_artifact(connection, UUID(payload["id"]))
        locator = connection.scalar(
            select(artifacts.c.storage_locator).where(artifacts.c.id == record.id)
        )
    assert locator == f"artifacts/{record.id.hex}"
    assert byte_store.uploads[record.id] == content


def test_owner_upload_rejects_missing_csrf_before_storage(upload_context) -> None:
    client, _, byte_store, config, _ = upload_context

    response = client.post(
        "/api/v1/artifacts",
        content=_png(),
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-1",
            "origin": config.origin,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"
    assert byte_store.uploads == {}


def test_owner_upload_rejects_malformed_png_before_storage(upload_context) -> None:
    client, engine, byte_store, config, principal = upload_context
    with engine.begin() as connection:
        before_count = connection.scalar(select(func.count()).select_from(artifacts))

    response = client.post(
        "/api/v1/artifacts",
        content=b"not a PNG",
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-invalid",
            "origin": config.origin,
            "x-csrf-token": principal.csrf,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ARTIFACT_CONTENT_INVALID"
    assert byte_store.uploads == {}
    with engine.begin() as connection:
        after_count = connection.scalar(select(func.count()).select_from(artifacts))
    assert after_count == before_count


def test_owner_upload_rejects_oversized_body_before_storage(
    upload_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine, byte_store, config, principal = upload_context
    monkeypatch.setattr(artifact_api, "MAX_ARTIFACT_CONTENT_BYTES", 8)
    with engine.begin() as connection:
        before_count = connection.scalar(select(func.count()).select_from(artifacts))

    response = client.post(
        "/api/v1/artifacts",
        content=b"x" * 9,
        headers={
            "content-type": "image/png",
            "x-artifact-revision": "render-oversized",
            "origin": config.origin,
            "x-csrf-token": principal.csrf,
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "ARTIFACT_TOO_LARGE"
    assert byte_store.uploads == {}
    with engine.begin() as connection:
        after_count = connection.scalar(select(func.count()).select_from(artifacts))
    assert after_count == before_count
