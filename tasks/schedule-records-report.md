# P6-02b internal schedule descriptors

Status: verified and normally merged in
[#42](https://github.com/yanxel18/animetron/pull/42) at
`8bc096c95b3065f782dc0a624284224fd8e1b8c3`. This does not complete P6-02 or P9.
The original implementation base was P4 #40 at
`2ac321366c96bf062370d4d774a073dc03292431`; parent commits `674bf5a` and
`cfbd844` retain P4 reconciliation and the approved slice boundary.

The earlier local/publication blockers below are historical. The owner pushed
the exact integrated head; the assistant created #42 without uploading source,
performed direct integration review, verified independent test execution and
exact-head GitGuardian success, then merged normally. Root master was pulled
with pre-existing unrelated edits preserved.

Independent integrated QA reproduced 341 passed/20 skipped, migration lifecycle,
Ruff, strict Linux-target mypy31, dependency consistency and cleanup absence at
`8af75bf629dd7a7316f3197263bd4d8ac4fe5c5f`. The unchanged store/spec/test core
matches the previously independently reviewed `ee8318d`. No formal self-approval,
force-push or protection/check waiver occurred.

## Integrated checkpoint after #41

The verified repair #41 was merged at
`921ce335e4d9b62de19b6d47656b276372ddd505` and incorporated locally.
Both auth and review metadata are retained. The unpushed schedule migration
now follows `0008_auth_review_merge`; the migration graph regression failed
with two heads before this change.

Full integrated owned PostgreSQL/Keycloak/browser harness: **341 passed,
20 unchanged Windows skips**. Upgrade/check, downgrade to
`0005_artifact_metadata`, re-upgrade, Ruff, strict Linux-target mypy31 and
dependency consistency passed. This is parent integration verification, not
new independent schedule reassessment. The earlier independent store QA below
remains evidence for the unchanged store core.

Owned harness containers and network were removed; an exact-name query
confirmed absence. Worktree caches are retained rather than deleting paths
whose pre-run ownership was not established. No deployment or source upload
was performed. The historical #33 scanner finding remains unresolved.

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

The earlier standalone database commands are superseded by the merged auth
ownership guard. Reproduce the integrated suite using the existing harness,
which creates its own database capability/marker and ignores inherited URLs:

```powershell
Set-Location D:\animetron\.worktrees\schedule-records\backend
$py = 'D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Get-Location).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONTZPATH = ''
& $py -c 'import app; print(app.__file__)'
if ($LASTEXITCODE -ne 0) { throw 'Import verification failed' }
& $py tests\run_auth_checks.py
if ($LASTEXITCODE -ne 0) { throw 'Owned integration harness failed' }
& $py -m pip check
```

The original isolated verification container used
`postgres@sha256:846a7ddaa67a4b354ae1d21087b683901aa6113a4ed626d3787cfbf6c85e3e07`,
loopback-only dynamic port and task-specific labels. No dispatch or external
integration was exercised in that earlier isolated run. The integrated suite
above does not establish Linux-only OS behavior or production deployment.

## Cleanup

Container `2590573f11539d77f001e5918371f6995e58d6b4d216a9dff151e7a69d1e7751`
was removed only after JSON inspection confirmed its exact ID, pinned image and
labels `project=animetron`, `task=P6-02b`, `owner=copilot-8f392d47`.
An exact-ID query confirmed absence. The task-owned mypy cache was removed and
the task-specific pytest temp path was absent. The root worktree was not edited.
