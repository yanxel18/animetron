import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.api import reviews as reviews_api
from app.api.auth import SESSION_COOKIE
from app.core.auth import AuthConfig, AuthDenied, AuthStore, Principal, sessions
from app.core.database import create_database_engine
from app.core.outbox import outbox
from app.main import SecurityHeaders, create_api
from app.services.reviews import decisions as decisions_service
from app.services.reviews.scope import ReviewDestination, ReviewScope
from app.services.reviews.store import (
    DecisionOutcome,
    DeliveryOutcome,
    ReviewNotFound,
    ReviewState,
    create_review_request,
    deliver_review_request,
    get_review_decision,
    get_review_request,
)
from app.services.workflows.runs import create_run


@pytest.fixture
def review_context():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    config = AuthConfig(
        issuer="https://identity.example/realms/reviews",
        client_id="animetron-reviews",
        client_secret=secrets.token_urlsafe(32),
        origin="https://control.example",
        owner_subject="review-owner",
        grants={"review-operator": "operator", "review-viewer": "viewer"},
    )
    store = AuthStore(engine, config)
    with TestClient(SecurityHeaders(create_api(config, engine)), base_url=config.origin) as client:
        handle, principal = store.create_session("review-owner", "test-request")
        client.cookies.set(SESSION_COOKIE, handle)
        yield client, store, engine, handle, principal
    engine.dispose()


def new_scope(*, run_id=None, revision="render-1"):
    return ReviewScope(
        run_id or uuid4(),
        revision,
        "a" * 64,
        "b" * 64,
        (ReviewDestination("facebook", "page-1"),),
    )


def create_review(
    engine, *, scope=None, expires_at=None, delivered=True, create_run_record=True,
):
    scope = scope or new_scope()
    review_id = uuid4()
    with engine.begin() as connection:
        if create_run_record:
            create_run(connection, scope.run_id)
        create_review_request(
            connection,
            review_id,
            scope,
            expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        )
        if delivered:
            deliver_review_request(
                connection, review_id, outcome=DeliveryOutcome.DELIVERED,
            )
    return review_id, scope


def decision_payload(scope, outcome="APPROVED"):
    return {
        "expectedScope": {
            "runId": str(scope.run_id),
            "artifactRevision": scope.artifact_revision,
            "artifactSha256": scope.artifact_sha256,
            "captionSha256": scope.caption_sha256,
            "destinations": [
                {"provider": item.provider, "accountId": item.account_id}
                for item in scope.destinations
            ],
        },
        "outcome": outcome,
    }


def owner_headers(principal):
    return {
        "Origin": "https://control.example",
        "X-CSRF-Token": principal.csrf,
    }


def assert_error(response, status):
    try:
        body = response.json()
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    except ValueError:
        code = None
    assert response.status_code == status, (
        f"expected status {status}, got {response.status_code}, error code {code!r}"
    )
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message", "requestId"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-request-id"] == response.json()["error"]["requestId"]


def assert_status(response, status):
    try:
        body = response.json()
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    except ValueError:
        code = None
    assert response.status_code == status, (
        f"expected status {status}, got {response.status_code}, error code {code!r}"
    )


@pytest.mark.parametrize(
    "declared", ["9" * 5000, "0" * 5000 + "4097"],
    ids=["extreme-digits", "zero-padded-oversized"],
)
def test_decision_body_guard_rejects_extreme_content_length_without_database(declared):
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/reviews/00000000-0000-4000-8000-000000000001/decisions",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": declared},
        )
    assert_error(response, 422)
    assert response.json()["error"]["code"] == "REVIEW_BODY_TOO_LARGE"


def test_decision_body_guard_caps_chunked_body_without_content_length():
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/reviews/00000000-0000-4000-8000-000000000001/decisions",
            content=iter([b" " * 2048, b" " * 2049]),
            headers={"Content-Type": "application/json"},
        )
    assert "content-length" not in response.request.headers
    assert response.request.headers["transfer-encoding"] == "chunked"
    assert_error(response, 422)
    assert response.json()["error"]["code"] == "REVIEW_BODY_TOO_LARGE"


@pytest.mark.parametrize(
    "declared", ["4096", "0" * 5000 + "4096", "0" * 5000],
    ids=["exact-cap", "zero-padded-cap", "all-zero"],
)
def test_decision_body_guard_allows_bounded_leading_zero_lengths(declared):
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/reviews/00000000-0000-4000-8000-000000000001/decisions",
            content=b" " * 4094 + b"{}",
            headers={"Content-Type": "application/json", "Content-Length": declared},
        )
    # Valid JSON at exactly the cap reaches the existing fail-closed auth path.
    assert_error(response, 503)
    assert response.json()["error"]["code"] == "AUTH_UNAVAILABLE"


def test_decision_body_guard_parses_chunked_json_at_exact_cap():
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/reviews/00000000-0000-4000-8000-000000000001/decisions",
            content=iter([b" " * 2048, b" " * 2047 + b"{"]),
            headers={"Content-Type": "application/json"},
        )
    assert "content-length" not in response.request.headers
    # Malformed JSON at exactly the cap reaches parsing, not the size rejection.
    assert_error(response, 422)
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_reviews_api_is_disabled_without_both_auth_configuration_and_engine():
    with TestClient(
        SecurityHeaders(create_api()), base_url="https://control.example",
    ) as client:
        response = client.get("/api/v1/reviews")
    assert_error(response, 503)
    assert response.json()["error"]["code"] == "AUTH_UNAVAILABLE"


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_review_queue_and_decisions_are_owner_only(review_context, role):
    client, store, engine, _, _ = review_context
    review_id, scope = create_review(engine)
    handle, principal = store.create_session(
        "review-operator" if role == "operator" else "review-viewer", "role-test",
    )
    client.cookies.set(SESSION_COOKIE, handle)

    assert_error(client.get("/api/v1/reviews"), 403)
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope),
        headers=owner_headers(principal),
    )
    assert_error(response, 403)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION


def test_review_queue_requires_an_authenticated_session(review_context):
    client, _, engine, _, _ = review_context
    create_review(engine)
    client.cookies.clear()
    response = client.get("/api/v1/reviews")
    assert_error(response, 401)
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("expired_by", ["absolute", "idle"])
def test_review_queue_rejects_expired_sessions(review_context, expired_by):
    client, store, engine, handle, _ = review_context
    with engine.begin() as connection:
        if expired_by == "absolute":
            connection.execute(sessions.update().values(
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ))
        else:
            connection.execute(sessions.update().values(
                last_seen_at=datetime.now(UTC) - timedelta(hours=1),
            ))
    create_review(engine)
    response = client.get("/api/v1/reviews")
    assert_error(response, 401)
    with pytest.raises(AuthDenied):
        store.authenticate(handle)


def test_review_queue_rejects_revoked_sessions(review_context):
    client, store, engine, handle, _ = review_context
    create_review(engine)
    store.revoke(handle, "test-revoke")
    assert_error(client.get("/api/v1/reviews"), 401)


@pytest.mark.parametrize("origin,csrf", [
    (None, None),
    ("https://control.example", None),
    ("https://evil.example", "valid"),
    ("https://control.example", "wrong"),
])
def test_decision_requires_exact_origin_and_csrf(review_context, origin, csrf):
    client, _, engine, _, principal = review_context
    review_id, scope = create_review(engine)
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    if csrf == "valid":
        headers["X-CSRF-Token"] = principal.csrf
    elif csrf == "wrong":
        headers["X-CSRF-Token"] = secrets.token_urlsafe(32)
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope),
        headers=headers,
    )
    assert_error(response, 403)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION


def test_decision_rejects_duplicate_origin_or_csrf_headers(review_context):
    client, _, engine, _, principal = review_context
    review_id, scope = create_review(engine)
    headers = [
        ("Origin", "https://control.example"),
        ("Origin", "https://control.example"),
        ("X-CSRF-Token", principal.csrf),
        ("Content-Type", "application/json"),
    ]
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        content=json.dumps(decision_payload(scope)),
        headers=headers,
    )
    assert_error(response, 403)
    headers = [
        ("Origin", "https://control.example"),
        ("X-CSRF-Token", principal.csrf),
        ("X-CSRF-Token", principal.csrf),
        ("Content-Type", "application/json"),
    ]
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        content=json.dumps(decision_payload(scope)),
        headers=headers,
    )
    assert_error(response, 403)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION


def test_review_queue_is_capped_keyset_paginated_and_tie_safe(review_context):
    client, _, engine, _, _ = review_context
    scopes = [new_scope() for _ in range(3)]
    review_ids = []
    with engine.begin() as connection:
        for scope in scopes:
            create_run(connection, scope.run_id)
            review_id = uuid4()
            review_ids.append(review_id)
            create_review_request(
                connection, review_id, scope,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            deliver_review_request(
                connection, review_id, outcome=DeliveryOutcome.DELIVERED,
            )

    first = client.get("/api/v1/reviews?limit=1")
    assert first.status_code == 200, (
        f"expected queue status 200, got {first.status_code}, "
        f"error code {first.json().get('error', {}).get('code')!r}"
    )
    first_page = first.json()
    assert len(first_page["data"]) == 1
    assert first_page["nextCursor"]
    assert set(first_page) == {"data", "nextCursor"}
    assert set(first_page["data"][0]) == {
        "id", "runId", "artifactRevision", "artifactSha256", "captionSha256",
        "destinations", "expiresAt", "createdAt", "state", "stateChangedAt",
        "deliveryErrorCode",
    }
    assert first_page["data"][0]["state"] in {
        "PENDING_DELIVERY", "AWAITING_DECISION", "APPROVED", "REJECTED",
        "EXPIRED", "SUPERSEDED", "DELIVERY_FAILED", "DELIVERY_UNKNOWN",
    }
    assert "bytes" not in first.text.lower()

    seen = [first_page["data"][0]["id"]]
    cursor = first_page["nextCursor"]
    while cursor:
        page = client.get("/api/v1/reviews", params={"limit": 1, "cursor": cursor})
        assert page.status_code == 200, (
            f"expected next page status 200, got {page.status_code}, "
            f"error code {page.json().get('error', {}).get('code')!r}"
        )
        result = page.json()
        seen.extend(item["id"] for item in result["data"])
        cursor = result["nextCursor"]
    with engine.connect() as connection:
        created_at = {
            item: get_review_request(connection, item).created_at for item in review_ids
        }
    expected_order = sorted(
        review_ids, key=lambda item: (created_at[item], str(item)),
    )
    positions = [seen.index(str(item)) for item in expected_order]
    assert positions == sorted(positions)
    assert all(str(item) in seen for item in review_ids)
    assert len(set(seen)) == len(seen)

    assert client.get("/api/v1/reviews").status_code == 200
    assert client.get("/api/v1/reviews?limit=100").status_code == 200
    for query in (
        "?limit=0", "?limit=101", "?limit=-1", "?cursor=bad",
        "?unknown=1", "?limit=1&limit=2", "?cursor=bad&cursor=also-bad",
    ):
        assert_error(client.get("/api/v1/reviews" + query), 422)


def test_review_queue_does_not_materialize_or_expose_nonmetadata_fields(review_context):
    client, _, engine, _, _ = review_context
    review_id, _ = create_review(engine, delivered=False)
    response = client.get("/api/v1/reviews?limit=100")
    assert_status(response, 200)
    record = next(item for item in response.json()["data"] if item["id"] == str(review_id))
    assert record["state"] == "PENDING_DELIVERY"
    assert "reviewerId" not in response.text
    assert "csrf" not in response.text.lower()
    assert "approval" not in response.text.lower()


@pytest.mark.parametrize("outcome", ["APPROVED", "REJECTED"])
def test_owner_can_decide_exact_scope_and_retry_after_fresh_authentication(
    review_context, outcome,
):
    client, store, engine, _, principal = review_context
    review_id, scope = create_review(engine)
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope, outcome),
        headers=owner_headers(principal),
    )
    assert_status(response, 200)
    first = response.json()
    assert set(first) == {"reviewId", "outcome", "decidedAt"}
    assert first["reviewId"] == str(review_id)
    assert first["outcome"] == outcome
    assert "reviewerId" not in first

    retry = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope, outcome),
        headers=owner_headers(principal),
    )
    assert_status(retry, 200)
    assert retry.json() == first

    with engine.connect() as connection:
        decision = get_review_decision(connection, review_id)
        assert decision.outcome is DecisionOutcome(outcome)
        assert decision.reviewer_id == principal.id
        request = get_review_request(connection, review_id)
        assert request.state.value == outcome
        intents = connection.execute(
            select(outbox).where(outbox.c.resource_id == review_id)
        ).all()
        assert len(intents) == (1 if outcome == "APPROVED" else 0)
        if intents:
            assert intents[0].topic == decisions_service.APPROVED_TOPIC

    # A persisted decision does not bypass current session authentication on replay.
    handle = client.cookies.get(SESSION_COOKIE)
    store.revoke(handle, "revoke-before-replay")
    replay = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope, outcome),
        headers=owner_headers(principal),
    )
    assert_error(replay, 401)


def test_http_decision_outer_rollback_removes_decision_and_intent(
    review_context, monkeypatch,
):
    _, store, engine, handle, principal = review_context
    review_id, scope = create_review(engine)
    record = reviews_api.record_decision

    def fail_after_record(
        connection: Connection,
        user: Principal,
        expected_scope: ReviewScope,
        request_id: UUID,
        outcome: DecisionOutcome,
    ) -> None:
        record(connection, user, expected_scope, request_id, outcome)
        raise RuntimeError("simulated failure after transactional service")

    monkeypatch.setattr(reviews_api, "record_decision", fail_after_record)
    with TestClient(
        SecurityHeaders(create_api(store.config, store.engine)),
        base_url=store.config.origin,
        raise_server_exceptions=False,
    ) as client:
        client.cookies.set(SESSION_COOKIE, handle)
        response = client.post(
            f"/api/v1/reviews/{review_id}/decisions",
            json=decision_payload(scope),
            headers=owner_headers(principal),
        )
    assert_error(response, 503)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION
        with pytest.raises(ReviewNotFound):
            get_review_decision(connection, review_id)
        assert connection.execute(
            select(outbox).where(outbox.c.resource_id == review_id)
        ).all() == []


def test_decision_rejects_changed_scope_or_opposing_replay(review_context):
    client, _, engine, _, principal = review_context
    review_id, scope = create_review(engine)
    original = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope),
        headers=owner_headers(principal),
    )
    assert_status(original, 200)
    changed = decision_payload(scope)
    changed["expectedScope"]["captionSha256"] = "c" * 64
    assert_error(client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=changed,
        headers=owner_headers(principal),
    ), 409)
    assert_error(client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope, "REJECTED"),
        headers=owner_headers(principal),
    ), 409)


def test_decision_maps_missing_review_to_not_found(review_context):
    client, _, _, _, principal = review_context
    response = client.post(
        f"/api/v1/reviews/{uuid4()}/decisions",
        json=decision_payload(new_scope()),
        headers=owner_headers(principal),
    )
    assert_error(response, 404)
    assert response.json()["error"]["code"] == "REVIEW_NOT_FOUND"


@pytest.mark.parametrize("payload", [
    {"expectedScope": {}, "outcome": "APPROVED", "principalId": "owner"},
    {
        "expectedScope": {
            "runId": str(uuid4()), "artifactRevision": "",
            "artifactSha256": "a" * 64, "captionSha256": "b" * 64,
            "destinations": [{"provider": "facebook", "accountId": "page-1"}],
        },
        "outcome": "APPROVED",
    },
    {
        "expectedScope": {
            "runId": str(uuid4()), "artifactRevision": "render-1",
            "artifactSha256": "a" * 64, "captionSha256": "b" * 64,
            "destinations": [{"provider": "facebook", "accountId": "page-1",
                              "reviewerId": "forged"}],
        },
        "outcome": "APPROVED",
    },
    {
        "expectedScope": {
            "runId": str(uuid4()), "artifactRevision": "render-1",
            "artifactSha256": "a" * 64, "captionSha256": "b" * 64,
            "destinations": [{"provider": "facebook", "accountId": "page-1"}],
        },
        "outcome": "PENDING",
    },
])
def test_decision_rejects_invalid_or_unknown_body_fields(review_context, payload):
    client, _, engine, _, principal = review_context
    review_id, _scope = create_review(engine)
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=payload,
        headers=owner_headers(principal),
    )
    assert_error(response, 422)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION
        with pytest.raises(ReviewNotFound):
            get_review_decision(connection, review_id)


def test_decision_rejects_oversized_and_non_json_bodies(review_context):
    client, _, engine, _, principal = review_context
    review_id, _scope = create_review(engine)
    headers = owner_headers(principal)
    assert_error(client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        content=b"x" * 4097,
        headers={**headers, "Content-Type": "application/json"},
    ), 422)
    assert_error(client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        content="{}",
        headers={**headers, "Content-Type": "text/plain"},
    ), 422)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION


def test_expired_review_cannot_be_decided(review_context):
    client, _, engine, _, principal = review_context
    review_id, scope = create_review(
        engine, expires_at=datetime.now(UTC) + timedelta(milliseconds=400),
    )
    time.sleep(0.5)
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope),
        headers=owner_headers(principal),
    )
    assert_error(response, 409)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.AWAITING_DECISION


def test_superseded_review_cannot_be_decided(review_context):
    client, _, engine, _, principal = review_context
    review_id, scope = create_review(engine)
    create_review(
        engine,
        scope=new_scope(run_id=scope.run_id, revision="render-2"),
        create_run_record=False,
    )
    response = client.post(
        f"/api/v1/reviews/{review_id}/decisions",
        json=decision_payload(scope),
        headers=owner_headers(principal),
    )
    assert_error(response, 409)
    with engine.connect() as connection:
        assert get_review_request(connection, review_id).state is ReviewState.SUPERSEDED


def test_invalid_path_uuid4_is_rejected(review_context):
    client, _, _, _, principal = review_context
    response = client.post(
        "/api/v1/reviews/not-a-uuid/decisions",
        json=decision_payload(new_scope()),
        headers=owner_headers(principal),
    )
    assert_error(response, 422)
