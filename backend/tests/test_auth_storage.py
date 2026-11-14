import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from owned_auth_database import reset_auth_tables
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import (
    AuthConfig,
    AuthDenied,
    AuthStore,
    audit_events,
    denial_counters,
    digest,
    login_states,
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
    reset_auth_tables(engine)
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


def test_denial_audit_has_shared_bounded_storage(store):
    for index in range(240):
        store.audit("access_denied", str(index), digest(str(index)))
        store.audit("login_failed", str(index))
    with store.engine.connect() as conn:
        assert not conn.execute(select(audit_events)).all()
    other = AuthStore(store.engine, config())
    counts = other.denial_counts()
    totals = {}
    for row in counts:
        totals[row["event"]] = totals.get(row["event"], 0) + row["occurrences"]
    assert totals == {
        "access_denied": 240, "login_failed": 240,
    }


def test_denial_counter_updates_are_atomic_across_connection_pools(store):
    other_engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    try:
        other = AuthStore(other_engine, config())
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(
                lambda index: (store if index % 2 else other).audit(
                    "access_denied", str(index), digest(str(index)),
                ),
                range(128),
            ))
        assert sum(row["occurrences"] for row in other.denial_counts()) == 128
        with store.engine.connect() as conn:
            assert not conn.execute(select(audit_events)).all()
    finally:
        other_engine.dispose()


def test_denial_ring_reuses_slots_and_expires_on_writes_and_owner_reads(store):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with store.transaction() as conn:
        store.record(conn, "logout", "old", now=start - timedelta(days=91))
        store.record(conn, "logout", "recent", now=start)
    for index in range(120):
        now = start + timedelta(minutes=15 * index)
        with store.transaction() as conn:
            for event in ("access_denied", "login_failed"):
                for _ in range(2):
                    store.record(conn, event, str(index), now=now)
    counts = store.denial_counts(now=now)
    assert len(counts) == 192
    assert all(row["occurrences"] == 2 for row in counts)
    assert all(row["window_start"] > now - timedelta(days=1) for row in counts)
    with store.engine.connect() as conn:
        assert conn.execute(select(audit_events.c.request_id)).scalars().all() == ["recent"]
    assert store.denial_counts(now=now + timedelta(days=1)) == []


@pytest.mark.parametrize("event,slot", [("client-controlled", 0), ("access_denied", 96)])
def test_denial_keys_are_bounded_by_database_constraints(store, event, slot):
    with pytest.raises(IntegrityError), store.transaction() as conn:
        conn.execute(denial_counters.insert().values(
            event=event, slot=slot, window_start=datetime.now(UTC), occurrences=1,
            last_request_id="request", last_occurred_at=datetime.now(UTC),
        ))


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


def test_idle_expiry_and_validation_only_checks_do_not_extend_session(store):
    handle, _ = store.create_session("owner", "request")
    initial = datetime.now(UTC)
    store.authenticate(handle, now=initial + timedelta(minutes=20), touch=False)
    with pytest.raises(AuthDenied):
        store.authenticate(handle, now=initial + timedelta(minutes=31))


def test_shared_login_limit_cannot_be_bypassed_by_new_browser_handles(store):
    for _ in range(30):
        store.start_login("nonce", "v" * 48, "request")
    other = AuthStore(store.engine, config())
    for _ in range(2):
        with pytest.raises(AuthDenied) as error:
            other.start_login("nonce", "v" * 48, "request")
        assert error.value.status == 429
    with store.engine.connect() as conn:
        assert len(conn.execute(select(login_states)).all()) == 30
