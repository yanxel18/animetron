import base64
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
from owned_auth_database import reset_auth_tables
from sqlalchemy import select
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from app.core.auth import (
    AuthConfig,
    AuthStore,
    audit_events,
    sessions,
)
from app.core.database import create_database_engine
from app.main import SecurityHeaders, configured_api, create_api

_TEST_CLIENT_SECRET = secrets.token_urlsafe(32)


def auth_config():
    return AuthConfig(
        issuer="https://identity.example/realms/animetron",
        client_id="animetron", client_secret=_TEST_CLIENT_SECRET,
        origin="https://control.example", owner_subject="owner", grants={"reader": "viewer"},
    )


def test_auth_fixture_client_secret_is_not_embedded_in_source():
    assert auth_config().client_secret not in Path(__file__).read_text(encoding="utf-8")


@pytest.fixture
def context():
    engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    config = auth_config()
    store = AuthStore(engine, config)
    reset_auth_tables(engine)
    with TestClient(SecurityHeaders(create_api(config, engine)),
                    base_url=config.origin) as client:
        yield client, store
    engine.dispose()


@pytest.mark.parametrize("path", [
    "/api/v1/auth/login", "/api/v1/auth/session", "/api/v1/readiness",
    "/api/v1/audit-events", "/api/v1/auth/callback?state=fake&code=fake",
])
def test_no_configuration_fails_closed_without_header_bypass(path):
    with TestClient(SecurityHeaders(create_api()), base_url="https://control.example") as client:
        response = client.get(path, headers={
            "X-User": "owner", "X-Principal": "owner", "X-Role": "owner",
            "Authorization": "Bearer " + secrets.token_urlsafe(32),
        })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_UNAVAILABLE"
    assert "requestId" in response.json()["error"]


def test_malformed_database_configuration_preserves_only_public_liveness(monkeypatch):
    values = {
        "ANIMETRON_OIDC_ISSUER": "https://identity.example/realms/test",
        "ANIMETRON_OIDC_CLIENT_ID": "animetron",
        "ANIMETRON_OIDC_CLIENT_SECRET": secrets.token_urlsafe(32),
        "ANIMETRON_BROWSER_ORIGIN": "https://control.example",
        "ANIMETRON_OWNER_SUBJECT": "owner",
        "ANIMETRON_DATABASE_URL": "not-a-database-url",
        "ANIMETRON_SUBJECT_GRANTS": "{}",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with TestClient(SecurityHeaders(configured_api()), base_url="https://control.example") as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/readiness").status_code == 503


@pytest.mark.parametrize("path", [
    "/api/v1/auth/session", "/api/v1/readiness", "/api/v1/audit-events",
])
def test_missing_session_is_unauthenticated(context, path):
    client, _ = context
    response = client.get(path, headers={"X-User": "owner"})
    assert response.status_code == 401


def test_session_and_role_authorization_are_real_and_origin_bound(context):
    client, store = context
    handle, principal = store.create_session("reader", "request")
    client.cookies.set("__Host-animetron_session", handle)
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json()["principalId"] == principal.id
    assert response.json()["role"] == "viewer"
    assert response.json()["csrfToken"] == principal.csrf
    assert client.get("/api/v1/readiness").status_code == 403
    assert client.get("/api/v1/audit-events").status_code == 403
    assert client.get("/api/v1/auth/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/v1/auth/session", headers={"Host": "evil.example"}).status_code == 403


@pytest.mark.parametrize("headers", [
    {}, {"Origin": "https://control.example"},
    {"Origin": "https://evil.example", "X-CSRF-Token": secrets.token_urlsafe(32)},
    {"Origin": "null", "X-CSRF-Token": secrets.token_urlsafe(32)},
    {"Origin": "https://control.example", "X-CSRF-Token": secrets.token_urlsafe(32)},
])
def test_logout_requires_origin_and_csrf_and_never_revokes_on_failure(context, headers):
    client, store = context
    handle, _ = store.create_session("owner", "request")
    client.cookies.set("__Host-animetron_session", handle)
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 403
    assert store.authenticate(handle).role == "owner"
    assert client.get("/api/v1/auth/logout").status_code == 405


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "https://control.example/"])
def test_websocket_refuses_missing_or_wrong_origin(context, origin):
    client, store = context
    handle, _ = store.create_session("owner", "request")
    client.cookies.set("__Host-animetron_session", handle)
    headers = {} if origin is None else {"Origin": origin}
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(store.config.origin.replace("https://", "wss://") + "/api/v1/ws", headers=headers),
    ):
        pass
    assert error.value.code == 4403


def test_websocket_requires_principal_and_rechecks_revocation(context):
    client, store = context
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(store.config.origin.replace("https://", "wss://") + "/api/v1/ws", headers={"Origin": store.config.origin}),
    ):
        pass
    assert error.value.code == 4401
    handle, principal = store.create_session("owner", "request")
    client.cookies.set("__Host-animetron_session", handle)
    with client.websocket_connect(store.config.origin.replace("https://", "wss://") + "/api/v1/ws", headers={"Origin": store.config.origin}) as websocket:
        assert websocket.receive_json() == {"type": "authenticated", "principalId": principal.id}
        store.revoke(handle, "request")
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.send_text("ping")
            websocket.receive_json()
        assert error.value.code == 4401


def test_websocket_idle_timeout_checks_do_not_refresh_persisted_activity(context, monkeypatch):
    client, store = context
    handle, _ = store.create_session("owner", "request")
    baseline = datetime.now(UTC) - timedelta(minutes=29)
    with store.engine.begin() as conn:
        conn.execute(sessions.update().values(last_seen_at=baseline))
    client.cookies.set("__Host-animetron_session", handle)
    original_receive = WebSocket.receive
    observed = []

    async def receive_with_idle_timeout(socket):
        if socket.application_state == WebSocketState.CONNECTED and len(observed) < 2:
            with store.engine.connect() as conn:
                observed.append(conn.execute(select(sessions.c.last_seen_at)).scalar_one())
            if len(observed) == 1:
                # Force the real timeout recovery branch without a wall-clock sleep.
                raise TimeoutError
        return await original_receive(socket)

    monkeypatch.setattr(WebSocket, "receive", receive_with_idle_timeout)
    with client.websocket_connect(
        store.config.origin.replace("https://", "wss://") + "/api/v1/ws",
        headers={"Origin": store.config.origin},
    ) as socket:
        assert socket.receive_json()["type"] == "authenticated"
        socket.send_text("ping")
        assert socket.receive_json()["type"] == "pong"
        assert observed == [baseline, baseline]
        with store.engine.connect() as conn:
            assert conn.execute(select(sessions.c.last_seen_at)).scalar_one() > baseline


def test_owner_audit_history_is_capped_cursor_paginated(context):
    client, store = context
    handle, _ = store.create_session("owner", "request")
    client.cookies.set("__Host-animetron_session", handle)
    store.audit("websocket_authenticated", "request")
    response = client.get("/api/v1/audit-events?limit=1")
    assert response.status_code == 200
    page = response.json()
    assert len(page["data"]) == 1
    assert page["nextCursor"] is not None
    next_page = client.get("/api/v1/audit-events", params={"cursor": page["nextCursor"]}).json()
    assert next_page["data"][0]["id"] > page["data"][0]["id"]
    assert client.get("/api/v1/audit-events?limit=101").status_code == 422
    assert client.get("/api/v1/audit-events?cursor=-1").status_code == 422
    with store.engine.connect() as conn:
        assert conn.execute(select(audit_events)).mappings().all()


def test_repeated_unauthenticated_requests_are_counted_without_append_growth(context):
    client, store = context
    for _ in range(110):
        assert client.get("/api/v1/auth/session").status_code == 401
        assert client.get("/api/v1/auth/callback").status_code == 400
        assert client.get("/api/v1/readiness",
                          headers={"Origin": "https://evil.example"}).status_code == 403
    with store.engine.connect() as conn:
        assert not conn.execute(select(audit_events)).all()
    with store.transaction() as conn:
        # Simulate pre-migration legacy append-only data, not a new denial write.
        conn.execute(audit_events.insert().values(
            event="access_denied", request_id="legacy",
            occurred_at=datetime.now(UTC) - timedelta(days=91),
        ))
    handle, _ = store.create_session("owner", "owner-request")
    client.cookies.set("__Host-animetron_session", handle)
    page = client.get("/api/v1/audit-events").json()
    counts = {}
    for row in page["denials"]:
        counts[row["event"]] = counts.get(row["event"], 0) + row["occurrences"]
        assert set(row) == {
            "event", "windowStart", "occurrences", "lastRequestId", "lastOccurredAt",
        }
        assert len(row["lastRequestId"]) == 36
    assert counts == {"access_denied": 220, "login_failed": 110}
    assert len(page["data"]) == 1


@pytest.mark.parametrize("attack", [
    "issuer", "audience", "nonce", "missing_nonce", "nonce_supported_false",
    "expired", "future_iat", "azp", "signature", "unsigned", "hmac", "unknown_key",
])
def test_callback_rejects_adversarial_signed_claims_and_algorithms(context, monkeypatch, attack):
    client, store = context
    key = RSAKey.generate_key(parameters={"kid": "test"})
    nonce = ""
    provider_tokens: list[str] = []
    base = store.config.issuer + "/protocol/openid-connect/"

    async def response(_transport, request):
        if str(request.url).endswith("/.well-known/openid-configuration"):
            payload = {
                "issuer": store.config.issuer,
                "authorization_endpoint": base + "auth", "token_endpoint": base + "token",
                "jwks_uri": base + "certs", "end_session_endpoint": base + "logout",
                "code_challenge_methods_supported": ["S256"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "response_types_supported": ["code"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            }
        elif str(request.url) == base + "certs":
            payload = {"keys": [key.as_dict()]}
        else:
            assert str(request.url) == base + "token"
            claims = {
                "iss": store.config.issuer, "sub": "owner", "aud": store.config.client_id,
                "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": nonce,
            }
            changes = {
                "issuer": {"iss": "https://evil.example"},
                "audience": {"aud": "another-client", "azp": store.config.client_id},
                "nonce": {"nonce": "wrong"},
                "nonce_supported_false": {"nonce": "wrong", "nonce_supported": False},
                "expired": {"exp": int(time.time()) - 10},
                "future_iat": {"iat": int(time.time()) + 600},
                "azp": {"aud": [store.config.client_id, "other"], "azp": "other"},
            }
            claims.update(changes.get(attack, {}))
            if attack == "missing_nonce":
                claims.pop("nonce")
            token = jwt.encode({"alg": "RS256", "kid": "test"}, claims, key)
            if attack == "signature":
                header, body, signature = token.split(".")
                signature = ("A" if signature[0] != "A" else "B") + signature[1:]
                token = f"{header}.{body}.{signature}"
            elif attack == "unsigned":
                header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
                token = header + "." + token.split(".")[1] + "."
            elif attack == "hmac":
                token = jwt.encode({"alg": "HS256"}, claims, OctKey.generate_key(256))
            elif attack == "unknown_key":
                token = jwt.encode({"alg": "RS256", "kid": "unknown"}, claims, key)
            access_token = secrets.token_urlsafe(32)
            provider_tokens.extend((access_token, token))
            payload = {"access_token": access_token, "token_type": "Bearer",
                       "id_token": token}
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", response)
    started = client.get("/api/v1/auth/login", follow_redirects=False)
    assert started.status_code == 302
    query = parse_qs(urlsplit(started.headers["location"]).query)
    nonce = query["nonce"][0]
    callback = "/api/v1/auth/callback?state=" + query["state"][0] + "&code=test-code"
    rejected = client.get(callback, follow_redirects=False)
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "IDENTITY_REJECTED"
    assert all(token not in rejected.text for token in provider_tokens)
    assert "__Host-animetron_session" not in client.cookies
    assert client.get(callback, follow_redirects=False).status_code == 400
    with store.engine.connect() as conn:
        assert conn.execute(select(sessions)).first() is None
    assert client.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize("attack", ["issuer", "token_endpoint", "pkce", "oversized", "redirect"])
def test_discovery_refuses_untrusted_or_unbounded_provider_metadata(context, monkeypatch, attack):
    client, store = context
    base = store.config.issuer + "/protocol/openid-connect/"

    async def response(_transport, request):
        if attack == "oversized":
            return httpx.Response(200, content=b"x" * 262145, request=request)
        if attack == "redirect":
            return httpx.Response(302, headers={"Location": "https://evil.example"}, request=request)
        payload = {
            "issuer": store.config.issuer,
            "authorization_endpoint": base + "auth", "token_endpoint": base + "token",
            "jwks_uri": base + "certs", "end_session_endpoint": base + "logout",
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "response_types_supported": ["code"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }
        if attack == "pkce":
            payload["code_challenge_methods_supported"] = ["plain"]
        else:
            payload[attack] = "https://evil.example"
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", response)
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 503
    assert "__Host-animetron_session" not in client.cookies
