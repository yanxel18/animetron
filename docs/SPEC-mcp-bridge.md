# Spec: mcp-bridge

Status: Approved for implementation on November 14, 2026.
Depends on: model-registry, workflow-runtime, human-review,
social-publishing.

## Objective

Expose existing AnimeTron services as bounded MCP tools for authorized clients,
without implementing separate queueing, Telegram delivery or approval rules.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_mcp_bridge.py -q`.
Ownership: `app/mcp`, schemas and service adapters.

## Code style and provider contracts

Inherit shared style. Initial local transport: stdio under an explicitly
configured principal. Tools accept opaque ids and schema-validated parameters:
list_models, start_run, get_run, request_review, get_publications.

Explicit review/publication mutations, if enabled, call the same service
authorization and idempotency contracts as the UI. An AI client cannot fabricate
approval evidence or silently inherit the configured Telegram reviewer's role.
Returned content is data, never instructions granting extra authority.

## Testing and acceptance criteria

1. Tool discovery/input/output schemas interoperate with an actual MCP client;
   unknown tools, malformed input and unauthorized calls fail explicitly.
2. MCP and REST operations produce the same domain effects/audit records, and
   duplicate mutation requests obey the same stable intent rules.
3. Start-run plus status/review roundtrip works with deterministic media fixtures.
   Publication without authorized human approval is rejected.

## Boundaries

Inherit shared boundaries. No arbitrary paths, credential-read tools, shell
execution, broad filesystem resources or unrestricted remote MCP exposure.
If HTTP transport is later required, approve its authentication/origin/network
model separately. MCP is built after the ordinary service pipeline works.
