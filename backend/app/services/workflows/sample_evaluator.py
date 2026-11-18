"""Pure local sample handlers; this module is not a workflow runtime."""

import heapq
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.workflows.document import (
    ParsedWorkflowDocument,
    parse_workflow_document,
)
from app.services.workflows.plan import create_dependency_plan
from app.services.workflows.snapshot import InvalidWorkflowGraph
from app.services.workflows.validation import (
    GraphLimits,
    Node,
    NodeDefinition,
    Port,
    ValidationIssue,
)

MAX_SAMPLE_NODES = 32
MAX_SAMPLE_EDGES = 48
MAX_SAMPLE_DOCUMENT_BYTES = 32_768
MAX_SAMPLE_OUTPUT_VALUE_BYTES = 8_192
MAX_SAMPLE_TOTAL_OUTPUT_BYTES = 16_384

_GRAPH_LIMITS = GraphLimits(MAX_SAMPLE_NODES, MAX_SAMPLE_EDGES)


class _SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ConstantConfig(_SampleConfig):
    text: str


class _PrefixConfig(_SampleConfig):
    prefix: str


class _JoinConfig(_SampleConfig):
    separator: str = " | "


class _SampleHandler(Protocol):
    def __call__(
        self, config: BaseModel | None, inputs: Mapping[str, str]
    ) -> Mapping[str, str]: ...


class _SampleNodeFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SampleNodeResult:
    node_id: str
    status: Literal["succeeded", "failed", "skipped"]
    outputs: tuple[tuple[str, str], ...] = ()
    error_code: str | None = None


@dataclass(frozen=True)
class SampleEvaluation:
    revision: str
    execution_order: tuple[str, ...]
    nodes: tuple[SampleNodeResult, ...]


def _constant(config: BaseModel | None, inputs: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(config, _ConstantConfig) or inputs:
        raise _SampleNodeFailure("INVALID_HANDLER_INPUT")
    return {"text": config.text}


def _prefix(config: BaseModel | None, inputs: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(config, _PrefixConfig) or set(inputs) != {"text"}:
        raise _SampleNodeFailure("INVALID_HANDLER_INPUT")
    return {"text": config.prefix + inputs["text"]}


def _join(config: BaseModel | None, inputs: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(config, _JoinConfig) or set(inputs) != {"left", "right"}:
        raise _SampleNodeFailure("INVALID_HANDLER_INPUT")
    return {"text": inputs["left"] + config.separator + inputs["right"]}


def _fail(config: BaseModel | None, inputs: Mapping[str, str]) -> Mapping[str, str]:
    if config is not None or set(inputs) != {"text"}:
        raise _SampleNodeFailure("INVALID_HANDLER_INPUT")
    raise _SampleNodeFailure("SAMPLE_FAILURE")


_DEFINITIONS: dict[str, NodeDefinition] = {
    "sample.constant": NodeDefinition(
        outputs={"text": Port("text")},
        config_model=_ConstantConfig,
    ),
    "sample.prefix": NodeDefinition(
        inputs={"text": Port("text", required=True)},
        outputs={"text": Port("text")},
        config_model=_PrefixConfig,
    ),
    "sample.join": NodeDefinition(
        inputs={
            "left": Port("text", required=True),
            "right": Port("text", required=True),
        },
        outputs={"text": Port("text")},
        config_model=_JoinConfig,
    ),
    "sample.fail": NodeDefinition(
        inputs={"text": Port("text", required=True)},
        outputs={"text": Port("text")},
    ),
}

_HANDLERS: dict[str, _SampleHandler] = {
    "sample.constant": _constant,
    "sample.prefix": _prefix,
    "sample.join": _join,
    "sample.fail": _fail,
}


def validate_sample_document(data: bytes) -> ParsedWorkflowDocument:
    """Validate against the fixed sample catalog without running its handlers."""
    return parse_workflow_document(
        data,
        _DEFINITIONS,
        _GRAPH_LIMITS,
        max_bytes=MAX_SAMPLE_DOCUMENT_BYTES,
    )


def _topological_order(
    plan_nodes: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[str, ...]:
    positions = {node_id: index for index, (node_id, _) in enumerate(plan_nodes)}
    children: dict[str, list[str]] = {node_id: [] for node_id in positions}
    remaining = {node_id: len(dependencies) for node_id, dependencies in plan_nodes}
    for node_id, dependencies in plan_nodes:
        for dependency in dependencies:
            children[dependency].append(node_id)

    ready = [
        (positions[node_id], node_id)
        for node_id, count in remaining.items()
        if count == 0
    ]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for child in children[node_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, (positions[child], child))
    if len(ordered) != len(plan_nodes):
        # The dependency planner validates cycles; keep this fail-closed if its
        # contract changes or becomes inconsistent.
        raise InvalidWorkflowGraph(
            [ValidationIssue("CYCLE", "Graph contains a directed cycle")]
        )
    return tuple(ordered)


def _validated_config(node: Node) -> BaseModel | None:
    model = _DEFINITIONS[node.type].config_model
    if model is None:
        return None
    try:
        return model.model_validate(dict(node.config), strict=True, extra="forbid")
    except (ValidationError, TypeError, ValueError):
        # The document parser already validated this config. Do not expose its
        # content if a trusted model behaves inconsistently between validations.
        raise _SampleNodeFailure("INVALID_HANDLER_CONFIG") from None


def _validate_outputs(
    node: Node, outputs: Mapping[str, str], total_output_bytes: int
) -> tuple[tuple[tuple[str, str], ...], int] | str:
    expected = _DEFINITIONS[node.type].outputs
    if set(outputs) != set(expected) or any(
        port.type != "text" for port in expected.values()
    ):
        return "INVALID_HANDLER_OUTPUT"

    normalized: list[tuple[str, str]] = []
    output_bytes = 0
    for port_name in sorted(outputs):
        value = outputs[port_name]
        if type(value) is not str:
            return "INVALID_HANDLER_OUTPUT"
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            return "INVALID_HANDLER_OUTPUT"
        if size > MAX_SAMPLE_OUTPUT_VALUE_BYTES:
            return "OUTPUT_VALUE_LIMIT_EXCEEDED"
        output_bytes += size
        normalized.append((port_name, value))
    if total_output_bytes + output_bytes > MAX_SAMPLE_TOTAL_OUTPUT_BYTES:
        return "TOTAL_OUTPUT_LIMIT_EXCEEDED"
    return tuple(normalized), output_bytes


def evaluate_sample_graph(data: bytes) -> SampleEvaluation:
    """Evaluate the fixed text-only sample catalog without persistence or effects.

    Graph size is limited to 32 nodes, 48 edges and 32 KiB of input JSON.
    Successful outputs are limited to 8 KiB per value and 16 KiB total.
    """
    plan = create_dependency_plan(
        data,
        _DEFINITIONS,
        _GRAPH_LIMITS,
        max_bytes=MAX_SAMPLE_DOCUMENT_BYTES,
    )
    parsed = validate_sample_document(data)
    if parsed.issues:
        raise InvalidWorkflowGraph(parsed.issues)

    plan_nodes = tuple((node.node_id, node.dependencies) for node in plan.nodes)
    execution_order = _topological_order(plan_nodes)
    nodes = {node.id: node for node in parsed.graph.nodes}
    inputs: dict[str, dict[str, tuple[str, str]]] = {
        node.id: {} for node in parsed.graph.nodes
    }
    for edge in parsed.graph.edges:
        inputs[edge.target][edge.target_port] = (edge.source, edge.source_port)

    result_by_id: dict[str, SampleNodeResult] = {}
    outputs_by_id: dict[str, dict[str, str]] = {}
    total_output_bytes = 0
    results: list[SampleNodeResult] = []

    for node_id in execution_order:
        node = nodes[node_id]
        connected = inputs[node_id]
        if any(
            result_by_id[source].status != "succeeded"
            for source, _ in connected.values()
        ):
            result = SampleNodeResult(node_id, "skipped", error_code="UPSTREAM_FAILED")
        else:
            handler_inputs = {
                port_name: outputs_by_id[source][source_port]
                for port_name, (source, source_port) in connected.items()
            }
            try:
                produced = _HANDLERS[node.type](
                    _validated_config(node), handler_inputs
                )
            except _SampleNodeFailure as error:
                result = SampleNodeResult(
                    node_id, "failed", error_code=error.code
                )
            else:
                validated = _validate_outputs(node, produced, total_output_bytes)
                if isinstance(validated, str):
                    result = SampleNodeResult(
                        node_id, "failed", error_code=validated
                    )
                else:
                    node_outputs, output_bytes = validated
                    outputs_by_id[node_id] = dict(node_outputs)
                    total_output_bytes += output_bytes
                    result = SampleNodeResult(
                        node_id, "succeeded", outputs=node_outputs
                    )
        results.append(result)
        result_by_id[node_id] = result

    return SampleEvaluation(plan.revision, execution_order, tuple(results))
