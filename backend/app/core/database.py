from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError


def create_database_engine(database_url: str) -> Engine:
    try:
        url = make_url(database_url)
    except ArgumentError:
        raise ValueError("A valid PostgreSQL database URL is required") from None

    if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
        raise ValueError("A PostgreSQL URL with the psycopg driver, host and database is required")

    return create_engine(url, pool_pre_ping=True, hide_parameters=True)
