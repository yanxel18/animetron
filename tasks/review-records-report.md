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

- The initial author checks did not identify the defects subsequently found by
  independent QA at `21ca53f217753db4bdbadae19b39af8330fc0118`. That QA verdict
  was **FAIL**, not approval. Correction cycle 1/3 below records the fixes;
  independent reassessment remains pending. GitGuardian passed on the earlier
  checked PR heads; any later update must pass a fresh check.
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
temporary directories used for this task were removed by their
`p4-02-20261114-1215` session prefix after the final PR check. All direct
entries under `.agent-tmp` belonged to that task session; the directory was
absent after cleanup.

## Pull request

Open PR [#40](https://github.com/yanxel18/animetron/pull/40), targeting
`master` from `feature/review-records`. P4-02 remains unchecked pending merge.

## Independent QA correction cycle 1/3

Initial QA at `21ca53f217753db4bdbadae19b39af8330fc0118` failed on:

1. Raw inserts could start `APPROVED`/`REJECTED` without a decision because
   the deferred decision/state trigger covered updates only.
2. The workflow revision validator admitted reviewer labels the database's
   `ck_review_reviewer_id` rejected, aborting the caller transaction.
3. Disabling the database expiry guard left the original seven store tests
   green; direct SQL expired-delivery transitions were not covered.

Resolution is limited to those findings:

- Added a database insert trigger requiring `PENDING_DELIVERY`, with symmetric
  function removal on downgrade. Raw-SQL approved/rejected insert regressions
  both failed before the fix, then passed.
- Replaced the inappropriate revision validator with the existing store's
  `re.fullmatch` pattern, matching the database's
  `[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}` identifier format. Documented that
  reviewer labels confer no authority. Invalid-label regressions prove no
  decision/state write remains, the transaction is usable without a savepoint,
  and a subsequent valid decision commits. Space-containing and leading-dash
  labels reproduced the database error before the fix.
- Added a deterministic raw-SQL expired-request transition regression (no
  sleeps and no application delivery guard). Temporarily disabling the
  migration's existing expiry guard made it fail with `DID NOT RAISE`;
  the correct source guard was restored unchanged.

Verification on a fresh exact-owned pinned PostgreSQL container:

- New regression RED run: 4 failed, 3 passed (two insert-state failures and
  two reviewer-format failures). Expiry mutation: 1 failed as intended.
- Corrected store/scope suite: **36 passed**.
- Coupled full backend suite: **258 passed, 20 unchanged Linux-only skips**
  on Windows.
- Corrected migration upgrade/check/downgrade/re-upgrade/check passed on a
  fresh database. Both schema checks reported no new operations.
- Ruff passed after combining the expiry test's nested contexts; strict
  Linux-target mypy passed for 26 source files and `pip check` found no broken
  requirements. The final store/scope rerun after that test-only edit also
  passed all 36 cases.
- The earlier mutation database had the pre-correction migration installed.
  A corrected-source downgrade there encountered the absent new insert-guard
  function and rolled back. Final lifecycle verification used a new fresh
  database, not a destructive reset or a production database. This amends an
  unmerged migration; already-upgraded disposable QA databases must be
  recreated for reassessment. No production migration or deployment is implied.

Only store, review migration/tests, related README and this report/tracker were
changed. Auth #33 and all authorization/publication/model gates are unchanged.

QA1 cleanup: container
`8b0805f6d339d510bbfcfc461e56123b288d785cdedcc138e8569869c6b4bbb7`
was removed by exact ID after checking the pinned PostgreSQL image, loopback
binding and `P4-02` / `p4-02-qa1-20261114-1256` / owner labels. A captured
inspect subsequently returned “no such object”. All QA1 helpers/caches are
confined to `.agent-tmp/p4-02-qa1-20261114-1256`; they are removed after the
final GitHub verification, with exact absence evidence returned to the reviewer.

## Verified merge checkpoint - 2026-11-14

Independent reassessment passed at `d7c345d` after the corrections recorded above.
The reviewer reproduced 36 focused and 258 full passing tests, 20 unchanged
Windows skips, the migration lifecycle, Ruff, Linux-target mypy26 and dependency
consistency. The expiry mutation was caught. Parent-verified GitGuardian and
clean mergeability passed before normal merge of
[#40](https://github.com/yanxel18/animetron/pull/40) at `2ac3213`.
The prior in-review and failure notes above are historical checkpoints.
Authorization, publication, Auth #33 integration and P9 remain open.
