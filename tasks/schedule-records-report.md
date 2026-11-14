# P6-02b internal schedule descriptors

Status: independent local QA passed; push/PR step remains blocked. This
does not complete P6-02 or P9. Base: merged P4 #40 at
`2ac321366c96bf062370d4d774a073dc03292431`; parent commits `674bf5a` and
`cfbd844` retain P4 reconciliation and the approved slice boundary.

The repository remote was inspected. No push or PR creation was attempted, so
there was no tool or technical permission denial. Source remains local; no
branch push, remote checks or merge are claimed.

## Independent local QA checkpoint

The independent reviewer passed the assigned implementation snapshot
`ee8318dfbaa0929940617c7e0443fdea59a7f77d`, with no high-confidence defects.
They reproduced 50 focused tests, the fresh PostgreSQL migration lifecycle,
Ruff, strict Linux-target mypy for 27 source files, dependency consistency and
whitespace checks. Weakening the AUTOCOMMIT guard in a private copy made its
regression fail. Their exact owned containers and scratch paths were verified
removed. The full suite and Linux-only OS cases were not independently run.

The reviewer excluded the uncommitted four-line report clarification from their
snapshot. The parent reviewed that clarification and records the final
documentation-only checkpoint separately. P6-02b stays unchecked: there is no
PR, GitGuardian result or merge for this branch. Auth #33 and P9 remain blocked.

## Decisions and limits

- SQLAlchemy Core functions use the caller's explicit non-autocommit
  transaction. A composite foreign key and `get_revision` bind an existing,
  integrity-checked immutable workflow revision.
- The caller supplies both an aware cursor and enabled boolean on every create
  and replacement update. `preview_occurrences` validates cron and zone and
  calculates the first strictly future UTC due time. Paused descriptors store
  null; resume recomputes from the supplied cursor, without catch-up.
- Optimistic version checks use a single conditional update. A missing record
  and a stale version are distinct errors. Reads have an exclusive UUID cursor
  and maximum page size 100. Only approved `skip` overlap/missed-run policy
  descriptors are stored.
- This is not authorization, slot claiming, scheduling, overlap arbitration,
  dispatch, skipped-slot audit or publication approval. It does not modify
  existing run bindings. Auth #33 remains scanner-blocked; no Auth migration
  merge or protection bypass was attempted.

## Verification

The existing `D:\animetron\backend\.venv\Scripts\python.exe` imported
`app` from this worktree's `backend\app\__init__.py`. No dependencies were
installed. Focused TDD first failed on the absent new module, then passed.
Fresh PostgreSQL upgrade/check/downgrade to
`p4_02_review_records_20261114`/re-upgrade/check passed. After re-upgrade,
50 targeted store, preview, workflow revision and run revision tests passed,
including real concurrent edits, rollback, DST, no-catch-up and bound-run
immutability. A deliberate inverted pause condition caused a focused test to
fail and was restored. Ruff passed; strict Linux-target mypy passed 27 source
files; `pip check` reported no broken requirements.

Reproduce using a **new disposable, owned** PostgreSQL database, never a shared
or inherited URL. The example uses a unique label and loopback-only random
port; preserve the ID for verified cleanup:

```powershell
Set-Location D:\animetron\.worktrees\schedule-records\backend
$py = 'D:\animetron\backend\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Get-Location).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONTZPATH = ''
$env:TEMP = (Get-Location).Path
$env:TMP = $env:TEMP
$owner = 'p602b-qa-' + [guid]::NewGuid().ToString('N')
$image = 'postgres@sha256:846a7ddaa67a4b354ae1d21087b683901aa6113a4ed626d3787cfbf6c85e3e07'
$id = docker run -d --name $owner --label project=animetron --label task=P6-02b --label "owner=$owner" -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=schedule_test -p 127.0.0.1::5432 $image
# Wait for pg_isready in this exact container before continuing.
docker exec $id pg_isready -U postgres -d schedule_test
$port = (docker port $id 5432/tcp).Split(':')[-1]
$env:ANIMETRON_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:$port/schedule_test"
$env:ANIMETRON_TEST_DATABASE_URL = $env:ANIMETRON_DATABASE_URL
& $py -c 'import app; print(app.__file__)'
& $py -m alembic upgrade head
& $py -m alembic check
& $py -m alembic downgrade p4_02_review_records_20261114
& $py -m alembic upgrade head
& $py -m alembic check
& $py -m pytest tests/test_schedule_store.py tests/test_scheduling.py tests/test_workflow_revisions.py tests/test_run_revisions.py -q -p no:cacheprovider
& $py -m ruff check --no-cache app tests migrations
& $py -m mypy --platform linux --cache-dir .p602b-mypy app
& $py -m pip check
```

Stop on any failed command. Before removing the QA container, inspect its JSON
and verify its full ID, image digest and all three labels against the values
created above; remove only that ID and query it afterward to confirm absence.
Remove only the QA-owned cache created by the commands.

The verification container used
`postgres@sha256:846a7ddaa67a4b354ae1d21087b683901aa6113a4ed626d3787cfbf6c85e3e07`,
loopback-only dynamic port and task-specific labels. No dispatch or external
integration was exercised. The full suite, Linux-only OS behavior and production
deployment were not tested.

## Cleanup

Container `2590573f11539d77f001e5918371f6995e58d6b4d216a9dff151e7a69d1e7751`
was removed only after JSON inspection confirmed its exact ID, pinned image and
labels `project=animetron`, `task=P6-02b`, `owner=copilot-8f392d47`.
An exact-ID query confirmed absence. The task-owned mypy cache was removed and
the task-specific pytest temp path was absent. The root worktree was not edited.
