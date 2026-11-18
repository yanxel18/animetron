# AnimeTron project progress

This is the single project-wide implementation checklist. Last reconciled with
verified remote `master` at `c0560a1` on 2026-11-18. #53 and #54 merged
the mobile navigation and API contract slices; #55 reached master through #54.
#56 reconciled progress documentation, #57 merged read-only run monitoring,
and #58, #59 and #60 merged the schedule list, preview and pause/resume.
#61 merged Chromium coverage for schedule-conflict focus recovery.
#62 merged owner-only reads of known immutable workflow revisions.
#63 merged bounded revision discovery for a known workflow ID.
#64 merged owner-only discovery of workflow IDs with persisted revisions.
The historical #33 scanner failure remains unresolved. #73 merged at
`df80d91`, but is not credited until the missing GitHub review and check gates
are satisfied. #84, #86 and #87 also merged; their only reported check is
GitGuardian and none has an independent GitHub review record.
The owner approved the
[module specifications](../docs/SPECIFICATIONS.md) for implementation and version
control on 2026-11-14. Their explicit provider, model, scheduling, performance
and human-acceptance gates still apply. This checklist does not replace them.

## Overall progress snapshot - 2026-11-18

**31.6%: 18 of 57 top-level P0-P9 checklist tasks are complete.** This is an
unweighted task count, not a measure of effort, functionality or production
readiness. Nested slices are not counted separately; a partially completed
parent task stays incomplete, and open PRs do not count as complete. No phase
or P9 acceptance is complete. Recalculate this snapshot when the checklist or
merged status changes and after each completed task or slice, even if the
percentage is unchanged. Recalculated after reconciling latest verified master
`c0560a1`; #82, #83, #84, #86, #87, #88, #89, #90, #91, #92 and #93 are merged but
are not credited without a passing independent review and required checks.
#86 includes P1-08c and P1-10c;
#87 adds P1-11b; #88 adds P1-12a; #89 adds P1-12b; #90 adds P0-07d; #91
verifies P0-07c; #92 adds P1-12c; #93 addresses the #91 review findings.
P1-09f reached master via
#82, and P1-09i via #84. These slices do not complete their parent tasks; the
percentage and per-phase counts remain unchanged.

| Phase | Top-level tasks complete |
| --- | ---: |
| P0 Foundations | 4 / 9 |
| P1 Workflow runtime | 7 / 12 |
| P2 Model readiness | 1 / 6 |
| P3 Media generation | 0 / 5 |
| P4 Human review | 4 / 6 |
| P5 Publication | 0 / 4 |
| P6 Scheduling | 1 / 3 |
| P7 Creator studio | 1 / 6 |
| P8 MCP bridge | 0 / 2 |
| P9 Integrated readiness | 0 / 4 |

Main remaining gates include the unresolved #33 scanner review/check state,
missing authorized artifact lifecycle and workflow execution/editing services,
model feasibility and capacity, real media generation, and owner-involved P9
acceptance.

## How to use

- Toggle a Markdown task by editing `[ ]` to `[x]` (or back to `[ ]`).
- Check a task only when its work is merged to `master` and its stated checks
  have passed. Link the merged PR or other evidence. An open PR is not done:
  leave the box unchecked and link the PR as **in review**.
- Before starting and with each task PR, reconcile merged work, update the
  affected items and this document's date, and record blockers or changed scope.
  Split an item into smaller checkboxes when necessary; keep their evidence.
- After each completed task or slice, record accomplished work and recalculate
  the top-level counts, percentage and phase table; nested slices alone do not
  change the top-level percentage.
- Phase completion requires every task in that phase and its completion gate.
  Phases are dependency ordered, but independent slices may run in parallel.
- No delivery date or effort estimate is established. Estimate and update dates
  only after scope, hardware, provider eligibility and capacity are confirmed.
- The owner has authorized the assistant to merge reviewed, verified PRs.
  This checklist does not authorize deployment, live publishing, model licenses,
  model downloads or external transmission.

### Session handoff - 2026-11-14

An earlier session stopped at the owner's request. At that point P7-01b was
paused and unimplemented, and its incomplete test and manifest changes had
been removed. Subsequent work is recorded below.
P0-P9 is not complete. Preserve all unchecked tasks and approval gates.
See the [closeout report](session-closeout-report.md) for cleanup scope and
verification. This checklist remains the only current progress source.

### Earlier activity - 2026-11-18 (superseded by latest reconciliation)

The following session notes precede the reconciliation with master `181bf6c`;
use the current-work section below for present branch and PR status.

- P7-05a mobile navigation focus merged to master in
  [#53](https://github.com/yanxel18/animetron/pull/53).
- P7-01b generated API contracts and P7-04a review metadata queue reached
  master via [#54](https://github.com/yanxel18/animetron/pull/54) and
  [#55](https://github.com/yanxel18/animetron/pull/55). The combined frontend
  unit tests, production build, seven Chromium tests, API drift check and
  GitGuardian passed; an independent source review found stale report
  instructions, which were corrected before the owner merged #54.
- P7-03a merged in [#57](https://github.com/yanxel18/animetron/pull/57).
  This read-only, run-ID-based monitor uses persisted status and event-replay
  endpoints; it does not create or cancel runs or invent progress.
- P7-04b merged in [#58](https://github.com/yanxel18/animetron/pull/58):
  a read-only owner-only schedule list using the existing authenticated
  descriptor API. Create, edit, preview and dispatch were outside that slice.
- P7-04c merged in [#59](https://github.com/yanxel18/animetron/pull/59):
  preview five occurrences of an existing schedule without saving or dispatching.
- P7-04d merged in [#60](https://github.com/yanxel18/animetron/pull/60):
  version-checked owner-only pause/resume, without scheduler dispatch.
- P7-05b merged in [#61](https://github.com/yanxel18/animetron/pull/61):
  verify schedule conflict-recovery focus in Chromium with delayed responses.
- P1-09b merged in [#62](https://github.com/yanxel18/animetron/pull/62):
  owner-only reading of an already-known immutable workflow revision.
- P1-09c merged in [#63](https://github.com/yanxel18/animetron/pull/63): bounded
  discovery of revisions for a known workflow ID.
- P1-09d merged in [#64](https://github.com/yanxel18/animetron/pull/64): discover workflow
  IDs with persisted revisions without inventing draft or readiness data.
- P7-02a merged in [#65](https://github.com/yanxel18/animetron/pull/65):
  a read-only workflow and revision browser, without editing or execution.
- P7-02b merged in [#66](https://github.com/yanxel18/animetron/pull/66): inspect an
  immutable revision as read-only data, without editing or execution.
- P7-04e merged in [#67](https://github.com/yanxel18/animetron/pull/67): create schedule
  descriptors without dispatch, preserving uncertain-outcome handling.
- P6-02d merged in [#68](https://github.com/yanxel18/animetron/pull/68): internal durable
  schedule-slot observations, without scheduler dispatch or outcome decisions.
- P1-10b merged in [#69](https://github.com/yanxel18/animetron/pull/69): pure deterministic
  sample graph evaluation, not persisted or dispatched execution.
- P1-09e draft persistence had been investigated only before the 2026-11-15 stop.
  The internal mutable-draft slice merged in
  [#73](https://github.com/yanxel18/animetron/pull/73) at `df80d91`. It stores
  bounded exact UTF-8 bytes separately from immutable revisions and uses
  caller-owned transactions with version-checked updates; it adds no API, UI,
  validation, execution or external effects. The PR reports 7 focused PostgreSQL
  tests, Alembic upgrade/check, Ruff, Linux-target mypy, and a backend suite
  outside owner-gated auth suites (348 passed, 335 skipped). The PR description
  reports an independent review with no findings, and GitGuardian passed; GitHub
  has no review record and the combined status is pending. It merged before
  those required gates were recorded; keep this slice unchecked and do not infer
  approval from the PR description or merge.
- [#70](https://github.com/yanxel18/animetron/pull/70) merged the previous
  progress reconciliation. On `c0da081`, recounting confirms 18 of 57
  top-level tasks complete (31.6%); newly completed slices do not by themselves
  complete their parent tasks.
- [#71](https://github.com/yanxel18/animetron/pull/71) merged at `edb4858`,
  adding task-by-task progress recount instructions. An independent
  post-merge review found no code corrections; however, GitHub has no review
  records and the PR body said independent review was pending at merge. The
  exact-head GitGuardian check passed, but no other check runs or statuses were
  present. The merge did not satisfy the independent-review gate.
- P1-09f owner-only mutable draft read is pushed on
  `task/p1-09f-workflow-draft-read` at `0afb79f` (implementation commit
  `4b6ff05`), based on `master` at `df80d91`. Workflow API, draft persistence
  and OpenAPI tests passed (62 passed, 22 skipped); PostgreSQL/Keycloak
  verification remains blocked by Windows Application Control preventing
  psycopg from loading. No PR was created through the read-only GitHub
  integration; keep unchecked and use the
  [branch link](https://github.com/yanxel18/animetron/pull/new/task/p1-09f-workflow-draft-read).
- P1-09g owner-only mutable draft write is pushed on
  `task/p1-09g-workflow-draft-write` at `b989872` (implementation commit
  `f0d21a7`), stacked on P1-09f. Focused workflow API, persistence and OpenAPI
  tests passed (76 passed, 22 skipped); Ruff and strict Linux-target mypy
  passed. PostgreSQL/Keycloak verification is blocked by the same psycopg
  restriction. No PR was created through the read-only integration; keep
  unchecked and use the
  [compare page](https://github.com/yanxel18/animetron/compare/task/p1-09f-workflow-draft-read...task/p1-09g-workflow-draft-write?expand=1).
- P1-09h owner-only mutable draft validation is pushed on
  `task/p1-09h-workflow-draft-validation` at `c6de17a` (implementation commit
  `2ceb73b`), based on P1-09g. Focused workflow/API/OpenAPI tests passed
  (119 passed, 20 skipped); Ruff, strict Linux-target mypy, and a stale-version
  mutation check passed. PostgreSQL/Keycloak verification remains blocked by
  the psycopg restriction. No PR or review comment can be created through the
  read-only integration; keep unchecked and use the
  [compare page](https://github.com/yanxel18/animetron/compare/task/p1-09g-workflow-draft-write...task/p1-09h-workflow-draft-validation?expand=1).
- P1-09i owner-only idempotent run creation is implemented in `abbb12b` on
  `task/p1-09i-workflow-run-create`, based directly on `master` at `df80d91`.
  Focused API/OpenAPI tests passed (65 passed, 20 skipped); Ruff and strict
  Linux-target mypy passed. The earlier full backend run lacked database and
  OIDC test configuration (379 passed, 335 skipped, 3 failed, 48 errors).
  No PR or review can be created through the read-only integration; keep
  unchecked and use the
  [compare page](https://github.com/yanxel18/animetron/compare/master...task/p1-09i-workflow-run-create?expand=1).
- Reconciled remote `master` at `df80d91` on 2026-11-18. Open PRs to master
  are #74, #75, #78, #79 and #81; no PRs #76, #77 or #80 targeting master were
  returned, and no new master merges were found. Recount remains 18/57
  (31.6%), P0 4/9 and P1 7/12; unmerged slices do not change these counts.
P0-P9 and owner-involved P9 acceptance remain incomplete.
Slices not yet merged to master remain unchecked. No external publishing was done.

### Current work - 2026-11-18

- Reconciled with verified `master` at `c0560a1`. PRs #75, #78, #79, #81,
  #82, #83, #84, #86, #87, #88, #89, #90, #91, #92 and #93 merged. #75 includes the
  P0-08a recovery harness from #76;
  P0-07c remains unchecked pending independent review and remaining
  integration verification. #79 includes #80 and P1-09e1; P1-09e1 stays unchecked because
  required review and status gates were not recorded. #82, #83, #84, #86 and
  #87 have no independent GitHub review records; their only reported check is
  GitGuardian. Keep the affected runtime and draft slices unchecked. #77 merged
  into stacked #76, not master; P0-07d later reached master through #90.
- P1-08c reached master through [#86](https://github.com/yanxel18/animetron/pull/86)
  at `dc26469` (implementation commit `c231472`). Focused readiness, binding,
  revision, run-request, artifact and migration tests passed (111 passed,
  123 skipped); Ruff and Linux-target mypy passed. Database-gated cases remain
  skipped because `ANIMETRON_TEST_DATABASE_URL` is unavailable. The
  handler-digest mutation was caught and restored; no model/artifact downloads
  or handler loading occurred. #86 has no independent review record and only a
  GitGuardian check. Keep unchecked pending review and required verification.
- P1-09f reached master via the P1-09g stack in
  [#82](https://github.com/yanxel18/animetron/pull/82) at `429e1a7`
  (implementation commit `4aca101`). Six focused tests, Ruff and mypy passed.
  PostgreSQL/Keycloak verification is blocked by Windows Application Control.
  #82 has no independent review record and only a GitGuardian check; keep
  unchecked.
- P1-09g merged through [#82](https://github.com/yanxel18/animetron/pull/82)
  at `429e1a7`, stacked on P1-09f. Focused tests passed (76 passed, 22
  skipped); Ruff and Linux-target mypy passed. Its only check is GitGuardian
  and it has no independent review record; PostgreSQL/Keycloak verification
  remains blocked by Windows Application Control. Keep unchecked.
- P1-09h merged through [#83](https://github.com/yanxel18/animetron/pull/83)
  at `3e5c52a`, based on P1-09g. Focused tests passed (124 passed, 22
  skipped); Ruff and Linux-target mypy passed. The full backend run had 408
  passed, 341 skipped, 3 failures and 48 errors; auth/database cases were
  blocked by the missing test database URL. Its only check is GitGuardian and
  it has no independent review record; keep unchecked.
- P1-09i merged through
  [#84](https://github.com/yanxel18/animetron/pull/84) at `eb79dbb`.
  Focused tests passed (65 passed, 52 skipped); Ruff and Linux-target mypy
  passed. The PostgreSQL-backed service tests remain unverified without the
  test database URL. #84 has no independent review record and only a
  GitGuardian check; keep unchecked.
- P1-10 production dispatch remains gated on P1-08 runtime enforcement; the
  approved spec explicitly says P1-10b's sample evaluator does not verify
  handler artifacts or model readiness and does not satisfy this prerequisite.
- P1-10c is merged through
  [#86](https://github.com/yanxel18/animetron/pull/86) at `dc26469`, stacked on
  P1-08c (implementation commit `38a6f5b`).
  The slice persists validated node dependencies and a distinct run-ready
  outbox record atomically with the run transition; readiness failures do not
  create executable intents. Focused dispatch/readiness tests pass
  (147 passed, 111 skipped), full backend Ruff passes, Linux-target strict
  mypy passes (47 app files), and Alembic reports the new revision as head.
  The full backend suite returned 420 passed, 341 skipped, 3 failures and 48
  errors; the failures are database-ownership tests and the errors are
  auth/database/Keycloak setup cases blocked by absent owned harness
  configuration, including `ANIMETRON_TEST_DATABASE_URL`. Mutating the
  duplicate-state guard made its regression test fail as expected. A live
  migration upgrade/check is likewise blocked by unavailable owned database
  configuration. Keep unchecked pending its required review and verification
  gates.
- P1-11b is merged through
  [#87](https://github.com/yanxel18/animetron/pull/87) at `cfbd7a3` (implementation
  commit `66a39de`), stacked on P1-10c.
  The owner-only endpoint records a cooperative `CANCELLING` intent and uses a
  run-derived stable outbox key; retries are idempotent and do not claim worker
  termination. Focused cancellation/dispatch/readiness/API/OpenAPI tests passed
  (26 passed, 40 skipped); skipped API cases require the unavailable owned
  PostgreSQL/auth harness. Ruff and strict Linux-target mypy passed. Frontend
  API types were regenerated; 113 frontend tests, typecheck, production build
  and API type-drift check passed. The generated contract also reconciles
  previously missing workflow-draft/validation types in the current OpenAPI
  schema. A mutation of the active-state guard failed all three targeted
  regression cases; restoring it returned all 11 cancellation service tests
  to passing. #87 has no independent review record and only a GitGuardian
  check; keep unchecked because the top-level P1-11 task remains incomplete.
- P1-12a merged through [#88](https://github.com/yanxel18/animetron/pull/88)
  at `2679b6c`. Its file-backed SQLite reconnect regression verifies cancellation state,
  ordered events and single outbox intent survive engine disposal, and a retry
  after reconnect returns the existing intent. The focused run suite passed
  (19 passed, 40 auth/database cases skipped); Ruff passed. This does not
  exercise a worker consumer or prove PostgreSQL locking behavior. Commit
  `e8e0e28` is included in #88; GitGuardian passed, but no independent GitHub
  review is recorded and the combined status is pending. Keep unchecked.
- P1-12b tests that a committed cancellation prevents a later dispatch
  preparation from producing node or run-ready intents. A retry preserves the
  cancellation intent and ordered events. Focused workflow/API tests passed
  (28 passed, 40 skipped); Ruff passed. Simultaneously weakening the dispatch
  and preflight state guards caused the new regression to fail, and restoring
  them passed. This test is sequential and SQLite-based; it does not prove a
  PostgreSQL race, stop an already-prepared run, or test a worker consumer.
  The slice merged in [#89](https://github.com/yanxel18/animetron/pull/89) at
  `4cce20c`. Its GitGuardian check passed, but no independent review is
  recorded and the combined status is pending; keep it unchecked.
  Full P1-12 end-to-end verification still requires the workflow dispatch
  consumer/worker, which is not present in the current backend.
- P0-07d merged in [#90](https://github.com/yanxel18/animetron/pull/90) at
  `b92bcc6`. Its owned PostgreSQL harness passed 7 artifact API tests,
  migrations, Ruff and Linux-target mypy. Both non-owner tests failed when
  the owner dependency was weakened, then passed after restoration. The
  OpenAPI export test, generated API type drift check, frontend typecheck,
  113 frontend tests and build passed. It exposes metadata only, not bytes or
  uploads. GitGuardian passed; no independent review is recorded and the
  combined status is pending, so keep unchecked.
- P0-07c PostgreSQL audit verification merged in
  [#91](https://github.com/yanxel18/animetron/pull/91) at `f7b3171`. Its
  owned harness passed 61 artifact tests, migrations, Ruff and Linux-target
  mypy. GitGuardian passed, but the combined status is pending. A post-merge
  independent review identified three test gaps: shared-row isolation,
  transaction ownership and separate digest/size mismatches.
- The P0-07c review follow-up in [#93](https://github.com/yanxel18/animetron/pull/93) adds
  temporary-table isolation, verifies rollback and tests the two mismatches
  separately. The owned harness passed 61 tests, migrations, Ruff and
  Linux-target mypy. Individually removing isolation, committing the caller
  transaction, or omitting either comparison caused the new regression to
  fail; restored code passed. Merged at `c0560a1`; GitGuardian passed, but no
  independent review is recorded and the combined status is pending. Actual
  filesystem/byte-store integration remains outside this test; keep unchecked.
- P1-12c verifies that a concurrent PostgreSQL cancellation request waits for
  the first transaction and reuses its committed cancellation intent. The
  owned PostgreSQL harness passed 13 cancellation tests, migrations, Ruff and
  Linux-target mypy. Removing the row lock caused the new test to fail with
  a duplicate outbox key; the restored implementation passed. Related dispatch,
  readiness and OpenAPI tests passed (14). This does not test a worker,
  dispatch contention or cancellation of already-running external effects.
  The slice merged in [#92](https://github.com/yanxel18/animetron/pull/92)
  at `5bce7b7`. GitGuardian passed, but no independent review is recorded and
  combined status is pending; keep unchecked.
- P1-12d tests both cancellation-first and dispatch-first lock orderings on
  PostgreSQL using real persisted run requests and a fake execution binding.
  The owned harness passed 8 dispatch and 13 cancellation tests, migrations,
  Ruff and Linux-target mypy. Removing both dispatch and preflight locks made
  cancellation-first resolve a handler before cancellation committed, failing
  the regression; restored locks passed. If dispatch wins, its run-ready and
  node intents remain after cancellation. No worker or suppression of such
  previously prepared work is tested. This slice is in review in
  [#94](https://github.com/yanxel18/animetron/pull/94).
- Recount remains 18/57 (31.6%), P0 4/9 and P1 7/12, recalculated after
  reconciling #93 and recording P1-12d. Nested slices do not change the project
  counts.

## Phase 0 - Plan and shared foundations

Depends on: none. Complete when shared specifications are available to the
team, the remaining draft decisions are approved, and foundational services
have the security and recovery guarantees below.

- [ ] P0-01 Review and approve the remaining draft module specifications and
  resolve deployment, security and provider choices.
  - Storage runtime approved on 2026-11-14: dedicated Linux service with a
    private Docker named volume. Docker-managed artifact volumes are an explicit
    exception to the project-directory-only storage boundary; no deployment or
    live publishing is authorized by this decision.
  - Owner approval on 2026-11-14: all nine specifications may be implemented
    and committed. A maintained identity-provider integration is selected;
    provider selection is delegated to the assistant. Other explicit decisions
    and acceptance gates remain open. See the
    [P0-P9 readiness assessment](development-report.md#p0-p9-readiness-assessment---2026-11-14)
    for verification results and the remaining owner decisions. Autonomous
    workflow instructions are merged in
    [#25](https://github.com/yanxel18/animetron/pull/25); no phase completion
    or external-action permission is implied.
- [x] P0-02 With the owner's approval, make the local specification documents
  available in version control and link them from this checklist.
  - Approved and merged on 2026-11-14:
    [#27](https://github.com/yanxel18/animetron/pull/27). Documentation review,
    whitespace validation and GitGuardian checks passed.
- [x] P0-03 Add a minimal API liveness endpoint. [#1](https://github.com/yanxel18/animetron/pull/1)
- [x] P0-04 Add a PostgreSQL engine foundation. [#2](https://github.com/yanxel18/animetron/pull/2)
- [x] P0-05 Add transactional outbox storage with leases.
  [#6](https://github.com/yanxel18/animetron/pull/6)
- [ ] P0-06 Implement authenticated sessions, authorization, CSRF protection,
  audit records, authorized readiness, and protected WebSocket handshakes.
  - [ ] P0-06b OIDC/Keycloak session foundation was manually merged in
    [#33](https://github.com/yanxel18/animetron/pull/33) at
    `c39d4851dda89c9aa07f617a7e6d90a62a0eb371`, fetched on 2026-11-14.
    The final head `8b8a63277084d1ca962067af25bf5c2ac9e759a1` still has
    a completed/failed GitGuardian check; the merge did not clear that gate.
    Its migration integration defects were repaired and normally merged in
    [#41](https://github.com/yanxel18/animetron/pull/41) at
    `921ce335e4d9b62de19b6d47656b276372ddd505`. Independent test execution:
    330 passed/20 Windows skips, migration lifecycle, Ruff, strict
    Linux-target mypy30 and dependency consistency passed. Exact-head
    GitGuardian passed on #41; that does not clear the historical #33 finding.
    The repair received direct source review; no formal self-approval or
    protection waiver was used. Keep P0-06b unchecked pending scanner triage.
    [Current integration findings](auth-review-integration-report.md).
    [Historical scanner provenance](development-report.md#github-secret-scan-provenance---2026-11-14).
  - [x] P0-06a Apply browser security headers to API responses, including
    unhandled errors ([#19](https://github.com/yanxel18/animetron/pull/19);
    not authentication or CSRF protection).
    The [auth contract](../backend/AUTH.md) and
    [prior repair findings](../backend/AUTH-FINDINGS.md) describe the bounded
    session implementation. Deployment, artifact/workflow HTTP, publishing,
    back-channel logout and phase-completion certification are not included.
- [ ] P0-07 Implement bounded artifact upload, metadata and authorized
  download with opaque IDs, content checks and safe storage.
  - [x] P0-07a Persist immutable artifact metadata in caller-owned transactions
    ([#21](https://github.com/yanxel18/animetron/pull/21); not byte
    storage, content verification or authorization).
  - [x] P0-07b Implement bounded, integrity-checked internal Linux byte storage
    with no-replace publication ([#23](https://github.com/yanxel18/animetron/pull/23);
    no HTTP, media probing, authorization,
    byte/metadata atomicity or automatic orphan recovery).
  - [ ] P0-07c Add a bounded, report-only audit that reconciles metadata and
    byte inventories without changing either store.
    Implemented in pushed commits `a25fd7f` and `0944cf9` on branch
    `task/p0-07c-artifact-reconciliation`; merged to master through
    [#75](https://github.com/yanxel18/animetron/pull/75) (PR head `f9d12df`).
    GitGuardian passed; the earlier PostgreSQL harness attempt could not start
    because Windows Application Control blocked the installed psycopg DLL.
    A later owned PostgreSQL harness passed 61 artifact tests, including a new
    audit regression against migrated metadata with a fake byte inventory,
    merged in #91. A post-merge review identified test gaps; their follow-up
    merged in #93, pending independent review and required checks. The test is
    not a real filesystem integration test; keep
    unchecked pending review, required checks and remaining integration
    verification. Its branch included master commit
    `8d10be9` to resolve the checklist conflict.
    Verification: SQLite metadata tests (34 passed, 25 skipped), Linux
    byte-store tests (26 passed), backend suite outside owner-gated auth tests
    (352 passed, 340 skipped), Ruff and Linux-target mypy passed. The audit
    requires all metadata and byte writers to be stopped; it does not repair
    or adopt files.
  - [ ] P0-07d Expose owner-only reads of artifact metadata without returning
    storage locators or artifact bytes. Implemented in `6ccd3c2` on
    `task/p0-07d-artifact-metadata-read`; PR #77 merged into the #76 branch, not
    `master`. Reapplied in [#90](https://github.com/yanxel18/animetron/pull/90)
    from `4cce20c`, and merged at `b92bcc6`. Seven owned PostgreSQL
    authorization/API tests, migrations, Ruff and mypy passed. OpenAPI export,
    frontend type drift, typecheck, 113 tests and build passed. GitGuardian
    passed, but independent review is not recorded and combined status is
    pending; keep unchecked.
- [ ] P0-08 Establish private service networking, loopback gateway, retention,
  and tested backup/restore for metadata and artifacts.
  - [x] P0-08a Add a local-only, disposable backup/restore check for PostgreSQL
    metadata and artifact bytes. Verify restored metadata matches restored bytes
    by SHA-256, PostgreSQL is not host-published, and the test gateway binds to
    loopback. The harness must use uniquely labeled resources and clean up only
    resources it created. This does not select production networking, a
    persistent backup target or encryption, retention duration, or deletion
    behavior. Implemented in `3fde341` on `task/p0-08-local-recovery-test`,
    stacked through [#76](https://github.com/yanxel18/animetron/pull/76) and
    included in master via #75.
    No independent review was recorded; keep unchecked pending review-gate
    reconciliation. The disposable Docker test restored a synthetic metadata
    row and artifact into fresh resources with a matching SHA-256, verified
    private PostgreSQL networking and a loopback-only test endpoint,
    and left no labeled resources. Ruff and Python compilation passed; the
    backend suite outside owner-gated auth files passed (352 passed, 340
    skipped). Reversing the restored-hash assertion failed as expected, then
    the restored check passed. This does not prove a production backup
    procedure or actual gateway setup.
- [ ] P0-09 Verify unauthenticated access, malformed uploads, secret redaction,
  transaction recovery and backup/restore with integration tests.
  - [x] P0-09a Add the owner's explicit local credential-file exclusion.
    Existing `*.env` protection remains intact; the local file is preserved.
    Names-only tracking and ignore checks passed. Merged in
    [#39](https://github.com/yanxel18/animetron/pull/39); this is not a fix
    for or clearance of the blocked auth scanner.
    [Credential exclusion evidence](development-report.md#hugging-face-credential-file-exclusion).
  - [x] P0-09b Assert that authentication failure responses never reflect a
    supplied bearer token. Implemented in commit `c8ab7a2` on
    `task/p0-09b-auth-error-secret-redaction`; merged in
    [#78](https://github.com/yanxel18/animetron/pull/78). Five parameterized
    route cases passed; a disposable mutation reflecting the Authorization
    header made all five fail, then was restored. Ruff and `git diff --check`
    passed. GitGuardian passed; no independent GitHub review was recorded at
    merge. Keep unchecked pending review-gate reconciliation. This slice does
    not cover malformed uploads, transaction recovery or backup/restore.
  - [ ] P0-09c Assert that OIDC callback failure responses never reflect
    provider-returned access or ID tokens. Implemented in commit `2c8af75` on
    `task/p0-09c-oidc-token-redaction`; merged through stacked
    [#80](https://github.com/yanxel18/animetron/pull/80) and #79.
    The owned auth/integration harness passed 733 tests with 20 skips; Ruff,
    Linux-target mypy and Alembic upgrade/check passed. Inverting the assertion
    made all 12 invalid-claim/signature variants fail, then the correct
    assertion was restored. GitGuardian passed; no independent GitHub review
    was recorded at merge. Keep unchecked pending review-gate reconciliation.
    This does not resolve upload or production backup policy.
  - [ ] P0-09d Verify artifact metadata transaction recovery after a constraint
    failure. Implemented and merged in [#81](https://github.com/yanxel18/animetron/pull/81)
    at master `181bf6c`; the owned PostgreSQL harness passed 56 tests, with Ruff,
    Linux-target mypy and Alembic upgrade/check. The PR body reported no
    independent review; keep unchecked pending review-gate reconciliation.

## Phase 1 - Workflow runtime

Depends on: Phase 0 for authenticated operation. Internal foundations may be
developed earlier. Complete when an authorized user can run a validated,
immutable workflow and recover its state without duplicate effects.

- [x] P1-01 Validate graph topology, limits, node types and ports.
  [#3](https://github.com/yanxel18/animetron/pull/3)
- [x] P1-02 Persist run state and ordered events.
  [#4](https://github.com/yanxel18/animetron/pull/4)
- [x] P1-03 Validate backend-owned node configuration.
  [#5](https://github.com/yanxel18/animetron/pull/5)
- [x] P1-04 Parse bounded versioned workflow documents.
  [#8](https://github.com/yanxel18/animetron/pull/8)
- [x] P1-05 Create immutable validated workflow snapshot values.
  [#9](https://github.com/yanxel18/animetron/pull/9)
- [x] P1-06 Persist immutable workflow revisions.
  [#10](https://github.com/yanxel18/animetron/pull/10)
- [x] P1-07 Bind runs to stored revisions.
  [#11](https://github.com/yanxel18/animetron/pull/11)
- [ ] P1-08 Pin handler implementations, configuration defaults and model
  revisions so an old snapshot remains executable as approved.
  - [x] P1-08a Merged in
    [#49](https://github.com/yanxel18/animetron/pull/49) at
    `65bd2daff2483ed214c62bc0e403c734ad3c1b4d`: internal,
    immutable execution snapshot values binding handler artifact digests,
    materialized validated configuration defaults and existing pinned model
    manifests. Preserve legacy workflow snapshot behavior. This slice does
    not acquire models, load code, establish readiness, authorize execution
    or complete persisted/runtime enforcement of P1-08.
    Corrected core `36eae705d9d20a7336357d225df17120d030995f` passed
    independent QA: 552 full tests/20 existing Windows skips, 69 focused,
    migrations, Ruff, strict Linux-target mypy39 and dependency consistency.
    Direct review reproduced numeric-default type comparison and empty-alias
    defects; correction cycle 1 added 16 cases (10 failed before/16 passed
    after). Exact input/output byte limits and complete handler/model pinning
    passed. Source/user files were unchanged by QA. Exact-head GitGuardian
    passed at `419e8ea`; normal merge followed review/independent QA with
    no self-approval or check/protection waiver. Root master was pulled and
    backend/spec matched the tested core.
    [Pinning verification](workflow-execution-pins-report.md).
  - [x] P1-08b Merged in
    [#50](https://github.com/yanxel18/animetron/pull/50) at
    `a871aaaf32120207c3876ba93739ddde04191dcc`: persist
    immutable execution snapshot bytes bound to an exact stored workflow
    revision/digest, with checked loading, atomic save/replay and conflict
    rejection. No implicit repinning, installed-code verification, model
    readiness, worker execution, HTTP or authorization authority.
    Core `19213f60d45fd1f9fac054b7faa85db1d0020a0d` passed direct source
    review and independent QA: 583 full tests/20 existing Windows skips,
    30 focused, migration lifecycle/metadata parity, Ruff, strict Linux-target
    mypy40 and dependency consistency. No-DB: 1 passed/33 skipped. Real
    contention, SQL rollback and catalog drift passed; author digest mutation
    failed its regression. Captured test resources were verified removed,
    inventories and source/user files unchanged. Exact-head GitGuardian passed
    at `711e78a`; normal merge followed review/independent QA without
    self-approval or gate waiver. Root master was pulled; tested source,
    migrations, tests and spec matched. Runtime enforcement remains open.
    [Binding verification](execution-revision-bindings-report.md).
  - [ ] P1-08c Implement a pre-execution readiness gate: resolve only exact-pinned
    installed handlers from a trusted server-owned catalog, require exact
    pinned model manifests to be `READY`, and prevent all node handlers from
    starting if any check fails. The owner confirmed the catalog and terminal
    `FAILED` run behavior on 2026-11-18. Draft is in
    `docs/SPEC-workflow-runtime.md` on
    `task/p1-08c-runtime-readiness-spec`; the owner approved the contract on
    2026-11-18. Implementation is pushed on dependent branch
    `task/p1-08c-runtime-readiness`, based on spec commit `6615b19`. Exact
    handler digest and full model-manifest matching, full-graph preflight,
    safe typed terminal failure events, and no partial handles on failure are
    implemented in `c231472`. The branch integrates verified master
    `181bf6c`. Readiness, binding, revision, run-request, artifact and migration
    tests passed (111 passed, 123 skipped); Ruff and Linux-target mypy passed.
    Database-gated cases were skipped because `ANIMETRON_TEST_DATABASE_URL` is
    unavailable. A deliberate handler-digest comparison mutation failed its
    regression test and was restored. No downloads, model acquisition, artifact
    fetching or handler code loading occurred. Merged as part of
    [#86](https://github.com/yanxel18/animetron/pull/86) at `dc26469`.
    #86 has no independent review record and only a GitGuardian check; keep
    unchecked pending the missing review and required verification gates.
- [ ] P1-09 Implement authorized workflow CRUD, validation and idempotent run
  creation; persist node intents and outbox effects in one transaction.
  - [ ] P1-09e Internal mutable draft persistence merged in
    [#73](https://github.com/yanxel18/animetron/pull/73) at `df80d91`. Keep
    unchecked because GitHub has no review record and the combined status is
    pending.
    - [ ] P1-09e1 Update migration downgrade integration-test expectations for
      `workflow_drafts` added by P1-09e. Implemented in commit `efe330c` on
      `task/p1-09e-migration-downgrade-tests`; merged through
      [#79](https://github.com/yanxel18/animetron/pull/79). The owned migration
      harness passed all 5 migration tests; the full backend auth/integration
      harness passed 733 tests with 20 skips. Alembic upgrade/check, Ruff and
      Linux-target mypy passed. No migration or production behavior changed.
      GitGuardian passed; no independent GitHub review was recorded at merge.
      Keep unchecked pending review-gate reconciliation.
  - [ ] P1-09f Expose an owner-only read of an existing mutable workflow draft,
    preserving its stored UTF-8 text and version. Implemented at `4aca101` and
    included in the P1-09g stack merged through
    [#82](https://github.com/yanxel18/animetron/pull/82) at `429e1a7`. Its
    required PostgreSQL/Keycloak verification is blocked by Windows Application
    Control; #82 has no independent review record and only a GitGuardian
    check. Keep unchecked.
  - [ ] P1-09g Add an owner-only version-checked write for an existing mutable
    workflow draft. Implemented in `f0d21a7` and merged through
    [#82](https://github.com/yanxel18/animetron/pull/82) at `429e1a7`.
    Focused tests passed (76 passed, 22 skipped); Ruff and Linux-target mypy
    passed. The PostgreSQL/Keycloak harness is blocked by Windows Application
    Control; no independent GitHub review record exists. Keep unchecked.
  - [ ] P1-09h Add owner-only, version-checked validation of a mutable workflow
    draft. Implemented in `2ceb73b` and merged through
    [#83](https://github.com/yanxel18/animetron/pull/83) at `3e5c52a`.
    Focused tests passed (124 passed, 22 skipped); Ruff and Linux-target mypy
    passed. The full backend run's auth/database failures were blocked by the
    missing test database URL; no independent GitHub review record exists.
    Keep unchecked.
  - [x] P1-09b Add owner-only read of a known persisted immutable workflow
    revision, returning exact canonical JSON and digest; fail closed on missing
    authorization, invalid input, database errors and integrity failures.
    No write, list, editing or execution authority is added. Merged in
    [#62](https://github.com/yanxel18/animetron/pull/62): 17 focused cases passed against an
    isolated PostgreSQL instance; 637 backend cases passed with 20 Windows
    skips, excluding the live OIDC test module because the Python Playwright
    package is missing. Migrations, Ruff, Linux-target mypy, frontend build and
    API type drift checks passed. Independent review and offline QA found no
    significant issues. An owner-guard mutation failed its focused regression
    and was restored. Exact-head GitGuardian passed; merged at `c7bc998`.
    The live OIDC module and full workflow UI remain unverified.
  - [x] P1-09c List immutable revisions for a known workflow ID with bounded
    owner-only pagination. This does not discover workflow IDs, edit workflows,
    validate execution readiness or dispatch work. The separate query lookup
    reads identifiers containing path separators or dot segments without changing
    the existing path lookup. Merged in
    [#63](https://github.com/yanxel18/animetron/pull/63): 664 backend tests passed using an
    isolated PostgreSQL instance, with 20 Windows skips; the live OIDC module was
    excluded because Python Playwright is missing. Ruff, Linux-target mypy,
    migration checks, API type drift and frontend build passed. A maximal
    Unicode cursor failed before its bound was corrected; a listed slash ID
    exposed the path-lookup limitation and the query lookup now covers it.
    Independent review found no remaining required issues after correction;
    independent offline QA passed 28 cases with 17 database cases skipped.
    Exact-head GitGuardian passed; merged at `7faf5d6`.
  - [x] P1-09d List workflow IDs with persisted revisions using bounded,
    owner-only pagination. No workflow drafts, names, execution readiness or
    dispatch are implied. Merged in
    [#64](https://github.com/yanxel18/animetron/pull/64): 690 backend tests passed using an
    isolated PostgreSQL instance, with 20 Windows skips; the live OIDC module
    was excluded because Python Playwright is missing. Migrations, Ruff,
    Linux-target mypy, 48 frontend tests, frontend build and API type drift
    check passed. A duplicate-seek mutation failed its focused regression and
    was restored. Independent source review found no significant issues;
    independent offline API QA passed 23 tests without database verification.
    Pagination is not a snapshot and physical index work is not strictly bounded.
    Exact-head GitGuardian passed; merged at `cff6851`.
  - [x] P1-09a Merged in
    [#48](https://github.com/yanxel18/animetron/pull/48) at
    `d5f7f43e3ccaafdc2f4b24dc294633158c29bf69`: internal
    caller-transactional idempotent run-request persistence, exact immutable
    revision/digest binding and one stable internal outbox intent. No HTTP,
    role authority, handler/model readiness, node intents, worker execution
    or scheduler dispatch. This does not bypass P1-08 implementation pinning.
    Core `6e0e28632922bbf07dd87b9f97142abf8edf8940` passed author checks:
    32 focused and 483 full tests/20 existing Windows skips, migrations,
    Ruff, strict Linux-target mypy38 and dependency consistency. Author also
    ran 21 unchanged Linux filesystem regressions. Real concurrent key
    conflicts and savepoint/outer SQL rollback are exercised; an intent-guard
    mutation produced 2 failures. Direct source review found no required
    correction. Independent QA reproduced 483 passed/20 skips, all 32 focused
    cases, migrations, Ruff/mypy38 and dependency consistency at that core.
    No-DB checks: 1 passed/34 skipped. Captured test resources were removed;
    baseline files/resources remained unchanged. Exact-head GitGuardian
    passed at `aaccce7`; normal merge followed review/independent QA with
    no self-approval or check/protection waiver. Root master was pulled and
    backend/spec matched the tested core. Parent P1-09 remains unchecked.
    [Run-request verification](run-request-records-report.md).
  - [ ] P1-09i Add owner-only idempotent run creation for an existing immutable
    workflow revision. Implemented in `abbb12b` and merged through
    [#84](https://github.com/yanxel18/animetron/pull/84) at `eb79dbb`.
    Focused tests passed (65 passed, 52 skipped); Ruff and Linux-target mypy
    passed. PostgreSQL-backed service tests remain unverified without the
    owned test database. #84 has no independent review record and only a
    GitGuardian check. Keep unchecked.
- [ ] P1-10 Implement typed handlers, dispatch, fan-out/join and failure/skip
  behavior with deterministic sample nodes.
  - [x] P1-10a Derive immutable node dependencies from a validated workflow
    ([#15](https://github.com/yanxel18/animetron/pull/15); no scheduling or
    dispatch).
  - [x] P1-10b Evaluate a bounded deterministic sample graph internally,
    demonstrating typed fan-out/join and failure/skip behavior without dispatch.
    Independent review found no required issues; independent QA passed 58
    focused tests, Ruff and Linux-target mypy. An isolated PostgreSQL-backed
    regression passed 723 tests with 20 Windows filesystem skips, excluding
    live OIDC because Python Playwright is missing. Migrations, Ruff and
    Linux-target whole-app mypy passed. Weakening the upstream-failure guard
    failed its focused regression; the source was restored and passed.
    No runtime, handler-pin enforcement,
    model readiness or production execution is implied.
    Exact-head GitGuardian passed; [#69](https://github.com/yanxel18/animetron/pull/69)
    merged at `391ecd9`.
  - [ ] P1-10c Persist a verified node-intent plan and a distinct run-ready
    outbox intent in one caller-owned transaction, only after the P1-08c
    whole-graph readiness preflight succeeds. A readiness failure must leave
    the run terminally failed with no node intents or executable outbox event;
    duplicate notifications must not create duplicate intents. This slice does
    not invoke handlers, acquire models or fetch artifacts. Implemented in
    `38a6f5b` and merged through
    [#86](https://github.com/yanxel18/animetron/pull/86) at `dc26469`.
    #86 has no independent review record and only a GitGuardian check; keep
    unchecked pending the required review and verification gates.
- [ ] P1-11 Implement cancellation, safe recovery, event replay and
  authenticated live updates; distinguish unknown external effects.
  - [x] P1-11a Merged in
    [#51](https://github.com/yanxel18/animetron/pull/51) at
    `4e31490deac801002cd7c73f49c87fb9c58d516a`: authenticated
    owner-only HTTP reads of actual persisted run state and bounded ordered
    event replay. Reuse fresh-session/origin policy. No execution, cancellation,
    WebSocket/live push, node-state journal or recovery authority in this slice.
    Core `33f68b4b46509ed52ff8a9320a66fee076de7a32` passed direct source
    review and independent QA: 622 full tests/20 existing Windows skips,
    39 focused, migrations, Ruff, strict Linux-target mypy41 and dependency
    consistency. No-DB new-file checks: 1 passed/38 skipped. Pagination,
    tail/append, strict query limits, revocation/logout and role/origin guards
    passed. Author pagination mutation failed three cases and was restored.
    Captured resources were verified removed; inventories/files unchanged.
    Exact-head GitGuardian passed at `5c65b2b`; normal merge followed direct
    review/independent QA without self-approval or gate waiver. Root master
    was pulled and tested backend/spec matched.
    [Run replay evidence](run-read-replay-api-report.md).
  - [ ] P1-11b Implement the owner-only cooperative cancellation endpoint:
    atomically transition an active run to `CANCELLING` and enqueue one stable
    cancellation intent. Retries must not duplicate the intent; do not report
    `CANCELLED` before a worker confirms termination. This slice does not
    interrupt workers or reconcile unknown external effects. Implemented in
    `66a39de` and merged through
    [#87](https://github.com/yanxel18/animetron/pull/87) at `cfbd7a3`, stacked
    on P1-10c. Focused
    backend, Ruff, mypy, frontend typecheck/build/tests and generated API drift
    checks passed; 40 database/auth API tests were skipped without the owned
    harness. #87 has no independent review record and only a GitGuardian check;
    keep unchecked pending the required review and verification gates.
- [ ] P1-12 Verify restart, reconnect, concurrency and cancellation behavior
  end-to-end, including duplicate message handling.
  - [ ] P1-12a Verify a cancellation intent survives database reconnect and a
    retry reuses it without duplication. Implemented as a file-backed SQLite
    regression in commit `e8e0e28`, merged through
    [#88](https://github.com/yanxel18/animetron/pull/88) at `2679b6c`. Focused
    run/cancellation/API tests passed (19 passed, 40 database/auth cases
    skipped) and Ruff passed. This does not verify PostgreSQL locking, worker
    delivery, or handler execution. GitGuardian passed; no independent review
    is recorded and the combined status is pending. Keep unchecked.
  - [ ] P1-12b Verify a committed cancellation blocks subsequent dispatch
    preparation without creating node or run-ready intents. Implemented on
    [#89](https://github.com/yanxel18/animetron/pull/89); focused workflow/API tests
    passed (28 passed, 40 skipped) and Ruff passed. This does not verify a
    concurrent PostgreSQL race or stop previously prepared work. Keep
    unchecked: merged at `4cce20c`, but independent review is not recorded
    and combined status is pending.
  - [ ] P1-12c Verify concurrent cancellation requests serialize and reuse one
    intent on PostgreSQL. The owned harness passed 13 cancellation tests, and
    a row-lock mutation failed the new regression. This does not verify worker
    execution or dispatch contention. Merged in
    [#92](https://github.com/yanxel18/animetron/pull/92) at `5bce7b7`;
    GitGuardian passed, but independent review is not recorded and combined
    status is pending, so keep unchecked.
  - [ ] P1-12d Verify cancellation and dispatch preparation serialize on
    PostgreSQL in both lock orderings. Eight dispatch and 13 cancellation
    tests passed in the owned harness. Uses a fake execution binding and does
    not verify a worker or suppression of already-prepared run-ready intents;
    keep unchecked pending review, required checks and merge of
    [#94](https://github.com/yanxel18/animetron/pull/94).

## Phase 2 - Model registry and hardware readiness

Depends on: Phase 0; workflow model pinning also depends on Phase 1. Complete
when explicitly authorized, pinned models are verifiably ready on supported
hardware and failures never appear ready.

- [x] P2-01 Add model acquisition preflight for license, access and storage.
  [#7](https://github.com/yanxel18/animetron/pull/7)
- [ ] P2-02 Inspect actual VRAM, driver, WSL2/CUDA and available storage; record
  supported runtime choices and benchmark plan.
  - [x] P2-02a Record host resources and Linux-container NVIDIA visibility.
    [#28](https://github.com/yanxel18/animetron/pull/28); no CUDA kernel, model
    compatibility, Docker-volume capacity or inference benchmark is certified.
    See [hardware evidence](development-report.md#hardware-evidence---2026-11-14).
- [ ] P2-03 Define pinned manifests, repository allowlists, integrity metadata,
  license/access records and typed readiness states.
  - [x] P2-03a Validate immutable Hugging Face repository and commit identities
    ([#14](https://github.com/yanxel18/animetron/pull/14); not a manifest,
    allowlist or readiness check).
  - [x] P2-03b Verify an individual model stream's size and digest with
    bounded reads ([#16](https://github.com/yanxel18/animetron/pull/16);
    not a model readiness check).
  - [x] P2-03c Define immutable model manifest and file integrity metadata
    ([#17](https://github.com/yanxel18/animetron/pull/17); not a
    license acceptance, allowlist or readiness check).
- [ ] P2-04 Implement confirmed, deduplicated acquisition with staging,
  integrity checks and atomic readiness; keep credentials server-side.
- [ ] P2-05 Expose authorized model and download status; test interrupted,
  corrupt, inaccessible, concurrent and disk-constrained acquisitions.
- [ ] P2-06 Benchmark approved model candidates and document real resource
  usage, compatibility, runtime and visual quality before selecting defaults.
  - [ ] P2-06a Run the explicitly approved pinned Wan 2.2 TI2V 5B feasibility
    experiment. Partial evidence merged in
    [#34](https://github.com/yanxel18/animetron/pull/34); full model feasibility
    remains **blocked before acquisition** by the RAM planning gate. See
    [bounded execution evidence](wan-benchmark-report.md).
    PyTorch 2.9.1/cu128 synchronized sm_120 kernels passed; conservative
    shared-host/Linux RAM capacity was not established. No model acquisition,
    READY status, scene output or P3/P9 acceptance. Exact-owned containers and
    transient runtime were removed after worker-termination verification.
  - On 2026-11-14 the owner accepted applicable licenses and authorized the
    three-file Wan2.2 TI2V 5B candidate at
    `Comfy-Org/Wan-2.2@ee6f4a40737a995bf5818954cfce6d59443b0f04`.
    Acquisition/local testing remain conditional on capacity, integrity and
    framework safety checks. [Exact consent scope](development-report.md#pinned-model-consent---2026-11-14).
    The partial feasibility report is merged in
    [#34](https://github.com/yanxel18/animetron/pull/34), blocked before model
    acquisition by conservative RAM-capacity uncertainty. Consent authorizes
    no other model, voice, cloud inference or publishing.

## Phase 3 - Local media generation

Depends on: Phases 1 and 2. Complete when a real local reel passes the media
checks and a measured hardware benchmark, without cloud inference fallback.

- [ ] P3-01 Implement schema-validated story/scene planning with duration
  budgets and explicit failures for malformed model output.
- [ ] P3-02 Implement character references, keyframes and scene animation
  using pinned models and allowlisted handlers.
- [ ] P3-03 Implement narration, alignment and deterministic rendering with
  safe FFmpeg argument handling and artifact provenance.
- [ ] P3-04 Validate 9:16 output, decodability, audio and duration: target
  30-60 seconds, hard maximum 90 seconds; verify boundary cases.
- [ ] P3-05 Measure an actual short reel's resource peaks, elapsed time,
  versions and output hashes; obtain human review of quality and alignment.

## Phase 4 - Human review

Depends on: Phases 0 and 1; full preview requires Phase 3. Complete when an
authorized human can decide on the exact output without occupying a worker.

- [x] P4-01 Define an internal immutable scope for run, artifact revision and
  digest, caption digest and destination identities.
  [#12](https://github.com/yanxel18/animetron/pull/12)
- [x] P4-02 Persist review requests, delivery states, expiry and immutable
  decisions; supersede prior approval when its scope changes.
  - [#40](https://github.com/yanxel18/animetron/pull/40) merged on 2026-11-14
    after independent reassessment passed at `d7c345d`. Independently verified
    36 focused and 258 full tests passed, with 20 unchanged Windows skips;
    migration lifecycle, Ruff, Linux-target mypy26 and dependency checks passed.
    The expiry-guard mutation now fails its regression. See the
    [review records design and verification report](review-records-report.md).
    Independent QA failed at `21ca53f` on insert-state enforcement, reviewer-ID
    validation and DB expiry-guard coverage; correction cycle 1/3 resolved them.
    This is internal persistence only, not role policy, authorization proofs,
    authenticated APIs or publication/outbox effects.
- [x] P4-03 Enforce role, scope, expiry and transactional single-winner checks;
  persist decisions and outbox effects atomically.
  - Internal decision service merged in
    [#43](https://github.com/yanxel18/animetron/pull/43) at
    `70035139e69a601d68ac0bc8d55b66102d9d7046`.
    Owner approved owner-only approve/reject permission on 2026-11-14;
    operators/viewers cannot decide. Preserve that least-privilege boundary.
    Reuse the durable review store and caller-owned transaction; no Telegram,
    live publishing or approval bypass is authorized.
    Acceptance: a fresh trusted authenticated owner principal and exact current
    scope are required; expired/superseded/conflicting decisions fail explicitly.
    Approve/reject races have one winner. Decision plus one internal approval
    notification intent commit or roll back together; rejection never creates
    an approval/publication intent. This is not a publication-approval proof
    or an HTTP/MCP/Telegram endpoint.
    Local implementation at `0673bbc` passed independent final QA:
    380 full tests/20 platform skips, both real lock-wait expiry regressions,
    migrations, Ruff, strict Linux-target mypy32 and dependency consistency.
    Without a database URL, 39 infrastructure skips and zero errors preserve
    the existing test convention. Direct source-review corrections cover
    no-database behavior and expiry after blocking intent locks.
    The owner published the branch. Exact-head GitGuardian passed, and the
    assistant merged normally after direct source review and independent QA.
    No self-approval or protection/check waiver was used. HTTP/MCP/Telegram
    entrypoints, current publication approval lookup and live effects remain
    separate tasks.
- [x] P4-04 Add authorized paginated review and decision APIs and a valid
  approval lookup for publication; reject stale, unauthorized and replayed actions.
  - [x] P4-04b Internal exact-scope approval lookup merged in
    [#44](https://github.com/yanxel18/animetron/pull/44) at
    `61b3cad16ee2d0ce264b271be3e59b4f92d8e724`, based on verified #43.
    Require current APPROVED state, exact scope, unexpired request, matching
    current configured owner identity and the decision service's reserved
    intent association. Use the advancing DB clock after lock waits; reject
    missing/stale/rejected/superseded/colliding records explicitly.
    A returned checked record is not a reusable authorization capability.
    Trusted callers must recheck every attempt in the caller-owned transaction;
    artifact byte verification, REST/MCP/Telegram and publishing remain excluded.
    Author verification: 28 focused tests, 408 full tests/20 existing Windows
    skips, migration lifecycle, Ruff, strict Linux-target mypy33 and dependency
    consistency passed. A private guard mutation produced 11 failing tests.
    Independent final execution at `0989d27` reproduced 408 passed/20 skips,
    all 28 lookup cases and both existing decision expiry-lock regressions,
    Ruff/mypy33 and dependency consistency; no-DB invocation skipped all 28.
    Captured containers, network and anonymous volume were removed. Exact-head
    GitGuardian passed at `5228271`; normal merge followed direct source review
    and independent QA, without self-approval or check/protection waivers.
    [Lookup verification and findings](review-approval-lookup-report.md).
  - [x] P4-04a Merged in
    [#46](https://github.com/yanxel18/animetron/pull/46) at
    `b008e1c5c6d037c48a2fdacc346a820becf11028`: authenticated
    paginated review queue and exact-scope
    decision HTTP APIs, reusing current session/origin/CSRF controls and
    owner-only decision authority. No Telegram, artifact bytes, live
    transmission or publishing. P4-04 is complete only for these APIs and the
    internal lookup; P4-05/P4-06 and phase acceptance remain open.
    Canonical status reconciliation merged in
    [#45](https://github.com/yanxel18/animetron/pull/45); exact-head GitGuardian
    and documentation whitespace checks passed. Root master was pulled.
    Corrected core `ed1635479b113b4cdf0c55452682bd3174ff9dd2` passed
    442 tests/20 existing Windows skips, migrations, Ruff, strict Linux-target
    mypy35 and dependency consistency. Direct review reproduced an oversized
    decimal Content-Length returning 503 instead of 422; correction cycle 1
    added seven header/streaming-limit regressions (4 failed before, 7 passed
    after). Independent QA at `4e2c761` reproduced 442 passed/20 skips,
    all 34 API cases, the existing lock-wait regressions, migrations,
    Ruff/mypy35 and dependency consistency. Without DB infrastructure,
    8 passed/26 skipped. Owned test resources were removed. Exact-head
    GitGuardian passed at `57ab7a8`; normal merge followed direct corrected
    source review and independent QA, without self-approval or check waivers.
    [HTTP API verification and findings](review-http-api-report.md).
- [ ] P4-05 Implement explicitly consented Telegram polling, durable update
  deduplication, single-use callback tokens and reviewer/chat identity checks.
- [ ] P4-06 Show exact preview, caption, destinations and expiry; expose
  delivery failure and unknown outcomes and test restart and race cases.

## Phase 5 - Official social publishing

Depends on: Phase 4; live tests require separate authorization. Complete when
eligible destinations publish only approved content with per-destination
outcomes and safe reconciliation.

- [ ] P5-01 Implement durable publication intents, approval rechecks,
  idempotency and per-destination states, including UNKNOWN and reconciliation.
- [ ] P5-02 Verify current Facebook Page Reels eligibility and official API
  requirements; implement its adapter and an authorized live acceptance test.
- [ ] P5-03 Independently verify and implement eligible Instagram Reels,
  YouTube Shorts and TikTok adapters; leave unsupported flows visibly blocked.
- [ ] P5-04 Test concurrent attempts, changed payloads, mixed outcomes,
  uncertain finalization and cancellation without blind duplicate publishing.

## Phase 6 - Scheduling

Depends on: Phase 1 and approved schedule/DST policy. Complete when a persisted
schedule creates at most one run intent per due slot and never grants approval.

- [x] P6-01 Approve cron, time zone, overlap, missed-run and DST behavior.
  - Owner approved five-field/IANA/OR matching, skipped GPU overlap and missed
    slots without catch-up, spring-forward gaps skipped and fall-back's earlier
    occurrence once on 2026-11-14. Policy documentation merged in
    [#30](https://github.com/yanxel18/animetron/pull/30); documentation review,
    whitespace and GitGuardian checks passed. Runtime boundary tests remain
    required by P6-03.
- [ ] P6-02 Implement authorized schedule CRUD, next-occurrence preview,
  durable slots and atomic run-intent/outbox creation.
  - [x] P6-02d Persist immutable schedule-slot observations without dispatching
    runs, recording skip decisions or conferring publication approval.
    Local checks passed: 21 PostgreSQL cases; 712 backend cases with 20 Windows
    filesystem skips, excluding live OIDC collection because Python Playwright
    is missing; migrations, Ruff and Linux-target mypy passed. Independent
    source review found no significant issues. Independent PostgreSQL QA passed
    21 focused cases and migration lifecycle and Ruff; strict mypy passed with
    a temporary owned cache after the harness's `NUL` cache setting failed on
    Windows. Removing the canonical-key check failed its focused regression.
    The ledger does not decide whether a slot is due, skipped or dispatched.
    Exact-head GitGuardian passed; [#68](https://github.com/yanxel18/animetron/pull/68)
    merged at `42dab5c`.
  - [x] P6-02c Merged in
    [#47](https://github.com/yanxel18/animetron/pull/47) at
    `f315e9bbb877893d871174d6542355c767c2e80a`: authenticated
    descriptor create/read/update/list and next-five preview,
    preserving owner-only controls, optimistic versions and approved DST policy.
    No hard delete, due-slot dispatch, scheduler process, GPU admission,
    run/outbox creation or publication authority in this HTTP slice.
    Core `455296d41e17c7602c734b6d74ad9ffabc1795e0` passed author checks:
    450 tests/20 existing Windows skips, migrations, Ruff, strict Linux-target
    mypy37 and dependency consistency. Shared bounded JSON extraction retains
    review error codes; actual fragmented-stream mutation regression failed
    when the scheduling cap was raised. Direct source review found no required
    correction. Independent QA reproduced 450 passed/20 skips, all 8 scheduling
    and 34 review API cases, actual lock-expiry regressions, migrations,
    Ruff/mypy37 and dependency consistency. No-DB checks: 5 passed/3 skipped.
    Captured containers, network and anonymous volume were verified removed,
    with baseline files/resources unchanged. Exact-head GitGuardian passed at
    `6e851f8`; normal merge followed direct review and independent QA without
    self-approval or check/protection waivers. Parent P6-02 stays unchecked.
    [Scheduling HTTP verification](schedule-http-api-report.md).
  - [x] P6-02a Internal next-five preview core merged in
    [#35](https://github.com/yanxel18/animetron/pull/35): approved
    five-field/OR/IANA matching, gap skip, earlier fold only and deterministic
    zone/local-slot keys. Native suite 187 passed/77 existing integration skips,
    Ruff/strict Linux mypy and GitGuardian passed. Tests do not
    establish persistence, authorized CRUD, overlap/restart or dispatch.
    [Preview verification and findings](scheduling-preview-report.md).
  - [x] P6-02b Persist internal schedule descriptors, merged in
    [#42](https://github.com/yanxel18/animetron/pull/42) at
    `8bc096c95b3065f782dc0a624284224fd8e1b8c3`.
    - Bind an existing immutable workflow revision and reuse the approved
      cron/IANA preview calculation with an aware cursor.
    - Require caller-owned transactions, bounded reads and optimistic edit
      conflicts; resume computes a future occurrence without catch-up.
    - Verify fresh PostgreSQL persistence, rollback, edit races, preview/DST
      parity and the migration lifecycle, plus Ruff and strict mypy.
    This slice adds no HTTP/role authorization, due slots, GPU arbitration,
    scheduler process, run/outbox dispatch or publication approval.
    Independent verification: 50 focused tests, migration lifecycle,
    Ruff/mypy27 and dependency checks passed; an AUTOCOMMIT-guard mutation
    failed its regression. Independent integrated QA at `8af75bf` reproduced
    341 passed/20 Windows skips, migration lifecycle, Ruff, strict Linux-target
    mypy31 and dependency consistency. Exact-head GitGuardian passed, and
    direct integration source review found no defects. Normal merge used no
    self-approval or protection/check waiver. The migration follows
    `0008_auth_review_merge`.
    [Verification and cleanup](schedule-records-report.md).
- [ ] P6-03 Implement a single scheduler process with observable recovery and
  skipped slots; test pause, restart, overlap, DST and duplicate dispatch.

## Phase 7 - Creator studio

Depends on: corresponding authorized backend services; build usable slices
alongside the phases above. Complete when the real browser flows and
accessibility checks pass, not merely when mock screens exist.

- [x] P7-01 Establish the dark/cyan workspace, local/system typography,
  responsive layout and accessible component foundations.
  [#36](https://github.com/yanxel18/animetron/pull/36) merged after independent
  whole-UI review: 3 unit/6 Chromium cases, typecheck/build, script-disabled
  frozen install, audit and GitGuardian passed. Native 200% browser zoom and
  assistive technology remain unverified; P7-05/P7-06/P9 are not complete.
  [Measured foundation evidence](studio-foundation-report.md).
  - [x] P7-01b Generate
    TypeScript contracts directly from local backend OpenAPI and detect drift.
    No live schema fetch, credential reading, runtime client or new screen.
    Merged to master in [#54](https://github.com/yanxel18/animetron/pull/54).
    `@hey-api/openapi-ts@0.99.0` uses the TypeScript-only plugin; the frontend
    compiler is pinned to 5.9.3 because 7.0.2 lacks runtime APIs the generator
    uses despite its declared peer range. A scoped `js-yaml@4.3.2` override
    clears the transitive advisory; the full npm audit reports zero findings.
    [P7-01b report](p7-01b-contracts-report.md). This is a prerequisite to
    backend-owned frontend contracts, not P7 completion.
- [ ] P7-02 Implement workflow editing, inspector, validation and saved draft
  versus immutable revision using backend-owned contracts.
  - Editing remains blocked: workflow create/update and validation routes are
    unavailable; prerequisite P1-09 remains unchecked. Do not invent a
    frontend-only workflow schema or enable editing before those APIs exist.
  - [x] P7-02a Browse persisted workflow IDs and immutable revision metadata
    read-only, with bounded pagination and truthful loading, errors and access
    states. This does not provide editing, validation or execution.
    Local checks passed: 59 frontend tests, production build, API drift check and
    16 fixture-backed Chromium cases. Independent QA passed 57 tests, build,
    drift and three focused Chromium cases before a Unicode boundary fix.
    A valid 128-codepoint supplementary-Unicode revision was rejected by the
    client; a regression failed before correcting the codepoint count.
    Independent review found no remaining required issues after correction;
    independent correction QA passed six API client cases and verified the
    backend model's 128/129-codepoint boundary.
    Live authenticated backend and screen-reader testing remain unverified.
    Exact-head GitGuardian passed; [#65](https://github.com/yanxel18/animetron/pull/65)
    merged at `5f2e981`.
  - [x] P7-02b Inspect exact canonical JSON and digest of a selected immutable
    revision through the authorized query lookup, without editing or execution.
    Local checks passed: 81 frontend tests, production build, API drift check and
    18 fixture-backed Chromium cases. Independent source review found no
    significant issues; independent QA passed 32 focused tests, build, API drift
    and five fixture-backed Chromium cases, with screenshot inspection.
    Removing the late-response guard failed its focused regression; the source
    was restored and that regression passed.
    The digest is displayed as returned, not independently verified. Live
    authenticated backend and screen-reader testing remain unverified.
    Exact-head GitGuardian passed; [#66](https://github.com/yanxel18/animetron/pull/66)
    merged at `f0e610b`.
- [ ] P7-03 Implement run monitoring, reconnect/replay, library and preview with
  truthful loading, errors, waiting and progress states.
  - [x] P7-03a Add an owner-only run-ID monitor backed by persisted run status
    and bounded event replay. Poll durable state after reconnect; distinguish
    loading, live, stale/error and terminal states. No create/cancel controls or
    inferred progress. Merged in [#57](https://github.com/yanxel18/animetron/pull/57).
    Library and artifact preview remain outside this slice. A failed later
    replay page previously advanced the cursor without preserving earlier
    events; the refresh now commits cursor and events together. Authorization
    loss clears previously displayed run details. Regression tests reproduced
    both issues before the fixes; Chromium also caught and verified a skip-link
    focus fix. Validation: 24 frontend unit tests, production build, API drift
    check and eight Chromium cases passed using local fixtures. Independent
    source review found no significant issues and reproduced the unit suite
    and build. Live authenticated backend and assistive-technology testing
    remain unverified.
- [ ] P7-04 Implement review, models, schedules, connections and publication
  screens against their authorized services; explain blocked actions.
  - [x] P7-04e Create schedule descriptors from persisted workflows and
    revisions. Preserve explicit non-idempotent uncertainty and do not imply
    dispatch or execution.
    Local checks passed: 113 frontend tests, production build and API drift;
    15 fixture-backed Chromium cases passed before a revision-validation
    correction. Independent review found no remaining required issues after
    correction. Independent QA passed 38 focused tests, build, drift and two
    Chromium cases before correction; correction QA passed 67 focused tests and
    compared 40 values against the backend validator. Disabling the uncertainty
    acknowledgement guard failed its regression; source was restored and passed.
    The pending-attempt marker
    is browser-profile/origin scoped and cannot survive cleared storage or
    coordinate across devices. A matching descriptor cannot prove an uncertain
    attempt succeeded. Live authenticated backend and screen-reader testing
    remain unverified.
    Exact-head GitGuardian passed; [#67](https://github.com/yanxel18/animetron/pull/67)
    merged at `d50a8b3`.
  - [x] P7-04a Add the owner-only review metadata queue with truthful loading,
    empty, error and pagination states. Keep decisions unavailable until the
    exact artifact and caption can be previewed; depends on P7-01b API types.
    [#55](https://github.com/yanxel18/animetron/pull/55) merged to #54's
    branch and reached master in #54. Unit, production-build, API-drift and
    seven Chromium checks passed.
    See [P7-04a report](p7-04a-review-queue-report.md).
  - [x] P7-04b Show owner-only saved schedule descriptors with truthful
    loading, empty, error and pagination states. Use the existing P6-02c API,
    explain that dispatch is not implemented, and expose no mutation controls.
    Verify authorized and error states, pagination, responsive layout, keyboard
    access and preservation of existing navigation.
    Local checks passed: 32 frontend unit tests, production build, API contract
    drift check and nine fixture-backed Chromium cases, including four viewport
    widths and skip-link focus. Live authenticated backend and assistive
    technology remain unverified. Independent source review found no significant
    issues; it did not independently run tests. Exact-head GitGuardian passed
    and [#58](https://github.com/yanxel18/animetron/pull/58) merged normally
    at `ac10dd023eb492aa35ac37299ec287d60bb8dbdd`.
  - [x] P7-04c Preview the next five server-calculated occurrences for a saved
    schedule via the existing owner-only, CSRF-protected P6-02c API. Display
    offset-bearing local times and UTC due times with truthful loading and
    errors; do not save, edit, dispatch or imply execution. Verify authorization,
    CSRF handling, response validation, keyboard and responsive behavior.
    Local checks: 39 frontend tests, production build, API drift check and ten
    fixture-backed Chromium cases passed. Independent review identified a
    non-UTC value mislabeled as UTC and missing preview-completion announcement;
    both were reproduced and fixed, then independently re-reviewed. Removing
    the UTC guard caused the regression test to fail. Browser checks do not
    establish live authenticated backend or assistive-technology behavior.
    Exact-head GitGuardian passed and [#59](https://github.com/yanxel18/animetron/pull/59)
    merged normally at `d7fb6dc428d88c820919b1e4cfbaeeb0d161cd25`.
  - [x] P7-04d Allow owner-only pause/resume using the saved descriptor's
    expected version and existing CSRF-protected replacement API. Preserve all
    other fields, handle conflicts and uncertain outcomes by requiring a fresh
    list, and never retry a mutation automatically. Verify authorization,
    concurrent edits, error recovery, keyboard and responsive behavior.
    Local checks passed: 48 frontend tests, production build, API drift check and
    11 fixture-backed Chromium cases. Independent review identified lost focus
    after failed updates; two reproduced cases were corrected and independently
    re-reviewed, including preservation of unrelated focus. No live authenticated
    backend or assistive-technology test was performed. An expected-version
    mutation failed its focused regression and was restored.
    Exact-head GitGuardian passed and [#60](https://github.com/yanxel18/animetron/pull/60)
    merged normally at `9b94b8082b576db89b94d68f22fdde1e6f821ca2`.
- [ ] P7-05 Test keyboard and non-drag alternatives, focus, announcements,
  200% zoom, reduced motion and 375/768/1024/1440px layouts.
  - [x] P7-05a Merged in
    [#53](https://github.com/yanxel18/animetron/pull/53): close the mobile
    Studio navigation on Escape and restore focus to its disclosure button.
    Regression test, typecheck/build and all six Chromium acceptance cases pass;
    this is a narrow keyboard interaction slice, not full P7-05 evidence. See
    the [mobile navigation report](p7-05a-mobile-nav-focus-report.md).
  - [x] P7-05b Verify in Chromium that a delayed schedule conflict returns focus
    to recovery when the focused schedule control is removed, while preserving
    focus moved to another section. Confirm no mutation retry and a fresh list
    on recovery; fixture-based evidence does not establish screen-reader behavior.
    Merged in [#61](https://github.com/yanxel18/animetron/pull/61): all 13
    fixture-backed Chromium cases passed. Disabling focus recovery made the schedule-focus regression
    fail; the source was restored. Independent review found no significant
    issues. Exact-head GitGuardian passed; merged at `7c189e8`.
    Live authenticated backend and screen-reader behavior are unverified.
- [ ] P7-06 Measure contrast for implemented themes and agree, then test, a
  real 100-node/150-edge responsiveness target.
  - [x] P7-06a Record the owner-approved responsiveness target: Chromium on the
    reference computer at 1440px, real 100-node/150-edge workflow, p95
    keyboard/click selection to correctly updated inspector at most 200ms,
    100 measured selections after warm-up.
    [#31](https://github.com/yanxel18/animetron/pull/31); documentation review,
    whitespace and GitGuardian checks passed. Runtime performance/contrast
    tests remain open.

## Phase 8 - MCP bridge

Depends on: working authorized services in Phases 1, 2, 4 and 5. Complete when
an actual MCP client uses the same service authorization, audit and idempotency
rules without independent approval authority.

- [ ] P8-01 Implement bounded local stdio tools for models, runs, reviews and
  publications under an explicitly configured principal.
- [ ] P8-02 Verify schemas, malformed/unauthorized requests, REST/MCP parity,
  deterministic roundtrip and refusal to publish without human approval.

## Phase 9 - Integrated readiness

Depends on: all applicable phases and separately granted external permissions.
Complete only when the end-to-end acceptance evidence and recovery procedures
exist; this is not an automatic production deployment approval.

- [ ] P9-01 Run the authenticated sample-workflow-to-review flow with durable
  state, restart recovery and browser accessibility evidence.
- [ ] P9-02 Run an explicitly authorized real-model and eligible-platform
  acceptance flow; record resource usage, output checks and provider outcomes.
- [ ] P9-03 Verify backup/restore, private networking, secret handling,
  monitoring, failure recovery and documented rollback procedures.
- [ ] P9-04 Review remaining blockers, supported hardware and provider
  eligibility with the owner before requesting launch approval.
