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
This value is not an approval proof and provides no authorization, persistence,
expiry, decision handling, Telegram delivery, or publishing.

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
