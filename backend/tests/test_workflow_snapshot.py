import hashlib
import json

import pytest
from pydantic import BaseModel

from app.services.workflows.snapshot import InvalidWorkflowGraph, create_snapshot
from app.services.workflows.validation import GraphLimits, NodeDefinition


class StoryConfig(BaseModel):
    prompt: str


DEFINITIONS = {"story": NodeDefinition(config_model=StoryConfig)}
LIMITS = GraphLimits(max_nodes=10, max_edges=10)


def test_snapshot_is_immutable_and_deterministic_for_object_key_order() -> None:
    first = (
        b'{"revision":"r1","schemaVersion":1,"nodes":'
        b'[{"id":"a","type":"story","config":{"prompt":"hello"}}],"edges":[]}'
    )
    second = (
        b'{ "nodes": [{"config": {"prompt": "hello"}, "type": "story", "id": "a"}], '
        b'"edges": [], "schemaVersion": 1, "revision": "r1" }'
    )
    snapshot = create_snapshot(first, DEFINITIONS, LIMITS, max_bytes=1024)
    reordered = create_snapshot(second, DEFINITIONS, LIMITS, max_bytes=1024)
    assert snapshot.canonical_json == reordered.canonical_json
    assert snapshot.sha256 == reordered.sha256
    assert snapshot.sha256 == hashlib.sha256(snapshot.canonical_json).hexdigest()
    assert json.loads(snapshot.canonical_json)["revision"] == "r1"
    assert isinstance(snapshot.canonical_json, bytes)
    with pytest.raises(AttributeError):
        snapshot.canonical_json = b"changed"


def test_distinct_revisions_change_snapshot_identity() -> None:
    value = {
        "schemaVersion": 1,
        "revision": "r1",
        "nodes": [{"id": "a", "type": "story", "config": {"prompt": "hello"}}],
        "edges": [],
    }
    original = create_snapshot(
        json.dumps(value).encode(), DEFINITIONS, LIMITS, max_bytes=1024
    )
    value["revision"] = "r2"
    modified = create_snapshot(
        json.dumps(value).encode(), DEFINITIONS, LIMITS, max_bytes=1024
    )
    assert original.sha256 != modified.sha256
    assert json.loads(original.canonical_json)["revision"] == "r1"


def test_changed_configuration_changes_snapshot_identity() -> None:
    value = {
        "schemaVersion": 1,
        "revision": "r1",
        "nodes": [{"id": "a", "type": "story", "config": {"prompt": "hello"}}],
        "edges": [],
    }
    original = create_snapshot(
        json.dumps(value).encode(), DEFINITIONS, LIMITS, max_bytes=1024
    )
    value["nodes"][0]["config"]["prompt"] = "different"
    modified = create_snapshot(
        json.dumps(value).encode(), DEFINITIONS, LIMITS, max_bytes=1024
    )
    assert original.sha256 != modified.sha256
    assert json.loads(original.canonical_json)["nodes"][0]["config"]["prompt"] == "hello"


def test_invalid_graph_cannot_be_snapshotted() -> None:
    data = b'{"schemaVersion":1,"revision":"r","nodes":[{"id":"a","type":"story","config":{"prompt":3}}],"edges":[]}'
    with pytest.raises(InvalidWorkflowGraph) as error:
        create_snapshot(data, DEFINITIONS, LIMITS, max_bytes=1024)
    assert [issue.code for issue in error.value.issues] == ["INVALID_NODE_CONFIG"]
    assert "3" not in str(error.value)
