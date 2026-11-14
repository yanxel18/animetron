import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def migration_config():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def test_integrated_migrations_have_one_upgrade_target(migration_config):
    assert ScriptDirectory.from_config(migration_config).get_current_head() is not None


def test_upgraded_schema_matches_all_models(migration_config, monkeypatch):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    monkeypatch.setenv("ANIMETRON_DATABASE_URL", url)
    command.upgrade(migration_config, "head")
    command.check(migration_config)


def test_run_request_downgrade_reupgrade_preserves_existing_tables(migration_config, monkeypatch):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    monkeypatch.setenv("ANIMETRON_DATABASE_URL", url)
    command.upgrade(migration_config, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            before = set(inspect(conn).get_table_names())
            assert "workflow_run_requests" in before
        command.downgrade(migration_config, "p4_04a_review_queue_20261114")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) == before - {
                "workflow_run_requests", "workflow_execution_bindings",
            }
            assert conn.scalar(text("SELECT to_regprocedure('guard_workflow_run_request()')")) is None
            assert any(
                item["name"] == "ix_review_queue_created_id"
                for item in inspect(conn).get_indexes("review_requests")
            )
        command.upgrade(migration_config, "head")
        command.check(migration_config)
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) == before
    finally:
        engine.dispose()


def test_execution_binding_downgrade_removes_only_own_table_and_guard(migration_config, monkeypatch):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    monkeypatch.setenv("ANIMETRON_DATABASE_URL", url)
    command.upgrade(migration_config, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            before = set(inspect(conn).get_table_names())
            assert "workflow_execution_bindings" in before
        command.downgrade(migration_config, "p1_09a_run_requests")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) == before - {"workflow_execution_bindings"}
            assert conn.scalar(text("SELECT to_regprocedure('guard_workflow_execution_binding()')")) is None
        command.upgrade(migration_config, "head")
        command.check(migration_config)
    finally:
        engine.dispose()
