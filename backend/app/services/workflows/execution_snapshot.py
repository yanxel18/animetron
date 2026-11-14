"""Internal execution metadata values; not a runtime loader or authorization."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass

from pydantic import AliasChoices, AliasPath, BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from app.services.models.integrity import validate_sha256
from app.services.models.manifest import ModelManifest
from app.services.workflows.document import parse_workflow_document
from app.services.workflows.snapshot import InvalidWorkflowGraph
from app.services.workflows.validation import GraphLimits, NodeDefinition


class InvalidExecutionSnapshot(ValueError):
    pass


@dataclass(frozen=True)
class HandlerArtifact:
    artifact_id: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", self.artifact_id) is None
        ):
            raise InvalidExecutionSnapshot("Invalid handler artifact identifier")
        validate_sha256(self.sha256)


@dataclass(frozen=True)
class ExecutionNodeDefinition:
    definition: NodeDefinition
    handler: HandlerArtifact
    models: tuple[ModelManifest, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.definition) is not NodeDefinition
            or type(self.handler) is not HandlerArtifact
            or type(self.models) is not tuple
            or any(type(model) is not ModelManifest for model in self.models)
        ):
            raise InvalidExecutionSnapshot("Invalid execution node definition")


@dataclass(frozen=True)
class ExecutionSnapshot:
    canonical_json: bytes

    def __post_init__(self) -> None:
        if type(self.canonical_json) is not bytes:
            raise TypeError("Execution snapshot requires immutable bytes")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json).hexdigest()


def _json_value(value: object, *, aliases: bool) -> object:
    """Read actual fields, not serializers that can hide invalid defaults."""
    if isinstance(value, BaseModel):
        fields: dict[str, object] = {}
        for name, field in type(value).model_fields.items():
            key = (field.serialization_alias or field.alias or name) if aliases else name
            if key in fields:
                raise InvalidExecutionSnapshot("Ambiguous configuration alias")
            fields[key] = _json_value(getattr(value, name), aliases=aliases)
        return fields
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item, aliases=aliases) for item in value]
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return {key: _json_value(item, aliases=aliases) for key, item in value.items()}
    raise InvalidExecutionSnapshot("Configuration must contain finite JSON values")


def _check_explicit(original: object, resolved: object) -> None:
    """Reject transformations while allowing omitted model fields to gain defaults."""
    if isinstance(resolved, BaseModel) and isinstance(original, dict):
        for name, field in type(resolved).model_fields.items():
            alias = field.validation_alias
            choices = alias.choices if isinstance(alias, AliasChoices) else [alias]
            for choice in [*choices, name]:
                if choice is None:
                    continue
                path = AliasPath(choice) if isinstance(choice, str) else choice
                supplied = path.search_dict_for_path(original)
                if supplied is not PydanticUndefined:
                    _check_explicit(supplied, getattr(resolved, name))
                    break
        return
    if isinstance(original, dict) and isinstance(resolved, dict):
        if original.keys() != resolved.keys():
            raise InvalidExecutionSnapshot("Configuration validation changed explicit values")
        for key in original:
            _check_explicit(original[key], resolved[key])
        return
    if isinstance(original, list) and isinstance(resolved, list):
        if len(original) != len(resolved):
            raise InvalidExecutionSnapshot("Configuration validation changed explicit values")
        for before, after in zip(original, resolved, strict=True):
            _check_explicit(before, after)
        return
    if type(original) is not type(resolved) or original != resolved:
        raise InvalidExecutionSnapshot("Configuration validation changed explicit values")


def _resolve_config(config: Mapping[str, object], definition: NodeDefinition) -> object:
    model = definition.config_model
    if model is None:
        return {}
    try:
        resolved = model.model_validate(deepcopy(dict(config)), strict=True, extra="forbid")
        _check_explicit(dict(config), resolved)
        # Defaults (including nested defaults) become explicit input. Validation
        # by field name avoids interpreting serialization aliases as input aliases.
        materialized = _json_value(resolved, aliases=False)
        checked = model.model_validate(
            materialized, strict=True, extra="forbid", by_name=True, by_alias=False,
        )
        if _json_value(checked, aliases=False) != materialized:
            raise InvalidExecutionSnapshot("Configuration validation changed defaults")
        return _json_value(checked, aliases=True)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise InvalidExecutionSnapshot("Invalid resolved node configuration") from None


def create_execution_snapshot(
    data: bytes,
    catalog: Mapping[str, ExecutionNodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> ExecutionSnapshot:
    definitions = {name: entry.definition for name, entry in catalog.items()}
    parsed = parse_workflow_document(data, definitions, limits, max_bytes=max_bytes)
    if parsed.issues:
        raise InvalidWorkflowGraph(parsed.issues)
    # The parser has already checked this exact bounded JSON. Read explicit
    # configs afresh: a trusted model validator may have mutated its first input.
    original_nodes = json.loads(data)["nodes"]
    document = {
        "kind": "internal.workflow-execution",
        "schemaVersion": 1,
        "revision": parsed.revision,
        "nodes": [
            {
                "id": node.id, "type": node.type,
                "config": _resolve_config(
                    original["config"], catalog[node.type].definition,
                ),
            }
            for node, original in zip(parsed.graph.nodes, original_nodes, strict=True)
        ],
        "edges": [
            {
                "id": edge.id, "source": edge.source, "sourcePort": edge.source_port,
                "target": edge.target, "targetPort": edge.target_port,
            }
            for edge in parsed.graph.edges
        ],
        "nodePins": {
            node.id: {
                "handler": {
                    "artifactId": catalog[node.type].handler.artifact_id,
                    "sha256": catalog[node.type].handler.sha256,
                },
                "pinnedModelManifest": [
                    asdict(model) for model in catalog[node.type].models
                ],
            }
            for node in parsed.graph.nodes
        },
    }
    try:
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise InvalidExecutionSnapshot("Execution snapshot is not JSON serializable") from None
    if len(encoded) > max_bytes:
        raise InvalidExecutionSnapshot("Execution snapshot exceeds byte limit")
    return ExecutionSnapshot(encoded)
