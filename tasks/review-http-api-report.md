# P4-04a Review HTTP API Delivery Report

## Delivered

- Added owner-only `GET /api/v1/reviews` for existing request metadata and
  `POST /api/v1/reviews/{id}/decisions` for exact-scope approve/reject decisions.
- Reused the canonical request-bound auth dependency and existing
  `record_decision` service. Every decision, including an identical retry,
  authenticates the current opaque server session; owner role, exact Origin,
  and CSRF are enforced server-side.
- Queue traversal is ascending `(created_at, id)` keyset pagination, with an
  opaque timestamp/UUID cursor, `limit` default 50/max 100, a bounded
  `limit + 1` query, and a matching composite database index.
- Enforced strict camelCase input, unknown-field/query rejection, UUID4 and
  review-scope validation, and a 4096-byte decision body cap. Responses use
  shared error envelopes and security headers; internal database details are
  not returned.
- Updated the human-review spec, backend auth guide and backend README. This
  change adds no review creation/delivery, content-byte access, approval lookup,
  UI, MCP, Telegram, model, outbound/live publication or deployment surface.

## Verification

Using
`D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe` and the
owned disposable PostgreSQL/Keycloak harness:

- Focused review API checks: **27 passed**.
- Full backend/auth harness: **435 passed, 20 skipped**.
- Ruff: passed.
- Strict Linux mypy: passed, 35 source files.
- Alembic upgrade/check and downgrade/upgrade regression: passed in the harness.
- `pip check`: no broken requirements.
- `git diff --check`: passed.
- Targeted private mutation changed strict input handling from `extra="forbid"`
  to `"ignore"`; the unknown-body-field test failed as expected (**26 passed,
  1 failed**). The original source was restored immediately.

The harness used cached PostgreSQL 18 and Keycloak 26.8.2 images with
`--pull=never`; it removed only its owned containers, anonymous volumes, and
network. The owner preview at `127.0.0.1:5173` was left running.

## Scope and handoff

The queue is metadata-only and does not create byte or publication authority.
Decision state, expiry, replay, supersession, intent, and transaction rollback
remain governed by the existing service. `create_api` without explicitly
configured auth and engine remains fail-closed.

Parent-owned `tasks/todo.md` and `tasks/development-report.md` were not staged
or included in the implementation commit.

## Required correction cycle 1: Content-Length digit limit

Corrected implementation SHA:
`ed1635479b113b4cdf0c55452682bd3174ff9dd2`
(original implementation: `e47737e78fb05b5a131cdbf4fee8d6aba0707c3f`).

Direct review reproduced an attacker-sized decimal Content-Length raising
Python's integer digit-limit ValueError and returning the generic 503. Replaced
integer conversion with canonical decimal length/lexicographic comparison.
ASCII decimal validation and leading-zero numeric semantics are preserved;
oversized values now return the explicit 422 `REVIEW_BODY_TOO_LARGE`.
No parser or auth redesign was needed.

Added seven no-database regressions for extreme/zero-padded lengths, streaming
without Content-Length above 4096 bytes, leading-zero acceptance, and the
exact-4096-byte parsing/auth paths. Requests assert shared redacted envelopes
and security headers. Chunked cases assert that Content-Length was absent.

- Smallest focused RED (`pytest tests/test_reviews_api.py -k body_guard -q
  --tb=short -p no:cacheprovider`): **4 failed, 3 passed, 27 deselected**.
  Oversized declarations incorrectly returned 503; long zero-padded accepted
  values returned `DEPENDENCY_UNAVAILABLE` instead of reaching fail-closed auth.
- Same focused GREEN after correction: **7 passed, 27 deselected**.
- Full owned cached-image harness: **442 passed, 20 skipped**; Ruff and strict
  Linux mypy passed (35 source files), as did Alembic checks/round trip.
- `pip check`: no broken requirements; diff whitespace checks passed.
- All captured owned containers/volumes/network were removed. No preview,
  shared settings, parent tracker/report, remote branch, PR or deployment was
  changed. Short failure output contained no credentials.

## Independent final verification

Independent QA executed HEAD
`4e2c761ff68c85ebc390269ebd85b2478bb66458`, corrected core `ed163547`,
on base `9d14aca`. `python -u tests/run_auth_checks.py` passed with
**442 passed, 20 skipped**, including all 34 API cases, actual final-intent
approval expiry-lock and both decision expiry-lock regressions. Migrations,
Ruff and strict Linux-target mypy (35 files) passed. `pip check` passed.
Without database URLs, `python -m pytest tests/test_reviews_api.py -q --tb=no
-p no:cacheprovider` produced **8 passed, 26 skipped**.

The first QA run passed tests but exited 2 because its process-local
`MYPY_CACHE_DIR=NUL` was invalid for mypy on Windows. A disposable cache resolved
that invocation error; the entire harness was rerun successfully. This was
not a source defect or a waived check.

Imports resolved to this worktree. Cached PostgreSQL/Keycloak images were used
with `--pull=never`; both runs' captured containers, networks and anonymous
volumes were confirmed removed. No shared resource cleanup occurred. Backend
matched HEAD and nothing was staged by QA. Parent documentation edits explain
hash changes during preparation; subsequent hashes remained stable.

Direct source review found no remaining required correction after the bounded
decimal fix. No formal GitHub self-approval is implied. PR/remote checks/merge
remain pending at this checkpoint, and full P9 is not complete.
