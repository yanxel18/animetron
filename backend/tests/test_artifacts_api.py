import hashlib
import os
import secrets
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.core.artifacts import ArtifactMetadata, save_artifact
from app.core.auth import AuthConfig, AuthStore
from app.core.database import create_database_engine
from app.main import SecurityHeaders, create_api


@pytest.fixture
def artifact_context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/artifacts",
        client_id="animetron-artifacts",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="artifact-owner",
        grants={
            "artifact-operator": "operator",
            "artifact-viewer": "viewer",
        },
    )
    store = AuthStore(engine, config)
    with TestClient(
        SecurityHeaders(create_api(config, engine)), base_url=config.origin,
    ) as client:
        handle, principal = store.create_session("artifact-owner", "test-request")
        client.cookies.set(SESSION_COOKIE, handle)
        yield client, store, engine, principal
    engine.dispose()


def create_artifact(engine):
    content = b"synthetic"
    record = ArtifactMetadata(
        id=uuid4(),
        owner_id="creator-1",
        revision="render-1",
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        media_type="video/mp4",
    )
    with engine.begin() as connection:
        save_artifact(connection, record)
    return record


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert set(response.json()["error"]) == {"code", "message", "requestId"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_owner_reads_artifact_metadata_without_internal_locator(artifact_context):
    client, _, engine, _ = artifact_context
    record = create_artifact(engine)

    response = client.get(f"/api/v1/artifacts/{record.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(record.id),
        "ownerId": record.owner_id,
        "revision": record.revision,
        "sha256": record.sha256,
        "byteSize": record.byte_size,
        "mediaType": record.media_type,
    }
    assert "storageLocator" not in response.json()


@pytest.mark.parametrize(
    "subject", ["artifact-operator", "artifact-viewer"],
)
def test_non_owner_cannot_read_artifact_metadata(artifact_context, subject):
    client, store, engine, _ = artifact_context
    record = create_artifact(engine)
    handle, _ = store.create_session(subject, "test-request")
    client.cookies.set(SESSION_COOKIE, handle)

    response = client.get(f"/api/v1/artifacts/{record.id}")

    assert_error(response, 403, "FORBIDDEN")


def test_unauthenticated_cannot_read_artifact_metadata(artifact_context):
    client, _, engine, _ = artifact_context
    record = create_artifact(engine)
    client.cookies.clear()

    response = client.get(f"/api/v1/artifacts/{record.id}")

    assert_error(response, 401, "UNAUTHENTICATED")


def test_owner_gets_not_found_for_unknown_artifact(artifact_context):
    client, _, _, _ = artifact_context

    response = client.get(f"/api/v1/artifacts/{uuid4()}")

    assert_error(response, 404, "ARTIFACT_NOT_FOUND")


def test_owner_cannot_read_with_unsupported_query_parameters(artifact_context):
    client, _, engine, _ = artifact_context
    record = create_artifact(engine)

    response = client.get(f"/api/v1/artifacts/{record.id}?include=bytes")

    assert_error(response, 422, "INVALID_REQUEST")


def test_owner_gets_not_found_for_non_uuid4_identifier(artifact_context):
    client, _, _, _ = artifact_context

    response = client.get(f"/api/v1/artifacts/{UUID(int=0)}")

    assert_error(response, 404, "ARTIFACT_NOT_FOUND")
