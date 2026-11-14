# P1-09a internal run-request records

## Scope and baseline

- Worktree: `D:\animetron\.worktrees\run-request-records`.
- Branch: `feature/run-request-records`.
- Verified starting HEAD and local master:
  `f315e9bbb877893d871174d6542355c767c2e80a` (#47).
- Sole tracker read: `tasks/todo.md`. The parent's uncommitted
  `tasks/todo.md`, `tasks/development-report.md` and
  `tasks/schedule-http-api-report.md` were not edited, staged or committed.
- The internal contract was added to the existing workflow spec and backend
  README before the implementation.

## Delivered boundary

`request_run(connection, request_id, workflow_id, revision, expected_sha256)`
accepts a stable caller UUID4 request identity, exact workflow UUID/revision and
lowercase SHA-256. It returns frozen checked request/run metadata. The existing
snapshot loader verifies bytes; canonical `create_run_with_revision` creates the
server UUID4 run, initial QUEUED event and immutable revision association.

One new table claims the request through its primary key and uniquely associates
the run. Deferred foreign keys permit claim-first canonical creation. An inner
savepoint covers every write. Identical replay checks persisted run, binding,
initial event, snapshot and reserved outbox evidence; changed payload conflicts,
missing/mismatched evidence fails without adoption, promotion or repair.

The reserved outbox ID is the request ID, resource is the run ID, topic is
`internal.workflow-run-requested.v1`. This is an INTERNAL notification only;
there is no consumer or execution/authorization/readiness claim.
The database guards request UPDATE/DELETE; no automatic expiry/deletion exists.
Callers retain identity/association indefinitely and own the outer transaction,
timeouts and whole-transaction database retries at READ COMMITTED.

No HTTP/auth, role/default principal, source-path authority, node intents, graph
validation reimplementation, scheduler/due slots, workflow CRUD, handlers,
workers, GPU/inference, packages/downloads, publishing or external effects were
added. P1-08 handler/default/model pinning remains an EXECUTION prerequisite.
Workflows do not import review-specific code. Privileged SQL remains outside the
trust boundary; hashes and UUID shape are not authorization/provenance proofs.

## Verification

All commands used the existing
`D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe`,
with `PYTHONPATH` set to this worktree's backend,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONTZPATH=''` and project-local disposable
caches. No dependencies were installed. Harness invocations were sequential;
its normal ownership marker/capability checks remained active and it stripped
inherited database URLs/settings. Cached images used `--pull=never`.

- Behavioral RED: the first real-PG request/replay test failed with
  `NotImplementedError` before the persistence implementation.
- Focused owned PostgreSQL suite: **32 passed**. Covers success/exact retry;
  workflow/revision/digest conflicts; missing/corrupt revision and wrong expected
  digest; actual late SQL unique violation with savepoint rollback and unrelated
  outer commit; actual outer SQL failure rolling back a successful request;
  missing/mismatched binding/event/intent and missing low-level run;
  UPDATE/DELETE mutation guards; transaction/autocommit/driver/input guards;
  later run/delivery state; and real concurrent identical/different payloads.
  Concurrency observes `pg_blocking_pids`, not sleeps as a correctness oracle.
  Final assertions check exactly one additional claim/run/binding/event/intent.
- Mutation experiment: removing the reserved intent topic/resource comparison
  produced **2 failed, 30 passed**, precisely the two mismatched-intent cases.
  The comparison was restored; service SHA-256 before/after matched:
  `c3928fac736d883d0bf26d77601af4a3b5ab74741619a353d609ea691cad02fc`.
- Final full `tests/run_auth_checks.py`: **483 passed, 20 skipped**
  (38.63 seconds). The 20 skips are the existing Linux filesystem boundary tests
  on Windows; no new tests were skipped.
- Existing dependency-free Linux filesystem regression in an owned read-only,
  no-network cached Python container/private volume: **21 passed**, including
  those Windows-skipped cases. No filesystem-test code changed.
- No-DB run of `test_run_requests.py` and `test_migrations.py`:
  **1 passed, 34 skipped**, preserving the fixture skip convention.
- Alembic: single head `p1_09a_run_requests`, directly after
  `p4_04a_review_queue_20261114`; upgrade/check succeeded. New regression
  downgrades/reupgrades the request migration, checks removal of its function,
  and preserves every existing table plus the review queue index. The full
  harness also downgraded to `0005_artifact_metadata` and reupgraded successfully.
- Ruff across `app tests migrations`: passed.
- Strict mypy `--platform linux app`: passed, **38 source files**.
- `pip check`: **No broken requirements found**.
- Scoped diff/secret review and `git diff --check`: passed.

Unexpected correction cycles: **2** (migration parent corrected to the actual
existing head; focused-test import/literal lint cleanup). Intentional behavioral
RED and mutation failures are expected evidence, not unresolved failures.

Cached image identities:

- PostgreSQL:
  `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`
- Keycloak:
  `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`
- Python Linux filesystem regression:
  `sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`

## Cleanup and disposition

Every harness invocation removed its captured PostgreSQL/Keycloak containers,
anonymous volumes and owned network. The Linux test container
`eaf0fe6a6fd6ed63dbef60bc6c181d0ca62b6d34ffad11e5174c82f1d4168476` and
volume `animetron-run-request-bytes-4a9d3df25e9b4db9a8455911ae2c2390` were
verified against ownership labels and removed by exact captured identity.
Only the captured worktree-local `data/oidc-test-temp` and
`data/run-request-mypy` caches were deleted; unrelated Docker resources, shared
venv, OS/WSL/Docker/global settings and processes were untouched.

No implementation blocker remains. This is not execution readiness or a
production launch certification. Downgrading a populated request table destroys
replay evidence and requires explicit authorization/recovery planning.
No push, PR, merge or external publication was performed by the author.

## Independent review and execution - 2026-11-14

Direct source review found no required correction at
`6e0e28632922bbf07dd87b9f97142abf8edf8940`. A separate QA agent verified
that exact HEAD/base/import provenance and independently executed:

- Full owned harness: **483 passed, 20 existing Windows skips** (39.06s).
- Focused owned request suite: **32 passed** (1.31s), including real contention,
  payload conflicts, late unique violation/savepoint and outer SQL rollback.
- No-DB request/migration tests: **1 passed, 34 skipped** (0.23s).
- Single migration head, upgrade/metadata parity, new downgrade/reupgrade
  regression and lifecycle roundtrip to `0005_artifact_metadata`: passed.
- Ruff, strict Linux-target mypy (**38 source files**) and pip consistency:
  passed. The 21 Linux filesystem cases above remain author-only evidence.

No product or test changes were needed. A preflight import path was corrected
before harness execution. QA used sequential owned harnesses, cached images,
disposable local caches and no downloads or dependency installation.
Exact captured PostgreSQL/Keycloak containers, networks and anonymous volumes
were verified absent afterward. Docker inventories returned to baseline;
131 target and 128 parent baseline file hashes were unchanged. Existing dirty
parent reconciliation/user files were preserved.

The persistence slice is verified locally. Remote checks and normal merge
remain pending; P1-09a remains unchecked in the sole tracker.

## Verified merge checkpoint

Merged normally in [#48](https://github.com/yanxel18/animetron/pull/48) at
`d5f7f43e3ccaafdc2f4b24dc294633158c29bf69` after the direct review and
independent execution above. Exact-head GitGuardian passed at
`aaccce7f2c3a1c6066afed371e875a72494508ef`; mergeability was clean, with
no outstanding requested reviewers or branch rules. No self-approval or
check/protection waiver occurred. Root master was pulled and backend/spec
matched the independently tested core. Prior pending statuses are historical.
[todo.md](todo.md) remains the sole current checklist. Only P1-09a is complete;
this does not complete workflow APIs, node execution or P9.
