"""Owner-only reads of known immutable workflow revisions."""

import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import update

from app.api.auth import SESSION_COOKIE
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.core.database import create_database_engine
from app.main import SecurityHeaders, create_api
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    revisions,
    save_revision,
)
from app.services.workflows.snapshot import WorkflowSnapshot, create_snapshot
from app.services.workflows.validation import GraphLimits, NodeDefinition


class StoryConfig(BaseModel):
    prompt: str


DEFINITIONS = {"story": NodeDefinition(config_model=StoryConfig)}
LIMITS = GraphLimits(max_nodes=10, max_edges=10)


@pytest.fixture
def offline_context(monkeypatch):
    config = AuthConfig(
        issuer="https://identity.example/realms/workflow-revisions",
        client_id="animetron-workflow-revisions",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="workflow-owner",
    )
    principals = {
        "owner-session": Principal(
            id="workflow-owner",
            role="owner",
            csrf="owner-csrf",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        "operator-session": Principal(
            id="workflow-operator",
            role="operator",
            csrf="operator-csrf",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    }

    class OfflineStore:
        transaction_error = None

        def authenticate(self, handle):
            if handle not in principals:
                raise AuthDenied()
            return principals[handle]

        def audit(self, *_args, **_kwargs):
            return None

        @contextmanager
        def transaction(self):
            if self.transaction_error is not None:
                raise self.transaction_error
            yield object()

    store = OfflineStore()
    monkeypatch.setattr("app.main.AuthStore", lambda *_args: store)
    with TestClient(
        SecurityHeaders(create_api(config, object())),
        base_url=config.origin,
        raise_server_exceptions=False,
    ) as client:
        client.cookies.set(SESSION_COOKIE, "owner-session")
        yield client, store


@pytest.fixture
def context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/workflow-revisions",
        client_id="animetron-workflow-revisions",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="workflow-owner",
        grants={"workflow-operator": "operator", "workflow-viewer": "viewer"},
    )
    store = AuthStore(engine, config)
    with TestClient(
        SecurityHeaders(create_api(config, engine)),
        base_url=config.origin,
        raise_server_exceptions=False,
    ) as client:
        handle, principal = store.create_session("workflow-owner", "test-request")
        client.cookies.set(SESSION_COOKIE, handle)
        yield client, store, engine, handle, principal
    engine.dispose()


def workflow_document(revision: str = "rev-1") -> bytes:
    return json.dumps(
        {
            "schemaVersion": 1,
            "revision": revision,
            "nodes": [
                {"id": "story-1", "type": "story", "config": {"prompt": "hello"}}
            ],
            "edges": [],
        }
    ).encode()


def save_workflow_revision(engine, workflow_id, revision="rev-1"):
    with engine.begin() as connection:
        return save_revision(
            connection,
            workflow_id,
            workflow_document(revision),
            DEFINITIONS,
            LIMITS,
            max_bytes=4096,
        )


def assert_error(response, status):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "requestId"}
    assert body["error"]["message"] == "Request could not be completed"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-request-id"] == body["error"]["requestId"]


def test_owner_reads_exact_persisted_revision_document_and_digest(context):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    snapshot = save_workflow_revision(engine, workflow_id)

    response = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions/{snapshot.revision}"
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["canonicalJson"] == snapshot.canonical_json.decode("ascii")
    assert response.json() == {
        "workflowId": str(workflow_id),
        "revision": snapshot.revision,
        "canonicalJson": snapshot.canonical_json.decode("ascii"),
        "sha256": snapshot.sha256,
    }
    assert hashlib.sha256(
        response.json()["canonicalJson"].encode("ascii")
    ).hexdigest() == response.json()["sha256"]


@pytest.mark.parametrize("role,subject", [
    ("operator", "workflow-operator"),
    ("viewer", "workflow-viewer"),
])
def test_non_owner_is_denied_before_revision_lookup(context, monkeypatch, role, subject):
    client, store, _, _, _ = context
    handle, _ = store.create_session(subject, "role-test")
    client.cookies.set(SESSION_COOKIE, handle)

    def forbidden_lookup(*_args, **_kwargs):
        pytest.fail("revision lookup occurred before owner authorization")

    monkeypatch.setattr("app.api.workflows.get_revision", forbidden_lookup)
    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
    )
    assert_error(response, 403)


def test_offline_owner_receives_byte_exact_validated_revision_and_digest(
    offline_context, monkeypatch
):
    client, _ = offline_context
    workflow_id = uuid4()
    snapshot: WorkflowSnapshot = create_snapshot(
        workflow_document(), DEFINITIONS, LIMITS, max_bytes=4096
    )
    monkeypatch.setattr(
        "app.api.workflows.get_revision",
        lambda _connection, actual_workflow_id, actual_revision: (
            snapshot
            if (actual_workflow_id, actual_revision)
            == (workflow_id, snapshot.revision)
            else pytest.fail("unexpected revision lookup")
        ),
    )

    response = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions/{snapshot.revision}"
    )

    assert response.status_code == 200
    assert response.json() == {
        "workflowId": str(workflow_id),
        "revision": snapshot.revision,
        "canonicalJson": snapshot.canonical_json.decode("ascii"),
        "sha256": snapshot.sha256,
    }
    assert hashlib.sha256(response.json()["canonicalJson"].encode("ascii")).hexdigest() == (
        response.json()["sha256"]
    )
    assert response.headers["cache-control"] == "no-store"


def test_offline_non_owner_and_stale_session_fail_before_revision_read(
    offline_context, monkeypatch
):
    client, _ = offline_context
    monkeypatch.setattr(
        "app.api.workflows.get_revision",
        lambda *_args, **_kwargs: pytest.fail("unauthorized revision lookup"),
    )
    path = f"/api/v1/workflows/{uuid4()}/revisions/rev-1"

    client.cookies.set(SESSION_COOKIE, "operator-session")
    assert_error(client.get(path), 403)
    client.cookies.clear()
    assert_error(client.get(path), 401)
    client.cookies.set(SESSION_COOKIE, "stale-session")
    assert_error(client.get(path), 401)


def test_offline_boundary_rejects_bad_identifiers_queries_and_origins(
    offline_context,
):
    client, _ = offline_context
    path = f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
    assert_error(client.get("/api/v1/workflows/not-a-uuid/revisions/rev-1"), 422)
    assert_error(
        client.get(f"/api/v1/workflows/{uuid4()}/revisions/%20%20"),
        422,
    )
    assert_error(client.get(path + "?unexpected=1"), 422)
    assert_error(client.get(path, headers={"Origin": "https://evil.example"}), 403)


@pytest.mark.parametrize(
    "failure,status",
    [
        (RevisionNotFound(), 404),
        (RevisionCorrupt("private stored content"), 503),
    ],
)
def test_offline_revision_failures_use_generic_error_envelopes(
    offline_context, monkeypatch, failure, status
):
    client, _ = offline_context

    def fail_lookup(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("app.api.workflows.get_revision", fail_lookup)
    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
    )

    assert_error(response, status)
    assert "private stored content" not in response.text


def test_offline_database_failure_is_generic_and_fail_closed(
    offline_context,
):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
    )

    assert_error(response, 503)
    assert "private connection information" not in response.text


def test_revision_read_requires_a_fresh_authenticated_session(context):
    client, store, engine, handle, _ = context
    workflow_id = uuid4()
    snapshot = save_workflow_revision(engine, workflow_id)
    path = f"/api/v1/workflows/{workflow_id}/revisions/{snapshot.revision}"

    client.cookies.clear()
    assert_error(client.get(path), 401)

    store.revoke(handle, "test-revoke")
    client.cookies.set(SESSION_COOKIE, handle)
    assert_error(client.get(path), 401)


def test_revision_read_rejects_malformed_workflow_and_revision_identifiers(context):
    client, _, _, _, _ = context
    assert_error(client.get("/api/v1/workflows/not-a-uuid/revisions/rev-1"), 422)
    assert_error(client.get(f"/api/v1/workflows/{uuid4()}/revisions/%20%20"), 422)
    assert_error(
        client.get(f"/api/v1/workflows/{uuid4()}/revisions/{'r' * 129}"),
        422,
    )


def test_missing_revision_is_not_found(context):
    client, _, _, _, _ = context
    response = client.get(f"/api/v1/workflows/{uuid4()}/revisions/absent")
    assert_error(response, 404)


def test_corrupt_revision_fails_closed_without_exposing_stored_data(context):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    snapshot = save_workflow_revision(engine, workflow_id)
    with engine.begin() as connection:
        connection.execute(
            update(revisions)
            .where(
                revisions.c.workflow_id == workflow_id,
                revisions.c.revision == snapshot.revision,
            )
            .values(document=b"private corruption detail")
        )

    response = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions/{snapshot.revision}"
    )

    assert_error(response, 503)
    assert "private corruption detail" not in response.text
    assert "sha256" not in response.text


def test_unavailable_database_dependency_fails_closed_without_internals(context, monkeypatch):
    client, _, _, _, _ = context

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("private database connection detail")

    monkeypatch.setattr("app.api.workflows.get_revision", unavailable)
    response = client.get(f"/api/v1/workflows/{uuid4()}/revisions/rev-1")

    assert_error(response, 503)
    assert "private database connection detail" not in response.text


def test_unconfigured_auth_and_database_fail_closed_without_lookup():
    with TestClient(
        SecurityHeaders(create_api()),
        base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        response = client.get(
            f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
        )

    assert_error(response, 503)


def test_revision_read_rejects_unknown_query_parameters(context):
    client, _, _, _, _ = context
    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions/rev-1?unexpected=1"
    )
    assert_error(response, 422)


def test_revision_read_requires_exact_single_origin(context):
    client, _, _, _, _ = context
    path = f"/api/v1/workflows/{uuid4()}/revisions/rev-1"
    assert_error(
        client.get(path, headers={"Origin": "https://evil.example"}),
        403,
    )
    assert_error(
        client.get(
            path,
            headers=[
                ("Origin", "https://control.example"),
                ("Origin", "https://control.example"),
            ],
        ),
        403,
    )
