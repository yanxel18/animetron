import hashlib
import importlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from queue import Queue
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from test_execution_snapshot import LIMITS, MANIFEST, catalog, document

from app.core.outbox import outbox
from app.services.workflows.execution_snapshot import (
    HandlerArtifact,
    create_execution_snapshot,
)
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    revisions,
    save_revision,
)
from app.services.workflows.run_revisions import run_revisions
from app.services.workflows.runs import events, runs


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the owned disposable database harness")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def bindings():
    return importlib.import_module("app.services.workflows.execution_bindings")


def save(conn, workflow_id):
    selected = catalog()
    return save_revision(
        conn, workflow_id, json.dumps(document()).encode(),
        {name: entry.definition for name, entry in selected.items()},
        LIMITS, max_bytes=100_000,
    )


def bind(service, conn, workflow_id, sha, selected=None, max_bytes=100_000):
    return service.bind_execution_snapshot(
        conn, workflow_id, "r1", sha, catalog() if selected is None else selected,
        LIMITS, max_bytes=max_bytes,
    )


def effects(conn):
    return tuple(conn.scalar(select(func.count()).select_from(table))
                 for table in (runs, events, run_revisions, outbox))


def test_bind_checked_source_and_exact_retry(engine, bindings):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        before = effects(conn)
        first = bind(bindings, conn, workflow_id, source.sha256)
        assert first.workflow_id == workflow_id
        assert first.revision == "r1"
        assert first.source_sha256 == source.sha256
        expected = create_execution_snapshot(source.canonical_json, catalog(), LIMITS, max_bytes=100_000)
        assert first.execution_bytes == expected.canonical_json
        assert first.execution_sha256 == expected.sha256
        assert first.created_at.utcoffset().total_seconds() == 0
        with pytest.raises(FrozenInstanceError):
            first.revision = "changed"
        assert bind(bindings, conn, workflow_id, source.sha256) == first
        assert bindings.get_execution_binding(conn, workflow_id, "r1") == first
        assert conn.scalar(select(func.count()).select_from(bindings.bindings).where(
            bindings.bindings.c.workflow_id == workflow_id,
        )) == 1
        assert effects(conn) == before


@pytest.mark.parametrize("change", ["default", "config", "handler", "model"])
def test_catalog_drift_conflicts_but_load_preserves_bytes(engine, bindings, change):
    class Changed(BaseModel):
        prompt: str = "different"
        steps: int = 4
        enabled: bool = True
        options: dict[str, list[int]] = {"weights": [1, 2]}

    class ChangedAlias(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        prompt: str = "hello"
        steps: int = Field(4, serialization_alias="differentSteps")
        enabled: bool = True
        options: dict[str, list[int]] = {"weights": [1, 2]}

    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        first = bind(bindings, conn, workflow_id, source.sha256)
        selected = catalog()
        if change == "default":
            selected = catalog(Changed)
        elif change == "config":
            selected = catalog(ChangedAlias)
        elif change == "handler":
            selected["story"] = replace(selected["story"], handler=HandlerArtifact("other", "d" * 64))
        else:
            selected["story"] = replace(selected["story"], models=(replace(MANIFEST, engine="other"),))
        with pytest.raises(bindings.ExecutionBindingConflict):
            bind(bindings, conn, workflow_id, source.sha256, selected)
        assert bindings.get_execution_binding(conn, workflow_id, "r1") == first


@pytest.mark.parametrize("failure", ["missing", "digest", "corrupt"])
def test_bad_source_does_not_claim_and_outer_transaction_survives(engine, bindings, failure):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        if failure == "corrupt":
            conn.execute(update(revisions).where(revisions.c.workflow_id == workflow_id)
                         .values(document=b"corrupt"))
        exc = {"missing": RevisionNotFound, "digest": bindings.ExecutionBindingConflict,
               "corrupt": RevisionCorrupt}[failure]
        with pytest.raises(exc):
            bindings.bind_execution_snapshot(
                conn, workflow_id, "missing" if failure == "missing" else "r1",
                "0" * 64 if failure == "digest" else source.sha256,
                catalog(), LIMITS, max_bytes=100_000,
            )
        assert conn.scalar(select(func.count()).select_from(bindings.bindings).where(
            bindings.bindings.c.workflow_id == workflow_id,
        )) == 0
        assert conn.scalar(text("SELECT 1")) == 1


def test_unbound_legacy_revision_is_not_promoted(engine, bindings):
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id)
        with pytest.raises(bindings.ExecutionBindingNotFound):
            bindings.get_execution_binding(conn, workflow_id, "r1")


def test_source_changed_with_valid_new_hash_is_detected_on_load(engine, bindings):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        bind(bindings, conn, workflow_id, source.sha256)
        changed = source.canonical_json + b" "
        conn.execute(update(revisions).where(revisions.c.workflow_id == workflow_id).values(
            document=changed, sha256=hashlib.sha256(changed).hexdigest(),
        ))
        with pytest.raises(bindings.ExecutionBindingCorrupt):
            bindings.get_execution_binding(conn, workflow_id, "r1")
        with pytest.raises(bindings.ExecutionBindingCorrupt):
            bind(bindings, conn, workflow_id, hashlib.sha256(changed).hexdigest())


@pytest.mark.parametrize("column", ["execution_bytes", "execution_sha256", "source_sha256"])
def test_corrupt_binding_fails_without_repair(engine, bindings, column):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        bind(bindings, conn, workflow_id, source.sha256)
        conn.execute(text("ALTER TABLE workflow_execution_bindings DISABLE TRIGGER "
                          "workflow_execution_binding_immutable"))
        conn.execute(update(bindings.bindings).where(bindings.bindings.c.workflow_id == workflow_id)
                     .values(**{column: b"bad" if column == "execution_bytes" else "0" * 64}))
        conn.execute(text("ALTER TABLE workflow_execution_bindings ENABLE TRIGGER "
                          "workflow_execution_binding_immutable"))
        with pytest.raises(bindings.ExecutionBindingCorrupt):
            bindings.get_execution_binding(conn, workflow_id, "r1")
        with pytest.raises(bindings.ExecutionBindingCorrupt):
            bind(bindings, conn, workflow_id, source.sha256)


@pytest.mark.parametrize("field,value", [
    ("kind", "other"), ("revision", "other"), ("schemaVersion", True),
])
def test_checked_load_rejects_wrong_execution_association(engine, bindings, field, value):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        first = bind(bindings, conn, workflow_id, source.sha256)
        payload = json.loads(first.execution_bytes)
        payload[field] = value
        data = json.dumps(payload).encode()
        conn.execute(text("ALTER TABLE workflow_execution_bindings DISABLE TRIGGER "
                          "workflow_execution_binding_immutable"))
        conn.execute(update(bindings.bindings).where(bindings.bindings.c.workflow_id == workflow_id)
                     .values(execution_bytes=data, execution_sha256=hashlib.sha256(data).hexdigest()))
        conn.execute(text("ALTER TABLE workflow_execution_bindings ENABLE TRIGGER "
                          "workflow_execution_binding_immutable"))
        with pytest.raises(bindings.ExecutionBindingCorrupt):
            bindings.get_execution_binding(conn, workflow_id, "r1")


def test_immutable_database_guard_and_real_outer_rollback(engine, bindings):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        first = bind(bindings, conn, workflow_id, source.sha256)
        for statement in (update(bindings.bindings).values(execution_sha256="0" * 64),
                          delete(bindings.bindings)):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(statement.where(bindings.bindings.c.workflow_id == workflow_id))
        assert bindings.get_execution_binding(conn, workflow_id, "r1") == first
    other = uuid4()
    with engine.begin() as conn:
        other_source = save(conn, other)
    with pytest.raises(SQLAlchemyError), engine.begin() as conn:
        bind(bindings, conn, other, other_source.sha256)
        conn.execute(text("SELECT 1 / 0"))
    with engine.begin() as conn, pytest.raises(bindings.ExecutionBindingNotFound):
        bindings.get_execution_binding(conn, other, "r1")


def test_real_late_sql_error_preserves_outer_transaction(engine, bindings):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        conn.execute(text("""
            CREATE FUNCTION pg_temp.reject_binding() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test rejection' USING ERRCODE = '23514'; END; $$
        """))
        conn.execute(text("CREATE TRIGGER test_reject_binding AFTER INSERT ON "
                          "workflow_execution_bindings FOR EACH ROW "
                          "EXECUTE FUNCTION pg_temp.reject_binding()"))
        with pytest.raises(IntegrityError):
            bind(bindings, conn, workflow_id, source.sha256)
        assert conn.scalar(text("SELECT 1")) == 1
        conn.execute(text("DROP TRIGGER test_reject_binding ON workflow_execution_bindings"))
    with engine.begin() as conn:
        assert conn.scalar(select(revisions.c.workflow_id).where(
            revisions.c.workflow_id == workflow_id,
        )) == workflow_id
        with pytest.raises(bindings.ExecutionBindingNotFound):
            bindings.get_execution_binding(conn, workflow_id, "r1")


@pytest.mark.parametrize("different", [False, True])
def test_unique_insert_blocks_concurrent_contender(engine, bindings, different):
    workflow_id = uuid4()
    with engine.begin() as conn:
        source = save(conn, workflow_id)
        before = effects(conn)
    pid_queue = Queue()

    def contender():
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            pid_queue.put(conn.scalar(text("SELECT pg_backend_pid()")))
            selected = catalog()
            if different:
                selected["story"] = replace(
                    selected["story"], handler=HandlerArtifact("other", "d" * 64),
                )
            try:
                return bind(bindings, conn, workflow_id, source.sha256, selected)
            except bindings.ExecutionBindingConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=1) as pool, engine.connect() as winner:
        transaction = winner.begin()
        try:
            winner_pid = winner.scalar(text("SELECT pg_backend_pid()"))
            first = bind(bindings, winner, workflow_id, source.sha256)
            future = pool.submit(contender)
            pid = pid_queue.get(timeout=5)
            deadline = time.monotonic() + 5
            with engine.connect() as observer:
                while time.monotonic() < deadline:
                    if winner_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Contender never waited for the unique-key winner")
            assert not future.done()
            transaction.commit()
        finally:
            if transaction.is_active:
                transaction.rollback()
        assert future.result(timeout=10) == ("conflict" if different else first)
    with engine.begin() as conn:
        assert effects(conn) == before
        assert conn.scalar(select(func.count()).select_from(bindings.bindings).where(
            bindings.bindings.c.workflow_id == workflow_id,
        )) == 1


@pytest.mark.parametrize("field,value,error", [
    ("workflow_id", "not-a-uuid", TypeError), ("revision", 1, TypeError),
    ("revision", " ", ValueError), ("revision", "x" * 129, ValueError),
    ("expected_sha256", 1, TypeError), ("expected_sha256", "F" * 64, ValueError),
    ("expected_sha256", "0" * 63, ValueError), ("max_bytes", 0, ValueError),
    ("max_bytes", True, ValueError),
])
def test_input_guards(engine, bindings, field, value, error):
    values = {"workflow_id": uuid4(), "revision": "r1", "expected_sha256": "0" * 64,
              "catalog": catalog(), "limits": LIMITS, "max_bytes": 100_000}
    values[field] = value
    with engine.begin() as conn:
        with pytest.raises(error):
            bindings.bind_execution_snapshot(conn, **values)
        assert conn.scalar(text("SELECT 1")) == 1


def test_requires_explicit_non_autocommit_psycopg(engine, bindings):
    args = (uuid4(), "r1", "0" * 64, catalog(), LIMITS)
    with engine.connect() as conn, pytest.raises(RuntimeError):
        bindings.bind_execution_snapshot(conn, *args, max_bytes=100_000)
    with engine.connect() as conn, pytest.raises(RuntimeError):
        bindings.get_execution_binding(conn, args[0], args[1])
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(),
        pytest.raises(RuntimeError),
    ):
        bindings.bind_execution_snapshot(conn, *args, max_bytes=100_000)
    sqlite = create_engine("sqlite://")
    try:
        with sqlite.begin() as conn, pytest.raises(RuntimeError):
            bindings.bind_execution_snapshot(conn, *args, max_bytes=100_000)
    finally:
        sqlite.dispose()
