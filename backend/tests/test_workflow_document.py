import json

import pytest
from pydantic import BaseModel

from app.services.workflows.document import (
    InvalidWorkflowDocument,
    parse_workflow_document,
)
from app.services.workflows.validation import GraphLimits, NodeDefinition, Port


class SourceConfig(BaseModel):
    prompt: str


DEFINITIONS = {
    "source": NodeDefinition(outputs={"out": Port("text")}, config_model=SourceConfig),
    "sink": NodeDefinition(inputs={"in": Port("text", required=True)}),
}
LIMITS = GraphLimits(max_nodes=3, max_edges=3)


def document() -> dict:
    return {
        "schemaVersion": 1,
        "revision": "rev-1",
        "nodes": [
            {"id": "a", "type": "source", "config": {"prompt": "original story"}},
            {"id": "b", "type": "sink", "config": {}},
        ],
        "edges": [
            {
                "id": "e",
                "source": "a",
                "sourcePort": "out",
                "target": "b",
                "targetPort": "in",
            }
        ],
    }


def parse(value: dict):
    return parse_workflow_document(
        json.dumps(value).encode(), DEFINITIONS, LIMITS, max_bytes=4096
    )


def test_document_maps_ports_and_validates_node_config() -> None:
    result = parse(document())
    assert result.revision == "rev-1"
    assert result.graph.nodes[0].config == {"prompt": "original story"}
    assert result.graph.edges[0].source_port == "out"
    assert result.issues == []


def test_document_reports_graph_and_config_issues() -> None:
    value = document()
    value["nodes"][0]["config"] = {"prompt": 5}
    value["edges"][0]["targetPort"] = "missing"
    result = parse(value)
    assert {issue.code for issue in result.issues} == {
        "INVALID_NODE_CONFIG",
        "INVALID_TARGET_PORT",
        "MISSING_REQUIRED_INPUT",
    }


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schemaVersion":1,"schemaVersion":1,"revision":"r","nodes":[],"edges":[]}',
        b'{"schemaVersion":true,"revision":"r","nodes":[],"edges":[]}',
        b'{"schemaVersion":2,"revision":"r","nodes":[],"edges":[]}',
        b'{"schemaVersion":1,"revision":"  ","nodes":[],"edges":[]}',
        b'{"schemaVersion":1,"revision":"r","nodes":[],"edges":[],"secret":"value"}',
        b'{"schemaVersion":1,"revision":"r","nodes":[],"edges":[],"x":NaN}',
        b'{"schemaVersion":1,"revision":"r","nodes":[{"id":"a","type":"source","config":{"prompt":"a","prompt":"b"}}],"edges":[]}',
        b'{"schemaVersion":1,"revision":"r","nodes":[{"id":"a","type":"source","config":{"n":1e999}}],"edges":[]}',
        b"\xff",
    ],
)
def test_invalid_document_is_rejected_without_echoing_input(raw: bytes) -> None:
    with pytest.raises(InvalidWorkflowDocument) as error:
        parse_workflow_document(raw, DEFINITIONS, LIMITS, max_bytes=4096)
    assert "secret" not in str(error.value)


def test_oversized_input_is_rejected_before_parsing() -> None:
    with pytest.raises(InvalidWorkflowDocument):
        parse_workflow_document(b"not-json", DEFINITIONS, LIMITS, max_bytes=4)


def test_graph_limits_are_applied_to_document() -> None:
    value = document()
    value["nodes"].extend(
        [
            {"id": "c", "type": "sink", "config": {}},
            {"id": "d", "type": "sink", "config": {}},
        ]
    )
    result = parse(value)
    assert [issue.code for issue in result.issues] == ["GRAPH_TOO_LARGE"]
