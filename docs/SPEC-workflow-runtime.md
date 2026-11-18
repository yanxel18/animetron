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

## Owner-only immutable workflow revision read (P1-09b)

`GET /api/v1/workflows/{id}/revisions/{revision}` reads one already-known
immutable revision through the persisted `get_revision` integrity-checked
service. It returns exactly
`{ "workflowId": "<UUID>", "revision": "<revision>",
"canonicalJson": "<exact stored canonical JSON bytes decoded as ASCII>",
"sha256": "<lowercase SHA-256 of canonicalJson>" }`. `canonicalJson` preserves
the exact persisted bytes so callers can independently verify the digest.

The route accepts no query parameters. The workflow ID must parse as a UUID;
the revision identifier uses the existing validator and is bounded to 1–128
characters. Malformed identifiers or query parameters return the standard
generic `422`; unauthenticated or stale sessions return `401`; non-owner
roles are denied with `403` before revision lookup; an absent revision returns
`404`. Missing auth/database configuration, database failures, and revision
integrity failures fail closed with the standard generic `503` envelope;
responses never expose stored content or internal failure details on errors.
Successful and error responses retain the shared security headers and
`Cache-Control: no-store`; the route reuses the fresh-session and exact-origin
owner dependency.

This is a read of one addressed revision only. It adds no workflow create,
list, update, delete, validation, execution, scheduling, model, or publishing
behavior, and does not claim workflow editing is available.

## Owner-only bounded workflow revision discovery (P1-09c)

`GET /api/v1/workflows/{id}/revisions?cursor=<opaque>&limit=50` discovers
metadata for already-persisted immutable revisions. It returns exactly
`{ "data": [{ "workflowId": "<UUID>", "revision": "<revision>",
"createdAt": "<timezone-aware UTC timestamp>" }], "nextCursor": "<opaque>" }`.
`nextCursor` is `null` when the response has no additional row. The list never
returns canonical workflow JSON or other revision content; callers that need
to verify or inspect a selected revision use the query lookup described below.
An unknown workflow ID returns an empty page rather than distinguishing an
absent workflow from one with no stored revisions.

The stable exact order is `created_at DESC`, then `revision DESC` using the
PostgreSQL collation configured for the `revision` column. The unique
`(workflow_id, revision)` key makes every position distinct. The
opaque, versioned URL-safe cursor is bound to the path workflow UUID and
contains the final returned row's timestamp and revision. It is exclusive:
the next query returns positions strictly after that pair in the stated
descending order. Pages use an indexed keyset query and fetch no more than
`limit + 1` rows; there is no count query or offset scan. Inserting a newer
revision does not shift positions already returned and cannot duplicate an
already-returned row. This is not a cross-request database snapshot: a new row
that sorts before the current cursor is not included in the remainder of that
traversal; clients refresh from the first page to discover newer revisions.

`limit` defaults to `50`, accepts ASCII decimal digits only (up to 3 encoded
characters), and is bounded to `1..100`; leading zeroes are accepted only
within that encoded-length bound. `cursor` is optional and, when present,
must be one canonical cursor of at most 2304 URL-safe characters for the same
workflow. Unknown or repeated query parameters, malformed UUIDs, malformed or
foreign cursors, and invalid limits return the standard generic `422`.
Unauthenticated or stale sessions return `401`; non-owner roles return `403`
before revision lookup. Database failures or invalid stored revision metadata
fail closed with the generic `503` envelope; successful and error responses
retain the shared security headers and `Cache-Control: no-store`.

This endpoint discovers persisted immutable revision metadata only. It adds no
workflow draft editing, create/update/delete, validation, execution,
scheduling, publishing, or model-readiness behavior. Listing a revision does
not assert that it is runnable or model-ready.

`GET /api/v1/workflows/{id}/revision?revision=<identifier>` retrieves the same
integrity-checked response as P1-09b, with identical authorization and error
semantics. The exact identifier is supplied as a single URL-encoded query value
so valid identifiers containing slashes or dot segments remain addressable;
missing, repeated, unknown or invalid parameters return `422`. The earlier
path-based read remains available for identifiers representable in a path.

## Owner-only workflow ID discovery (P1-09d)

`GET /api/v1/workflows?limit=50&cursor=<opaque>` returns exactly
`{ "data": [{ "workflowId": "<UUID>" }], "nextCursor": "<opaque>" }`,
where `nextCursor` is `null` on the final page.
Only IDs with at least one persisted revision appear, once each. No name,
draft, timestamp, content, validity, runnability, or readiness is implied.
The ascending PostgreSQL UUID order is stable. A versioned canonical URL-safe
cursor encodes the last returned UUID; it is exclusive, is not a snapshot or
an authorization credential, and need not refer to an existing row. New IDs
after the cursor may appear in subsequent pages; new IDs at or before it are
missed until refresh. New revisions for an existing ID do not duplicate it.

The primary key `(workflow_id, revision)` supports successive ordered index
seeks, one per distinct ID, bounded to `limit + 1` probes/rows, rather than a
distinct/group scan through every revision. There is no offset or count query.
PostgreSQL may choose a different execution plan, and physical index/heap work
is not a strict constant bound under MVCC, bloat, or concurrent activity.
`limit` defaults to 50, is ASCII decimal, 1..100, at most three characters
(leading zeroes allowed). The optional cursor is 1..128 URL-safe characters,
canonical and versioned. Unknown or repeated parameters and invalid cursors or
limits return generic 422. Missing or stale authentication returns 401; other
roles return 403 before lookup. Persistence failures return generic 503.
All responses retain shared security headers and `Cache-Control: no-store`.
This is discovery only, with no writes, execution, scheduling, model, or
publication behavior.

## Owner-only idempotent run creation (P1-09i)

`POST /api/v1/workflows/{id}/runs` accepts exactly
`{ "revision": "<existing immutable revision identifier>" }` and one
`Idempotency-Key` header containing a canonical lowercase RFC-variant UUID4.
The client creates the key once per run intent and reuses it on retries. The
body is strict JSON, limited to 4,096 bytes, and the request accepts no query
parameters. The revision identifier uses the existing 1..128-character
validator.

The endpoint reads and integrity-checks the addressed immutable revision, then
calls the internal run-request service in the same caller-owned transaction.
The service atomically claims the key, associates one new run with that exact
revision and digest, records the initial `QUEUED` event, and adds one reserved
internal outbox notification. That notification is not a dispatcher or
execution intent. No caller-supplied run ID or digest is accepted.

Success returns `202` with exactly `{ "runId": "<UUID>" }` and a relative
`Location: /api/v1/runs/{runId}` status link. Replaying the same key with the
same workflow and revision returns the same run ID and location; reusing the
key for a different workflow or revision returns `409` when the addressed
revision exists. A missing revision returns `404` before the run-request
service is called; malformed input or headers return generic `422`;
unauthenticated or stale sessions return `401`; non-owner, origin or CSRF
failures return `403`; corrupt stored state or persistence failures return
generic `503`. Responses retain shared security headers and
`Cache-Control: no-store`.

This endpoint requests a run against an existing immutable revision only. It
does not create or edit workflows or revisions, validate mutable drafts,
execute handlers, dispatch an outbox message, or authorize model readiness or
external effects.

## Owner-only mutable workflow draft read (P1-09f)

`GET /api/v1/workflows/{id}/draft` reads one stored draft and returns exactly
`{ "workflowId": "<UUID>", "document": "<UTF-8 draft text>",
"version": <positive integer> }`. `document` is the stored UTF-8 bytes decoded
as text; it is not parsed, normalized, validated, or required to be complete.
The version supports later compare-and-swap updates but this endpoint does not
write drafts.

The route accepts no query parameters and reuses the fresh-session,
exact-origin owner dependency. A malformed workflow UUID or any query parameter
returns the standard generic `422`; unauthenticated or stale sessions return
`401`; non-owner roles return `403` before draft lookup; an absent draft returns
`404`. Database failures or invalid stored draft metadata fail closed with the
generic `503` envelope. Successful and error responses retain the shared
security headers and `Cache-Control: no-store`.

This endpoint exposes only an existing mutable draft. It adds no workflow
creation, update, deletion, validation, immutable revision, execution,
scheduling, publishing, or model-readiness behavior.

## Owner-only mutable workflow draft write (P1-09g)

`PUT /api/v1/workflows/{id}/draft` accepts exactly
`{ "document": "<UTF-8 draft text>", "expectedVersion": null | <integer> }`
and returns the same `{ "workflowId": "<UUID>", "document": "<UTF-8 draft
text>", "version": <positive integer> }` shape as P1-09f. Extra fields are
rejected. The document is stored as UTF-8 without parsing, normalization,
validation, or a completeness requirement. Its encoded size is limited to
32,768 bytes; the bounded outer JSON request is limited to 262,144 bytes.

`expectedVersion: null` creates a draft at version 1 only when no draft exists.
A positive expected version updates only a draft at that version and increments
the version by one. A stale version, or a create for an existing draft, returns
`409`; updating a missing draft returns `404`. The compare-and-swap is the
retry-safety mechanism; clients that receive a conflict after an uncertain
response must read the draft to reconcile state. The accepted expected-version
range is 1 through 2,147,483,646.

The route reuses the fresh-session, exact-origin owner dependency and requires
the normal `Origin` and CSRF headers for `PUT`. It accepts no query parameters,
requires JSON with identity content encoding, and retains shared security
headers and `Cache-Control: no-store`. Malformed input, an oversized document
or request, unsupported headers, invalid UTF-8 text, or an unknown query
parameter returns generic `422`; unauthenticated or stale sessions return
`401`; non-owner, origin or CSRF failures return `403`; database failures or
invalid stored draft metadata fail closed with generic `503`.

This endpoint writes only the mutable draft row within one database
transaction. It does not create an immutable revision or workflow entity, and
adds no workflow validation, deletion, execution, scheduling, publishing, or
model-readiness behavior.

## Owner-only mutable workflow draft validation (P1-09h)

`POST /api/v1/workflows/{id}/validations` accepts exactly
`{ "expectedVersion": <positive integer> }` and validates the stored draft only
when its version matches. The accepted version range is 1 through
2,147,483,646. A stale version returns `409`; a missing draft returns `404`.
The response is
`{ "workflowId": "<UUID>", "draftVersion": <positive integer>,
"isValid": <boolean>, "issues": [...] }`.

The current backend-owned catalog is the fixed text-only sample catalog from
P1-10b, bounded to 32 nodes, 48 edges and 32 KiB of draft UTF-8 text. Validation
does not execute sample handlers. Each issue returns a stable `code`,
human-readable `message`, and only the applicable identifiers among `nodeId`,
`edgeId`, `sourcePort` and `targetPort`. A well-formed graph with validation
issues returns `200` with `isValid: false`; a valid graph returns `200` with
`isValid: true` and an empty issue list. Invalid JSON, unsupported document
shape, or other parse failures return one generic `INVALID_DOCUMENT` issue
without echoing draft content.

The request uses the fresh-session, exact-origin owner dependency and requires
JSON, identity content encoding, `Origin` and CSRF headers. The bounded request
is limited to 256 KiB; unknown fields or query parameters return generic
`422`. Unauthenticated or stale sessions return `401`; non-owner, origin or
CSRF failures return `403`. Corrupt stored draft metadata or database failures
fail closed with generic `503`. Responses retain the shared security headers
and `Cache-Control: no-store`.

Validation is read-only and applies to one observed draft version. No
validation result is persisted; this endpoint creates no immutable revision,
workflow entity, run, or external effect.

## Authenticated read-only run status and event replay (P1-11a)

The owner-only, authenticated HTTP contract exposes only persisted workflow-run
state and ordered events:

- `GET /api/v1/runs/{id}` returns exactly
  `{ "runId": "<UUID>", "state": "<RunState>", "lastSequence": <integer> }`.
- `GET /api/v1/runs/{id}/events?afterSequence=0&limit=50` returns exactly
  `{ "data": [{ "runId": "<UUID>", "sequence": <integer>, "state":
  "<RunState>", "message": "<plain JSON string>", "occurredAt":
  "<timezone-aware UTC timestamp>" }], "nextAfterSequence": <integer>,
  "hasMore": <boolean> }`.

The `afterSequence` cursor is exclusive, defaults to `0`, and is bounded to
`0..2147483647`. `limit` defaults to `50` and is bounded to `1..100`. Decimal
values accept ASCII digits only, at most 10 characters for the cursor and 3
for the limit; leading zeroes are accepted within those encoded lengths.
Unknown or repeated query parameters, malformed UUIDs, and invalid bounds
return the standard generic `422` error. Event reads request at most
`limit + 1` stored rows; only the first `limit` are returned. `hasMore` reports
whether that extra row exists. `nextAfterSequence` is the final returned
sequence, or the input cursor when the page is empty. A future cursor is not
clamped: an empty page retains it and reports `hasMore: false`, so the caller
can poll with the same cursor later. `hasMore: false` is not a terminal-run
signal.

Both routes reuse the existing fresh-session, exact-origin, owner dependency.
Unauthenticated requests return `401`, non-owner roles return `403` before
run lookup, and missing runs return `404`. Disabled auth/database
configuration fails closed with the standard `503` envelope. Responses use
the standard security/no-store headers and never expose session, auth,
configuration, artifact-byte or filesystem-path data. Event messages remain
untrusted plain JSON text: consumers must not interpret them as HTML or
instructions, and future event producers remain responsible for redaction.

These are domain-read-only endpoints; existing session authentication may
update its last-seen timestamp. Reads do not require model readiness, dispatch,
or execution claims and do not start, cancel, recover, or report simulated
execution progress. They return only the durable state and event rows already
stored. This contract does not add node state, a journal, or WebSockets.

## Cooperative cancellation intent (P1-11b)

`POST /api/v1/runs/{id}/cancellations` is an owner-only, CSRF-protected
request with no body or query parameters. For `QUEUED`, `RUNNING`, or
`WAITING_REVIEW` runs, it atomically transitions the run to `CANCELLING` and
enqueues one stable `internal.workflow-run-cancellation-requested.v1` outbox
intent in the caller-owned transaction. The `202` response contains exactly
`{ "runId": "<UUID>", "state": "CANCELLING", "lastSequence": <integer>,
"outcome": "REQUESTED" }`.

Retries while already `CANCELLING` return the same state and sequence with
`outcome: "ALREADY_REQUESTED"` and do not enqueue a duplicate. A previously
`CANCELLED` run returns `outcome: "ALREADY_CANCELLED"` without another intent.
Successful cancellation requests use `202`; missing runs return `404`, terminal
non-cancelled runs return generic `409`, invalid identifiers or query
parameters return generic `422`, and inconsistent persisted intent state or
unavailable dependencies fail closed with generic `503`. The route reuses the
fresh-session, exact-origin, owner and CSRF dependencies and standard security
headers.

`CANCELLING` records an accepted cooperative request, not worker termination.
This slice does not interrupt a handler, mark a run `CANCELLED`, or reconcile
unknown external effects; a future worker must confirm termination and record
the terminal state.

## Bounded internal P1-08a value contract

`app.services.workflows.execution_snapshot.create_execution_snapshot(data,
catalog, limits, max_bytes=...)` builds a distinct internal `ExecutionSnapshot`,
not a v1 `WorkflowSnapshot`. The trusted backend caller selects an approved
catalog mapping node types to `ExecutionNodeDefinition`: existing
`NodeDefinition`, `HandlerArtifact` (opaque artifact ID and exact lowercase
SHA-256), and a tuple of existing `ModelManifest` values. Catalog selection is
trusted; clients supply only the existing v1 graph document, never pins or
default overrides. Artifact IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`.
Unknown node types and missing pins fail closed.

The canonical JSON object has `kind: "internal.workflow-execution"`,
`schemaVersion: 1`, `revision`, `nodes`, `edges`, and `nodePins` keyed by every
node ID. Each pin contains `handler: {artifactId, sha256}` and
`pinnedModelManifest`, an ordered list of complete manifests: `reference`
(`provider`, `repository`, exact commit `revision`), `engine`, `license_id`,
`files` (`path`, `size`, `sha256`) and `estimated_bytes`. Empty model lists
explicitly mean no model dependency; absence of a node pin is never acceptable.

Node configs are validated with the backend model using strict types and
`extra="forbid"`. Materialized defaults are validated too; omitted, invalid,
non-JSON or non-finite defaults must not silently repair invalid input.
Configuration keys serialize using model serialization aliases, consistently
for defaults and explicit inputs (including nested models and validation alias
choices/paths). Empty serialization aliases are valid keys, not absent aliases;
colliding aliases fail. Validation that transforms explicit or materialized
default values is rejected, comparing native JSON value types recursively
(`true`, `1` and `1.0` are distinct) against an independent prevalidation copy,
rather than relying on Python numeric equality. Serialization reads actual
model fields, including excluded fields; custom serializers cannot conceal an invalid default or
introduce executable content. Only JSON-native values are accepted; JSON
encoding never invokes a fallback string conversion. Nodes without a config
model still accept only empty config. Selected config models/validators/default
factories are trusted backend code and must be deterministic and side-effect
free; this builder is not a sandbox.

Encoding uses sorted object keys, compact separators, ASCII JSON escapes and
finite numbers, preserving node/edge/model/file order. SHA-256 covers every
canonical byte, including revision, full graph, resolved configs and all pins.
The frozen value retains only bytes, with its digest derived from those bytes:
mutating caller catalog/default/port/config objects cannot mutate a value.
Both original input bytes and generated canonical bytes must fit `max_bytes`
exactly; defaults, aliases, metadata and Unicode escaping may expand output.
Existing document/graph failures remain typed; resolved value/config failures
use `InvalidExecutionSnapshot` without echoing config contents. Invalid catalog
records raise `InvalidExecutionSnapshot`; the reused SHA validator raises
`ValueError` for malformed artifact digests.

This is a pure value/serialization contract, with no decoder or runtime loader.
Existing v1 create/parse/save/run APIs and behavior are unchanged: legacy
snapshots are never automatically promoted. No durable binding, migration,
node intents, HTTP/auth, registry readiness, downloads, network, executable
configuration, URLs, dynamic code import or pickle loading is added. Artifact
IDs are opaque labels, not paths, URLs or import instructions. SHA metadata is
neither authorization nor proof of installed code; future runtime enforcement
must verify the installed artifact against its pin and enforce model readiness.
This P1-08a value alone does not provide durable binding or enforcement.

## Bounded internal P1-08b binding contract

The internal binding service accepts a caller-owned connection, workflow UUID,
revision, exact expected source SHA-256, trusted catalog, limits and byte limit.
It reads the checked stored revision through `get_revision`, rejects missing,
corrupt or mismatched source, and builds only from those stored bytes using
`create_execution_snapshot`. It accepts no caller-deserialized execution value.
One immutable row per workflow and revision retains the source SHA, exact
execution bytes and SHA, and server creation time; returned metadata is frozen.
An atomic unique insert serializes contenders. Exact retry replays the checked
record; changed defaults, configuration, handler or model metadata conflict.
Never overwrite, repin, adopt or repair: a new revision is required.

The internal checked load validates both stored digests, association with the
current checked source revision, and execution revision and kind without
consulting current catalog or defaults. Unbound legacy revisions are not
promoted. Hashes are integrity checks, not authorization or provenance;
privileged SQL is outside the trusted-writer boundary. No decoder loads code.
Calls require an explicit non-autocommit psycopg transaction; an inner
savepoint preserves unrelated outer work on failure. The caller owns commit,
timeouts and whole-transaction retries at READ COMMITTED. No runs, nodes or
outbox effects are created. P1-08 remains incomplete until runtime enforcement.

Downgrading a populated binding table destroys replay evidence and requires
explicit authorization and a recovery plan. Destructive migration tests run
only against the harness-owned disposable database.

## P1-08c pre-execution readiness gate (approved 2026-11-18)

This slice enforces the installed-code and model pins retained by a
checked execution binding before any workflow node handler starts. It does not
acquire models or execute handlers.

The owner confirmed on 2026-11-18 that handler resolution uses a trusted
server-owned catalog and readiness failures persist a terminal `FAILED` run
before node dispatch.

The trusted runtime loads the stored binding through
`get_execution_binding` and verifies the source revision association and both
digests. Before starting any node, it preflights every node in the immutable
execution snapshot:

- Resolve each `artifactId` through a server-owned handler catalog. The
  installed artifact digest must exactly match the node's pinned lowercase
  SHA-256. The resolver returns an opaque handle bound to that verified
  artifact; workflow data cannot provide a path, module name, URL or import
  instruction.
- Resolve each pinned model using its full immutable provider, repository and
  revision identity. The registry must report `READY` and the resolved
  manifest (engine, license identifier and complete file path/size/digest set)
  must exactly match the snapshot. An Ollama engine or matching model tag alone
  does not establish readiness; the exact pinned local model and file
  integrity must be verified by the registry.
- Complete the whole-graph preflight before invoking any handler. If any pin is
  missing, mismatched or not ready, invoke no handlers and create no node
  intents or execution outbox work. The existing run-request notification
  remains non-executable.

On failure, persist the run as `FAILED` with a typed, non-sensitive readiness
reason before node dispatch. Do not repair or repin the binding, choose a
fallback handler/model, or infer readiness from a directory, Ollama
availability, or a model tag. This guard never pulls models, fetches artifacts,
accepts licenses, or uses credentials. If acquisition is later needed, it is a
separate model-registry task subject to its license, access and resource gates.
A fully ready preflight returns the verified opaque handles to the dispatcher;
dispatch and handler execution remain separate work.

The trusted handler catalog is an injected server-side dependency. This slice
consumes only verified digest-bound handles; artifact installation, packaging
and filesystem layout are outside its scope. Workflow data must never select
those locations or load executable code.

Focused tests must prove exact handler/model matches pass, missing or changed
pins fail closed, and one unready node prevents every handler from starting.
Tests use fake trusted catalogs and readiness results; they perform no model
downloads or external requests.

This contract was approved by the owner on 2026-11-18. Implement the gate
before enabling node dispatch; this approval does not authorize model downloads,
artifact fetching or external effects.

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

## P1-10d node admission contract (approved 2026-11-18)

The owner approved this contract for implementation on 2026-11-18. It is the
first durable worker-facing building block, not a running worker. The existing
run-request notification remains non-executable; this proposal does not add a
consumer for it or change the meaning of any outbox topic.

A caller-owned PostgreSQL transaction may claim one node from an already
prepared run. Admission locks the run row before examining or changing node
state, so it serializes with cancellation. It admits a node only while the run
is `RUNNING`, the node belongs to the persisted plan, and every predecessor has
a persisted successful outcome. Initially only nodes without predecessors are
eligible; this slice does not introduce outcome recording.

The database records a stable caller-supplied UUID4 admission identity and its
run and node association, with uniqueness enforced atomically for both the
identity and node. Reusing the identity for the same association reports an
existing claim, even after cancellation, not permission to invoke the handler
again. Reusing it for a different association fails. A different identity
cannot claim an already claimed node. Cancellation committed before admission
prevents a new claim; admission committed first does not mean that
cancellation has terminated any in-flight work.

No claim expires or is automatically reassigned in this slice. If a claimant
disappears, its outcome is unknown: leave it claimed and require a separately
designed reconciliation path. A database claim or fencing token alone cannot
prove that an external effect did not happen. The caller must commit the claim
before any future execution attempt; the claim itself does not authorize
execution, verify installed handler/model pins, or release a worker from
checking cancellation. A future executor must revalidate exact pins and define
how an already-admitted attempt is stopped or reconciled before it invokes
handlers or effects.

`claim_node(connection, claim_id, run_id, node_id)` returns `CLAIMED` for a new
claim or `ALREADY_CLAIMED` for an exact replay. A different association or an
ineligible node raises `AdmissionConflict`; a non-running run raises
`RunConflict` for a new claim, and a missing run raises `RunNotFound`. A running
run without its expected run-ready outbox record raises `RunDispatchCorrupt`.
The function accepts an explicit non-autocommit psycopg transaction and checks
the claim UUID4 and bounded node ID. Errors propagate rather than triggering
retry. Its savepoint rolls back failed claim operations without committing the
outer transaction.

The implementation must use an additive migration, caller-owned transactions,
parameterized queries and bounded lock/statement timeouts supplied by the
caller. Failed operations must not leave partial claims, even if the caller
catches the error and commits unrelated work. PostgreSQL tests must cover
duplicate identities, competing claimants, rollback, prerequisite gating,
and both cancellation/admission lock orderings. No handler invocation, broker,
model download, external transmission, retry or production deployment is
authorized by this slice.

Completion, failure, skip propagation, fencing of actual execution, and
recovery of unknown effects need separate contracts and are not solved by this
slice. Downgrading the claim migration destroys evidence and requires explicit
authorization and recovery planning on populated databases.

## Bounded internal P1-10b sample evaluator

`app.services.workflows.sample_evaluator.evaluate_sample_graph(data)` is a
pure, local demonstration over workflow-document bytes. It uses the existing
backend-owned document, port and strict config validation and dependency plan.
Its fixed text-only catalog contains `sample.constant` (configured text
output), `sample.prefix` (prefix transform), `sample.join` (left/right join,
default separator `" | "`), and `sample.fail` (deliberate typed failure).
Handlers receive validated Pydantic config values and text inputs by declared
port; successful outputs must contain exactly the declared text ports and
string values.

The evaluator rejects documents over 32,768 bytes and graphs over 32 nodes or
48 edges. It emits at most 8,192 UTF-8 bytes per output value and 16,384 UTF-8
bytes across all successful node outputs. Topological ordering uses original
node declaration order as the tie-break among ready nodes; each node's output
ports are returned in name order. Invalid documents raise the existing
`InvalidWorkflowDocument`; invalid or unsupported graphs raise
`InvalidWorkflowGraph`. `sample.fail` returns a failed node with error code
`SAMPLE_FAILURE`. An output type or per-value/aggregate output-bound violation
fails that node with a stable error code and no partial outputs. Any node with
a failed or skipped predecessor is skipped with `UPSTREAM_FAILED`; independent
nodes continue. These outcomes are returned in deterministic topological
order in the frozen `SampleEvaluation(revision, execution_order, nodes)`;
per-node results contain `node_id`, `status` (`succeeded`, `failed` or
`skipped`), sorted `(port, text)` output tuples and an optional stable
`error_code`. Failed and skipped nodes have no outputs. Unexpected programming
exceptions are not converted into simulated node failures.

This evaluator is not production execution and does not load or verify pinned
handler artifacts or models. It does not claim model readiness, create runs,
persist state, dispatch work, start workers, authorize callers, or perform
external effects. In particular, execution-snapshot handler digests remain
metadata only here; this sample evaluator is not a consumer of that snapshot
or a fulfillment of the P1-08 runtime-enforcement prerequisite.

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
