import pytest
from pydantic import BaseModel, Field

from app.services.workflows.validation import (
    Edge,
    Graph,
    GraphLimits,
    Node,
    NodeDefinition,
    Port,
    validate_graph,
)

DEFINITIONS = {
    "source": NodeDefinition(outputs={"out": Port("text")}),
    "transform": NodeDefinition(
        inputs={"in": Port("text", required=True)}, outputs={"out": Port("text")}
    ),
    "sink": NodeDefinition(inputs={"in": Port("text", required=True)}),
    "image_sink": NodeDefinition(inputs={"in": Port("image", required=True)}),
}
LIMITS = GraphLimits(max_nodes=10, max_edges=10)


def graph(nodes: list[Node], edges: list[Edge] | None = None) -> Graph:
    return Graph(nodes=nodes, edges=edges or [])


def codes(value: Graph) -> set[str]:
    return {issue.code for issue in validate_graph(value, DEFINITIONS, LIMITS)}


def test_valid_fan_out_and_join() -> None:
    definitions = {
        **DEFINITIONS,
        "join": NodeDefinition(
            inputs={"left": Port("text", True), "right": Port("text", True)}
        ),
    }
    value = graph(
        [Node("a", "source"), Node("b", "transform"), Node("c", "join")],
        [
            Edge("1", "a", "out", "b", "in"),
            Edge("2", "a", "out", "c", "left"),
            Edge("3", "b", "out", "c", "right"),
        ],
    )
    assert validate_graph(value, definitions, LIMITS) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (graph([Node("", "source")]), "INVALID_NODE_ID"),
        (graph([Node("a", "source"), Node("a", "source")]), "DUPLICATE_NODE_ID"),
        (graph([Node("a", "unknown")]), "UNKNOWN_NODE_TYPE"),
        (
            graph([Node("a", "source")], [Edge("", "a", "out", "a", "in")]),
            "INVALID_EDGE_ID",
        ),
        (
            graph(
                [Node("a", "source")],
                [Edge("e", "a", "out", "a", "in"), Edge("e", "a", "out", "a", "in")],
            ),
            "DUPLICATE_EDGE_ID",
        ),
        (
            graph([Node("a", "source")], [Edge("e", "missing", "out", "a", "in")]),
            "UNKNOWN_SOURCE",
        ),
        (
            graph([Node("a", "source")], [Edge("e", "a", "out", "missing", "in")]),
            "UNKNOWN_TARGET",
        ),
        (
            graph(
                [Node("a", "source"), Node("b", "sink")],
                [Edge("e", "a", "bad", "b", "in")],
            ),
            "INVALID_SOURCE_PORT",
        ),
        (
            graph(
                [Node("a", "source"), Node("b", "sink")],
                [Edge("e", "a", "out", "b", "bad")],
            ),
            "INVALID_TARGET_PORT",
        ),
        (
            graph(
                [Node("a", "source"), Node("b", "image_sink")],
                [Edge("e", "a", "out", "b", "in")],
            ),
            "INCOMPATIBLE_PORTS",
        ),
        (graph([Node("a", "sink")]), "MISSING_REQUIRED_INPUT"),
        (
            graph(
                [Node("a", "source"), Node("b", "sink")],
                [Edge("1", "a", "out", "b", "in"), Edge("2", "a", "out", "b", "in")],
            ),
            "MULTIPLE_INPUT_EDGES",
        ),
        (graph([Node("a", "transform")], [Edge("e", "a", "out", "a", "in")]), "CYCLE"),
        (
            graph(
                [Node("a", "transform"), Node("b", "transform")],
                [Edge("1", "a", "out", "b", "in"), Edge("2", "b", "out", "a", "in")],
            ),
            "CYCLE",
        ),
    ],
)
def test_invalid_graph_cases(value: Graph, expected: str) -> None:
    assert expected in codes(value)


def test_incompatible_edge_does_not_satisfy_required_input() -> None:
    value = graph(
        [Node("a", "source"), Node("b", "image_sink")],
        [Edge("e", "a", "out", "b", "in")],
    )
    assert {"INCOMPATIBLE_PORTS", "MISSING_REQUIRED_INPUT"} <= codes(value)


def test_limits_reject_oversized_graph_before_detailed_validation() -> None:
    value = graph([Node("a", "source"), Node("b", "source")])
    issues = validate_graph(value, DEFINITIONS, GraphLimits(max_nodes=1, max_edges=1))
    assert [issue.code for issue in issues] == ["GRAPH_TOO_LARGE"]


def test_edge_limit_is_enforced() -> None:
    value = graph(
        [Node("a", "source"), Node("b", "sink")],
        [Edge("1", "a", "out", "b", "in"), Edge("2", "a", "out", "b", "in")],
    )
    issues = validate_graph(value, DEFINITIONS, GraphLimits(max_nodes=2, max_edges=1))
    assert [issue.code for issue in issues] == ["GRAPH_TOO_LARGE"]


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError):
        GraphLimits(max_nodes=0, max_edges=1)


class SampleConfig(BaseModel):
    duration: int = Field(ge=1, le=90)


def test_node_config_is_validated_against_backend_schema() -> None:
    definitions = {"sample": NodeDefinition(config_model=SampleConfig)}
    valid = graph([Node("a", "sample", config={"duration": 30})])
    assert validate_graph(valid, definitions, LIMITS) == []


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"duration": 0},
        {"duration": 91},
        {"duration": "30"},
        {"duration": 30, "shell": "run"},
    ],
)
def test_invalid_node_config_is_rejected_without_echoing_values(config: dict) -> None:
    definitions = {"sample": NodeDefinition(config_model=SampleConfig)}
    issues = validate_graph(
        graph([Node("a", "sample", config=config)]), definitions, LIMITS
    )
    assert [(issue.code, issue.node_id) for issue in issues] == [
        ("INVALID_NODE_CONFIG", "a")
    ]
    assert all("run" not in issue.message for issue in issues)


def test_node_without_config_schema_rejects_nonempty_config() -> None:
    value = graph([Node("a", "source", config={"unexpected": "value"})])
    assert "INVALID_NODE_CONFIG" in codes(value)


def test_non_mapping_config_is_rejected_even_without_a_schema() -> None:
    value = graph([Node("a", "source", config=[])])
    assert "INVALID_NODE_CONFIG" in codes(value)


def test_unknown_type_does_not_select_an_untrusted_config_schema() -> None:
    value = graph([Node("a", "unknown", config={"arbitrary": "data"})])
    assert codes(value) == {"UNKNOWN_NODE_TYPE"}
