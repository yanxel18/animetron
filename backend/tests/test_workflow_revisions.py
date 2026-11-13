import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, update

from app.services.workflows.revisions import (
    RevisionConflict,
    RevisionCorrupt,
    RevisionNotFound,
    get_revision,
    revisions,
    save_revision,
)
from app.services.workflows.snapshot import InvalidWorkflowGraph
from app.services.workflows.validation import GraphLimits, NodeDefinition


class StoryConfig(BaseModel):
    prompt: str


DEFINITIONS = {"story": NodeDefinition(config_model=StoryConfig)}
LIMITS = GraphLimits(max_nodes=10, max_edges=10)


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_engine(url)
    yield engine
    engine.dispose()


def workflow(revision: str, prompt: object = "story") -> bytes:
    return json.dumps(
        {
            "schemaVersion": 1,
            "revision": revision,
            "nodes": [{"id": "a", "type": "story", "config": {"prompt": prompt}}],
            "edges": [],
        }
    ).encode()


def save(conn, workflow_id, data):
    return save_revision(conn, workflow_id, data, DEFINITIONS, LIMITS, max_bytes=4096)


def test_save_replay_idempotency_and_conflict(engine) -> None:
    workflow_id = uuid4()
    with engine.begin() as conn:
        original = save(conn, workflow_id, workflow("rev1"))
        assert save(conn, workflow_id, workflow("rev1")) == original
        with pytest.raises(RevisionConflict):
            save(conn, workflow_id, workflow("rev1", "changed"))
        other = save(conn, workflow_id, workflow("rev2"))
        assert other.sha256 != original.sha256
    with engine.connect() as conn:
        assert get_revision(conn, workflow_id, "rev1") == original
        assert get_revision(conn, workflow_id, "rev2") == other
        with pytest.raises(RevisionNotFound):
            get_revision(conn, uuid4(), "rev1")


def test_transaction_rollback_and_invalid_graph_do_not_save(engine) -> None:
    workflow_id = uuid4()
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        save(conn, workflow_id, workflow("rev1"))
        raise RuntimeError("abort")
    with engine.begin() as conn:
        with pytest.raises(InvalidWorkflowGraph):
            save(conn, workflow_id, workflow("rev2", 7))
        with pytest.raises(RevisionNotFound):
            get_revision(conn, workflow_id, "rev1")
        with pytest.raises(RevisionNotFound):
            get_revision(conn, workflow_id, "rev2")


def test_corrupt_content_is_rejected_on_read(engine) -> None:
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, workflow("rev1"))
        conn.execute(
            update(revisions)
            .where(revisions.c.workflow_id == workflow_id)
            .values(document=b"corrupted")
        )
    with engine.connect() as conn, pytest.raises(RevisionCorrupt):
        get_revision(conn, workflow_id, "rev1")


def test_corrupt_revision_key_is_rejected_on_read(engine) -> None:
    workflow_id = uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id, workflow("rev1"))
        conn.execute(
            update(revisions)
            .where(revisions.c.workflow_id == workflow_id)
            .values(revision="different")
        )
    with engine.connect() as conn, pytest.raises(RevisionCorrupt):
        get_revision(conn, workflow_id, "different")


def test_invalid_stored_document_is_rejected_even_with_matching_digest(engine) -> None:
    workflow_id = uuid4()
    invalid = b"not-json"
    with engine.begin() as conn:
        save(conn, workflow_id, workflow("rev1"))
        conn.execute(
            update(revisions)
            .where(revisions.c.workflow_id == workflow_id)
            .values(document=invalid, sha256=hashlib.sha256(invalid).hexdigest())
        )
    with engine.connect() as conn, pytest.raises(RevisionCorrupt):
        get_revision(conn, workflow_id, "rev1")


def test_concurrent_different_content_has_exactly_one_winner(engine) -> None:
    workflow_id = uuid4()
    barrier = Barrier(2)

    def attempt(prompt):
        try:
            with engine.begin() as conn:
                barrier.wait(timeout=5)
                save(conn, workflow_id, workflow("rev1", prompt))
            return "saved"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["first", "second"])) == ["conflict", "saved"]


def test_concurrent_identical_writes_are_idempotent(engine) -> None:
    workflow_id = uuid4()
    barrier = Barrier(2)

    def attempt(_):
        with engine.begin() as conn:
            barrier.wait(timeout=5)
            return save(conn, workflow_id, workflow("rev1"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshots = list(pool.map(attempt, range(2)))
    assert snapshots[0] == snapshots[1]


def test_writes_require_explicit_transaction(engine) -> None:
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        save(conn, uuid4(), workflow("rev1"))
