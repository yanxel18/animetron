# P4-02 Review Records Report

## Scope and design

This slice adds an internal, trusted-server persistence store for review
requests, delivery outcomes, explicit expiry, and immutable decisions. It
reuses `ReviewScope` and `ReviewDestination`; it does not add HTTP/UI, reviewer
authorization, `getValidApproval`, Telegram or other network transmission,
outbox/publication effects, model behavior, or deployment. Stored records are
not authorization or approval proofs.

The caller supplies an aware expiry; 24 hours remains a proposal, not a
default. Writes require the caller's active non-autocommit psycopg transaction.
PostgreSQL guards immutable scope and decision data, legal state and expiry
transitions, a single current request per run, and the decision/state match.
Changes to a run's exact scope supersede its active prior request, including an
approved request, without rewriting the prior scope or decision. Delivery
outcomes record only a bounded error code and never transmit content.

## Bounded source inventory

- `backend/app/services/reviews/store.py` — typed caller-transactional store
  and state transitions.
- `backend/migrations/versions/p4_02_review_records_20261114.py` and
  `backend/migrations/env.py` — tables, constraints/triggers and Alembic
  metadata registration.
- `backend/tests/test_review_store.py` — disposable-PostgreSQL behavior,
  rollback, immutability and race tests.
- `backend/README.md` and `docs/SPEC-human-review.md` — implementation boundary,
  expiry caveat and future migration-head note.
- `tasks/todo.md` — P0-09a reconciliation with merged #39; P4-02 remains
  unchecked until its PR is merged.

## Verification

- TDD began with a failing import for the missing store. The focused real-PostgreSQL
  review and scope tests passed (29 tests); an intentional delivery-state guard
  mutation caused its test to fail, then the original guard was restored.
- Full backend suite on the exact-owned disposable PostgreSQL database:
  **251 passed, 20 skipped**. The skips are existing Linux-only artifact
  filesystem cases on this Windows host.
- Ruff: passed (`app`, `tests`, `migrations`).
- Strict Linux-target mypy: passed, 26 source files.
- `pip check`: no broken requirements.
- On the fresh disposable database: `alembic upgrade head`, `alembic check`,
  `alembic downgrade -1`, re-upgrade to head, and final `alembic check` all
  passed. Both checks reported no new upgrade operations; the sole head was
  `p4_02_review_records_20261114`.

## Findings and residual risks

- No outstanding P4-02-specific correctness finding was identified in the
  implementation and verification above. This is not an independent approval
  or a production-readiness claim; PR review and the configured scanner remain
  gates.
- Auth #33 remains independently blocked by its historical GitGuardian result
  and conflicts. The merged credential-exclusion PR #39 is not Auth #33
  clearance.
- P4-02 descends from `0005_artifact_metadata`. Auth #33 also has a migration
  descending from that revision; when that branch is integrated, reconcile the
  parallel Alembic heads with an explicit merge revision. Neither branch's
  revision should be renamed to conceal the dependency.
- No delivery sender, role policy, valid-approval proof, or publication
  authorization is provided by this store. Do not treat stored decisions as
  permission to publish.

## Cleanup

After verification, removed only the exact P4-02-owned PostgreSQL container
`f33409614c309a5e93e9baca48bae0fcd841a42d3c561a1ec0a4f3763d487b91` using its
immutable ID after confirming the pinned image and `P4-02` task/session/owner
labels. A subsequent inspect confirmed the container was absent. Worktree-local
temporary directories are task-labeled and will be removed after the remaining
GitHub checks.

## Pull request

Pending push and creation/update of the separate PR targeting `master`.
