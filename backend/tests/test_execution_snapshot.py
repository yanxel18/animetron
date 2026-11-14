import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
)

from app.services.models.manifest import ModelFile, ModelManifest
from app.services.models.reference import ModelReference
from app.services.workflows.document import (
    InvalidWorkflowDocument,
    parse_workflow_document,
)
from app.services.workflows.execution_snapshot import (
    ExecutionNodeDefinition,
    ExecutionSnapshot,
    HandlerArtifact,
    InvalidExecutionSnapshot,
    create_execution_snapshot,
)
from app.services.workflows.snapshot import InvalidWorkflowGraph, create_snapshot
from app.services.workflows.validation import GraphLimits, NodeDefinition, Port

LIMITS = GraphLimits(10, 10)
MANIFEST = ModelManifest(
    ModelReference("huggingface", "studio/model", "a" * 40),
    "engine", "license", (ModelFile("model.safetensors", 7, "b" * 64),), 10,
)


class Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    prompt: str = "hello"
    steps: int = Field(4, alias="stepCount")
    enabled: bool = True
    options: dict[str, list[int]] = {"weights": [1, 2]}


def catalog(model=Config):
    return {
        "story": ExecutionNodeDefinition(
            NodeDefinition(config_model=model),
            HandlerArtifact("story-handler", "c" * 64),
            (MANIFEST,),
        )
    }


def document(config=None):
    return {
        "schemaVersion": 1, "revision": "r1",
        "nodes": [{"id": "a", "type": "story", "config": config or {}}],
        "edges": [],
    }


def build(value=None, selected=None, max_bytes=100_000):
    return create_execution_snapshot(
        json.dumps(document() if value is None else value).encode(),
        catalog() if selected is None else selected, LIMITS, max_bytes=max_bytes,
    )


def test_materializes_defaults_and_pins_full_metadata():
    snapshot = build()
    body = json.loads(snapshot.canonical_json)
    assert body["kind"] == "internal.workflow-execution"
    assert body["schemaVersion"] == 1
    assert body["revision"] == "r1"
    assert body["nodes"][0]["config"] == {
        "prompt": "hello", "stepCount": 4, "enabled": True,
        "options": {"weights": [1, 2]},
    }
    assert body["nodePins"] == {
        "a": {
            "handler": {"artifactId": "story-handler", "sha256": "c" * 64},
            "pinnedModelManifest": [json.loads(json.dumps(asdict(MANIFEST)))],
        }
    }
    assert snapshot.sha256 == hashlib.sha256(snapshot.canonical_json).hexdigest()
    assert snapshot.canonical_json == json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def test_default_drift_changes_new_values_not_old_values():
    class Updated(Config):
        steps: int = Field(8, alias="stepCount")

    old = build()
    new = build(selected=catalog(Updated))
    assert old.sha256 != new.sha256
    assert json.loads(old.canonical_json)["nodes"][0]["config"]["stepCount"] == 4
    explicit = document({"stepCount": 0, "enabled": False, "prompt": ""})
    assert build(explicit).canonical_json == build(explicit, catalog(Updated)).canonical_json


def test_aliases_defaults_and_explicit_values_are_consistent():
    by_name = build(document({"steps": 0, "prompt": "  雪  ", "enabled": False}))
    by_alias = build(document({"stepCount": 0, "prompt": "  雪  ", "enabled": False}))
    assert by_name == by_alias
    assert json.loads(by_name.canonical_json)["nodes"][0]["config"]["prompt"] == "  雪  "

    class SeparateAlias(BaseModel):
        amount: int = Field(3, validation_alias="inputCount", serialization_alias="count")

    omitted = build(selected=catalog(SeparateAlias))
    explicit = build(document({"inputCount": 3}), catalog(SeparateAlias))
    assert omitted == explicit
    assert json.loads(omitted.canonical_json)["nodes"][0]["config"] == {"count": 3}


def test_nested_defaults_and_validation_alias_paths_are_materialized():
    class Nested(BaseModel):
        count: int = Field(2, alias="n")

    class Outer(BaseModel):
        nested: Nested = Field(default_factory=Nested)
        steps: int = Field(
            3, validation_alias=AliasChoices("steps", AliasPath("settings", "count")),
            serialization_alias="stepCount",
        )

    omitted = build(selected=catalog(Outer))
    explicit = build(document({"settings": {"count": 3}, "nested": {"n": 2}}), catalog(Outer))
    assert omitted == explicit
    assert json.loads(omitted.canonical_json)["nodes"][0]["config"] == {
        "nested": {"n": 2}, "stepCount": 3,
    }


def test_serializers_cannot_hide_nonfinite_defaults():
    class Hidden(BaseModel):
        value: float = Field(float("inf"), exclude=True)

        @field_serializer("value")
        def serialize_value(self, value):
            return "hidden"

    with pytest.raises(InvalidExecutionSnapshot):
        build(selected=catalog(Hidden))


@pytest.mark.parametrize("config", [
    {"stepCount": "4"}, {"stepCount": True}, {"unknown": 4},
    {"stepCount": 4, "steps": 4}, {"options": {"weights": ["1"]}},
])
def test_invalid_explicit_config_never_falls_back_to_defaults(config):
    with pytest.raises(InvalidWorkflowGraph):
        build(document(config))


@pytest.mark.parametrize("default", ["4", None, float("nan"), float("inf")])
def test_invalid_typed_defaults_are_rejected(default):
    class Broken(BaseModel):
        count: int = Field(default=default)

    with pytest.raises(InvalidExecutionSnapshot):
        build(selected=catalog(Broken))


@pytest.mark.parametrize("default", [
    object(), (1, 2), {1: "bad-key"}, {"nested": [float("nan")]},
])
def test_non_json_or_nonfinite_defaults_are_rejected(default):
    class Broken(BaseModel):
        value: object = default

    with pytest.raises(InvalidExecutionSnapshot):
        build(selected=catalog(Broken))


def test_nested_invalid_default_is_validated():
    class Nested(BaseModel):
        count: int = Field(default="bad")

    class Outer(BaseModel):
        nested: Nested = Field(default_factory=Nested)

    with pytest.raises(InvalidExecutionSnapshot):
        build(selected=catalog(Outer))


def test_explicit_config_normalization_is_rejected_not_silently_changed():
    class Normalizing(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True)
        text: str

    with pytest.raises(InvalidExecutionSnapshot):
        build(document({"text": "  exact  "}), catalog(Normalizing))


def test_snapshot_cannot_retain_mutable_bytearray():
    with pytest.raises(TypeError):
        ExecutionSnapshot(bytearray(b"{}"))


@pytest.mark.parametrize("change", [
    {"reference": replace(MANIFEST.reference, repository="studio/other")},
    {"reference": replace(MANIFEST.reference, revision="d" * 40)},
    {"engine": "other"}, {"license_id": "other"},
    {"files": (replace(MANIFEST.files[0], path="other.safetensors"),)},
    {"files": (replace(MANIFEST.files[0], size=8),)},
    {"files": (replace(MANIFEST.files[0], sha256="e" * 64),)},
    {"estimated_bytes": 11},
    {"files": (*MANIFEST.files, ModelFile("extra.json", 1, "f" * 64))},
])
def test_every_model_manifest_field_is_digest_bound(change):
    selected = catalog()
    selected["story"] = replace(selected["story"], models=(replace(MANIFEST, **change),))
    assert build().sha256 != build(selected=selected).sha256


@pytest.mark.parametrize("handler", [
    HandlerArtifact("story-handler", "d" * 64),
    HandlerArtifact("another-handler", "c" * 64),
])
def test_handler_artifact_identity_is_digest_bound(handler):
    selected = catalog()
    selected["story"] = replace(selected["story"], handler=handler)
    assert build().sha256 != build(selected=selected).sha256


@pytest.mark.parametrize("artifact_id, digest", [
    ("https://example.invalid/code", "c" * 64), ("module:callable", "c" * 64),
    ("../code", "c" * 64), ("", "c" * 64), ("x" * 129, "c" * 64),
    ("handler", "C" * 64), ("handler", "latest"),
])
def test_handler_pins_are_exact_bounded_labels_not_code_locations(artifact_id, digest):
    with pytest.raises(ValueError):
        HandlerArtifact(artifact_id, digest)


def test_snapshot_retains_no_mutable_caller_references():
    selected = catalog()
    ports = {"text": Port("text")}
    selected["story"] = replace(
        selected["story"], definition=replace(selected["story"].definition, outputs=ports),
    )
    value = document({"options": {"weights": [9]}})
    snapshot = build(value, selected)
    default_snapshot = build()
    default_encoded = default_snapshot.canonical_json
    encoded, digest = snapshot.canonical_json, snapshot.sha256
    value["nodes"][0]["config"]["options"]["weights"].append(10)
    ports.clear()
    selected.clear()
    Config.model_fields["options"].default["weights"].append(3)
    try:
        assert snapshot.canonical_json == encoded
        assert snapshot.sha256 == digest
        assert default_snapshot.canonical_json == default_encoded
        assert json.loads(default_encoded)["nodes"][0]["config"]["options"] == {
            "weights": [1, 2],
        }
        assert json.loads(encoded)["nodes"][0]["config"]["options"] == {"weights": [9]}
    finally:
        Config.model_fields["options"].default["weights"].pop()
    with pytest.raises(FrozenInstanceError):
        snapshot.canonical_json = b"changed"


def test_revision_graph_and_node_order_are_digest_bound():
    base = document()
    for key, value in [("revision", "r2"), ("nodes", [
        {"id": "b", "type": "story", "config": {}},
    ])]:
        assert build().sha256 != build({**base, key: value}).sha256
    selected = catalog()
    selected["story"] = replace(selected["story"], definition=NodeDefinition(
        config_model=Config, inputs={"in": Port("text")}, outputs={"out": Port("text")},
    ))
    base["nodes"].append({"id": "b", "type": "story", "config": {}})
    connected = {**base, "edges": [
        {"id": "e", "source": "a", "sourcePort": "out", "target": "b", "targetPort": "in"},
    ]}
    assert build(base, selected).sha256 != build(connected, selected).sha256
    assert build(base).sha256 != build({**base, "nodes": list(reversed(base["nodes"]))}).sha256
    assert set(json.loads(build(base).canonical_json)["nodePins"]) == {"a", "b"}


@pytest.mark.parametrize("key", ["nodePins", "handler", "pinnedModelManifest", "defaults"])
def test_clients_cannot_override_backend_pins_or_defaults(key):
    value = document()
    value[key] = {}
    with pytest.raises(InvalidWorkflowDocument):
        build(value)
    value = document()
    value["nodes"][0][key] = {}
    with pytest.raises(InvalidWorkflowDocument):
        build(value)


def test_missing_catalog_entry_or_handler_pin_is_rejected():
    with pytest.raises(InvalidWorkflowGraph):
        build(selected={})
    with pytest.raises((TypeError, ValueError)):
        build(selected={"story": ExecutionNodeDefinition(NodeDefinition(), None)})


def test_model_less_nodes_still_have_explicit_complete_pins():
    selected = {"story": ExecutionNodeDefinition(
        NodeDefinition(), HandlerArtifact("noop", "c" * 64),
    )}
    body = json.loads(build(selected=selected).canonical_json)
    assert body["nodes"][0]["config"] == {}
    assert body["nodePins"]["a"]["pinnedModelManifest"] == []
    with pytest.raises(InvalidWorkflowGraph):
        build(document({"prompt": "not freeform"}), selected)


@pytest.mark.parametrize("models", [[MANIFEST], ({"reference": "latest"},), (None,)])
def test_catalog_requires_existing_typed_model_manifests(models):
    with pytest.raises(InvalidExecutionSnapshot):
        ExecutionNodeDefinition(NodeDefinition(), HandlerArtifact("noop", "c" * 64), models)


def test_legacy_bytes_and_parser_behavior_are_unchanged_and_not_promoted():
    definitions = {"story": NodeDefinition(config_model=Config)}
    data = json.dumps(document()).encode()
    old = create_snapshot(data, definitions, LIMITS, max_bytes=len(data))
    expected = json.dumps(document(), sort_keys=True, separators=(",", ":")).encode()
    assert old.canonical_json == expected
    assert old.sha256 == hashlib.sha256(expected).hexdigest()
    assert parse_workflow_document(data, definitions, LIMITS, max_bytes=len(data)).issues == []
    new = build()
    assert new.sha256 != old.sha256
    with pytest.raises(InvalidWorkflowDocument):
        parse_workflow_document(new.canonical_json, definitions, LIMITS, max_bytes=100_000)


def test_exact_output_byte_boundary_includes_default_and_unicode_expansion():
    class Expanded(BaseModel):
        text: str = "雪" * 100

    selected = catalog(Expanded)
    data = json.dumps(document()).encode()
    expected = build(selected=selected)
    size = len(expected.canonical_json)
    assert size > len(data)
    assert build(selected=selected, max_bytes=size) == expected
    with pytest.raises(InvalidExecutionSnapshot, match="byte limit"):
        build(selected=selected, max_bytes=size - 1)


def test_exact_input_byte_boundary_counts_whitespace_not_just_parsed_content():
    selected = catalog()
    data = json.dumps(document()).encode()
    expected = build()
    size = len(expected.canonical_json)
    padded = data + b" " * (size - len(data))
    assert create_execution_snapshot(padded, selected, LIMITS, max_bytes=size) == expected
    with pytest.raises(InvalidWorkflowDocument, match="byte limit"):
        create_execution_snapshot(padded + b" ", selected, LIMITS, max_bytes=size)
