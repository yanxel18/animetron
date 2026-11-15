import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from app.core.database import create_database_engine
from app.services.workflows.drafts import (
    WorkflowDraftConflict,
    WorkflowDraftNotFound,
    drafts,
    get_draft,
    save_draft,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    engine = create_database_engine(url) if url else create_engine("sqlite://")
    drafts.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.begin() as connection:
        yield connection


def test_draft_persists_exact_incomplete_document_bytes(connection: Connection) -> None:
    workflow_id = uuid4()
    document = b'{"schemaVersion":1,"nodes":['

    saved = save_draft(
        connection, workflow_id, document, expected_version=None, max_bytes=4096
    )

    assert saved.workflow_id == workflow_id
    assert saved.document == document
    assert saved.version == 1
    assert get_draft(connection, workflow_id) == saved


def test_draft_update_requires_current_version_and_preserves_winner(
    connection: Connection,
) -> None:
    workflow_id = uuid4()
    first = save_draft(
        connection, workflow_id, b"first", expected_version=None, max_bytes=4096
    )

    second = save_draft(
        connection, workflow_id, b"second", expected_version=first.version, max_bytes=4096
    )
    with pytest.raises(WorkflowDraftConflict):
        save_draft(
            connection, workflow_id, b"stale", expected_version=first.version, max_bytes=4096
        )

    assert second.version == 2
    assert get_draft(connection, workflow_id) == second


def test_concurrent_updates_have_one_compare_and_swap_winner(
    engine: Engine,
) -> None:
    if not os.environ.get("ANIMETRON_TEST_DATABASE_URL"):
        pytest.skip("Concurrent draft updates require the owned PostgreSQL harness")

    workflow_id = uuid4()
    with engine.begin() as connection:
        save_draft(
            connection, workflow_id, b"initial", expected_version=None, max_bytes=4096
        )
    barrier = Barrier(2)

    def update(document: bytes) -> str:
        try:
            with engine.begin() as connection:
                barrier.wait(timeout=5)
                save_draft(
                    connection,
                    workflow_id,
                    document,
                    expected_version=1,
                    max_bytes=4096,
                )
            return "saved"
        except WorkflowDraftConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, (b"first", b"second")))

    assert outcomes.count("saved") == 1
    assert outcomes.count("conflict") == 1
    with engine.connect() as connection:
        assert get_draft(connection, workflow_id).version == 2


def test_create_conflict_and_missing_draft_are_explicit(
    connection: Connection,
) -> None:
    workflow_id = uuid4()
    save_draft(connection, workflow_id, b"first", expected_version=None, max_bytes=4096)

    with pytest.raises(WorkflowDraftConflict):
        save_draft(connection, workflow_id, b"second", expected_version=None, max_bytes=4096)
    with pytest.raises(WorkflowDraftNotFound):
        get_draft(connection, uuid4())


def test_draft_rejects_invalid_utf8_and_oversized_content(connection: Connection) -> None:
    workflow_id = uuid4()

    with pytest.raises(ValueError, match="UTF-8"):
        save_draft(
            connection, workflow_id, b"\xff", expected_version=None, max_bytes=4096
        )
    with pytest.raises(ValueError, match="byte limit"):
        save_draft(
            connection, workflow_id, b"12345", expected_version=None, max_bytes=4
        )
    with pytest.raises(WorkflowDraftNotFound):
        get_draft(connection, workflow_id)


def test_draft_writes_require_an_explicit_transaction() -> None:
    engine = create_engine("sqlite://")
    drafts.metadata.create_all(engine)
    try:
        with engine.connect() as connection, pytest.raises(RuntimeError, match="transaction"):
            save_draft(
                connection, uuid4(), b"draft", expected_version=None, max_bytes=4096
            )
    finally:
        engine.dispose()


def test_draft_write_rolls_back_with_the_callers_transaction(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("Caller transaction rollback is verified by PostgreSQL")

    workflow_id = uuid4()

    with pytest.raises(RuntimeError, match="abort"), engine.begin() as connection:
        save_draft(
            connection, workflow_id, b"draft", expected_version=None, max_bytes=4096
        )
        raise RuntimeError("abort")

    with engine.connect() as connection, pytest.raises(WorkflowDraftNotFound):
        get_draft(connection, workflow_id)
