"""Owner-only reads of known immutable workflow revisions."""

import base64
import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.pool import StaticPool

from app.api.auth import SESSION_COOKIE
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal
from app.core.database import create_database_engine
from app.main import SecurityHeaders, create_api
from app.services.workflows.drafts import drafts as mutable_drafts
from app.services.workflows.drafts import save_draft
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    WorkflowRevisionSummary,
    revisions,
    save_revision,
)
from app.services.workflows.run_requests import (
    RunRequest,
    RunRequestConflict,
    RunRequestCorrupt,
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
        "viewer-session": Principal(
            id="workflow-viewer",
            role="viewer",
            csrf="viewer-csrf",
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


@pytest.fixture
def offline_draft_context(offline_context, monkeypatch):
    client, store = offline_context
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    mutable_drafts.metadata.create_all(engine)

    @contextmanager
    def transaction():
        with engine.begin() as connection:
            yield connection

    monkeypatch.setattr(store, "transaction", transaction)
    yield client, store, engine
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


def test_workflow_discovery_owner_pages_and_concurrent_inserts(context):
    from app.api.workflows import _encode_workflow_cursor

    client, _, engine, _, _ = context
    maximum = (1 << 128) - 1
    ids = [UUID(int=maximum - n) for n in (4, 3, 2, 1, 0)]
    for workflow_id in (ids[1], ids[2], ids[4]):
        save_workflow_revision(engine, workflow_id)
        save_workflow_revision(engine, workflow_id, "rev-2")
    first = client.get(
        "/api/v1/workflows",
        params={"limit": 2, "cursor": _encode_workflow_cursor(UUID(int=maximum - 5))},
    )
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert first.json()["data"] == [{"workflowId": str(ids[1])}, {"workflowId": str(ids[2])}]
    cursor = first.json()["nextCursor"]
    assert cursor
    save_workflow_revision(engine, ids[0])
    save_workflow_revision(engine, ids[3])
    second = client.get("/api/v1/workflows", params={"limit": 2, "cursor": cursor})
    assert second.status_code == 200, second.text
    assert second.json()["data"] == [{"workflowId": str(ids[3])}, {"workflowId": str(ids[4])}]
    assert second.json()["nextCursor"] is None


@pytest.mark.parametrize("query", [
    "?extra=1", "?limit=1&limit=2", "?cursor=x&cursor=y", "?cursor=",
    "?cursor=bad", "?limit=", "?limit=0", "?limit=101", "?limit=0001",
    "?limit=%2B1", "?limit=1.0", "?cursor=" + "a" * 129,
])
def test_workflow_discovery_rejects_bad_query(offline_context, query):
    client, _ = offline_context
    assert_error(client.get("/api/v1/workflows" + query), 422)


def test_workflow_discovery_authorization_precedes_lookup(offline_context, monkeypatch):
    client, _ = offline_context
    monkeypatch.setattr(
        "app.api.workflows.list_workflow_ids",
        lambda *_args, **_kwargs: pytest.fail("unauthorized lookup"),
        raising=False,
    )
    client.cookies.set(SESSION_COOKIE, "operator-session")
    assert_error(client.get("/api/v1/workflows"), 403)
    client.cookies.set(SESSION_COOKIE, "viewer-session")
    assert_error(client.get("/api/v1/workflows"), 403)
    client.cookies.clear()
    assert_error(client.get("/api/v1/workflows"), 401)
    client.cookies.set(SESSION_COOKIE, "stale-session")
    assert_error(client.get("/api/v1/workflows"), 401)
    client.cookies.set(SESSION_COOKIE, "owner-session")
    assert_error(client.get("/api/v1/workflows", headers={"Origin": "https://evil.example"}), 403)


@pytest.mark.parametrize("query,expected", [("", 51), ("?limit=001", 2), ("?limit=100", 101)])
def test_workflow_discovery_bounds_overfetch(offline_context, monkeypatch, query, expected):
    client, _ = offline_context
    observed = []

    def lookup(_connection, *, after, limit):
        observed.append((after, limit))
        return []

    monkeypatch.setattr("app.api.workflows.list_workflow_ids", lookup)
    response = client.get("/api/v1/workflows" + query)
    assert response.status_code == 200
    assert response.json() == {"data": [], "nextCursor": None}
    assert observed == [(None, expected)]


@pytest.mark.parametrize("payload", [
    b'{"after":"00000000-0000-0000-0000-000000000001","version":true}',
    b'{"after":"00000000-0000-0000-0000-000000000001","version":2}',
    b'{"after":"00000000000000000000000000000001","version":1}',
    b'{"version":1,"after":"00000000-0000-0000-0000-000000000001"}',
    b'{"after":"00000000-0000-0000-0000-000000000001","version":1,"extra":1}',
])
def test_workflow_discovery_rejects_noncanonical_cursor(offline_context, payload):
    client, _ = offline_context
    cursor = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    assert_error(client.get("/api/v1/workflows", params={"cursor": cursor}), 422)


def test_workflow_discovery_rejects_revision_cursor(offline_context):
    from app.api.workflows import _encode_revision_cursor

    client, _ = offline_context
    cursor = _encode_revision_cursor(uuid4(), datetime(2026, 1, 1, tzinfo=UTC), "one")
    assert_error(client.get("/api/v1/workflows", params={"cursor": cursor}), 422)


def test_workflow_discovery_database_failure_is_generic(offline_context):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")
    response = client.get("/api/v1/workflows")
    assert_error(response, 503)
    assert "private connection information" not in response.text


def test_workflow_discovery_rechecks_real_session_and_roles(context, monkeypatch):
    client, store, _, owner_handle, _ = context
    monkeypatch.setattr(
        "app.api.workflows.list_workflow_ids",
        lambda *_args, **_kwargs: pytest.fail("unauthorized lookup"),
    )
    for subject in ("workflow-operator", "workflow-viewer"):
        handle, _ = store.create_session(subject, "discovery-role-test")
        client.cookies.set(SESSION_COOKIE, handle)
        assert_error(client.get("/api/v1/workflows"), 403)
    store.revoke(owner_handle, "discovery-revoke")
    client.cookies.set(SESSION_COOKIE, owner_handle)
    assert_error(client.get("/api/v1/workflows"), 401)


def test_workflow_discovery_uses_index_seeks_with_many_revisions(context):
    from app.services.workflows.revisions import list_workflow_ids

    _, _, engine, _, _ = context
    first, second = UUID(int=100), UUID(int=200)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(
                "INSERT INTO workflow_revisions (workflow_id, revision, document, sha256) "
                "SELECT :id, 'bulk-' || n, '\\x00'::bytea, repeat('0',64) "
                "FROM generate_series(1, 10000) AS n"
            ), {"id": first})
            connection.execute(text(
                "INSERT INTO workflow_revisions (workflow_id, revision, document, sha256) "
                "VALUES (:id, 'one', '\\x00'::bytea, repeat('0',64))"
            ), {"id": second})
            connection.execute(text("ANALYZE workflow_revisions"))
            captured = []

            def capture(_conn, _cursor, statement, parameters, _context, _many):
                captured.append((statement, parameters))

            event.listen(connection, "before_cursor_execute", capture)
            try:
                result = list_workflow_ids(connection, after=UUID(int=99), limit=2)
            finally:
                event.remove(connection, "before_cursor_execute", capture)
            assert result == [first, second]
            assert len(captured) == 1
            sql, params = captured[0]
            assert all(word not in sql.upper() for word in ("DISTINCT", "OFFSET", "COUNT("))
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params
            ).scalar_one()[0]["Plan"]

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            scans = [node for node in nodes(plan) if node.get("Index Name") == "workflow_revisions_pkey"]
            assert len(scans) >= 2, plan
            assert all("workflow_id >" in node.get("Index Cond", "") for node in scans), plan
            assert all(node["Actual Rows"] <= 1 for node in scans), plan
            assert all(node["Actual Loops"] <= 2 for node in scans), plan
            assert list_workflow_ids(connection, after=UUID(int=(1 << 128) - 1), limit=2) == []
        finally:
            transaction.rollback()


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


def test_owner_lists_persisted_revisions_in_stable_bounded_pages(context):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    with engine.begin() as connection:
        for revision in ("rev-a", "rev-m", "rev-z"):
            save_revision(
                connection,
                workflow_id,
                workflow_document(revision),
                DEFINITIONS,
                LIMITS,
                max_bytes=4096,
            )

    first = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions?limit=2"
    )

    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    first_page = first.json()
    assert set(first_page) == {"data", "nextCursor"}
    assert [item["revision"] for item in first_page["data"]] == ["rev-z", "rev-m"]
    assert first_page["nextCursor"] is not None
    assert all(
        set(item) == {"workflowId", "revision", "createdAt"}
        and item["workflowId"] == str(workflow_id)
        and item["createdAt"].endswith("Z")
        for item in first_page["data"]
    )

    second = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions",
        params={"cursor": first_page["nextCursor"], "limit": 2},
    )

    assert second.status_code == 200, second.text
    second_page = second.json()
    assert [item["revision"] for item in second_page["data"]] == ["rev-a"]
    assert second_page["nextCursor"] is None


@pytest.mark.parametrize("revision", ["team/rev", "..", "\U0001f600" * 128])
def test_listed_revision_can_be_read_by_query(context, revision):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    snapshot = save_workflow_revision(engine, workflow_id, revision)
    path = f"/api/v1/workflows/{workflow_id}/revisions"
    listed = client.get(path)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["revision"] == snapshot.revision
    response = client.get(
        f"/api/v1/workflows/{workflow_id}/revision",
        params={"revision": revision},
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == snapshot.revision


@pytest.mark.parametrize(
    "query", ["", "?revision=", "?revision=one&revision=two", "?revision=one&extra=1"]
)
def test_revision_query_lookup_rejects_missing_or_ambiguous_input(offline_context, query):
    client, _ = offline_context
    response = client.get(f"/api/v1/workflows/{uuid4()}/revision{query}")
    assert_error(response, 422)


def test_revision_query_lookup_denies_non_owner_before_read(offline_context, monkeypatch):
    client, _ = offline_context
    monkeypatch.setattr(
        "app.api.workflows.get_revision",
        lambda *_args, **_kwargs: pytest.fail("unauthorized revision lookup"),
    )
    client.cookies.set(SESSION_COOKIE, "operator-session")
    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revision", params={"revision": "team/rev"}
    )
    assert_error(response, 403)


def test_revision_cursor_round_trips_maximum_unicode_identifier(context):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    long_revision = "\U0001f600" * 128
    with engine.begin() as connection:
        for revision in ("earlier", long_revision):
            save_revision(
                connection,
                workflow_id,
                workflow_document(revision),
                DEFINITIONS,
                LIMITS,
                max_bytes=4096,
            )
        connection.execute(
            update(revisions)
            .where(
                revisions.c.workflow_id == workflow_id,
                revisions.c.revision == long_revision,
            )
            .values(created_at=datetime(2030, 1, 1, tzinfo=UTC))
        )

    path = f"/api/v1/workflows/{workflow_id}/revisions"
    first = client.get(path, params={"limit": 1})
    assert first.status_code == 200, first.text
    assert first.json()["data"][0]["revision"] == long_revision
    cursor = first.json()["nextCursor"]
    assert cursor is not None
    second = client.get(path, params={"cursor": cursor, "limit": 1})
    assert second.status_code == 200, second.text
    assert [item["revision"] for item in second.json()["data"]] == ["earlier"]


def test_revision_cursor_traversal_does_not_repeat_rows_after_concurrent_insert(context):
    client, _, engine, _, _ = context
    workflow_id = uuid4()
    with engine.begin() as connection:
        for revision in ("rev-a", "rev-b", "rev-c", "rev-d"):
            save_revision(
                connection,
                workflow_id,
                workflow_document(revision),
                DEFINITIONS,
                LIMITS,
                max_bytes=4096,
            )

    first = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions?limit=2"
    )
    assert first.status_code == 200, first.text
    first_page = first.json()

    save_workflow_revision(engine, workflow_id, "rev-new")

    second = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions",
        params={"cursor": first_page["nextCursor"], "limit": 2},
    )
    assert second.status_code == 200, second.text
    visited = [
        item["revision"]
        for item in first_page["data"] + second.json()["data"]
    ]
    assert visited == ["rev-d", "rev-c", "rev-b", "rev-a"]
    assert len(visited) == len(set(visited))


@pytest.mark.parametrize(
    "query",
    [
        "?unexpected=1",
        "?limit=1&limit=2",
        "?cursor=bad",
        "?limit=",
        "?limit=0",
        "?limit=101",
        "?limit=0001",
        "?limit=%2B1",
        "?limit=1.0",
    ],
)
def test_revision_list_rejects_malformed_or_repeated_query_parameters(
    offline_context, query
):
    client, _ = offline_context

    response = client.get(f"/api/v1/workflows/{uuid4()}/revisions{query}")

    assert_error(response, 422)


def test_revision_list_accepts_bounded_leading_zero_limit_and_empty_page(
    offline_context, monkeypatch
):
    client, _ = offline_context
    monkeypatch.setattr(
        "app.api.workflows.list_revisions",
        lambda *_args, **_kwargs: [],
        raising=False,
    )

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions?limit=001"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"data": [], "nextCursor": None}


def test_revision_list_rejects_cursor_bound_to_another_workflow(
    offline_context, monkeypatch
):
    client, _ = offline_context
    workflow_id = uuid4()
    monkeypatch.setattr(
        "app.api.workflows.list_revisions",
        lambda *_args, **_kwargs: [
            WorkflowRevisionSummary(
                revision="rev-b",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            WorkflowRevisionSummary(
                revision="rev-a",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
    )
    first = client.get(
        f"/api/v1/workflows/{workflow_id}/revisions?limit=1"
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["nextCursor"]

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions",
        params={"cursor": cursor},
    )

    assert_error(response, 422)


def test_non_owner_is_denied_before_revision_list_lookup(
    offline_context, monkeypatch
):
    client, _ = offline_context

    def forbidden_lookup(*_args, **_kwargs):
        pytest.fail("revision list lookup occurred before owner authorization")

    monkeypatch.setattr(
        "app.api.workflows.list_revisions", forbidden_lookup, raising=False
    )
    client.cookies.set(SESSION_COOKIE, "operator-session")

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions"
    )

    assert_error(response, 403)


def test_revision_list_database_failure_uses_generic_error(offline_context):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/revisions"
    )

    assert_error(response, 503)
    assert "private connection information" not in response.text


def test_corrupt_revision_identifier_fails_closed_without_exposure(context):
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
            .values(revision=" ")
        )

    response = client.get(f"/api/v1/workflows/{workflow_id}/revisions")

    assert_error(response, 503)
    assert "private" not in response.text
    assert '"revision":" "' not in response.text


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
@pytest.mark.parametrize("lookup", ["path", "query"])
def test_offline_revision_failures_use_generic_error_envelopes(
    offline_context, monkeypatch, failure, status, lookup
):
    client, _ = offline_context

    def fail_lookup(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("app.api.workflows.get_revision", fail_lookup)
    workflow_id = uuid4()
    path = (
        f"/api/v1/workflows/{workflow_id}/revisions/rev-1"
        if lookup == "path"
        else f"/api/v1/workflows/{workflow_id}/revision?revision=rev-1"
    )
    response = client.get(path)

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


def test_owner_creates_idempotent_run_and_returns_status_location(
    offline_context, monkeypatch
):
    client, _ = offline_context
    workflow_id = uuid4()
    request_id = uuid4()
    run_id = uuid4()
    digest = "a" * 64
    snapshot = WorkflowSnapshot("rev-1", b'{"revision":"rev-1"}', digest)
    record = RunRequest(
        request_id,
        run_id,
        workflow_id,
        "rev-1",
        digest,
        datetime.now(UTC),
    )
    received = {}

    def load_revision(connection, actual_workflow_id, revision):
        received["revision"] = (connection, actual_workflow_id, revision)
        return snapshot

    def create_run(connection, key, actual_workflow_id, revision, expected_sha256):
        received["request"] = (
            connection,
            key,
            actual_workflow_id,
            revision,
            expected_sha256,
        )
        return record

    monkeypatch.setattr("app.api.workflows.get_revision", load_revision)
    monkeypatch.setattr("app.api.workflows.request_run", create_run, raising=False)
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
        "Idempotency-Key": str(request_id),
    }

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"revision": "rev-1"},
        headers=headers,
    )
    retry = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"revision": "rev-1"},
        headers=headers,
    )

    assert response.status_code == 202, response.text
    assert response.json() == {"runId": str(run_id)}
    assert response.headers["location"] == f"/api/v1/runs/{run_id}"
    assert response.headers["cache-control"] == "no-store"
    assert retry.status_code == 202, retry.text
    assert retry.json() == response.json()
    assert retry.headers["location"] == response.headers["location"]
    assert received["revision"][1:] == (workflow_id, "rev-1")
    assert received["request"][1:] == (
        request_id,
        workflow_id,
        "rev-1",
        digest,
    )
def test_workflow_draft_read_returns_stored_text_and_version(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    document = b'{"schemaVersion":1,"nodes":['
    with engine.begin() as connection:
        save_draft(
            connection,
            workflow_id,
            document,
            expected_version=None,
            max_bytes=4096,
        )

    response = client.get(f"/api/v1/workflows/{workflow_id}/draft")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workflowId": str(workflow_id),
        "document": document.decode("utf-8"),
        "version": 1,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_missing_workflow_draft_is_not_found(offline_draft_context):
    client, _, _ = offline_draft_context

    response = client.get(f"/api/v1/workflows/{uuid4()}/draft")

    assert_error(response, 404)


def test_corrupt_workflow_draft_fails_closed(offline_draft_context):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            mutable_drafts.insert().values(
                workflow_id=workflow_id,
                document=b"\xff",
                version=1,
            )
        )

    response = client.get(f"/api/v1/workflows/{workflow_id}/draft")

    assert_error(response, 503)


def test_workflow_draft_read_authorization_precedes_lookup(offline_context, monkeypatch):
    client, _ = offline_context

    def fail_lookup(*_args, **_kwargs):
        pytest.fail("unauthorized draft lookup")

    monkeypatch.setattr("app.api.workflows.get_draft", fail_lookup)
    client.cookies.set(SESSION_COOKIE, "operator-session")

    assert_error(client.get(f"/api/v1/workflows/{uuid4()}/draft"), 403)


def test_workflow_draft_read_rejects_unknown_query(offline_draft_context):
    client, _, _ = offline_draft_context

    assert_error(client.get("/api/v1/workflows/not-a-uuid/draft"), 422)

    response = client.get(
        f"/api/v1/workflows/{uuid4()}/draft?unexpected=1"
    )

    assert_error(response, 422)


def test_workflow_draft_read_database_failure_is_generic(offline_context):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")

    response = client.get(f"/api/v1/workflows/{uuid4()}/draft")

    assert_error(response, 503)
    assert "private connection information" not in response.text


def test_workflow_draft_write_uses_versioned_compare_and_swap(
    offline_draft_context,
):
    client, _, _ = offline_draft_context
    workflow_id = uuid4()
    path = f"/api/v1/workflows/{workflow_id}/draft"
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
    }

    created = client.put(
        path,
        json={"document": '{"nodes":[', "expectedVersion": None},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assert created.json() == {
        "workflowId": str(workflow_id),
        "document": '{"nodes":[',
        "version": 1,
    }
    assert created.headers["cache-control"] == "no-store"

    updated = client.put(
        path,
        json={"document": '{"nodes":[]}', "expectedVersion": 1},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2

    duplicate_create = client.put(
        path,
        json={"document": '{"nodes":["duplicate"]}', "expectedVersion": None},
        headers=headers,
    )
    assert_error(duplicate_create, 409)

    stale = client.put(
        path,
        json={"document": '{"nodes":["stale"]}', "expectedVersion": 1},
        headers=headers,
    )
    assert_error(stale, 409)
    assert client.get(path).json() == updated.json()


@pytest.mark.parametrize(
    "body",
    [
        {"document": "missing version"},
        {"document": "extra field", "expectedVersion": None, "unexpected": True},
        {"document": 42, "expectedVersion": None},
        {"document": "bad version", "expectedVersion": "1"},
        {"document": "boolean version", "expectedVersion": True},
    ],
)
def test_workflow_draft_write_rejects_invalid_shapes(offline_draft_context, body):
    client, _, _ = offline_draft_context
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
    }

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft",
        json=body,
        headers=headers,
    )

    assert_error(response, 422)


def test_workflow_draft_write_rejects_surrogate_text(offline_draft_context):
    client, _, _ = offline_draft_context
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
        "Content-Type": "application/json",
    }

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft",
        content=b'{"document":"\\ud800","expectedVersion":null}',
        headers=headers,
    )

    assert_error(response, 422)


def test_workflow_draft_write_enforces_document_and_body_limits(offline_draft_context):
    client, _, _ = offline_draft_context
    path = f"/api/v1/workflows/{uuid4()}/draft"
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
    }

    oversized_document = client.put(
        path,
        json={"document": "x" * 32_769, "expectedVersion": None},
        headers=headers,
    )
    assert_error(oversized_document, 422)

    oversized_utf8_document = client.put(
        path,
        json={"document": "é" * 16_385, "expectedVersion": None},
        headers=headers,
    )
    assert_error(oversized_utf8_document, 422)

    oversized_body = client.put(
        path,
        content=b'{"document":"' + b"x" * 262_144 + b'","expectedVersion":null}',
        headers={
            **headers,
            "Content-Type": "application/json",
        },
    )
    assert_error(oversized_body, 422)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://control.example", "X-CSRF-Token": "owner-csrf"},
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Idempotency-Key": "not-a-uuid",
        },
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Idempotency-Key": "00000000-0000-0000-0000-000000000000",
        },
    ],
)
def test_run_creation_requires_canonical_uuid4_idempotency_key(
    offline_context, headers
):
    client, _ = offline_context
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/runs",
        json={"revision": "rev-1"},
        headers=headers,
    )
    assert_error(response, 422)


def test_run_creation_rejects_noncanonical_uuid4_idempotency_key(offline_context):
    client, _ = offline_context
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/runs",
        json={"revision": "rev-1"},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Idempotency-Key": str(uuid4()).upper(),
        },
    )
    assert_error(response, 422)


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (RevisionNotFound("private missing revision"), 404),
        (RevisionCorrupt("private corrupt revision"), 503),
        (RunRequestConflict("private idempotency conflict"), 409),
        (RunRequestCorrupt("private corrupt request"), 503),
        (RuntimeError("private database failure"), 503),
    ],
)
def test_run_creation_maps_revision_and_request_failures(
    offline_context, monkeypatch, failure, status
):
    client, _ = offline_context
    workflow_id = uuid4()
    request_id = uuid4()
    snapshot = WorkflowSnapshot("rev-1", b'{"revision":"rev-1"}', "a" * 64)

    def fail(*_args, **_kwargs):
        raise failure

    if isinstance(failure, (RevisionNotFound, RevisionCorrupt)):
        monkeypatch.setattr("app.api.workflows.get_revision", fail)
    else:
        monkeypatch.setattr("app.api.workflows.get_revision", lambda *_args: snapshot)
        monkeypatch.setattr("app.api.workflows.request_run", fail, raising=False)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"revision": "rev-1"},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Idempotency-Key": str(request_id),
        },
    )

    assert_error(response, status)
    assert "private" not in response.text


def test_run_creation_rejects_extra_fields_and_query_parameters(offline_context):
    client, _ = offline_context
    path = f"/api/v1/workflows/{uuid4()}/runs"
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
        "Idempotency-Key": str(uuid4()),
    }
    assert_error(
        client.post(path, json={"revision": "rev-1", "runId": str(uuid4())}, headers=headers),
        422,
    )
    assert_error(
        client.post(path + "?unexpected=1", json={"revision": "rev-1"}, headers=headers),
        422,
    )


def test_run_creation_bounds_json_request_headers_and_body(offline_context):
    client, _ = offline_context
    path = f"/api/v1/workflows/{uuid4()}/runs"
    headers = [
        ("Origin", "https://control.example"),
        ("X-CSRF-Token", "owner-csrf"),
        ("Idempotency-Key", str(uuid4())),
        ("Content-Type", "application/json"),
    ]

    unsupported = client.post(
        path,
        content=b'{"revision":"rev-1"}',
        headers=headers + [("Content-Encoding", "gzip")],
    )
    oversized = client.post(
        path,
        content=b'{"revision":"' + b"x" * 4096 + b'"}',
        headers=headers,
    )

    assert_error(unsupported, 422)
    assert_error(oversized, 422)


def test_run_creation_rejects_duplicate_idempotency_keys(offline_context):
    client, _ = offline_context
    key = str(uuid4())
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/runs",
        json={"revision": "rev-1"},
        headers=[
            ("Origin", "https://control.example"),
            ("X-CSRF-Token", "owner-csrf"),
            ("Idempotency-Key", key),
            ("Idempotency-Key", key),
        ],
    )
    assert_error(response, 422)


@pytest.mark.parametrize(
    "headers",
    [
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    ],
)
def test_workflow_draft_write_rejects_unsupported_json_headers(
    offline_draft_context,
    headers,
):
    client, _, _ = offline_draft_context

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft",
        content=b'{"document":"draft","expectedVersion":null}',
        headers=headers,
    )

    assert_error(response, 422)


def test_workflow_draft_write_requires_existing_row_for_updates(offline_draft_context):
    client, _, _ = offline_draft_context

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft",
        json={"document": "draft", "expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert_error(response, 404)


def test_workflow_draft_write_rejects_query_parameters(offline_draft_context):
    client, _, _ = offline_draft_context

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft?unexpected=1",
        json={"document": "draft", "expectedVersion": None},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert_error(response, 422)


def test_workflow_draft_write_authorization_precedes_persistence(
    offline_context,
    monkeypatch,
):
    client, _ = offline_context

    def fail_save(*_args, **_kwargs):
        pytest.fail("unauthorized draft write")

    monkeypatch.setattr("app.api.workflows.save_draft", fail_save)
    path = f"/api/v1/workflows/{uuid4()}/draft"
    body = {"document": "draft", "expectedVersion": None}

    client.cookies.set(SESSION_COOKIE, "operator-session")
    assert_error(
        client.put(
            path,
            json=body,
            headers={
                "Origin": "https://control.example",
                "X-CSRF-Token": "operator-csrf",
            },
        ),
        403,
    )
    client.cookies.set(SESSION_COOKIE, "owner-session")
    assert_error(
        client.put(
            path,
            json=body,
            headers={"Origin": "https://control.example"},
        ),
        403,
    )
    client.cookies.clear()
    assert_error(
        client.put(
            path,
            json=body,
            headers={
                "Origin": "https://control.example",
                "X-CSRF-Token": "owner-csrf",
            },
        ),
        401,
    )


def test_workflow_draft_write_database_failure_is_generic(offline_context):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")

    response = client.put(
        f"/api/v1/workflows/{uuid4()}/draft",
        json={"document": "draft", "expectedVersion": None},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert_error(response, 503)
    assert "private connection information" not in response.text


def sample_workflow_document(nodes=None, edges=None):
    return json.dumps(
        {
            "schemaVersion": 1,
            "revision": "sample-r1",
            "nodes": nodes
            if nodes is not None
            else [{"id": "source", "type": "sample.constant", "config": {"text": "hi"}}],
            "edges": edges or [],
        }
    ).encode()


def save_workflow_draft(engine, workflow_id, document):
    with engine.begin() as connection:
        return save_draft(
            connection,
            workflow_id,
            document,
            expected_version=None,
            max_bytes=32_768,
        )


def test_workflow_draft_validation_returns_validity_and_version(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(engine, workflow_id, sample_workflow_document())

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workflowId": str(workflow_id),
        "draftVersion": 1,
        "isValid": True,
        "issues": [],
    }
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/api/v1/workflows/{workflow_id}/draft").json()["version"] == 1


def test_workflow_draft_validation_returns_structured_node_and_port_issues(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(
        engine,
        workflow_id,
        sample_workflow_document(
            nodes=[{"id": "prefix", "type": "sample.prefix", "config": {"prefix": "x"}}]
        ),
    )

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["isValid"] is False
    assert response.json()["issues"] == [
        {
            "code": "MISSING_REQUIRED_INPUT",
            "message": "Required input text is unconnected",
            "nodeId": "prefix",
            "targetPort": "text",
        }
    ]


def test_workflow_draft_validation_identifies_bad_edge_ports(offline_draft_context):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(
        engine,
        workflow_id,
        sample_workflow_document(
            nodes=[
                {"id": "source", "type": "sample.constant", "config": {"text": "hi"}},
                {"id": "target", "type": "sample.prefix", "config": {"prefix": "x"}},
            ],
            edges=[
                {
                    "id": "edge",
                    "source": "source",
                    "sourcePort": "missing",
                    "target": "target",
                    "targetPort": "bad",
                }
            ],
        ),
    )

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert response.status_code == 200, response.text
    issues = response.json()["issues"]
    assert {
        (
            issue["code"],
            issue.get("edgeId"),
            issue.get("sourcePort"),
            issue.get("targetPort"),
        )
        for issue in issues
    } >= {
        ("INVALID_SOURCE_PORT", "edge", "missing", None),
        ("INVALID_TARGET_PORT", "edge", None, "bad"),
    }


def test_workflow_draft_validation_reports_invalid_document_without_echo(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(engine, workflow_id, b'{"private":"not a workflow"}')

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["isValid"] is False
    assert response.json()["issues"] == [
        {"code": "INVALID_DOCUMENT", "message": "Workflow document is invalid"}
    ]
    assert "private" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expectedVersion": "1"},
        {"expectedVersion": True},
        {"expectedVersion": 1, "unexpected": True},
    ],
)
def test_workflow_draft_validation_rejects_invalid_requests(
    offline_draft_context,
    body,
):
    client, _, _ = offline_draft_context

    response = client.post(
        f"/api/v1/workflows/{uuid4()}/validations",
        json=body,
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert_error(response, 422)


def test_workflow_draft_validation_rejects_stale_version_and_query_parameters(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(engine, workflow_id, sample_workflow_document())
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
    }

    stale = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 2},
        headers=headers,
    )
    assert_error(stale, 409)

    query = client.post(
        f"/api/v1/workflows/{workflow_id}/validations?unexpected=1",
        json={"expectedVersion": 1},
        headers=headers,
    )
    assert_error(query, 422)


def test_workflow_draft_validation_missing_draft(offline_draft_context):
    client, _, _ = offline_draft_context
    path = f"/api/v1/workflows/{uuid4()}/validations"
    headers = {
        "Origin": "https://control.example",
        "X-CSRF-Token": "owner-csrf",
    }

    assert_error(
        client.post(path, json={"expectedVersion": 1}, headers=headers),
        404,
    )


@pytest.mark.parametrize(
    "headers",
    [
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
        {
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    ],
)
def test_workflow_draft_validation_rejects_unsupported_json_headers(
    offline_draft_context,
    headers,
):
    client, _, _ = offline_draft_context
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/validations",
        content=b'{"expectedVersion":1}',
        headers=headers,
    )
    assert_error(response, 422)


def test_workflow_draft_validation_bounds_request_body(offline_draft_context):
    client, _, _ = offline_draft_context
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/validations",
        content=b'{"expectedVersion":1,"padding":"' + b"x" * 262_144 + b'"}',
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
            "Content-Type": "application/json",
        },
    )
    assert_error(response, 422)


def test_non_owner_is_denied_before_run_revision_lookup(offline_context, monkeypatch):
    client, _ = offline_context

    def fail(*_args, **_kwargs):
        raise AssertionError("revision lookup must not run for a non-owner")

    monkeypatch.setattr("app.api.workflows.get_revision", fail)
    client.cookies.set(SESSION_COOKIE, "operator-session")
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/runs",
        json={"revision": "rev-1"},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "operator-csrf",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert_error(response, 403)
def test_workflow_draft_validation_database_failure_is_generic(offline_context):
    client, store = offline_context
    store.transaction_error = RuntimeError("private connection information")
    response = client.post(
        f"/api/v1/workflows/{uuid4()}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )
    assert_error(response, 503)
    assert "private connection information" not in response.text


def test_workflow_draft_validation_rejects_corrupt_stored_utf8(
    offline_draft_context,
):
    client, _, engine = offline_draft_context
    workflow_id = uuid4()
    save_workflow_draft(engine, workflow_id, sample_workflow_document())
    with engine.begin() as connection:
        connection.execute(
            update(mutable_drafts)
            .where(mutable_drafts.c.workflow_id == workflow_id)
            .values(document=b"\xff")
        )

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/validations",
        json={"expectedVersion": 1},
        headers={
            "Origin": "https://control.example",
            "X-CSRF-Token": "owner-csrf",
        },
    )

    assert_error(response, 503)
    assert "\ufffd" not in response.text


def test_workflow_draft_validation_authorization_precedes_draft_read(
    offline_context,
    monkeypatch,
):
    client, _ = offline_context

    def fail_read(*_args, **_kwargs):
        pytest.fail("unauthorized draft validation")

    monkeypatch.setattr("app.api.workflows.get_draft", fail_read)
    path = f"/api/v1/workflows/{uuid4()}/validations"
    body = {"expectedVersion": 1}

    client.cookies.set(SESSION_COOKIE, "operator-session")
    assert_error(
        client.post(
            path,
            json=body,
            headers={
                "Origin": "https://control.example",
                "X-CSRF-Token": "operator-csrf",
            },
        ),
        403,
    )
    client.cookies.set(SESSION_COOKIE, "owner-session")
    assert_error(
        client.post(
            path,
            json=body,
            headers={"Origin": "https://control.example"},
        ),
        403,
    )
    client.cookies.clear()
    assert_error(
        client.post(
            path,
            json=body,
            headers={
                "Origin": "https://control.example",
                "X-CSRF-Token": "owner-csrf",
            },
        ),
        401,
    )
