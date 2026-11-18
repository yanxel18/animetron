import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, insert
from test_execution_bindings import bind, save
from test_execution_snapshot import LIMITS, MANIFEST

from app.services.models.manifest import ModelFile, ModelManifest
from app.services.models.reference import ModelReference
from app.services.workflows import execution_bindings, execution_readiness
from app.services.workflows import run_requests as requests
from app.services.workflows.execution_bindings import ExecutionBinding
from app.services.workflows.execution_readiness import ReadyModel, ResolvedHandler
from app.services.workflows.run_requests import run_requests
from app.services.workflows.run_revisions import run_revisions
from app.services.workflows.runs import (
    RunState,
    create_run,
    get_run_status,
    list_events,
)
from app.services.workflows.validation import GraphLimits


class HandlerCatalog:
    def __init__(self, handler: ResolvedHandler | None) -> None:
        self.handler = handler
        self.calls: list[str] = []

    def resolve(self, artifact_id: str) -> ResolvedHandler | None:
        self.calls.append(artifact_id)
        if self.handler is None or self.handler.artifact_id != artifact_id:
            return None
        return self.handler


class ModelRegistry:
    def __init__(self, model: ReadyModel | None) -> None:
        self.model = model

    def resolve(self, manifest: ModelManifest) -> ReadyModel | None:
        if self.model is None:
            return None
        return self.model


def _manifest() -> ModelManifest:
    return ModelManifest(
        ModelReference("huggingface", "studio/sample", "a" * 40),
        "ollama",
        "approved-license",
        (ModelFile("model.gguf", 4, "b" * 64),),
        4,
    )


def _binding(
    workflow_id,
    revision: str,
    manifest: ModelManifest,
    node_ids: tuple[str, ...] = ("node-1",),
    edges: tuple[tuple[str, str], ...] = (),
) -> ExecutionBinding:
    source_sha256 = "c" * 64
    document = {
        "kind": "internal.workflow-execution",
        "schemaVersion": 1,
        "revision": revision,
        "nodes": [
            {"id": node_id, "type": "sample.node", "config": {}} for node_id in node_ids
        ],
        "edges": [
            {
                "id": f"edge-{index}",
                "source": source,
                "sourcePort": "text",
                "target": target,
                "targetPort": "text",
            }
            for index, (source, target) in enumerate(edges)
        ],
        "nodePins": {
            node_id: {
                "handler": {
                    "artifactId": f"handler-v{node_id[-1]}",
                    "sha256": "d" * 64,
                },
                "pinnedModelManifest": [asdict(manifest)],
            }
            for node_id in node_ids
        },
    }
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return ExecutionBinding(
        workflow_id,
        revision,
        source_sha256,
        data,
        hashlib.sha256(data).hexdigest(),
        datetime.now(UTC),
    )


@pytest.fixture
def queued_run():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    from app.services.workflows.runs import metadata as run_metadata

    run_metadata.create_all(engine)
    test_metadata = MetaData()
    Table(
        "workflow_run_requests",
        test_metadata,
        Column("request_id", Uuid),
        Column("run_id", Uuid),
        Column("workflow_id", Uuid),
        Column("revision", String(128)),
        Column("sha256", String(64)),
    )
    Table(
        "workflow_run_revisions",
        test_metadata,
        Column("run_id", Uuid),
        Column("workflow_id", Uuid),
        Column("revision", String(128)),
    )
    test_metadata.create_all(engine)

    run_id, request_id, workflow_id = uuid4(), uuid4(), uuid4()
    revision = "r1"
    source_sha256 = "c" * 64
    with engine.begin() as connection:
        create_run(connection, run_id)
        connection.execute(
            insert(run_requests).values(
                request_id=request_id,
                run_id=run_id,
                workflow_id=workflow_id,
                revision=revision,
                sha256=source_sha256,
            )
        )
        connection.execute(
            insert(run_revisions).values(
                run_id=run_id,
                workflow_id=workflow_id,
                revision=revision,
            )
        )
    yield engine, run_id, workflow_id, revision
    engine.dispose()


def test_preflight_returns_only_exact_ready_handler_and_model_handles(
    queued_run, monkeypatch
):
    engine, run_id, workflow_id, revision = queued_run
    manifest = _manifest()
    binding = _binding(workflow_id, revision, manifest)
    handler_handle, model_handle = object(), object()
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            HandlerCatalog(ResolvedHandler("handler-v1", "d" * 64, handler_handle)),
            ModelRegistry(ReadyModel(manifest, model_handle)),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is True
    assert result.failure_code is None
    assert result.handlers[0][0] == "node-1"
    assert result.handlers[0][1].handle is handler_handle
    assert result.models[0][0] == "node-1"
    assert result.models[0][2].handle is model_handle
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.QUEUED
        assert [event.state for event in list_events(connection, run_id, 0)] == [
            RunState.QUEUED
        ]


@pytest.mark.parametrize("binding_exists", [True, False])
def test_preflight_loads_persisted_binding_on_postgresql(binding_exists):
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_engine(url)
    workflow_id = uuid4()
    handler = object()
    model = object()
    try:
        with engine.begin() as connection:
            snapshot = save(connection, workflow_id)
            if binding_exists:
                bind(execution_bindings, connection, workflow_id, snapshot.sha256)
            request = requests.request_run(
                connection, uuid4(), workflow_id, "r1", snapshot.sha256,
            )
        catalog = HandlerCatalog(ResolvedHandler("story-handler", "c" * 64, handler))
        with engine.begin() as connection:
            result = execution_readiness.preflight_run(
                connection, request.run_id, catalog,
                ModelRegistry(ReadyModel(MANIFEST, model)), LIMITS, max_bytes=100_000,
            )
        with engine.connect() as connection:
            status = get_run_status(connection, request.run_id)
            events = list_events(connection, request.run_id, 0)
    finally:
        engine.dispose()

    if binding_exists:
        assert result.ready
        assert result.failure_code is None
        assert result.handlers[0][1].handle is handler
        assert result.models[0][2].handle is model
        assert status.state is RunState.QUEUED
        assert [event.state for event in events] == [RunState.QUEUED]
        assert catalog.calls == ["story-handler"]
    else:
        assert not result.ready
        assert (
            result.failure_code
            is execution_readiness.ReadinessFailureCode.EXECUTION_BINDING_NOT_FOUND
        )
        assert result.handlers == result.models == ()
        assert status.state is RunState.FAILED
        assert [event.state for event in events] == [RunState.QUEUED, RunState.FAILED]
        assert catalog.calls == []


def test_preflight_returns_node_dependencies_in_snapshot_order(
    queued_run, monkeypatch
):
    engine, run_id, workflow_id, revision = queued_run
    binding = _binding(
        workflow_id,
        revision,
        _manifest(),
        ("node-1", "node-2", "node-3"),
        (("node-2", "node-3"), ("node-1", "node-3")),
    )
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )

    class AllHandlers:
        def resolve(self, artifact_id: str) -> ResolvedHandler:
            return ResolvedHandler(artifact_id, "d" * 64, object())

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            AllHandlers(),
            ModelRegistry(ReadyModel(_manifest(), object())),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is True
    assert result.node_dependencies == (
        ("node-1", ()),
        ("node-2", ()),
        ("node-3", ("node-1", "node-2")),
    )


def test_preflight_fails_run_when_handler_digest_does_not_match(
    queued_run, monkeypatch
):
    engine, run_id, workflow_id, revision = queued_run
    binding = _binding(workflow_id, revision, _manifest())
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            HandlerCatalog(ResolvedHandler("handler-v1", "e" * 64, object())),
            ModelRegistry(None),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is False
    assert (
        result.failure_code
        is execution_readiness.ReadinessFailureCode.HANDLER_PIN_MISMATCH
    )
    assert result.handlers == ()
    assert result.models == ()
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.FAILED
        events = list_events(connection, run_id, 0)
        assert events[-1].message == "Execution readiness failed: HANDLER_PIN_MISMATCH"


@pytest.mark.parametrize(
    ("model_mismatch", "expected_code"),
    [
        (False, execution_readiness.ReadinessFailureCode.MODEL_NOT_READY),
        (True, execution_readiness.ReadinessFailureCode.MODEL_PIN_MISMATCH),
    ],
)
def test_preflight_fails_run_when_model_is_missing_or_changed(
    queued_run, monkeypatch, model_mismatch, expected_code
):
    engine, run_id, workflow_id, revision = queued_run
    manifest = _manifest()
    binding = _binding(workflow_id, revision, manifest)
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )
    model = (
        ReadyModel(replace(manifest, engine="other-engine"), object())
        if model_mismatch
        else None
    )

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            HandlerCatalog(ResolvedHandler("handler-v1", "d" * 64, object())),
            ModelRegistry(model),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is False
    assert result.failure_code is expected_code
    assert result.handlers == ()
    assert result.models == ()
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.FAILED


def test_unready_later_node_returns_no_partial_handles(queued_run, monkeypatch):
    engine, run_id, workflow_id, revision = queued_run
    binding = _binding(workflow_id, revision, _manifest(), ("node-1", "node-2"))
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )
    catalog = HandlerCatalog(ResolvedHandler("handler-v1", "d" * 64, object()))
    manifest = _manifest()

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            catalog,
            ModelRegistry(ReadyModel(manifest, object())),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is False
    assert (
        result.failure_code
        is execution_readiness.ReadinessFailureCode.HANDLER_NOT_READY
    )
    assert result.handlers == ()
    assert result.models == ()
    assert catalog.calls == ["handler-v1", "handler-v2"]
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.FAILED


def test_preflight_fails_run_for_invalid_persisted_execution_document(
    queued_run, monkeypatch
):
    engine, run_id, workflow_id, revision = queued_run
    valid_binding = _binding(workflow_id, revision, _manifest())
    invalid_bytes = b"{}"
    binding = replace(
        valid_binding,
        execution_bytes=invalid_bytes,
        execution_sha256=hashlib.sha256(invalid_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        execution_readiness,
        "get_execution_binding",
        lambda *_args: binding,
        raising=False,
    )
    catalog = HandlerCatalog(None)

    with engine.begin() as connection:
        result = execution_readiness.preflight_run(
            connection,
            run_id,
            catalog,
            ModelRegistry(None),
            GraphLimits(max_nodes=8, max_edges=8),
            max_bytes=4096,
        )

    assert result.ready is False
    assert (
        result.failure_code
        is execution_readiness.ReadinessFailureCode.EXECUTION_DOCUMENT_INVALID
    )
    assert catalog.calls == []
    with engine.connect() as connection:
        assert get_run_status(connection, run_id).state is RunState.FAILED
