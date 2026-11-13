import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import create_database_engine


@pytest.mark.parametrize(
    "url",
    ["", "sqlite:///local.db", "not a database url", "postgresql+psycopg:///missing_host"],
)
def test_rejects_non_postgresql_configuration(url: str) -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_database_engine(url)


def test_engine_creation_does_not_connect() -> None:
    engine = create_database_engine("postgresql+psycopg://user:password@localhost/example")
    engine.dispose()


def test_transaction_commit_and_rollback_on_postgresql() -> None:
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")

    engine = create_database_engine(url)
    table = f"test_transaction_{uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE {table} (value integer NOT NULL)"))
            connection.execute(text(f"INSERT INTO {table} (value) VALUES (1)"))

        with engine.connect() as connection:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
            connection.execute(text(f"INSERT INTO {table} (value) VALUES (2)"))
            connection.rollback()
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()
