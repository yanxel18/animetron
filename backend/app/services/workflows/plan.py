from collections.abc import Mapping
from dataclasses import dataclass

from app.services.workflows.document import parse_workflow_document
from app.services.workflows.snapshot import InvalidWorkflowGraph
from app.services.workflows.validation import GraphLimits, NodeDefinition


@dataclass(frozen=True)
class PlannedNode:
    node_id: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class DependencyPlan:
    revision: str
    nodes: tuple[PlannedNode, ...]


def create_dependency_plan(
    data: bytes,
    definitions: Mapping[str, NodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> DependencyPlan:
    document = parse_workflow_document(data, definitions, limits, max_bytes=max_bytes)
    if document.issues:
        raise InvalidWorkflowGraph(document.issues)

    order = {node.id: index for index, node in enumerate(document.graph.nodes)}
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in order}
    for edge in document.graph.edges:
        dependencies[edge.target].add(edge.source)
    return DependencyPlan(
        revision=document.revision,
        nodes=tuple(
            PlannedNode(node_id, tuple(sorted(parents, key=order.__getitem__)))
            for node_id, parents in dependencies.items()
        ),
    )
