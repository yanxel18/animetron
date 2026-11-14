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

## Bounded internal P1-09a contract

`app.services.workflows.run_requests.request_run(connection, request_id,
workflow_id, revision, expected_sha256)` is persistence only. The caller retains
one RFC-variant UUID4 request ID per intent, supplies the exact workflow UUID,
revision identifier and lowercase SHA-256 of the stored immutable snapshot.
It returns frozen `RunRequest` metadata: request ID, server-generated UUID4 run
ID, workflow ID, revision, SHA-256, and creation timestamp. No caller-supplied
run ID, role, principal or source path is accepted.

Use an explicit SQLAlchemy transaction backed by non-AUTOCOMMIT psycopg at
READ COMMITTED. The caller owns commit/rollback, bounded statement/lock timeouts
and whole-transaction retries after serialization/deadlock errors. A unique
request claim serializes duplicate callers (waiting until the winner commits or
rolls back). An inner savepoint covers the claim, canonical
`create_run_with_revision`, initial event and one reserved outbox insert, so a
caller catching any failure can commit unrelated outer work safely.

The outbox ID is the request ID, topic `internal.workflow-run-requested.v1`,
resource ID the generated run ID. It is an INTERNAL notification, **not an
execution/dispatcher intent**. A reserved ID collision fails; existing low-level
runs/intents are never adopted. Same ID plus exact payload replays the same
checked metadata; changed workflow/revision/digest raises `RunRequestConflict`.
The existing revision loader checks stored bytes against their digest; a
different expected digest raises `RunRequestConflict`. Missing/corrupt snapshot
errors propagate. Replay verifies the run, exact revision binding, original
QUEUED event and reserved topic/resource evidence; missing or inconsistent
evidence raises `RunRequestCorrupt`, without promotion or repair. Later run
state transitions and outbox delivery do not change request metadata.

The request association is retained indefinitely: **no automatic expiry or
deletion**. Database constraints and a mutation guard preserve request identity,
payload and run association. Privileged database tampering remains outside the
trust boundary; hashes are integrity checks, not authorization proofs.
Downgrading the request migration destroys replay evidence and requires explicit
authorization/recovery planning for populated databases.

This slice implements no HTTP/auth, workflow CRUD, graph revalidation, node
intents, scheduler/due slots, relay/consumer, handlers, inference or external
effects. P1-08 handler implementation, configuration-default and model-revision
pinning remain prerequisites to EXECUTION; a stored request proves none of them.

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
