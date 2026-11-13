"""Reject caller-provided database URLs before any test can mutate their data."""

import os

import pytest
from owned_auth_database import verify_owned_auth_database
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import create_database_engine


def pytest_sessionstart(session):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        return
    engine = None
    try:
        engine = create_database_engine(url)
        with engine.begin() as conn:
            verify_owned_auth_database(conn)
    except (RuntimeError, SQLAlchemyError, ValueError):
        raise pytest.UsageError(
            "Refusing auth test reset: use the owned disposable database harness"
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
