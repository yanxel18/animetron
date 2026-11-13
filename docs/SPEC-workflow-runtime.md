# Spec: workflow-runtime

Status: Approved for implementation on November 14, 2026.
Depends on: platform-core.

## Objective

Execute typed immutable DAG revisions durably while exposing truthful run and
node progress, cancellation and recovery.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_workflow_runtime.py -q`.
Ownership: workflow/run entities, `app/services/workflows`, `app/tasks`.

## Code style and provider contracts

Inherit shared style. Workflow JSON includes schemaVersion, revision, nodes
with typed configs, and edges identifying source/target ports. Backend node
definitions own config/input/output schemas; frontend cannot redefine validity.

- Workflow create/read/update endpoints under `/api/v1/workflows`.
- `POST /api/v1/workflows/{id}/validations`: structured node/port errors.
- `POST /api/v1/workflows/{id}/runs`: immutable revision and stable
  Idempotency-Key; return 202 + runId + status location.
- `GET /api/v1/runs/{id}` and `/events?afterSequence=...`: durable state/replay.
- `POST /api/v1/runs/{id}/cancellations`: cooperative cancellation intent.
- `GET /api/v1/runs/{id}/events/ws`: authenticated live ordered events.
- Provider `NodeHandler`: typed inputs/config, artifact outputs, progress,
  cancellation checks and typed failures.

Run states: QUEUED, RUNNING, WAITING_REVIEW, SUCCEEDED, PARTIAL_FAILURE, FAILED,
CANCELLING, CANCELLED. Review decisions and publication states are separate
domain records, not overloaded generation success.

## Testing and acceptance criteria

1. Reject cycles, dangling/duplicate ids, invalid ports/configs, oversized graphs
   and missing required inputs before enqueue; deterministic handlers demonstrate
   fan-out/join and failure/skip policies.
2. Persist snapshot, node intents and outbox atomically. Duplicate messages
   cannot commit duplicate effects; leases use fencing and unique intent keys.
   Restart recovery distinguishes confirmed failure from unknown external effect.
3. Reconnect replays ordered persisted events without losing terminal state.
   Cancellation prevents downstream dispatch and records in-flight effects.

## Boundaries

Inherit shared boundaries. One GPU admission slot covers all GPU-consuming
engines, including Ollama when GPU-enabled. Do not start a replacement GPU job
solely because a lease expired; establish engine termination/reconciliation.
Queues carry ids, not media binaries. Never keep a worker blocked on human
approval. Retry only classified safe/transient failures with bounded backoff.
