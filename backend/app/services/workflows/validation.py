from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Port:
    type: str
    required: bool = False


@dataclass(frozen=True)
class NodeDefinition:
    inputs: Mapping[str, Port] = field(default_factory=dict)
    outputs: Mapping[str, Port] = field(default_factory=dict)


@dataclass(frozen=True)
class Node:
    id: str
    type: str


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    source_port: str
    target: str
    target_port: str


@dataclass(frozen=True)
class Graph:
    nodes: Sequence[Node]
    edges: Sequence[Edge]


@dataclass(frozen=True)
class GraphLimits:
    max_nodes: int
    max_edges: int

    def __post_init__(self) -> None:
        if self.max_nodes < 1 or self.max_edges < 1:
            raise ValueError("Graph limits must be positive")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


def validate_graph(
    graph: Graph, definitions: Mapping[str, NodeDefinition], limits: GraphLimits
) -> list[ValidationIssue]:
    if len(graph.nodes) > limits.max_nodes or len(graph.edges) > limits.max_edges:
        return [
            ValidationIssue("GRAPH_TOO_LARGE", "Graph exceeds the configured limits")
        ]

    issues: list[ValidationIssue] = []
    node_counts = Counter(node.id for node in graph.nodes)
    edge_counts = Counter(edge.id for edge in graph.edges)
    for node in graph.nodes:
        if not node.id.strip():
            issues.append(
                ValidationIssue("INVALID_NODE_ID", "Node ID must not be blank", node.id)
            )
        elif node_counts[node.id] > 1:
            issues.append(
                ValidationIssue("DUPLICATE_NODE_ID", "Node ID is duplicated", node.id)
            )
        if node.type not in definitions:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_NODE_TYPE", "Node type is not allowed", node.id
                )
            )

    nodes = {
        node.id: node
        for node in graph.nodes
        if node.id.strip() and node_counts[node.id] == 1
    }
    incoming: Counter[tuple[str, str]] = Counter()
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}

    for edge in graph.edges:
        if not edge.id.strip():
            issues.append(
                ValidationIssue(
                    "INVALID_EDGE_ID", "Edge ID must not be blank", edge_id=edge.id
                )
            )
        elif edge_counts[edge.id] > 1:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_EDGE_ID", "Edge ID is duplicated", edge_id=edge.id
                )
            )
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if source is None:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_SOURCE",
                    "Source node is absent or ambiguous",
                    edge_id=edge.id,
                )
            )
        if target is None:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_TARGET",
                    "Target node is absent or ambiguous",
                    edge_id=edge.id,
                )
            )
        if source is None or target is None:
            continue

        adjacency[source.id].append(target.id)
        indegree[target.id] += 1
        source_def, target_def = (
            definitions.get(source.type),
            definitions.get(target.type),
        )
        if source_def is None or target_def is None:
            continue
        output, input_port = (
            source_def.outputs.get(edge.source_port),
            target_def.inputs.get(edge.target_port),
        )
        if output is None:
            issues.append(
                ValidationIssue(
                    "INVALID_SOURCE_PORT",
                    "Source output port is absent",
                    edge_id=edge.id,
                )
            )
        if input_port is None:
            issues.append(
                ValidationIssue(
                    "INVALID_TARGET_PORT",
                    "Target input port is absent",
                    edge_id=edge.id,
                )
            )
        if output is None or input_port is None:
            continue
        if output.type != input_port.type:
            issues.append(
                ValidationIssue(
                    "INCOMPATIBLE_PORTS", "Port types are incompatible", edge_id=edge.id
                )
            )
            continue
        incoming[(target.id, edge.target_port)] += 1

    for node in nodes.values():
        definition = definitions.get(node.type)
        if definition is None:
            continue
        for port_name, port in definition.inputs.items():
            count = incoming[(node.id, port_name)]
            if port.required and count == 0:
                issues.append(
                    ValidationIssue(
                        "MISSING_REQUIRED_INPUT",
                        f"Required input {port_name} is unconnected",
                        node.id,
                    )
                )
            if count > 1:
                issues.append(
                    ValidationIssue(
                        "MULTIPLE_INPUT_EDGES",
                        f"Input {port_name} has multiple connections",
                        node.id,
                    )
                )

    ready = deque(node_id for node_id, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        node_id = ready.popleft()
        visited += 1
        for target_id in adjacency[node_id]:
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    if visited != len(nodes):
        issues.append(ValidationIssue("CYCLE", "Graph contains a directed cycle"))
    return issues
