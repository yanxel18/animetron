import json

import pytest

from app.services.workflows.document import InvalidWorkflowDocument
from app.services.workflows.sample_evaluator import (
    MAX_SAMPLE_DOCUMENT_BYTES,
    MAX_SAMPLE_EDGES,
    MAX_SAMPLE_NODES,
    MAX_SAMPLE_OUTPUT_VALUE_BYTES,
    MAX_SAMPLE_TOTAL_OUTPUT_BYTES,
    evaluate_sample_graph,
)
from app.services.workflows.snapshot import InvalidWorkflowGraph


def document(nodes: list[dict], edges: list[dict] | None = None) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 1,
            "revision": "sample-r1",
            "nodes": nodes,
            "edges": edges or [],
        }
    ).encode()


def node(node_id: str, kind: str, config: dict | None = None) -> dict:
    return {"id": node_id, "type": kind, "config": config or {}}


def edge(
    edge_id: str, source: str, source_port: str, target: str, target_port: str
) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "sourcePort": source_port,
        "target": target,
        "targetPort": target_port,
    }


def by_id(evaluation):
    return {result.node_id: result for result in evaluation.nodes}


def fan_out_join_document(edges: list[dict] | None = None) -> bytes:
    return document(
        [
            node("join", "sample.join"),
            node("right", "sample.prefix", {"prefix": "R:"}),
            node("source", "sample.constant", {"text": "x"}),
            node("left", "sample.prefix", {"prefix": "L:"}),
            node("failure", "sample.fail"),
            node("blocked", "sample.prefix", {"prefix": "never:"}),
            node("independent", "sample.constant", {"text": "alone"}),
        ],
        edges
        or [
            edge("source-right", "source", "text", "right", "text"),
            edge("right-join", "right", "text", "join", "right"),
            edge("source-left", "source", "text", "left", "text"),
            edge("left-join", "left", "text", "join", "left"),
            edge("join-failure", "join", "text", "failure", "text"),
            edge("failure-blocked", "failure", "text", "blocked", "text"),
        ],
    )


def test_evaluates_typed_fan_out_join_and_failure_in_stable_topological_order():
    data = fan_out_join_document()

    evaluation = evaluate_sample_graph(data)
    results = by_id(evaluation)

    assert evaluation.revision == "sample-r1"
    assert evaluation.execution_order == (
        "source",
        "right",
        "left",
        "join",
        "failure",
        "blocked",
        "independent",
    )
    assert results["right"].outputs == (("text", "R:x"),)
    assert results["left"].outputs == (("text", "L:x"),)
    assert results["join"].outputs == (("text", "L:x | R:x"),)
    assert results["failure"].status == "failed"
    assert results["failure"].error_code == "SAMPLE_FAILURE"
    assert results["blocked"].status == "skipped"
    assert results["blocked"].error_code == "UPSTREAM_FAILED"
    assert results["independent"].outputs == (("text", "alone"),)
    assert evaluate_sample_graph(data) == evaluation


def test_edge_serialization_order_does_not_change_results_or_execution_order():
    original = fan_out_join_document()
    reversed_edges = fan_out_join_document(
        list(reversed(json.loads(original)["edges"]))
    )

    assert evaluate_sample_graph(reversed_edges) == evaluate_sample_graph(original)


@pytest.mark.parametrize(
    ("data", "issue_code"),
    [
        (
            document([node("n", "sample.unknown")]),
            "UNKNOWN_NODE_TYPE",
        ),
        (
            document([node("n", "sample.constant", {"text": 1})]),
            "INVALID_NODE_CONFIG",
        ),
        (
            document(
                [
                    node("source", "sample.constant", {"text": "x"}),
                    node("join", "sample.join"),
                ],
                [edge("bad-port", "source", "missing", "join", "left")],
            ),
            "INVALID_SOURCE_PORT",
        ),
        (
            document(
                [node("join", "sample.join")],
                [],
            ),
            "MISSING_REQUIRED_INPUT",
        ),
    ],
)
def test_rejects_invalid_sample_graph_before_evaluation(data: bytes, issue_code: str):
    with pytest.raises(InvalidWorkflowGraph) as error:
        evaluate_sample_graph(data)

    assert issue_code in {issue.code for issue in error.value.issues}


def test_rejects_graph_over_the_fixed_node_bound():
    data = document(
        [node(f"n{index}", "sample.constant", {"text": "x"})
         for index in range(MAX_SAMPLE_NODES + 1)]
    )

    with pytest.raises(InvalidWorkflowGraph) as error:
        evaluate_sample_graph(data)

    assert [issue.code for issue in error.value.issues] == ["GRAPH_TOO_LARGE"]


def test_rejects_graph_over_the_fixed_edge_bound():
    join_count = MAX_SAMPLE_EDGES // 2 + 1
    nodes = [node("source", "sample.constant", {"text": "x"})]
    nodes.extend(node(f"join{index}", "sample.join") for index in range(join_count))
    edges = [
        edge(f"{join_id}-{port}", "source", "text", join_id, port)
        for join_id in (f"join{index}" for index in range(join_count))
        for port in ("left", "right")
    ]

    with pytest.raises(InvalidWorkflowGraph) as error:
        evaluate_sample_graph(document(nodes, edges))

    assert [issue.code for issue in error.value.issues] == ["GRAPH_TOO_LARGE"]
    assert len(nodes) <= MAX_SAMPLE_NODES


def test_rejects_documents_over_the_fixed_byte_bound():
    data = document(
        [node("source", "sample.constant", {"text": "x" * MAX_SAMPLE_DOCUMENT_BYTES})]
    )

    with pytest.raises(InvalidWorkflowDocument, match="byte limit"):
        evaluate_sample_graph(data)


def test_oversized_handler_output_fails_that_node_and_skips_its_dependent():
    data = document(
        [
            node(
                "source",
                "sample.constant",
                {"text": "x" * (MAX_SAMPLE_OUTPUT_VALUE_BYTES + 1)},
            ),
            node("dependent", "sample.prefix", {"prefix": "next:"}),
        ],
        [edge("source-dependent", "source", "text", "dependent", "text")],
    )

    results = by_id(evaluate_sample_graph(data))

    assert results["source"].status == "failed"
    assert results["source"].error_code == "OUTPUT_VALUE_LIMIT_EXCEEDED"
    assert results["dependent"].status == "skipped"


def test_total_output_bound_fails_only_the_node_that_exceeds_it():
    first = "a" * (MAX_SAMPLE_OUTPUT_VALUE_BYTES - 1)
    second = "b" * (MAX_SAMPLE_OUTPUT_VALUE_BYTES - 1)
    third = "c" * 3
    data = document(
        [
            node("first", "sample.constant", {"text": first}),
            node("second", "sample.constant", {"text": second}),
            node("third", "sample.constant", {"text": third}),
        ]
    )

    results = by_id(evaluate_sample_graph(data))

    assert results["first"].status == "succeeded"
    assert results["second"].status == "succeeded"
    assert results["third"].status == "failed"
    assert results["third"].error_code == "TOTAL_OUTPUT_LIMIT_EXCEEDED"
    assert sum(
        len(value.encode("utf-8"))
        for result in results.values()
        for _, value in result.outputs
    ) <= MAX_SAMPLE_TOTAL_OUTPUT_BYTES
