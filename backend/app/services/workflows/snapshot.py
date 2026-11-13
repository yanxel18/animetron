import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from app.services.workflows.document import parse_workflow_document
from app.services.workflows.validation import (
    GraphLimits,
    NodeDefinition,
    ValidationIssue,
)


class InvalidWorkflowGraph(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("Workflow graph is invalid")
        self.issues = tuple(issues)


@dataclass(frozen=True)
class WorkflowSnapshot:
    revision: str
    canonical_json: bytes
    sha256: str


def create_snapshot(
    data: bytes,
    definitions: Mapping[str, NodeDefinition],
    limits: GraphLimits,
    *,
    max_bytes: int,
) -> WorkflowSnapshot:
    parsed = parse_workflow_document(data, definitions, limits, max_bytes=max_bytes)
    if parsed.issues:
        raise InvalidWorkflowGraph(parsed.issues)
    document = {
        "schemaVersion": 1,
        "revision": parsed.revision,
        "nodes": [
            {"id": node.id, "type": node.type, "config": node.config}
            for node in parsed.graph.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "source": edge.source,
                "sourcePort": edge.source_port,
                "target": edge.target,
                "targetPort": edge.target_port,
            }
            for edge in parsed.graph.edges
        ],
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return WorkflowSnapshot(
        revision=parsed.revision,
        canonical_json=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
