import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.auth import (
    AuthConfig,
    AuthDenied,
    AuthStore,
    audit_events,
    digest,
    sessions,
)
from app.core.database import create_database_engine


def config():
    return AuthConfig(
        issuer="https://identity.example/realms/animetron",
        client_id="animetron",
        client_secret="test-only-not-a-real-secret",
        origin="https://control.example",
        owner_subject="owner",
        grants={"reader": "viewer"},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": ""},
        {"issuer": "http://identity.example/realms/test"},
        {"issuer": "https://user:pass@identity.example/realm"},
        {"origin": "http://control.example"},
        {"origin": "https://control.example/path"},
        {"origin": "https://control.example/"},
        {"client_id": ""},
        {"client_secret": ""},
        {"owner_subject": ""},
        {"grants": {"attacker": "owner"}},
        {"session_seconds": 0},
    ],
)
def test_config_rejects_incomplete_or_untrusted_settings(changes):
    with pytest.raises(ValueError):
        replace(config(), **changes)


@pytest.fixture
def store():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Auth persistence tests require an isolated PostgreSQL database")
    engine = create_database_engine(url)
    with engine.begin() as conn:
        # Only this test suite's auth rows, never existing internal foundation data.
        for table in (sessions, audit_events):
            conn.execute(table.delete())
    yield AuthStore(engine, config())
    engine.dispose()


def test_login_state_is_bound_expiring_and_single_use_across_connections(store):
    state, browser = store.start_login("nonce", "v" * 48, "request-1")
    with pytest.raises(AuthDenied):
        store.consume_login(state, "wrong-browser")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(store, state, browser), range(2)))
    assert sum(result is not None for result in results) == 1
    accepted = next(result for result in results if result is not None)
    assert accepted["nonce"] == "nonce"
    assert accepted["verifier"] == "v" * 48
    expired, browser2 = store.start_login("nonce", "v" * 48, "request-2")
    with pytest.raises(AuthDenied):
        store.consume_login(expired, browser2, now=datetime.now(UTC) + timedelta(minutes=6))


def consume(store, state, browser):
    try:
        return store.consume_login(state, browser)
    except AuthDenied:
        return None


def test_session_is_durable_opaque_rotated_expiring_and_revocable(store):
    handle, principal = store.create_session("owner", "request-1")
    with store.engine.connect() as conn:
        row = conn.execute(select(sessions)).mappings().one()
        assert row["handle_hash"] == digest(handle)
        assert handle not in str(row)
    other_engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    try:
        other_store = AuthStore(other_engine, config())
        assert other_store.authenticate(handle) == principal
        replacement, _ = other_store.create_session("owner", "request-2")
        with pytest.raises(AuthDenied):
            store.authenticate(handle)
        assert store.authenticate(replacement).role == "owner"
        with pytest.raises(AuthDenied):
            store.authenticate(replacement, now=datetime.now(UTC) + timedelta(hours=9))
        store.revoke(replacement, "request-3")
        with pytest.raises(AuthDenied):
            other_store.authenticate(replacement)
    finally:
        other_engine.dispose()


def test_roles_fail_closed_and_config_changes_invalidate_sessions(store):
    with pytest.raises(AuthDenied):
        store.create_session("unlisted", "request")
    handle, principal = store.create_session("reader", "request")
    assert principal.role == "viewer"
    restricted = AuthStore(store.engine, replace(config(), grants={}))
    with pytest.raises(AuthDenied):
        restricted.authenticate(handle)
    changed = AuthStore(store.engine, replace(config(), client_id="different-client"))
    with pytest.raises(AuthDenied):
        changed.authenticate(handle)


def test_audit_contains_no_session_handle_or_provider_credentials(store):
    handle, principal = store.create_session("owner", "request-1")
    store.revoke(handle, "request-2")
    with store.engine.connect() as conn:
        rows = conn.execute(select(audit_events)).mappings().all()
    assert [row["event"] for row in rows] == ["login_succeeded", "logout"]
    assert all(row["principal_id"] == principal.id for row in rows)
    assert all(handle not in str(row) and config().client_secret not in str(row) for row in rows)
