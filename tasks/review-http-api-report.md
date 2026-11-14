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
