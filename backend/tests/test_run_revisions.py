import json
import os
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.exc import IntegrityError

from app.core.outbox import outbox
from app.services.workflows.revisions import (
    RevisionCorrupt,
    RevisionNotFound,
    revisions,
    save_revision,
)
from app.services.workflows.run_revisions import (
    RunRevisionNotFound,
    create_run_with_revision,
    get_run_snapshot,
)
from app.services.workflows.runs import RunNotFound, RunState, list_events
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


def save(conn, workflow_id):
    data = json.dumps(
        {
            "schemaVersion": 1,
            "revision": "rev1",
            "nodes": [{"id": "a", "type": "story", "config": {"prompt": "story"}}],
            "edges": [],
        }
    ).encode()
    return save_revision(conn, workflow_id, data, DEFINITIONS, LIMITS, max_bytes=4096)


def test_run_binds_stored_revision_without_dispatch(engine) -> None:
    workflow_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        snapshot = save(conn, workflow_id)
        create_run_with_revision(conn, run_id, workflow_id, "rev1")
    with engine.connect() as conn:
        assert get_run_snapshot(conn, run_id) == snapshot
        assert [event.state for event in list_events(conn, run_id, 0)] == [
            RunState.QUEUED
        ]
        assert (
            conn.scalar(select(outbox.c.id).where(outbox.c.resource_id == run_id))
            is None
        )


def test_missing_revision_does_not_create_run(engine) -> None:
    workflow_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        with pytest.raises(RevisionNotFound):
            create_run_with_revision(conn, run_id, workflow_id, "missing")
        with pytest.raises(RunNotFound):
            list_events(conn, run_id, 0)
        with pytest.raises(RunRevisionNotFound):
            get_run_snapshot(conn, run_id)


def test_run_and_binding_roll_back_together(engine) -> None:
    workflow_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id)
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        create_run_with_revision(conn, run_id, workflow_id, "rev1")
        raise RuntimeError("abort")
    with engine.connect() as conn:
        with pytest.raises(RunNotFound):
            list_events(conn, run_id, 0)
        with pytest.raises(RunRevisionNotFound):
            get_run_snapshot(conn, run_id)


def test_corrupt_revision_does_not_create_run(engine) -> None:
    workflow_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id)
        conn.execute(
            update(revisions)
            .where(revisions.c.workflow_id == workflow_id)
            .values(document=b"corrupted")
        )
    with engine.begin() as conn:
        with pytest.raises(RevisionCorrupt):
            create_run_with_revision(conn, run_id, workflow_id, "rev1")
        with pytest.raises(RunNotFound):
            list_events(conn, run_id, 0)


def test_referenced_revision_cannot_be_deleted(engine) -> None:
    workflow_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        save(conn, workflow_id)
        create_run_with_revision(conn, run_id, workflow_id, "rev1")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(delete(revisions).where(revisions.c.workflow_id == workflow_id))


def test_run_creation_requires_transaction(engine) -> None:
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        create_run_with_revision(conn, uuid4(), uuid4(), "rev1")
