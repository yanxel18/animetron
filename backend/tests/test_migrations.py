import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


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
