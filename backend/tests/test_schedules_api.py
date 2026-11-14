import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_reviews_api import assert_error, owner_headers
from test_schedule_store import save

from app.api.auth import SESSION_COOKIE
from app.core.auth import AuthConfig, AuthStore, digest, sessions
from app.core.database import create_database_engine
from app.core.outbox import outbox
from app.main import SecurityHeaders, create_api
from app.services.scheduling.preview import preview_occurrences
from app.services.scheduling.store import schedules
from app.services.workflows.runs import runs


@pytest.fixture
def context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/schedules",
        client_id="animetron",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="schedule-owner",
        grants={"schedule-viewer": "viewer", "schedule-operator": "operator"},
    )
    store = AuthStore(engine, config)
    with TestClient(SecurityHeaders(create_api(config, engine)), base_url=config.origin) as client:
        handle, principal = store.create_session("schedule-owner", "test")
        client.cookies.set(SESSION_COOKIE, handle)
        yield client, store, engine, handle, principal
    engine.dispose()


def payload(workflow_id, **changes):
    return {
        "workflowId": str(workflow_id),
        "revision": "v1",
        "expression": "30 2 * * *",
        "timeZone": "America/New_York",
        "enabled": True,
        "overlapPolicy": "skip",
        "missedRunPolicy": "skip",
        **changes,
    }


def test_unavailable_auth_and_body_bounds_without_database():
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        assert_error(client.get("/api/v1/schedules"), 503)
        for declared in ("9" * 5000, "0" * 5000 + "4097"):
            response = client.post(
                "/api/v1/schedules", content=b"{}",
                headers={"Content-Type": "application/json", "Content-Length": declared},
            )
            assert_error(response, 422)
        response = client.post(
            "/api/v1/schedules", content=iter([b" " * 2048, b" " * 2049]),
            headers={"Content-Type": "application/json"},
        )
        assert_error(response, 422)
        response = client.post(
            "/api/v1/schedules", content=b" " * 4094 + b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "0" * 5000 + "4096"},
        )
        assert_error(response, 503)


@pytest.mark.parametrize("path", [
    "/api/v1/schedules",
    "/api/v1/reviews/00000000-0000-4000-8000-000000000001/decisions",
])
@pytest.mark.parametrize("over_limit", [False, True])
def test_real_asgi_stream_stops_at_boundary(path, over_limit):
    async def exercise():
        app = SecurityHeaders(create_api())
        chunks = (
            [b" " * 2048, b" " * 2049, b"must-not-be-read"] if over_limit
            else [b" " * 2048, b" " * 2046, b"{}"]
        )
        consumed = []
        sent = []

        async def receive():
            chunk = chunks[len(consumed)]
            consumed.append(len(chunk))
            return {
                "type": "http.request", "body": chunk,
                "more_body": len(consumed) < len(chunks),
            }

        async def send(message):
            sent.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "https", "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "", "headers": [
                (b"host", b"control.example"), (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 1), "server": ("control.example", 443),
        }, receive, send)
        assert consumed == ([2048, 2049] if over_limit else [2048, 2046, 2])
        assert sent[0]["status"] == (422 if over_limit else 503)

    anyio.run(exercise)


def test_owner_create_read_page_pause_resume_conflict_and_preview(context):
    client, _, engine, _, principal = context
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
        before = conn.scalar(select(func.clock_timestamp()))
        counts = tuple(conn.scalar(select(func.count()).select_from(t)) for t in (runs, outbox))
    headers = owner_headers(principal)
    response = client.post("/api/v1/schedules", json=payload(workflow_id), headers=headers)
    assert response.status_code == 201
    original = response.json()
    schedule_id = UUID(original["id"])
    assert schedule_id.version == 4
    assert original["version"] == 1
    assert datetime.fromisoformat(original["nextDueAt"]) > before
    assert client.get(f"/api/v1/schedules/{schedule_id}").json() == original
    page = client.get("/api/v1/schedules", params={"limit": 1})
    assert page.status_code == 200 and len(page.json()["data"]) == 1
    cursor = page.json()["nextCursor"]
    assert cursor is not None
    assert all(
        UUID(row["id"]) > UUID(cursor)
        for row in client.get("/api/v1/schedules", params={"cursor": cursor}).json()["data"]
    )
    body = payload(workflow_id, enabled=False, expectedVersion=1)
    paused = client.put(f"/api/v1/schedules/{schedule_id}", json=body, headers=headers)
    assert paused.status_code == 200 and paused.json()["nextDueAt"] is None
    assert paused.json()["version"] == 2
    assert_error(client.put(f"/api/v1/schedules/{schedule_id}", json=body, headers=headers), 409)
    body.update(enabled=True, expectedVersion=2)
    resumed = client.put(f"/api/v1/schedules/{schedule_id}", json=body, headers=headers)
    assert resumed.status_code == 200 and resumed.json()["version"] == 3
    assert datetime.fromisoformat(resumed.json()["nextDueAt"]) > before
    for expression, after in (
        ("30 2 * * *", "2026-03-08T05:00:00+00:00"),
        ("30 1 * * *", "2026-11-01T04:00:00+00:00"),
    ):
        body.update(expression=expression, expectedVersion=resumed.json()["version"])
        resumed = client.put(f"/api/v1/schedules/{schedule_id}", json=body, headers=headers)
        assert resumed.status_code == 200
        result = client.post(
            f"/api/v1/schedules/{schedule_id}/previews",
            json={"after": after}, headers=headers,
        )
        assert result.status_code == 200
        actual = result.json()["occurrences"]
        expected = preview_occurrences(expression, "America/New_York", datetime.fromisoformat(after))
        assert len(actual) == 5
        for item, occurrence in zip(actual, expected, strict=True):
            assert set(item) == {"localTime", "dueAt", "slotKey"}
            assert item["localTime"] == occurrence.local_time.isoformat()
            assert datetime.fromisoformat(item["dueAt"]) == occurrence.due_at
            assert item["slotKey"] == occurrence.slot_key
    assert client.get(f"/api/v1/schedules/{schedule_id}").json() == resumed.json()
    with engine.connect() as conn:
        assert tuple(conn.scalar(select(func.count()).select_from(t)) for t in (runs, outbox)) == counts


def test_owner_auth_replay_and_security(context):
    client, store, engine, handle, principal = context
    headers = owner_headers(principal)
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
    body = payload(workflow_id)
    assert_error(client.post("/api/v1/schedules", json=body), 403)
    assert_error(client.post("/api/v1/schedules", json=body, headers={
        "Origin": "https://evil.example", "X-CSRF-Token": principal.csrf,
    }), 403)
    assert_error(client.post("/api/v1/schedules", json=body, headers=[
        ("Origin", "https://control.example"), ("Origin", "https://control.example"),
        ("X-CSRF-Token", principal.csrf),
    ]), 403)
    assert_error(client.post("/api/v1/schedules", json=body, headers=[
        ("Origin", "https://control.example"), ("X-CSRF-Token", principal.csrf),
        ("X-CSRF-Token", principal.csrf),
    ]), 403)
    viewer, viewer_principal = store.create_session("schedule-viewer", "test")
    client.cookies.set(SESSION_COOKIE, viewer)
    assert_error(client.get("/api/v1/schedules"), 403)
    assert_error(client.post("/api/v1/schedules", json=body, headers=owner_headers(viewer_principal)), 403)
    operator, operator_principal = store.create_session("schedule-operator", "test")
    client.cookies.set(SESSION_COOKIE, operator)
    assert_error(client.post("/api/v1/schedules", json=body, headers=owner_headers(operator_principal)), 403)
    client.cookies.set(SESSION_COOKIE, handle)
    store.revoke(handle, "test")
    assert_error(client.post("/api/v1/schedules", json=body, headers=headers), 401)
    fresh, fresh_principal = store.create_session("schedule-owner", "test")
    client.cookies.set(SESSION_COOKIE, fresh)
    with engine.begin() as conn:
        conn.execute(sessions.update().where(sessions.c.handle_hash == digest(fresh)).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        ))
    assert_error(client.post("/api/v1/schedules", json=body, headers=owner_headers(fresh_principal)), 401)
    fresh, fresh_principal = store.create_session("schedule-owner", "test")
    client.cookies.set(SESSION_COOKIE, fresh)
    with engine.begin() as conn:
        conn.execute(sessions.update().where(sessions.c.handle_hash == digest(fresh)).values(
            last_seen_at=datetime.now(UTC) - timedelta(hours=1),
        ))
    assert_error(client.post("/api/v1/schedules", json=body, headers=owner_headers(fresh_principal)), 401)
    client.cookies.clear()
    assert_error(client.get("/api/v1/schedules"), 401)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(schedules).where(
            schedules.c.workflow_id == workflow_id
        )) == 0


def test_reject_invalid_missing_and_preserve_transaction(context):
    client, _, engine, _, principal = context
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, "v1")
    headers = owner_headers(principal)
    endpoint = "/api/v1/schedules"
    for changes in (
        {"unknown": 1}, {"enabled": 1}, {"expression": "* * * * * *"},
        {"timeZone": "../UTC"}, {"overlapPolicy": "queue"},
        {"cursor": "2020-01-01T00:00:00Z"},
    ):
        assert_error(client.post(endpoint, json=payload(workflow_id, **changes), headers=headers), 422)
    assert_error(client.post(endpoint, json=payload(uuid4()), headers=headers), 404)
    missing_policy = payload(workflow_id)
    del missing_policy["missedRunPolicy"]
    assert_error(client.post(endpoint, json=missing_policy, headers=headers), 422)
    assert_error(client.post(endpoint, content=b"{", headers={
        **headers, "Content-Type": "application/json",
    }), 422)
    assert_error(client.post(endpoint, content=b"{}", headers=[
        ("Origin", "https://control.example"), ("X-CSRF-Token", principal.csrf),
        ("Content-Type", "application/json"), ("Content-Length", "2"),
        ("Content-Length", "2"),
    ]), 422)
    assert_error(client.post(endpoint, content=b"{}", headers={
        **headers, "Content-Type": "application/json", "Content-Encoding": "gzip",
    }), 422)
    assert_error(client.get(endpoint, params={"limit": 101}), 422)
    assert_error(client.get(endpoint, params={"cursor": "bad"}), 422)
    assert_error(client.get(endpoint, params={"unknown": "x"}), 422)
    assert_error(client.get(endpoint + "?limit=1&limit=2"), 422)
    assert_error(client.get(f"{endpoint}/{uuid4()}"), 404)
    assert_error(client.post(f"{endpoint}/{uuid4()}/previews", json={}, headers=headers), 404)
    assert_error(client.put(f"{endpoint}/{uuid4()}", json=payload(
        workflow_id, expectedVersion=1,
    ), headers=headers), 404)
    assert_error(client.get(f"{endpoint}/bad"), 422)
    made = client.post(endpoint, json=payload(workflow_id), headers=headers)
    assert made.status_code == 201
    schedule_id = made.json()["id"]
    assert_error(client.get(f"{endpoint}/{schedule_id}?unknown=x"), 422)
    assert_error(client.post(f"{endpoint}/{schedule_id}/previews", json={
        "after": "2026-01-01T00:00:00",
    }, headers=headers), 422)
    assert_error(client.post(f"{endpoint}/{schedule_id}/previews", json={
        "after": None,
    }, headers=headers), 422)
    assert_error(client.post(f"{endpoint}/{schedule_id}/previews", json={
        "after": "0001-01-01T00:00:00+00:00",
    }, headers=headers), 422)
    assert_error(client.put(f"{endpoint}/{schedule_id}", json=payload(
        uuid4(), expectedVersion=1,
    ), headers=headers), 404)
    assert client.post(f"{endpoint}/{schedule_id}/previews", json={}, headers=headers).status_code == 200
    assert client.get(f"{endpoint}/{schedule_id}").json() == made.json()
