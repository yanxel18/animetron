# AnimeTron backend

Project-wide progress and remaining work: [task checklist](../tasks/todo.md).

The API provides minimal public liveness and a bounded authenticated control
plane using Keycloak/Authlib and opaque PostgreSQL sessions. See
[AUTH.md](AUTH.md) for explicit fail-closed configuration, versioned routes,
CSRF, audit/readiness/WebSocket and review controls, and security limitations.
Review HTTP access is owner-only and metadata/decision-only. The artifact API
currently exposes only owner-only metadata reads; upload and content delivery
are not implemented.

The internal workflow graph validator checks graph limits, node and edge IDs,
allowlisted node types, port connections, required inputs, and cycles against
caller-supplied definitions. Definitions can also supply Pydantic config models:
validation is strict, unknown fields are rejected, and errors do not echo config
values. Nodes without a config model accept only empty config. This validator is
not exposed as an API or connected to run dispatch. It does not return parsed
config objects; execution must validate config again before use. Workflow
durable execution is not yet implemented. An internal, provisional document
parser accepts UTF-8 JSON with schemaVersion 1, an opaque nonblank revision,
nodes with configs, and camelCase edge ports. Callers must provide byte and
graph limits, check the returned validation issues, and must not treat a parsed
document as an immutable snapshot. Revision identifiers are nonblank UTF-8
strings up to 128 characters and cannot contain NUL. Owner-only workflow
routes provide immutable revision discovery/read and idempotent run creation.
Mutable draft editing and full workflow CRUD are not available on this branch.

The internal snapshot builder validates a document and produces immutable
canonical JSON bytes and a SHA-256 digest. Object keys are sorted, but node and
edge order is preserved; this is project-specific encoding, not an RFC 8785
canonicalization. An internal, caller-transactional revision store saves these
bytes under a workflow ID and revision, rejects conflicting content, and
checks the digest on read. Identical writes are idempotent. It has no workflow
ownership or authorization model, and does not prevent privileged direct
database changes. Digests detect corruption, not malicious tampering. It does
not pin handler implementations or schema defaults or make execution safe
across upgrades. Do not enqueue execution work until those guarantees exist.

### Internal execution snapshot values (P1-08a)

`app.services.workflows.execution_snapshot.create_execution_snapshot` accepts
v1 graph bytes, graph/byte limits and a **trusted backend-selected** catalog of
`ExecutionNodeDefinition` records (existing node definition, exact
`HandlerArtifact` ID/SHA-256 and complete model manifests). It returns a distinct
frozen bytes-backed value with a derived SHA-256. It materializes and strictly
validates defaults, rejects extras/non-JSON/non-finite values, uses serialization
aliases consistently, and bounds both input and expanded output bytes.
Empty serialization aliases are preserved; collisions fail. Default and
explicit-value comparisons distinguish native JSON types recursively, including
boolean/integer/float differences, even when Python considers them equal.
Every graph/revision/config/handler/model field participates in the digest.
Clients cannot supply pins/default overrides; catalogs are not client input.
See the [value contract](../docs/SPEC-workflow-runtime.md#bounded-internal-p1-08a-value-contract)
for the exact encoding and failure semantics.

This does not change or promote legacy snapshots, add durable execution
bindings, or load code/models. SHA metadata is not authorization or proof of
installed artifacts. Future runtime code must verify the installed handler
artifact and model readiness. P1-08 remains incomplete.
Focused test: `python -m pytest tests/test_execution_snapshot.py -q -p no:cacheprovider`.

### Internal execution revision bindings (P1-08b)

`app.services.workflows.execution_bindings.bind_execution_snapshot` generates
execution bytes from a checked stored workflow revision, exact expected source
digest and trusted catalog. One immutable binding per workflow/revision permits
exact replay; changed defaults, handler or model pins conflict and require a new
revision. `get_execution_binding` verifies retained byte/digest associations
without resolving current defaults. Unbound legacy revisions remain unbound.
Both functions require an explicit non-autocommit psycopg transaction; failed
operations roll back their savepoint, not unrelated outer work.
See the [binding contract](../docs/SPEC-workflow-runtime.md#bounded-internal-p1-08b-binding-contract).
These records are not authorization, installed-code verification, model
readiness or execution. Downgrading a populated binding table destroys replay
evidence and requires authorization and recovery planning.
Focused owned check: `python tests/run_auth_checks.py --storage --pytest-file tests/test_execution_bindings.py`.

### Durable node admission (P1-10d)

`claim_node(connection, claim_id, run_id, node_id)` records one root-node claim
for an already prepared running workflow. Claims serialize with cancellation;
an exact retry returns `ALREADY_CLAIMED`, never permission to execute again.
Different identities cannot claim the same node, and an identity cannot be
reused for a different node or run. Use a caller-owned non-autocommit psycopg
transaction and configure bounded lock/statement timeouts. Claims have no
expiry or automatic reassignment, and dependent nodes remain blocked.

This is not a worker or proof that a handler can execute: actual execution,
pin revalidation, outcome recording, cancellation of in-flight work, and
unknown-effect recovery require separate work. Downgrading the claim migration
destroys evidence and requires authorization and recovery planning on populated
databases. Focused owned check:
`python tests/run_auth_checks.py --storage --pytest-file tests/test_node_admission.py`.

An internal dependency plan derives each node's distinct predecessors from a
validated workflow. It does not bind to a stored snapshot, schedule nodes,
track outcomes, or execute work; document order is not execution order.

The internal run store persists run-state transitions and ordered replay events
in a caller-managed transaction. A separate internal creation path binds a run
to a stored revision and prevents deletion of referenced revisions. Existing
unbound runs and the original creation function remain available internally.
Neither path creates node intents, dispatches jobs, authorizes actions, or
implements review and publication. Only use them behind those future controls.

### Authenticated run status and event replay (P1-11a)

The owner-only `GET /api/v1/runs/{id}` and
`GET /api/v1/runs/{id}/events?afterSequence=0&limit=50` endpoints expose only
durable run state and ordered event metadata. Event cursors are exclusive;
pages default to 50 and cap at 100. Empty/future-cursor pages retain the input
cursor, and `hasMore: false` does not mean the run is terminal. These routes
reuse existing session/origin/owner controls and are domain-read-only. They
neither trigger nor imply dispatch, readiness, cancellation, recovery, or
execution progress. Event messages are plain untrusted JSON strings, not HTML
or instructions; future producers still need to redact them. See the
[P1-11a contract](../docs/SPEC-workflow-runtime.md#authenticated-read-only-run-status-and-event-replay-p1-11a)
for exact response shapes, limits, and error semantics.

### Internal run-request records (P1-09a)

`app.services.workflows.run_requests.request_run(connection, request_id,
workflow_id, revision, expected_sha256)` atomically claims a stable caller-supplied
RFC-variant UUID4 request identity, creates a server UUID4 run through
`create_run_with_revision`, and enqueues one reserved INTERNAL notification.
The exact stored snapshot must match the expected lowercase SHA-256; the
existing loader verifies its bytes. Frozen `RunRequest` metadata contains
`request_id`, `run_id`, `workflow_id`, `revision`, `sha256`, `created_at`.

Use a caller-owned explicit non-AUTOCOMMIT psycopg/SQLAlchemy transaction at
READ COMMITTED. The service uses a savepoint, never commits the outer transaction,
and rolls back all its writes even if the caller catches an error and commits
unrelated work. Callers own statement/lock timeout budgets and whole-transaction
retries for database serialization/deadlock failures. The request primary key
serializes concurrent duplicates; identical retries return the same checked
association, and changed payload/expected digest raises `RunRequestConflict`.
Missing/corrupt revisions propagate their existing errors. Replay checks the run,
exact binding, initial QUEUED event and reserved intent; inconsistent or missing
evidence raises `RunRequestCorrupt`, never recreating or adopting storage.

The reserved outbox ID equals the request ID; its resource is the run ID and its
topic is `internal.workflow-run-requested.v1`, distinct from actual dispatch.
An existing reserved ID causes failure, even if its topic looks correct.
There is **no consumer**. Request records and their association have **no automatic
expiry/deletion**; the database guards their mutation. The additive
`p1_09a_run_requests` migration preserves existing tables and the single head;
downgrading it destroys replay evidence (require authorization and recovery
planning on populated databases).

This service is not authorization, dispatcher/handler/model readiness or an
execution claim. No role/default principal or source path is accepted. It adds
no node intents, scheduling, workers or external effects. The separate
owner-only P1-09i HTTP route requests a run against an existing revision through
this service but does not execute or dispatch it. P1-08
implementation/default/model pinning remains an EXECUTION prerequisite.
Privileged SQL tampering is outside the trust boundary. See the
[internal contract](../docs/SPEC-workflow-runtime.md#bounded-internal-p1-09a-contract).

### Internal mutable workflow drafts (P1-09e)

`app.services.workflows.drafts` stores one bounded UTF-8 draft per workflow ID,
preserving exact bytes without parsing or validating the document. `save_draft`
creates a draft when `expected_version` is `None`, or replaces it only when the
supplied version matches; every update increments that version. `get_draft`
returns the stored bytes and version. The persistence operations themselves add
no HTTP or authorization. Owner-only `GET` and version-checked `PUT`
`/api/v1/workflows/{id}/draft` routes expose this store; owner-only
`POST /api/v1/workflows/{id}/validations` validates a matching stored draft
against the current fixed sample-node catalog without executing it. See the
[read contract](../docs/SPEC-workflow-runtime.md#owner-only-mutable-workflow-draft-read-p1-09f),
[write contract](../docs/SPEC-workflow-runtime.md#owner-only-mutable-workflow-draft-write-p1-09g)
and [validation contract](../docs/SPEC-workflow-runtime.md#owner-only-mutable-workflow-draft-validation-p1-09h).
Draft text remains unparsed when saved and has a 32 KiB UTF-8 limit. Writes
through the persistence helper require a caller-owned transaction; the HTTP
route wraps them in one transaction. The migration downgrade removes all draft
data and requires authorization/recovery planning for populated databases.

The internal transactional outbox stores intent IDs, topics, and resource IDs
in a caller-managed transaction. Claims use expiring database leases and a
token to reject stale acknowledgements. This is storage infrastructure only:
there is no relay, queue, automatic run dispatch, or exactly-once guarantee.
A relay must commit its claim before publishing, reuse the intent ID for
deduplication, and acknowledge only confirmed delivery. Consumers must make
effects idempotent; a lease cannot fence an external effect or prove that a
timed-out publication did not happen.

The internal review scope value binds a run, artifact revision and SHA-256,
caption SHA-256, and an unordered set of provider/account identities. Callers
must calculate and verify the hashes against the exact content themselves.
`app.services.reviews.store` durably stores this exact scope, a caller-supplied
timezone-aware expiry, delivery outcome and (when decided) an immutable decision.
Identical request-ID retries are idempotent; conflicting reuse fails. A new
different scope for the same run supersedes its active request, including an
approval, while preserving the original scope and historic decision. PostgreSQL
serializes scope changes on the run row, permits one current request per run,
guards immutable scope/decision fields, and checks legal state and expiry
transitions.

All writes require an active non-autocommit psycopg transaction; callers own
commit, rollback, timeouts and transaction retries. Expiry is explicit input:
the proposed 24-hour duration is **not** a default or accepted policy. Delivery
functions only record trusted outcomes and never transmit content. This store
does not implement authorization or role checks, a valid-approval proof,
Telegram, an outbox effect, or publishing. Records are not approval or
authorization proofs; do not use them to authorize publication.
The narrowly scoped HTTP adapter is documented below and in [AUTH.md](AUTH.md).

Reviewer identifiers are stored labels, not role or identity authorization:
1-128 ASCII characters matching `[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}`.
Invalid identifiers are rejected before decision writes, without aborting the
caller's transaction. Raw SQL request inserts must start in `PENDING_DELIVERY`;
the database also rejects an expired request's transition to
`AWAITING_DECISION`, even when application guards are bypassed.

The `p4_02_review_records_20261114` migration adds the internal review tables.
Auth #33 also descends from `0005_artifact_metadata`.
`0008_auth_review_merge` joins the two histories without changing either
branch's tables. Alembic's target metadata includes both auth and review models;
`alembic upgrade head` followed by `alembic check` must succeed. The owned
disposable database harness runs the migration regression tests with the suite.
`p4_04a_review_queue_20261114` adds the composite `(created_at, id)` index used
by the bounded keyset queue.

## Internal artifact metadata (bounded Phase 0 slice)

`app.core.artifacts` provides internal `ArtifactMetadata`, `save_artifact` and
`get_artifact` interfaces. `GET /api/v1/artifacts/{id}` exposes one metadata
record to an authenticated owner; it omits the internal storage locator and
artifact bytes. One immutable row represents one revision; changed revisions
need new IDs. There is no lineage or "latest".

Trusted server-side code must generate UUID4 IDs once and retain them for retries.
Python and PostgreSQL enforce version 4 and RFC variant bits, but **UUID4 shape
cannot prove randomness or trusted generation**. Other constraints:
- Owner/revision: `[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}`; owner is unverified.
  Use opaque identities, not names, emails or credentials.
- SHA-256: 64 lowercase hex characters. Size: integer `0..2**63-1`, not bool.
- Media type: restricted lowercase `type/subtype`, at most 255 characters, no
  parameters (see validator); syntax is not a content allowlist.
- Locator: `artifacts/<32 lowercase UUID hex digits>`, derived from the ID.
  PostgreSQL enforces nonnull fields, formats, UUID primary key and locator match.

Writes require an active non-autocommit psycopg transaction; use READ COMMITTED.
Callers own commit/rollback, timeouts and whole-transaction retries.
Identical retries succeed; changes raise `ArtifactConflict` without overwriting;
missing IDs raise `ArtifactNotFound`. Database errors propagate.

**Limits:** core helpers do not enforce authentication/authorization or perform
filesystem access/deletion; the metadata route is owner-role-only. Digest/size/
media type are assertions, not verified bytes; locators do not prove containment
or safe access. Privileged SQL can change/delete rows. No upload or content
route, lifecycle, retention/privacy policy, audit, run/review binding,
byte/metadata atomicity or backup/restore coordination exists. This establishes
no security or readiness.

The `0005_artifact_metadata` migration creates the table. Downgrade to `0004_run_revisions`
drops **all artifact metadata**: require authorization and a recovery plan for
populated databases. No bytes are deleted. Tests write rows/transactional DDL:
use the same disposable database for both URLs; database tests skip without a URL.

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
# ANIMETRON_DATABASE_URL: migrations; ANIMETRON_TEST_DATABASE_URL: tests.
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m pytest tests/test_artifacts.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check --no-cache app tests migrations
.\.venv\Scripts\python.exe -m mypy --cache-dir .mypy_cache app
```

From this directory in PowerShell, using Python 3.12 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe tests/run_auth_checks.py
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The full auth harness requires Docker and installed Edge on Windows; it creates
only disposable, loopback-bound test resources and ignores inherited database
URLs. A supplied `ANIMETRON_TEST_DATABASE_URL` must carry the harness-generated
capability and matching in-database ownership marker; otherwise pytest refuses
before collection or mutation. Do not point tests at shared databases or bypass
the guard. See [the ownership and denial-audit contract](AUTH.md).
The plain HTTP server command above is liveness-only: authenticated
operation requires the explicitly configured HTTPS origin and TLS boundary.

The owner-only `GET /api/v1/workflows/node-types` endpoint describes built-in
sample-validation node types, their ports and configuration JSON Schemas. It
does not report execution or model readiness. The response and security
contract are in [the workflow specification](../docs/SPEC-workflow-runtime.md#sample-validation-node-catalog).

## Internal Linux artifact bytes

`app.core.artifact_bytes.ArtifactByteStore` adds byte storage only, with no HTTP,
authorization, database writes or deployment. `put(id, binary_stream, max_bytes=...)`
computes immutable `StoredBytes(id, sha256, byte_size)` facts and publishes at
`artifacts/<UUID4 hex>`, matching metadata's locator. Trusted callers generate and
retain IDs; **even identical writes to an existing ID fail with FileExistsError**.
Build `ArtifactMetadata` from these facts plus caller-validated owner/revision/media
type. For reads, construct `StoredBytes(metadata.id, metadata.sha256,
metadata.byte_size)` from trusted metadata and call `read_verified(..., max_bytes=...)`.
Content is returned only after full hash/size verification, not progressively.

**Approved boundary:** run as a dedicated Linux service UID on a private, local
Docker named volume (the approved exception to project-directory-only storage).
Provision the root as that UID, exactly mode `0700`; ancestors must be root/service
owned and not group/other writable. Never share the UID or volume with untrusted
workers or other writer identities. Host admins/privileged actors are outside the
threat model. Runtime does not repair root ownership/permissions. Paths are walked
from `/` using pinned directory descriptors and `O_NOFOLLOW`, never `Path.resolve`;
files must be service-owned, mode `0600`, regular and single-link. Linux capability,
permission, link, sync and filesystem errors fail closed; native Windows is refused.
Network filesystems and Windows byte-storage bind mounts are not supported.

**Concurrency/crashes:** cooperating service writers take an exclusive directory
`flock`; readers take shared locks. Separate open descriptions also serialize
threads sharing an instance. Lock acquisition waits at most five seconds, then
raises `BlockingIOError`; close must not race operations, and stream callbacks must
not reenter storage. Input reads are at most 64 KiB, with one excess byte used to
detect overflow. Caller-supplied limits bound disk bytes and read memory (about
twice content size); synchronous source reads and filesystem I/O need caller-owned
execution deadlines and aggregate disk/concurrency quotas.

Publication uses `fsync(file)`, atomic no-replace `linkat`, removal of **only this
attempt's O_EXCL-created `.pending-<UUID hex>`**, then `fsync(directory)`. Errors
after linking may leave published bytes: never assume failure rolled them back.
A process crash before linking leaves an unused pending file; a crash between
linking and unlinking leaves two names for one inode, which reads reject. After
unlinking, a complete file can be read using trusted expectations. No pending
files are swept at startup, and no published files are deleted on failure.
`audit_artifacts(connection, store, max_total_bytes=..., max_entries=...)` provides
a bounded, report-only offline comparison. It reports consistent, missing,
orphaned, corrupt, unsafe and invalid metadata IDs (including mismatched
derived locators), exact safe/unsafe pending
names, and a count of unexpected directory entries. It checks private file
ownership/mode and single-link status, hashes valid artifact files, and returns
no content or storage paths. Entry/byte limit exhaustion fails without a partial
report; at most `max_entries + 1` names are enumerated to detect entry overflow.
Stop **all** metadata and byte writers before calling it: the database
transaction cannot make filesystem and metadata reads atomic. The audit never
changes either store, deletes or repairs files, authorizes access, or makes an
artifact usable. Pending bytes have no trusted digest and must not be adopted.
It is not a cleanup or recovery operation. Focused metadata checks:
`python -m pytest tests/test_artifacts.py -q -p no:cacheprovider`.
Process-crash tests do not certify power-loss durability; durability depends on
local filesystem/device sync behavior.

Byte publication and metadata commit are **not atomic**: DB rollback/crash can
leave orphan bytes. This report does not supply automatic recovery, retention,
coordinated backup, encryption, media signature/probing validation or readiness
certification. Hashes detect corruption, not malicious edits to both bytes and
metadata. Callers must validate media and enforce access policy before making
artifacts usable.

Dependency-free Linux tests use the existing `python:3.12-slim` image, read-only
code, no network, a fresh private named volume and service UID 10001. From this
worktree's `backend` directory in PowerShell:

```powershell
$tag = [guid]::NewGuid().ToString('N')
$volume = "animetron-byte-test-$tag"; $container = "animetron-byte-test-$tag"
$code = (Get-Location).Path
docker volume create $volume
if ($LASTEXITCODE -ne 0) { throw 'Volume creation failed' }
try {
  docker run --name $container --pull never --network none --read-only --cap-drop ALL --cap-add CHOWN --cap-add SETUID --cap-add SETGID --mount "type=bind,source=$code,target=/code,readonly" --mount "type=volume,source=$volume,target=/volume" -w /code -e PYTHONDONTWRITEBYTECODE=1 -e ARTIFACT_TEST_ROOT=/volume --entrypoint python python:3.12-slim -c "import os,sys,runpy; os.mkdir('/volume/foreign',0o755); os.chmod('/volume',0o700); os.chown('/volume',10001,10001); os.setgroups([]); os.setgid(10001); os.setuid(10001); sys.argv=['unittest','discover','-s','tests','-p','test_artifact_bytes.py','-v']; runpy.run_module('unittest',run_name='__main__')"
  if ($LASTEXITCODE -ne 0) { throw 'Linux tests failed' }
} finally {
  docker rm -f $container
  docker volume rm $volume
}
```

On Windows, use the auth harness above for the full suite, and the existing interpreter for
`ruff check --no-cache app tests migrations`, and
`mypy --platform linux --cache-dir .mypy_cache app`. Linux-only filesystem tests
are skipped on Windows; Windows refusal still runs. Runtime and tests add no deps.
Syscall references: [linkat](https://man7.org/linux/man-pages/man2/link.2.html),
[flock](https://man7.org/linux/man-pages/man2/flock.2.html),
[fsync](https://man7.org/linux/man-pages/man2/fsync.2.html).

## Disposable local backup/restore check

Run `python tests/run_platform_recovery_checks.py` from `backend` with Docker
and the cached `postgres:18` and `python:3.12-slim` images. The check creates
synthetic metadata and artifact bytes, backs them up, restores them into fresh
database and byte-store resources, and verifies the restored SHA-256 and
metadata match. It also checks that PostgreSQL has no published host port and
that a minimal test-only gateway is reachable only through a loopback binding.

Explicitly created Docker containers, named volumes and networks carry unique
owner labels; cleanup verifies those labels before removing them. The database's
anonymous volume is removed only with its verified test container. Backup files
live in a temporary directory created by the check. No existing project files
or application data are modified. This proves only a local test arrangement; it
does not configure or deploy product services, select a persistent or encrypted
backup target, define retention, or implement preview/confirmed deletion.

`GET /api/v1/health` returns `{"status":"ok"}` when the process responds.
It is a liveness check, not a readiness or security check. Interactive API
documentation is disabled to avoid loading third-party assets.
HTTP responses include restrictive browser security headers, including on
unhandled errors. Headers alone do not authenticate requests, prevent CSRF, enforce
trusted hosts, or replace a secure gateway. Routes are registered on `api`;
serve the outer ASGI `app` so the headers also cover error responses. See
[Starlette middleware documentation](https://www.starlette.io/middleware/#corsmiddleware-global-enforcement).

The database factory requires an explicit `postgresql+psycopg` URL including a
host and database. Do not commit credentials. Run PostgreSQL integration and
run-event tests using `tests/run_auth_checks.py`, which provisions its actual
owned disposable database, installs ownership proof and applies/checks migrations.
Manually setting a test database URL is insufficient and fails closed at pytest
startup. Without a test URL, optional foundation PostgreSQL smoke tests skip;
auth persistence tests deliberately require the owned harness database.

Back up existing databases before applying migrations. A downgrade removes run
and event data and must not be used without explicit authorization.

The internal model acquisition preflight reports missing license acceptance,
access confirmation, and insufficient storage. Its caller must supply verified
acceptance, access, and current storage facts; a successful check is not a
download, reservation, model integrity check, or readiness result. No model
downloads or model registry API are implemented.

An internal model reference identifies a Hugging Face model repository by its
full repository ID and full lowercase commit hash. It does not check whether a
repository or revision exists or is allowlisted, accepted, downloaded, or ready.
The internal file verifier checks a stream's exact size and SHA-256 using bounded
reads. Its caller must securely open the intended file and obtain trusted
expectations; matching one file does not establish model readiness.
An internal manifest value groups a pinned reference, engine and license
identifiers, expected file sizes and digests, and a minimum storage estimate.
It does not establish license acceptance, repository allowlisting, safe file
access, adequate staging space, verified downloads, or model readiness.

`ModelReferenceAllowlist` compares an exact provider, repository and revision
against a caller-supplied immutable set of pinned references. An empty set
denies all references; matching is case-sensitive. It does not load or enforce
trusted configuration, validate a manifest's file metadata, grant access or
license consent, initiate acquisition, or establish readiness. No runtime
service currently uses this policy.

`ModelManifestCatalog` selects an immutable manifest by exact pinned reference
from a caller-supplied tuple, returning `None` for an absent pin and rejecting
duplicate references. The caller must establish that catalog contents are
trusted. The catalog does not load configuration, validate repository access
or license acceptance, check installed files, acquire models or establish
readiness. It is not yet connected to a runtime service.

`check_manifest_acquisition` combines that exact-pin check with the existing
license, access and storage preflight, using the supplied manifest's estimated
size. The caller must supply a trusted manifest, trusted allowlist, acceptance
and access facts for that model, and current storage information. A permitted
reference does not authenticate the rest of a manifest, reserve disk space,
authorize a download, verify files or establish readiness. No runtime service
currently calls this helper.

## Internal schedule preview (Phase 6 slice)

`app.services.scheduling.preview.preview_occurrences(expression, time_zone, after)`
returns the next five strictly future `ScheduleOccurrence` values. The cursor
must be timezone-aware. Each result includes an offset-bearing `local_time`,
UTC `due_at`, and `slot_key` of `<IANA-zone>:<YYYY-MM-DDTHH:MM>`.
Future persistence must namespace that key by schedule identity and reuse it
for both preview and dispatch; the value itself does not deduplicate effects.

The approved POSIX-style five fields support numeric lists/ranges/steps,
wildcards, and three-letter month/weekday names. Restricted day-of-month and
weekday fields match with OR. Macros, seconds/years, hashed/random expressions,
and `L`/`W`/`#` extensions are rejected. Nonexistent local times are skipped;
ambiguous times use only the earlier occurrence, never an already missed slot.
Invalid input, impossible dates and exhaustion of the bounded 50-calendar-year
preview search raise `ValueError`; no partial successful preview is returned.

Croniter 7.0.0 supplies wall-clock candidates; an explicit UTC round-trip and
`fold=0` enforce the approved DST policy instead of its native DST iteration.
Python `zoneinfo` uses the host time-zone database, falling back to pinned
`tzdata==2026.6`. Set `PYTHONTZPATH=""` in the application/test process to use
the pinned fallback consistently across hosts; no machine-wide setting changes
are needed.

```powershell
$env:PYTHONTZPATH = ""
.\.venv\Scripts\python.exe -m pytest tests\test_scheduling.py -q -p no:cacheprovider
```

The internal `app.services.scheduling.store` persists descriptors bound to an
existing immutable workflow revision. Create and update require an explicit
non-autocommit caller transaction, an aware cursor and an explicit enabled
boolean. An enabled descriptor's next due time is the first preview occurrence
strictly after that cursor; a paused descriptor has no next due time. Resuming
recalculates from the supplied cursor and does not catch up missed occurrences.
Updates require the current version; stale writes conflict. Lists are ordered by
UUID with an exclusive cursor and a maximum page size of 100. The only persisted
overlap and missed-run descriptors are the approved `skip` policies.

The owner-only scheduling HTTP slice exposes create, get, keyset list, versioned
replacement and next-five preview. See the [contract](../docs/SPEC-scheduling.md).
Writes use the PostgreSQL clock, not a client cursor; preview may use an explicit
aware historical cursor without changing the schedule. These are descriptor
semantics, not dispatch guarantees. There is no Beat process, durable slot claim,
run intent, overlap/restart handling or publication permission in this slice.
These remain required before enabling scheduling.

## Internal review decisions (P4-03a)

`app.services.reviews.decisions.record_decision(connection, principal,
expected_scope, review_id, outcome) -> ReviewDecision` is an internal owner-only
approve/reject boundary. Callers must freshly authenticate through the trusted
server **on every call, including retries**; never deserialize `Principal` from
client input or treat a cached Principal as fresh authentication. Operator/viewer
are denied. The service requires an explicit non-AUTOCOMMIT SQLAlchemy psycopg
transaction, exact typed review scope, UUID4 review ID and `DecisionOutcome`.
Owner expiry must be aware. Owner and request expiry must be later than a fresh
database clock after the final intent lock/insert (also checked earlier),
before any successful return.

Locks follow `workflow_runs` then `review_requests`, matching supersession.
Scope, current state and expiry are checked again on replay. The existing review
store records the immutable winner; simultaneous approve/reject cannot both win.
An approval and one namespaced `internal.review-approved.v1` outbox notification
intent share a savepoint, so caught enqueue failures cannot leave a decision or
partial intent committed. Valid identical retries add no effects; changed
reviewer/outcome, stale scope and expired/superseded requests fail explicitly.
Rejection never creates an approval/publication intent.

The reserved service-owned topic/intent identity is trusted internal evidence,
not cryptographic proof or publication authority. Low-level APPROVED rows
without matching evidence fail closed and are not repaired by enqueueing.
Other trusted writers must not forge reserved intents; retention must preserve
them for replay. See [the approved boundary](../docs/SPEC-human-review.md) for
the exact namespace, error semantics and trust limits. The authenticated
metadata/decision HTTP adapter is described below; there is no MCP or Telegram
adapter, outbound notification or automatic publication consumer.

The caller owns outer commit/rollback and sets transaction-local lock/statement
budgets. Timeout/connection/enqueue errors propagate; retry only with fresh
authentication and the same review identity and exact intent. Focused tests are
`tests/test_review_decision_service.py`; run the full owned PostgreSQL/Keycloak/
browser harness with `python tests/run_auth_checks.py` (never inherited DB URLs).

## Authenticated review HTTP API (P4-04a)

`GET /api/v1/reviews` is owner-only and returns existing request metadata across
the defined review states. It uses an opaque ascending keyset cursor ordered by
`(created_at, id)`, default limit 50 and maximum 100; it does not count or
materialize the full table. Metadata includes scope identifiers/hashes,
destinations, state, expiry, creation/state-change times and bounded delivery
error code. It never includes artifact/caption bytes, paths, auth state,
decision intent internals or publication capability.

`POST /api/v1/reviews/{id}/decisions` accepts only a strict camelCase
`expectedScope` and `APPROVED`/`REJECTED` outcome. Each request (including
replay) obtains the principal from the current `AuthStore` opaque session and
requires exact Origin and `X-CSRF-Token`; no client principal, role or reviewer
ID is accepted. `ReviewScope` normalization and the existing
`record_decision` service enforce exact scope and transaction/state/expiry
guards. The adapter exposes no approval lookup, creation/delivery, content
bytes, Telegram, MCP, outbound publication or deployment surface.

Requests over 4096 bytes, unknown fields/query parameters, duplicate query
parameters and malformed cursors are rejected. Responses use the shared
request-ID error envelope/security headers: 401 unauthenticated, 403 forbidden
or origin/CSRF failure, 404 absent request, 409 decision conflict, 422 invalid
input, and 503 disabled auth or dependency failure. Focused real-PostgreSQL API
tests are in `tests/test_reviews_api.py`; use the ownership-checked harness
(`python tests/run_auth_checks.py`) rather than inherited DB URLs.

## Internal current-approval lookup (P4-04b)

`app.services.reviews.approvals.require_valid_approval(connection, review_id,
expected_scope, *, auth_config: AuthConfig) -> CheckedApproval` inspects an
existing approval without writes or transaction ownership changes. Supply only
**current trusted-server settings**, never client-deserialized configuration.
The human owner need not have an active session; fresh caller authorization
belongs to the future transport/publisher boundary.

It requires the existing explicit non-AUTOCOMMIT psycopg transaction and UUID4/
scope contracts. The shared `lock_review_request` locks the stored run then the
request, followed by the reserved outbox intent. It requires current APPROVED
state, an immutable APPROVED decision for that review and the exact current
owner identity (`auth.digest(issuer + "\0" + owner_subject)`), exact scope,
matching reserved intent ID/topic/resource, and request expiry strictly after a
fresh advancing DB clock **after the final intent lock**. Missing rows propagate
`ReviewNotFound`; invalid state/scope/owner/expiry or absent evidence raises
`ReviewConflict`, intent collisions raise `OutboxConflict`, and existing input/
DB errors propagate. It never repairs missing evidence or enqueues.

The frozen result contains scope, review/decision identity and expiry, valid only
for the checked state/settings in this caller transaction. It is **not** a
cryptographic proof, reusable permission, or artifact-byte verification.
A trusted publisher must call/recheck for every attempt and before effects.
Callers own lock/statement budgets and retries using current trusted settings.
Privileged arbitrary DB writers remain outside the integrity guarantee.
No approval-lookup HTTP endpoint, publisher, transmission, or full P4/P9
completion is supplied. Focused tests: `tests/test_review_approval_lookup.py`;
full gates use the same owned `tests/run_auth_checks.py` harness.
