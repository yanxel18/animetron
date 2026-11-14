"""Only the harness-owned database is used, including foreign-marker cases."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from owned_auth_database import reset_auth_tables, verify_owned_auth_database

from app.core.auth import audit_events, digest
from app.core.database import create_database_engine


def test_auth_fixtures_delegate_destructive_resets_to_shared_guard():
    for name in ("test_auth_api.py", "test_auth_storage.py", "test_oidc_live.py"):
        source = Path(__file__).with_name(name).read_text(encoding="utf-8")
        assert "reset_auth_tables(engine)" in source
        assert "conn.execute(table.delete())" not in source


@pytest.mark.parametrize("proof", ["missing", "foreign_marker", "wrong_token"])
def test_rejected_database_ownership_preserves_owned_sentinel(monkeypatch, proof):
    engine = create_database_engine(os.environ["ANIMETRON_TEST_DATABASE_URL"])
    marker_hash = digest(os.environ["ANIMETRON_TEST_DATABASE_OWNER_TOKEN"])
    sentinel = secrets.token_hex(16)
    with engine.begin() as conn:
        verify_owned_auth_database(conn)
        conn.execute(audit_events.insert().values(
            event="websocket_authenticated", request_id=sentinel,
            occurred_at=sa.func.now(),
        ))
        if proof == "foreign_marker":
            conn.execute(sa.text(
                "UPDATE animetron_oidc_test_guard.ownership SET token_hash = :foreign"
            ), {"foreign": digest(secrets.token_urlsafe(32))})
    try:
        if proof == "missing":
            monkeypatch.delenv("ANIMETRON_TEST_DATABASE_OWNER_TOKEN")
        elif proof == "wrong_token":
            monkeypatch.setenv("ANIMETRON_TEST_DATABASE_OWNER_TOKEN", secrets.token_urlsafe(32))
        with pytest.raises(RuntimeError, match="Refusing auth test reset"):
            reset_auth_tables(engine)
        rejected_session = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/test_auth_api.py::test_auth_fixture_client_secret_is_not_embedded_in_source",
             "-q", "--tb=no", "-p", "no:cacheprovider"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, timeout=30, check=False,
        )
        assert rejected_session.returncode == pytest.ExitCode.USAGE_ERROR
        with engine.connect() as conn:
            assert conn.scalar(sa.select(sa.func.count()).select_from(audit_events).where(
                audit_events.c.request_id == sentinel,
            )) == 1
    finally:
        # This exact engine was proven owned above, before deliberately changing
        # its test marker. Restore only that marker and this fixture's sentinel.
        with engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE animetron_oidc_test_guard.ownership SET token_hash = :original"
            ), {"original": marker_hash})
            conn.execute(audit_events.delete().where(audit_events.c.request_id == sentinel))
        engine.dispose()
