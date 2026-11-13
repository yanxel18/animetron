# AnimeTron backend

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
serialization and durable execution are not yet implemented.

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
