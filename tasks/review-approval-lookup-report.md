# P4-04b internal current-approval lookup — local handoff

Date: November 14, 2026. Status: implemented and locally verified only.

## Identity and owned scope

- Worktree: `D:\animetron\.worktrees\review-approval-lookup`.
- Branch: `feature/review-approval-lookup`.
- Verified base (merged #43): `70035139e69a601d68ac0bc8d55b66102d9d7046`.
- Verified implementation commit: `69374397fc8fdd47a8f26b0d0004c9d13f1ee64e`.
  This report is a separate documentation-only local commit; its SHA is supplied
  in the final handoff, not embedded self-referentially.
- Implementation commit owns only `backend/app/services/reviews/approvals.py`,
  `decisions.py`, `store.py`, `backend/tests/test_review_approval_lookup.py`,
  `backend/README.md`, and `docs/SPEC-human-review.md`.
- This report is the only additional owned task file.
- Required `Co-authored-by: Copilot
  <223556219+Copilot@users.noreply.github.com>` trailer is present.

The parent's uncommitted reconciliation files were not edited, staged or
committed. Before/after SHA-256 values are identical:

| Protected file | SHA-256 |
| --- | --- |
| `tasks/todo.md` | `7FBF5BE4C7A6E461AA7901389CED5387B9EC9583E5F9E805E8268EC04CF42604` |
| `tasks/development-report.md` | `B64E2DB46B9DA665052FD082604480142E9755B38EC50A7C8DB7561424492D56` |
| `tasks/review-decision-service-report.md` | `57D9AED647D874884DEACBFCD4DD2D54A55C435FCED368DF9FB2A384F340E59D` |

## Implemented contract

`require_valid_approval(connection, review_id, expected_scope, *,
auth_config: AuthConfig) -> CheckedApproval` is an 85-line internal service.
The returned record, its `ReviewScope`, and its `ReviewDecision` are frozen.
It contains exact scope, review/decision identity, decision owner/time and expiry.

It reuses existing transaction/UUID4 validators, scope/store reads,
`approval_intent_id`, `APPROVED_TOPIC`, and `auth.digest`. It derives the owner
identity as `digest(issuer + "\0" + owner_subject)`, matching
`AuthStore.create_session`; changed issuer/owner or a former owner now granted
operator access cannot match. Configuration must be current trusted-server
settings, never client supplied. An active human-owner session is not required.

One 18-line canonical `lock_review_request` extraction is shared by the existing
decision service and lookup. It locks the **stored** workflow run, then request,
then rereads. The lookup locks the reserved outbox intent last and checks expiry
strictly against fresh PostgreSQL `clock_timestamp()` after that lock. Current
APPROVED state, exact scope, matching immutable APPROVED decision/current owner,
and reserved intent ID/topic/resource are all required. Missing or invalid
records fail loudly via existing lookup/conflict/type/validation errors.
No duplicated transition state machine or new dependencies/schema are added.
The existing decision service's savepoint, transitions and final expiry guards
remain intact.

## Verification evidence

All harness runs used the existing interpreter:
`D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe`.
Process-local settings were task-backend `PYTHONPATH`,
`PYTHONDONTWRITEBYTECODE=1`, and `PYTHONTZPATH=''`.

Focused RED/GREEN runs executed the existing `tests/run_auth_checks.py` via
`runpy` with `--storage`; an in-process `subprocess.run` wrapper changed only the
pytest selection from auth storage to `tests/test_review_approval_lookup.py`.
It also forced Docker `--pull never`. The checked-in harness was never edited.
Its ownership marker, excluded inherited URLs, migration checks, loopback PG,
and captured-container/network cleanup remained unchanged. No independent DB
setup or ownership bypass was used.

| Gate | Exact result |
| --- | --- |
| RED, before lookup implementation | **27 setup errors**, absent `app.services.reviews.approvals`; these were missing-implementation errors, not 27 behavioral assertions |
| Initial GREEN attempt | **19 passed, 8 failed**; fixture construction violated existing immutable-history/state triggers |
| Corrected focused GREEN | **28 passed**, 5.50 s |
| Existing FULL `python tests/run_auth_checks.py` (no selection wrapper, no `--storage`) | **408 passed, 20 skipped**, 33.32 s; actual owned PG + Keycloak/browser checks |
| Full-harness Ruff | **All checks passed**, `ruff check --no-cache app tests migrations` |
| Full-harness strict Linux-target mypy | **Success: no issues found in 33 source files**, `mypy --platform linux app` with checked-in strict configuration |
| `python -m pip check` | **No broken requirements found** |
| `git diff --check` and staged equivalent | **Passed** |
| Focused run without DB URL | **28 skipped**, 0.19 s; existing infrastructure skip convention preserved |

Two small correction steps stayed within the maximum three cycles: import
ordering after RED, then schema-respecting test fixtures after initial GREEN.
No production guard required correction after implementation.

The 28 focused cases cover frozen success/no writes, unchanged caller transaction
and real outer rollback, success after actual AuthStore session creation/removal,
every non-APPROVED state, every scope field, missing review/decision/service
evidence, wrong intent ID/topic/resource, exact/current/former owner identity,
invalid transaction/AUTOCOMMIT/UUID/scope/config types, mismatched decision reads,
and expiry after a real final intent-lock wait.

The wait test holds the outbox row on a separate PG connection, observes the
lookup worker's `pg_stat_activity.wait_event_type = 'Lock'`, waits until advancing
DB time reaches request expiry, confirms the worker remains blocked, then releases
the lock and requires `ReviewConflict`. Locks and rollback are not mocked.
All nonapproved states use real existing store transitions. Missing decision is
an uncommitted intermediate state followed by actual rollback; deferred DB guards
would prohibit its commit. Two mismatched-decision metadata cases substitute the
store read because schema triggers prohibit those committed records; they do not
claim to reproduce database corruption or substitute locking.

## Private mutation and cleanup

A private copied backend at
`data/approval-lookup-mutation-958a4e10/backend` disabled the scope, current-owner
and expiry guards without touching committed source. Running its copied,
unchanged ownership-checked harness with the focused selection produced
**11 failed, 17 passed** in 5.54 s: all five scope cases, all five owner cases,
and the real final-lock expiry case detected the mutant. The deliberate private
owner-disable expression also produced Ruff `SIM223`; canonical source Ruff
remained clean. This is one targeted combined mutation, not a mutation-score
certification.

Every one of the five harness invocations removed its captured owned PostgreSQL
container/anonymous volumes and network; the full invocation also removed its
owned Keycloak container. Final label-filtered container/network listings were
empty. Cached images were verified before execution:

- PostgreSQL: `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`.
- Keycloak: `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.

Private copy cleanup checked the exact captured path beneath this worktree's
`data` directory and its preexisting ownership marker before removing it.
Absence was verified afterward. The task harness scratch directory was empty
after pytest cleanup; only ignored project-local mypy/pytest caches remain.
No inherited DB URL, download, shared environment change, nested agent, source
upload, push, PR, GitHub operation or live publication effect occurred.

## Boundaries and limitations

- This is current-state inspection only, **not** a cryptographic proof,
  reusable authorization capability, cached publication permission, or artifact
  byte verification.
- Metadata is valid only for checked state/current settings at this caller
  transaction. A trusted publisher must call/recheck on **every attempt and
  before effects**; time and settings can change after return.
- Fresh caller authentication/authorization remains a future transport/publisher
  boundary. No caller-supplied role/digest defaults are accepted.
- No enqueues, state transitions, transmission, commit/rollback ownership change,
  endpoint, publisher, deployment or full P4/P9 completion claim.
- Privileged arbitrary DB writers remain outside trusted-storage integrity.
- Caller owns transaction-local lock/statement budgets and bounded retries using
  current settings; database failures propagate.
- The full suite's 20 existing native-Windows platform skips remain. A separate
  Linux artifact-byte suite was not run for this lookup-only slice.
- No outstanding implementation or verification blocker. Independent review,
  publishing integration and any remote/merge action remain outside this handoff.
