# P4-03a internal review decision service

Date: November 14, 2026. Branch: `feature/review-decision-service`.
Base: verified #42 `8bc096c95b3065f782dc0a624284224fd8e1b8c3`, followed by
local documentation reconciliation `52e52eb`. This report is included in the
single scoped local feature commit; its SHA is returned in the caller handoff.

## Implemented boundary

- Added `backend/app/services/reviews/decisions.py` (138 lines after the source-review correction): typed
  `record_decision(connection, principal, expected_scope, review_id, outcome)`.
- Explicit non-AUTOCOMMIT SQLAlchemy psycopg caller transaction; owner-only,
  aware Principal and request expiry checked against a fresh advancing database
  clock after run/request locks and again after the final intent lock/insert.
  Fresh server authentication before every invocation is the caller's contract,
  not something this function can infer from a Principal value.
- Stored run lock precedes request lock, matching scope supersession. Exact
  scope, current state, expiry and replay guards precede decision/effects.
  Existing request/decision reads and `decide_review` remain the state machine.
- Approval and one stable internal outbox notification use one savepoint;
  database and Python enqueue failures roll back both even when caught by the
  caller. Outer commit/rollback and lock/statement budgets remain caller-owned.
- Namespaced UUID5 intent, reserved `internal.review-approved.v1` topic.
  Identical valid replay adds no effects. Changed topic/resource, conflicting
  reviewer/outcome and any pre-existing intent on an undecided request fail.
  Low-level APPROVED rows without matching service intent are not promoted.
- Rejections enqueue nothing. No new endpoint, migration, dependency, adapter,
  outbound content, publication proof/intent, automatic consumer or deployment.
- Updated only the requested SPEC boundary and backend README alongside code,
  focused tests and this report. Parent tracker edits were neither edited nor
  staged.

## Verification evidence

Interpreter: `D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe`.
Task-local `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONTZPATH=""`.
No dependency installs, source push, PR, GitHub access, model downloads or agents.

- **RED before implementation:** focused file failed collection because the
  service module did not exist: **1 collection error, 0 tests executed**.
  This is an import-boundary RED, not 37 behavioral failures.
- **Focused GREEN:** **37 passed**, 4.16 seconds.
- **Full GREEN:** **378 passed, 20 skipped**, 21.63 seconds. Existing Linux-only
  filesystem cases skip on Windows; no new skips or disabled assertions.
  Full harness includes actual PostgreSQL, Keycloak and browser checks,
  migration upgrade/check and downgrade/re-upgrade.
- Harness: `python tests/run_auth_checks.py`. Focused RED/GREEN used an in-process
  command-selection wrapper replacing only pytest's `tests` argument with
  `tests/test_review_decision_service.py`; the checked-in harness was unchanged.
  Owned provisioning, URL exclusion, ownership proof and cleanup stayed intact.
- Ruff `check --no-cache app tests migrations`: clean. Strict Linux-target mypy
  (`--platform linux`, strict project configuration): **32 source files clean**.
  Standalone `--strict` check also passed; `pip check`: no broken requirements.
  `git diff --check`: clean.
- Private project-contained mutations, using the full harness's same owned DB:
  widened role guard: **4 failed / 2 passed**; inverted exact-scope guard:
  **10 failed**; replaced savepoint with `nullcontext`: **2 failed**, covering
  real database and Python exceptions after a real outbox insertion.
  Each mutant had to exit with test-failure status; none survived.
- Tests also exercise opposite concurrent decisions on separate PostgreSQL
  connections, same valid replay across transactions, changed scope fields,
  stale/naive Principal, expired/superseded replay, low-level approval refusal,
  rejection without intents, outer rollback and explicit transaction/UUID typing.

## Parent source-review correction 1 (of maximum 3)

1. **No-URL regression:** the focused file's `engine` fixture raised `KeyError`
   without `ANIMETRON_TEST_DATABASE_URL` (parent repro: 1 setup error with
   `--maxfail=1`). Restored the same conditional missing-infrastructure
   `pytest.skip` used by existing DB suites. Now: **39 skipped**, no errors.
2. **Time-of-check flaw:** `database_now` was taken after run/request locks but
   before `select(outbox).with_for_update()`, so an identical approval replay
   blocked on a held intent row could return APPROVED after the Principal or
   request expired. Added a real PostgreSQL regression (parametrized principal/
   request expiry): a second connection holds the intent row lock, the replay
   runs on another connection, `pg_stat_activity.wait_event_type = 'Lock'` is
   observed, the test waits until the database clock passes expiry, then
   releases the blocker and expects `AuthDenied` / `ReviewConflict` with the
   decision and single intent unchanged.
   - **RED on prior code (owned harness, focused):** **2 failed, 37 passed**;
     failures were `DID NOT RAISE AuthDenied` and `DID NOT RAISE ReviewConflict`
     after the lock wait assertion passed.
   - **Fix:** `_require_unexpired` uses a fresh `clock_timestamp()`; called after
     run/request locks (unchanged early guard) and again after the last
     potentially blocking intent lock/insert before any successful return
     (replay and new decision). Failure inside the savepoint rolls back any
     decision/intent. Scope, current-state, collision guards and savepoint
     atomicity are unchanged.
   - **GREEN:** focused **39 passed**; full harness **380 passed, 20 skipped**
     (same 20 existing Linux-only Windows skips); Ruff clean; Linux-target mypy
     and `--strict` clean (32 files); `pip check` clean; `git diff --check` clean.
   Docs (SPEC/README) wording updated to match the recheck placement.
   Five correction harness runs (RED, two RED diagnostics, focused GREEN, full) each
   removed their owned containers/volumes/network; final Docker listings showed
   no `animetron-oidc` containers or networks. No mutation scratch copies used.

## Corrections, cleanup and limits

Two correction rounds, below the maximum of three: corrected three new-test
Ruff findings (imports/context managers), then corrected the new clock-error
exception type flagged by Ruff. No GREEN functional correction was needed.
An optional `.ruff.toml` inspection found no such file; this was a probe error,
not a failed quality gate, and no configuration was created or changed.

Three owned harness runs each removed their PostgreSQL/Keycloak containers,
anonymous volumes and network. Images were already cached:
PostgreSQL `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`;
Keycloak `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.
Final Docker listings showed no harness resources; unrelated Excel-translator
workloads were preserved. Private mutation copies were deleted only after exact
project-root/path and ownership-marker checks. Harness temp was empty/removed.
The actual service was never mutated during these experiments.

The reserved intent is trusted-writer bookkeeping evidence, **not authentication
or publication authority**: arbitrary database/outbox writers could forge it.
Callers must freshly authenticate (including revocation checks) and preserve
reserved intent history; deletion makes approval replay fail closed. No
`getValidApproval` or downstream publisher is implemented. The returned
`ReviewDecision` is an immutable record, not an approval proof.

No unresolved implementation blockers. Windows verification does not certify
the existing Linux filesystem tests, load performance, or any live deployment.
`tasks/todo.md` and `tasks/development-report.md` remain parent-owned and excluded
from the local feature commit.
