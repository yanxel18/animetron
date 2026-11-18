"""Fail-closed preflight for persisted workflow execution pins."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.services.models.manifest import ModelFile, ModelManifest
from app.services.models.reference import ModelReference
from app.services.workflows.execution_bindings import (
    ExecutionBinding,
    ExecutionBindingCorrupt,
    ExecutionBindingNotFound,
    get_execution_binding,
)
from app.services.workflows.execution_snapshot import HandlerArtifact
from app.services.workflows.run_requests import run_requests
from app.services.workflows.run_revisions import run_revisions
from app.services.workflows.runs import (
    RunConflict,
    RunNotFound,
    RunState,
    RunStatus,
    runs,
    transition_run,
)
from app.services.workflows.validation import GraphLimits


class ReadinessFailureCode(StrEnum):
    RUN_BINDING_INVALID = "RUN_BINDING_INVALID"
    EXECUTION_BINDING_NOT_FOUND = "EXECUTION_BINDING_NOT_FOUND"
    EXECUTION_BINDING_CORRUPT = "EXECUTION_BINDING_CORRUPT"
    EXECUTION_DOCUMENT_INVALID = "EXECUTION_DOCUMENT_INVALID"
    HANDLER_NOT_READY = "HANDLER_NOT_READY"
    HANDLER_PIN_MISMATCH = "HANDLER_PIN_MISMATCH"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    MODEL_PIN_MISMATCH = "MODEL_PIN_MISMATCH"


@dataclass(frozen=True)
class ResolvedHandler:
    artifact_id: str
    sha256: str
    handle: object

    def __post_init__(self) -> None:
        HandlerArtifact(self.artifact_id, self.sha256)
        if self.handle is None:
            raise ValueError("A verified handler handle is required")


@dataclass(frozen=True)
class ReadyModel:
    manifest: ModelManifest
    handle: object

    def __post_init__(self) -> None:
        if type(self.manifest) is not ModelManifest or self.handle is None:
            raise ValueError("A ready model handle and manifest are required")


class HandlerCatalog(Protocol):
    def resolve(self, artifact_id: str) -> ResolvedHandler | None: ...


class ModelRegistry(Protocol):
    def resolve(self, manifest: ModelManifest) -> ReadyModel | None: ...


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    failure_code: ReadinessFailureCode | None = None
    handlers: tuple[tuple[str, ResolvedHandler], ...] = ()
    models: tuple[tuple[str, int, ReadyModel], ...] = ()


@dataclass(frozen=True)
class _NodePins:
    node_id: str
    handler: HandlerArtifact
    models: tuple[ModelManifest, ...]


class _InvalidExecutionDocument(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidExecutionDocument("Duplicate execution document key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _InvalidExecutionDocument("Non-finite execution document number")


def _object(value: object, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _InvalidExecutionDocument("Invalid execution document object")
    return cast(Mapping[str, object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise _InvalidExecutionDocument("Invalid execution document string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise _InvalidExecutionDocument("Invalid execution document integer")
    return value


def _model_manifest(value: object) -> ModelManifest:
    data = _object(
        value,
        {"reference", "engine", "license_id", "files", "estimated_bytes"},
    )
    reference = _object(data["reference"], {"provider", "repository", "revision"})
    raw_files = data["files"]
    if type(raw_files) is not list:
        raise _InvalidExecutionDocument("Invalid pinned model files")
    try:
        return ModelManifest(
            ModelReference(
                _string(reference["provider"]),
                _string(reference["repository"]),
                _string(reference["revision"]),
            ),
            _string(data["engine"]),
            _string(data["license_id"]),
            tuple(
                ModelFile(
                    _string(file["path"]),
                    _integer(file["size"]),
                    _string(file["sha256"]),
                )
                for file in (
                    _object(item, {"path", "size", "sha256"}) for item in raw_files
                )
            ),
            _integer(data["estimated_bytes"]),
        )
    except (TypeError, ValueError):
        raise _InvalidExecutionDocument("Invalid pinned model manifest") from None


def _decode_pins(
    binding: ExecutionBinding, limits: GraphLimits, max_bytes: int
) -> tuple[_NodePins, ...]:
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Execution byte limit must be positive")
    if (
        type(binding.execution_bytes) is not bytes
        or len(binding.execution_bytes) > max_bytes
    ):
        raise _InvalidExecutionDocument("Execution binding exceeds its byte limit")
    if hashlib.sha256(binding.execution_bytes).hexdigest() != binding.execution_sha256:
        raise _InvalidExecutionDocument("Execution binding digest mismatch")
    try:
        document = json.loads(
            binding.execution_bytes,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        raise _InvalidExecutionDocument("Execution binding is not valid JSON") from None
    try:
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        raise _InvalidExecutionDocument(
            "Execution binding is not canonical JSON"
        ) from None
    if canonical != binding.execution_bytes:
        raise _InvalidExecutionDocument("Execution binding is not canonical JSON")
    root = _object(
        document,
        {"kind", "schemaVersion", "revision", "nodes", "edges", "nodePins"},
    )
    if (
        root["kind"] != "internal.workflow-execution"
        or type(root["schemaVersion"]) is not int
        or root["schemaVersion"] != 1
        or root["revision"] != binding.revision
    ):
        raise _InvalidExecutionDocument("Execution binding header is invalid")
    nodes, edges, pins = root["nodes"], root["edges"], root["nodePins"]
    if (
        type(nodes) is not list
        or len(nodes) > limits.max_nodes
        or type(edges) is not list
        or len(edges) > limits.max_edges
        or not isinstance(pins, dict)
    ):
        raise _InvalidExecutionDocument("Execution graph exceeds configured limits")

    node_ids: list[str] = []
    for item in nodes:
        node = _object(item, {"id", "type", "config"})
        node_id = _string(node["id"])
        if (
            not node_id
            or not _string(node["type"])
            or not isinstance(node["config"], dict)
        ):
            raise _InvalidExecutionDocument("Execution node is invalid")
        node_ids.append(node_id)
    if len(set(node_ids)) != len(node_ids) or set(pins) != set(node_ids):
        raise _InvalidExecutionDocument("Execution node pins are incomplete")
    for edge in edges:
        edge_data = _object(
            edge, {"id", "source", "sourcePort", "target", "targetPort"}
        )
        for key in ("id", "source", "sourcePort", "target", "targetPort"):
            _string(edge_data[key])

    decoded: list[_NodePins] = []
    for node_id in node_ids:
        pin = _object(pins[node_id], {"handler", "pinnedModelManifest"})
        handler_pin = _object(pin["handler"], {"artifactId", "sha256"})
        try:
            handler = HandlerArtifact(
                _string(handler_pin["artifactId"]),
                _string(handler_pin["sha256"]),
            )
        except (TypeError, ValueError):
            raise _InvalidExecutionDocument("Invalid handler pin") from None
        raw_models = pin["pinnedModelManifest"]
        if type(raw_models) is not list:
            raise _InvalidExecutionDocument("Invalid pinned model list")
        decoded.append(
            _NodePins(
                node_id,
                handler,
                tuple(_model_manifest(model) for model in raw_models),
            )
        )
    return tuple(decoded)


def _fail(
    connection: Connection,
    run_id: UUID,
    expected_sequence: int,
    code: ReadinessFailureCode,
) -> ExecutionReadiness:
    transition_run(
        connection,
        run_id,
        expected_sequence,
        RunState.FAILED,
        f"Execution readiness failed: {code.value}",
    )
    return ExecutionReadiness(False, code)


def preflight_run(
    connection: Connection,
    run_id: UUID,
    handler_catalog: HandlerCatalog,
    model_registry: ModelRegistry,
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> ExecutionReadiness:
    """Verify all immutable pins before dispatch; caller owns the transaction."""
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    row = connection.execute(
        select(runs.c.id, runs.c.state, runs.c.sequence)
        .where(runs.c.id == run_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise RunNotFound("Run not found")
    status = RunStatus(row.id, RunState(row.state), row.sequence)
    if status.state is not RunState.QUEUED:
        raise RunConflict("Only queued runs can be preflighted")

    request = connection.execute(
        select(
            run_requests.c.workflow_id,
            run_requests.c.revision,
            run_requests.c.sha256,
        ).where(run_requests.c.run_id == run_id)
    ).one_or_none()
    run_revision = connection.execute(
        select(run_revisions.c.workflow_id, run_revisions.c.revision).where(
            run_revisions.c.run_id == run_id
        )
    ).one_or_none()
    if (
        request is None
        or run_revision is None
        or tuple(request[:2]) != tuple(run_revision)
        or type(request.sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", request.sha256) is None
    ):
        return _fail(
            connection,
            run_id,
            status.last_sequence,
            ReadinessFailureCode.RUN_BINDING_INVALID,
        )

    try:
        binding = get_execution_binding(
            connection, request.workflow_id, request.revision
        )
    except ExecutionBindingNotFound:
        return _fail(
            connection,
            run_id,
            status.last_sequence,
            ReadinessFailureCode.EXECUTION_BINDING_NOT_FOUND,
        )
    except ExecutionBindingCorrupt:
        return _fail(
            connection,
            run_id,
            status.last_sequence,
            ReadinessFailureCode.EXECUTION_BINDING_CORRUPT,
        )
    if (
        binding.workflow_id != request.workflow_id
        or binding.revision != request.revision
        or binding.source_sha256 != request.sha256
    ):
        return _fail(
            connection,
            run_id,
            status.last_sequence,
            ReadinessFailureCode.RUN_BINDING_INVALID,
        )
    try:
        pins = _decode_pins(binding, limits, max_bytes)
    except _InvalidExecutionDocument:
        return _fail(
            connection,
            run_id,
            status.last_sequence,
            ReadinessFailureCode.EXECUTION_DOCUMENT_INVALID,
        )

    resolved_handlers: list[tuple[str, ResolvedHandler]] = []
    resolved_models: list[tuple[str, int, ReadyModel]] = []
    for node in pins:
        handler = handler_catalog.resolve(node.handler.artifact_id)
        if handler is None:
            return _fail(
                connection,
                run_id,
                status.last_sequence,
                ReadinessFailureCode.HANDLER_NOT_READY,
            )
        if (
            not isinstance(handler, ResolvedHandler)
            or handler.artifact_id != node.handler.artifact_id
            or handler.sha256 != node.handler.sha256
        ):
            return _fail(
                connection,
                run_id,
                status.last_sequence,
                ReadinessFailureCode.HANDLER_PIN_MISMATCH,
            )
        resolved_handlers.append((node.node_id, handler))

        for index, manifest in enumerate(node.models):
            model = model_registry.resolve(manifest)
            if model is None:
                return _fail(
                    connection,
                    run_id,
                    status.last_sequence,
                    ReadinessFailureCode.MODEL_NOT_READY,
                )
            if not isinstance(model, ReadyModel) or model.manifest != manifest:
                return _fail(
                    connection,
                    run_id,
                    status.last_sequence,
                    ReadinessFailureCode.MODEL_PIN_MISMATCH,
                )
            resolved_models.append((node.node_id, index, model))

    return ExecutionReadiness(
        True,
        handlers=tuple(resolved_handlers),
        models=tuple(resolved_models),
    )
