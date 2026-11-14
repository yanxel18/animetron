# AnimeTron backend

Project-wide progress and remaining work: [task checklist](../tasks/todo.md).

The API currently provides only process liveness. A PostgreSQL engine factory
is available for future persistence, but the API does not yet use a database
or implement authentication, storage, workflows, or creator features.

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
strings up to 128 characters and cannot contain NUL. There is no workflow API.

The internal snapshot builder validates a document and produces immutable
canonical JSON bytes and a SHA-256 digest. Object keys are sorted, but node and
edge order is preserved; this is project-specific encoding, not an RFC 8785
canonicalization. An internal, caller-transactional revision store saves these
bytes under a workflow ID and revision, rejects conflicting content, and
checks the digest on read. Identical writes are idempotent. It has no workflow
ownership or authorization model, and does not prevent privileged direct
database changes. Digests detect corruption, not malicious tampering. It does
not pin handler implementations or schema defaults or make execution safe
across upgrades. Do not enqueue work until those guarantees exist.

An internal dependency plan derives each node's distinct predecessors from a
validated workflow. It does not bind to a stored snapshot, schedule nodes,
track outcomes, or execute work; document order is not execution order.

The internal run store persists run-state transitions and ordered replay events
in a caller-managed transaction. A separate internal creation path binds a run
to a stored revision and prevents deletion of referenced revisions. Existing
unbound runs and the original creation function remain available internally.
Neither path creates node intents, dispatches jobs, authorizes actions, or
implements review and publication. Only use them behind those future controls.

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
does not implement authorization or role checks, a valid-approval proof, HTTP,
Telegram, an outbox effect, or publishing. Records are not approval or
authorization proofs; do not use them to authorize publication.

Reviewer identifiers are stored labels, not role or identity authorization:
1-128 ASCII characters matching `[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}`.
Invalid identifiers are rejected before decision writes, without aborting the
caller's transaction. Raw SQL request inserts must start in `PENDING_DELIVERY`;
the database also rejects an expired request's transition to
`AWAITING_DECISION`, even when application guards are bypassed.

The `p4_02_review_records_20261114` migration adds the internal review tables.
The independent Auth #33 migration also descends from `0005_artifact_metadata`;
when that branch is integrated, reconcile the parallel Alembic heads with an
explicit merge revision rather than renaming either migration.

## Internal artifact metadata (bounded Phase 0 slice)

`app.core.artifacts` provides internal `ArtifactMetadata`, `save_artifact` and
`get_artifact` interfaces, not HTTP endpoints. One immutable row represents one
revision; changed revisions need new IDs. There is no lineage or "latest".

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

**Limits:** no authentication/authorization or filesystem access/deletion.
Digest/size/media type are assertions, not verified bytes; locators do not prove
containment or safe access. Privileged SQL can change/delete rows. No lifecycle,
retention/privacy policy, audit, run/review binding, byte/metadata atomicity or
backup/restore coordination exists. This establishes no security or readiness.

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
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

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
Offline, explicitly authorized reconciliation must identify exact pending names,
verify UID/mode and inode/link relationships plus trusted hashes, and stop writers
before cleanup; it is **not implemented** here. Process-crash tests do not certify
power-loss durability; durability depends on local filesystem/device sync behavior.

Byte publication and metadata commit are **not atomic**: DB rollback/crash can
leave orphan bytes. No recovery/retention, coordinated backup, encryption, media
signature/probing validation or readiness certification is supplied. Hashes detect
corruption, not malicious edits to both bytes and metadata. Callers must validate
media and enforce access policy before making artifacts usable.

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

On Windows, use the existing interpreter for `pytest tests -q -p no:cacheprovider`,
`ruff check --no-cache app tests migrations`, and
`mypy --platform linux --cache-dir .mypy_cache app`. Linux-only filesystem tests
are skipped on Windows; Windows refusal still runs. Runtime and tests add no deps.
Syscall references: [linkat](https://man7.org/linux/man-pages/man2/link.2.html),
[flock](https://man7.org/linux/man-pages/man2/flock.2.html),
[fsync](https://man7.org/linux/man-pages/man2/fsync.2.html).

`GET /api/v1/health` returns `{"status":"ok"}` when the process responds.
It is a liveness check, not a readiness or security check. Interactive API
documentation is disabled to avoid loading third-party assets.
HTTP responses include restrictive browser security headers, including on
unhandled errors. They do not authenticate requests, prevent CSRF, enforce
trusted hosts, or replace a secure gateway. Routes are registered on `api`;
serve the outer ASGI `app` so the headers also cover error responses. See
[Starlette middleware documentation](https://www.starlette.io/middleware/#corsmiddleware-global-enforcement).

The database factory requires an explicit `postgresql+psycopg` URL including a
host and database. Do not commit credentials. To run the optional PostgreSQL
integration test, set `ANIMETRON_TEST_DATABASE_URL` to a disposable database
before running pytest. The test creates and removes a uniquely named table;
the database must not contain production data. Without that variable the
integration test is skipped.

Run-event tests also require the migration to be applied to that disposable
database. Set `ANIMETRON_DATABASE_URL` to the same URL, then run:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

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

These are descriptor semantics, not dispatch guarantees. There are no schedule
HTTP endpoints, Beat process, durable slot claims, run intents, overlap/restart
handling or publication permissions in this slice. These remain required before
enabling scheduling.
