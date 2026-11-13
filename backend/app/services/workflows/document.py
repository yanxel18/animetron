import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.services.workflows.validation import (
    Edge,
    Graph,
    GraphLimits,
    Node,
    NodeDefinition,
    ValidationIssue,
    validate_graph,
)


class InvalidWorkflowDocument(ValueError):
    pass


class _DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Node(_DocumentModel):
    id: str
    type: str
    config: dict[str, JsonValue]


class _Edge(_DocumentModel):
    id: str
    source: str
    source_port: str = Field(alias="sourcePort")
    target: str
    target_port: str = Field(alias="targetPort")


class _Document(_DocumentModel):
    schema_version: Annotated[int, Field(alias="schemaVersion", ge=1, le=1)]
    revision: Annotated[str, Field(min_length=1)]
    nodes: list[_Node]
    edges: list[_Edge]


@dataclass(frozen=True)
class ParsedWorkflowDocument:
    revision: str
    graph: Graph
    issues: list[ValidationIssue]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidWorkflowDocument("Duplicate JSON key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise InvalidWorkflowDocument("Non-finite JSON number")
    return result


def _reject_constant(value: str) -> None:
    raise InvalidWorkflowDocument("Non-finite JSON number")


def parse_workflow_document(
    data: bytes,
    definitions: Mapping[str, NodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> ParsedWorkflowDocument:
    if max_bytes < 1:
        raise ValueError("Document byte limit must be positive")
    if len(data) > max_bytes:
        raise InvalidWorkflowDocument("Workflow document exceeds byte limit")
    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=_finite_float,
            parse_constant=_reject_constant,
        )
        document = _Document.model_validate(payload)
        if not document.revision.strip():
            raise InvalidWorkflowDocument("Workflow revision must not be blank")
    except (UnicodeDecodeError, ValueError, ValidationError, RecursionError):
        raise InvalidWorkflowDocument("Workflow document is invalid") from None

    graph = Graph(
        nodes=[Node(node.id, node.type, node.config) for node in document.nodes],
        edges=[
            Edge(edge.id, edge.source, edge.source_port, edge.target, edge.target_port)
            for edge in document.edges
        ],
    )
    return ParsedWorkflowDocument(
        revision=document.revision,
        graph=graph,
        issues=validate_graph(graph, definitions, limits),
    )
