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
