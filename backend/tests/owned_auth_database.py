"""Destructive auth fixtures require a capability installed by our Docker harness."""

import hmac
import os
import re

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import audit_events, auth_rate, digest, login_states, sessions


def verify_owned_auth_database(conn: Connection) -> None:
    owner = os.environ.get("ANIMETRON_TEST_DATABASE_OWNER_ID", "")
    token = os.environ.get("ANIMETRON_TEST_DATABASE_OWNER_TOKEN", "")
    container = os.environ.get("ANIMETRON_TEST_DATABASE_CONTAINER_ID", "")
    refusal = "Refusing auth test reset: owned disposable database proof required"
    if (
        not re.fullmatch(r"[a-f0-9]{32}", owner)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
        or not re.fullmatch(r"[a-f0-9]{64}", container)
    ):
        raise RuntimeError(refusal)
    try:
        # The row lock keeps authority verification and deletion in one
        # transaction; a concurrent marker change cannot race a guarded reset.
        row = conn.execute(sa.text(
            "SELECT owner_id, token_hash, container_id, database_name, "
            "current_database() AS actual_database "
            "FROM animetron_oidc_test_guard.ownership WHERE singleton = true FOR SHARE"
        )).mappings().one_or_none()
    except SQLAlchemyError:
        raise RuntimeError(refusal) from None
    if (
        row is None or row["owner_id"] != owner or row["container_id"] != container
        or row["database_name"] != "animetron" or row["actual_database"] != "animetron"
        or not isinstance(row["token_hash"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", row["token_hash"])
        or not hmac.compare_digest(row["token_hash"], digest(token))
    ):
        raise RuntimeError(refusal)


def reset_auth_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("SET LOCAL statement_timeout = '3s'"))
        conn.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
        verify_owned_auth_database(conn)
        for table in (sessions, login_states, auth_rate, audit_events):
            conn.execute(table.delete())
