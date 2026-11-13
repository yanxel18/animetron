# AnimeTron backend

The API currently provides only process liveness. A PostgreSQL engine factory
is available for future persistence, but the API does not yet use a database
or implement authentication, storage, workflows, or creator features.

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
