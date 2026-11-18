"""Authenticated durable run status, event replay, and cancellation API."""

import os
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.auth import SESSION_COOKIE
from app.core.auth import AuthConfig, AuthStore
from app.core.database import create_database_engine
from app.core.outbox import outbox
from app.main import SecurityHeaders, create_api
from app.services.workflows import runs as run_service


@pytest.fixture
def run_context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/runs",
        client_id="animetron-runs",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="run-owner",
        grants={"run-operator": "operator", "run-viewer": "viewer"},
    )
    store = AuthStore(engine, config)
    with TestClient(
        SecurityHeaders(create_api(config, engine)), base_url=config.origin,
    ) as client:
        handle, principal = store.create_session("run-owner", "test-request")
        client.cookies.set(SESSION_COOKIE, handle)
        yield client, store, engine, handle, principal
    engine.dispose()


def create_durable_run(engine, *, run_id=None, terminal=True):
    identifier = run_id or uuid4()
    with engine.begin() as connection:
        run_service.create_run(connection, identifier)
        run_service.transition_run(
            connection, identifier, 1, run_service.RunState.RUNNING, "Started",
        )
        run_service.transition_run(
            connection, identifier, 2, run_service.RunState.WAITING_REVIEW,
            "Waiting for review",
        )
        run_service.transition_run(
            connection, identifier, 3, run_service.RunState.RUNNING, "Review resumed",
        )
        if terminal:
            run_service.transition_run(
                connection, identifier, 4, run_service.RunState.SUCCEEDED, "Finished",
            )
    return identifier


def create_long_run(engine, event_count=104):
    identifier = uuid4()
    with engine.begin() as connection:
        run_service.create_run(connection, identifier)
        for sequence in range(2, event_count + 1):
            state = (
                run_service.RunState.RUNNING
                if sequence % 2 == 0
                else run_service.RunState.WAITING_REVIEW
            )
            run_service.transition_run(
                connection, identifier, sequence - 1, state, f"event-{sequence}",
            )
    return identifier


def owner_headers(principal):
    return {"Origin": "https://control.example", "X-CSRF-Token": principal.csrf}


def assert_error(response, status):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "requestId"}
    assert body["error"]["message"] == "Request could not be completed"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-request-id"] == body["error"]["requestId"]


def assert_success(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_owner_reads_only_persisted_status_and_replays_exclusive_pages(run_context):
    client, _, engine, _, _ = run_context
    run_id = create_durable_run(engine)

    status = client.get(f"/api/v1/runs/{run_id}")
    assert_success(status)
    assert status.json() == {
        "runId": str(run_id),
        "state": "SUCCEEDED",
        "lastSequence": 5,
    }

    first = client.get(f"/api/v1/runs/{run_id}/events?limit=2")
    assert_success(first)
    first_page = first.json()
    assert set(first_page) == {"data", "nextAfterSequence", "hasMore"}
    assert [event["sequence"] for event in first_page["data"]] == [1, 2]
    assert [event["message"] for event in first_page["data"]] == ["Queued", "Started"]
    assert first_page["nextAfterSequence"] == 2
    assert first_page["hasMore"] is True
    assert set(first_page["data"][0]) == {
        "runId", "sequence", "state", "message", "occurredAt",
    }
    occurred_at = datetime.fromisoformat(first_page["data"][0]["occurredAt"])
    assert occurred_at.utcoffset() == timedelta(0)

    second = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=2&limit=2",
    )
    assert [event["sequence"] for event in second.json()["data"]] == [3, 4]
    assert second.json()["nextAfterSequence"] == 4
    assert second.json()["hasMore"] is True

    third = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=4&limit=2",
    )
    assert [event["sequence"] for event in third.json()["data"]] == [5]
    assert third.json()["nextAfterSequence"] == 5
    assert third.json()["hasMore"] is False
    assert "bytes" not in third.text.lower()
    assert "artifactPath" not in third.text
    assert "csrf" not in third.text.lower()


def test_tail_cursor_is_retained_and_replays_events_appended_later(run_context):
    client, _, engine, _, _ = run_context
    run_id = create_durable_run(engine, terminal=False)

    tail = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=4&limit=1",
    )
    assert_success(tail)
    assert tail.json() == {
        "data": [],
        "nextAfterSequence": 4,
        "hasMore": False,
    }

    with engine.begin() as connection:
        run_service.transition_run(
            connection, run_id, 4, run_service.RunState.SUCCEEDED, "Finished later",
        )
    replay = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=4&limit=1",
    )
    assert replay.json()["data"][0]["sequence"] == 5
    assert replay.json()["data"][0]["message"] == "Finished later"
    assert replay.json()["nextAfterSequence"] == 5


def test_future_cursor_is_not_clamped_or_treated_as_terminal(run_context):
    client, _, engine, _, _ = run_context
    run_id = create_durable_run(engine)
    future = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=2147483647",
    )
    assert_success(future)
    assert future.json() == {
        "data": [],
        "nextAfterSequence": 2147483647,
        "hasMore": False,
    }


def test_default_and_maximum_page_sizes_bound_database_replay(run_context, monkeypatch):
    client, _, engine, _, _ = run_context
    run_id = create_long_run(engine)
    original = run_service.list_events
    requested_limits = []

    def bounded_list_events(connection, identifier, after_sequence, limit=100):
        requested_limits.append(limit)
        return original(connection, identifier, after_sequence, limit)

    monkeypatch.setattr(run_service, "list_events", bounded_list_events)

    default_page = client.get(f"/api/v1/runs/{run_id}/events")
    assert_success(default_page)
    assert len(default_page.json()["data"]) == 50
    assert [item["sequence"] for item in default_page.json()["data"]] == list(range(1, 51))
    assert default_page.json()["nextAfterSequence"] == 50
    assert default_page.json()["hasMore"] is True

    maximum_page = client.get(
        f"/api/v1/runs/{run_id}/events?afterSequence=0000000050&limit=100",
    )
    assert_success(maximum_page)
    assert len(maximum_page.json()["data"]) == 54
    assert [item["sequence"] for item in maximum_page.json()["data"]] == list(range(51, 105))
    assert maximum_page.json()["nextAfterSequence"] == 104
    assert maximum_page.json()["hasMore"] is False
    assert requested_limits == [51, 101]
    assert "event-105" not in maximum_page.text


@pytest.mark.parametrize("role", ["operator", "viewer"])
@pytest.mark.parametrize("suffix", ["", "/events"])
def test_non_owner_roles_are_denied_before_run_lookup(run_context, monkeypatch, role, suffix):
    client, store, engine, _, _ = run_context
    run_id = create_durable_run(engine)
    handle, _ = store.create_session(
        "run-operator" if role == "operator" else "run-viewer", "role-test",
    )
    client.cookies.set(SESSION_COOKIE, handle)
    monkeypatch.setattr(
        run_service, "get_run_status",
        lambda *_args, **_kwargs: pytest.fail("run lookup occurred before role denial"),
        raising=False,
    )
    monkeypatch.setattr(
        run_service, "list_events",
        lambda *_args, **_kwargs: pytest.fail("event lookup occurred before role denial"),
    )
    assert_error(client.get(f"/api/v1/runs/{run_id}{suffix}"), 403)


def test_missing_runs_return_404_after_owner_authentication(run_context):
    client, _, _, _, _ = run_context
    missing = uuid4()
    assert_error(client.get(f"/api/v1/runs/{missing}"), 404)
    assert_error(client.get(f"/api/v1/runs/{missing}/events"), 404)


@pytest.mark.parametrize("suffix", ["", "/events"])
def test_run_reads_require_a_fresh_authenticated_session(run_context, suffix):
    client, store, _, handle, _ = run_context
    run_id = uuid4()
    client.cookies.clear()
    assert_error(client.get(f"/api/v1/runs/{run_id}{suffix}"), 401)

    store.revoke(handle, "test-revoke")
    client.cookies.set(SESSION_COOKIE, handle)
    assert_error(client.get(f"/api/v1/runs/{run_id}{suffix}"), 401)

    fresh_handle, _ = store.create_session("run-owner", "fresh-session")
    client.cookies.set(SESSION_COOKIE, fresh_handle)
    assert_error(client.get(f"/api/v1/runs/{run_id}{suffix}"), 404)


def test_logout_revokes_the_session_for_both_run_read_paths(run_context, monkeypatch):
    client, _, _, handle, principal = run_context

    async def logout_url(_self):
        return "https://identity.example/logout"

    monkeypatch.setattr("app.api.auth.Keycloak.logout_url", logout_url)
    response = client.post(
        "/api/v1/auth/logout",
        headers=owner_headers(principal),
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set(SESSION_COOKIE, handle)
    run_id = uuid4()
    assert_error(client.get(f"/api/v1/runs/{run_id}"), 401)
    assert_error(client.get(f"/api/v1/runs/{run_id}/events"), 401)


@pytest.mark.parametrize("suffix", ["", "/events"])
def test_run_reads_require_exact_single_origin(run_context, suffix):
    client, _, _, _, _ = run_context
    run_id = uuid4()
    assert_error(
        client.get(f"/api/v1/runs/{run_id}{suffix}", headers={"Origin": "https://evil.example"}),
        403,
    )
    duplicate_origin = [
        ("Origin", "https://control.example"),
        ("Origin", "https://control.example"),
    ]
    assert_error(
        client.get(f"/api/v1/runs/{run_id}{suffix}", headers=duplicate_origin),
        403,
    )


@pytest.mark.parametrize(
    "query",
    [
        "?afterSequence=",
        "?afterSequence=-1",
        "?afterSequence=%2B1",
        "?afterSequence=1.0",
        "?afterSequence=1%20OR%201%3D1",
        "?afterSequence=١",
        "?afterSequence=2147483648",
        "?afterSequence=9999999999",
        "?afterSequence=00000000000",
        "?afterSequence=1&afterSequence=2",
        "?afterSequence=1&unknown=2",
        "?limit=0",
        "?limit=101",
        "?limit=-1",
        "?limit=%2B1",
        "?limit=1.5",
        "?limit=1e1",
        "?limit=１２",
        "?limit=0000",
        "?limit=1;select",
        "?limit=1&limit=2",
    ],
)
def test_event_replay_rejects_invalid_untrusted_query_values(run_context, query):
    client, _, engine, _, _ = run_context
    run_id = create_durable_run(engine)
    with engine.connect() as connection:
        original_runs = connection.execute(
            select(
                run_service.runs.c.id, run_service.runs.c.state,
                run_service.runs.c.sequence,
            ).where(run_service.runs.c.id == run_id)
        ).all()
        original_events = connection.execute(
            select(
                run_service.events.c.run_id, run_service.events.c.sequence,
                run_service.events.c.state, run_service.events.c.message,
                run_service.events.c.occurred_at,
            ).where(run_service.events.c.run_id == run_id)
            .order_by(run_service.events.c.sequence)
        ).all()

    assert_error(client.get(f"/api/v1/runs/{run_id}/events{query}"), 422)

    with engine.connect() as connection:
        assert connection.execute(
            select(
                run_service.runs.c.id, run_service.runs.c.state,
                run_service.runs.c.sequence,
            ).where(run_service.runs.c.id == run_id)
        ).all() == original_runs
        assert connection.execute(
            select(
                run_service.events.c.run_id, run_service.events.c.sequence,
                run_service.events.c.state, run_service.events.c.message,
                run_service.events.c.occurred_at,
            ).where(run_service.events.c.run_id == run_id)
            .order_by(run_service.events.c.sequence)
        ).all() == original_events


def test_status_rejects_queries_and_malformed_uuid_without_echoing_input(run_context):
    client, _, _, _, _ = run_context
    assert_error(client.get("/api/v1/runs/not-a-uuid"), 422)
    assert_error(client.get(f"/api/v1/runs/{uuid4()}?unknown=1"), 422)
    assert_error(client.get(f"/api/v1/runs/{uuid4()}?unknown=1&unknown=2"), 422)


@pytest.mark.parametrize("query", [
    "?afterSequence=0000000000&limit=001",
    "?afterSequence=2147483647&limit=100",
])
def test_valid_decimal_boundaries_are_accepted(run_context, query):
    client, _, engine, _, _ = run_context
    run_id = create_durable_run(engine)
    response = client.get(f"/api/v1/runs/{run_id}/events{query}")
    assert_success(response)
    assert "error" not in response.json()


def test_disabled_api_fails_closed_without_database_for_both_reads():
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
    ) as client:
        run_id = uuid4()
        assert_error(client.get(f"/api/v1/runs/{run_id}"), 503)
        assert_error(client.get(f"/api/v1/runs/{run_id}/events"), 503)
        assert_error(
            client.post(f"/api/v1/runs/{run_id}/cancellations"),
            503,
        )


def test_owner_requests_cancellation_once(run_context):
    client, _, engine, _, principal = run_context
    run_id = uuid4()
    with engine.begin() as connection:
        run_service.create_run(connection, run_id)

    path = f"/api/v1/runs/{run_id}/cancellations"
    response = client.post(path, headers=owner_headers(principal))
    assert_success(response, status=202)
    assert response.json() == {
        "runId": str(run_id),
        "state": "CANCELLING",
        "lastSequence": 2,
        "outcome": "REQUESTED",
    }

    retry = client.post(path, headers=owner_headers(principal))
    assert_success(retry, status=202)
    assert retry.json() == {
        "runId": str(run_id),
        "state": "CANCELLING",
        "lastSequence": 2,
        "outcome": "ALREADY_REQUESTED",
    }

    with engine.begin() as connection:
        assert run_service.get_run_status(connection, run_id).state is (
            run_service.RunState.CANCELLING
        )
        assert connection.scalar(
            select(func.count()).select_from(outbox).where(
                outbox.c.resource_id == run_id,
                outbox.c.topic
                == "internal.workflow-run-cancellation-requested.v1",
            )
        ) == 1


def test_cancellation_requires_csrf_before_run_lookup(run_context):
    client, _, _, _, _ = run_context
    response = client.post(
        f"/api/v1/runs/{uuid4()}/cancellations",
        headers={"Origin": "https://control.example"},
    )
    assert_error(response, 403)


def test_cancellation_route_has_an_explicit_async_openapi_contract():
    schema = create_api().openapi()
    operation = schema["paths"]["/api/v1/runs/{id}/cancellations"]["post"]
    assert operation["responses"]["202"]["description"] == "Successful Response"
    assert operation["responses"]["409"]["description"] == "Request could not be completed"
