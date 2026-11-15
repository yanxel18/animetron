# AnimeTron project progress

This is the single project-wide implementation checklist. Last reconciled with
verified remote `master` at `2f003f6` on 2026-11-15. #53 and #54 merged
the mobile navigation and API contract slices; #55 reached master through #54.
#56 reconciled progress documentation. The historical #33 scanner failure
remains unresolved.
The owner approved the
[module specifications](../docs/SPECIFICATIONS.md) for implementation and version
control on 2026-11-14. Their explicit provider, model, scheduling, performance
and human-acceptance gates still apply. This checklist does not replace them.

## Overall progress snapshot - 2026-11-15

**31.6%: 18 of 57 top-level P0-P9 checklist tasks are complete.** This is an
unweighted task count, not a measure of effort, functionality or production
readiness. Nested slices are not counted separately; a partially completed
parent task stays incomplete, and open PRs do not count as complete. No phase
or P9 acceptance is complete. Recalculate this snapshot when the checklist or
merged status changes.

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

Main remaining gates include the historical #33 scanner failure, missing
workflow execution and editing services, model feasibility and capacity,
real media generation, and owner-involved P9 acceptance. P7-03a is local
in-progress work, not yet browser-verified, pushed or submitted as a PR.

## How to use

- Toggle a Markdown task by editing `[ ]` to `[x]` (or back to `[ ]`).
- Check a task only when its work is merged to `master` and its stated checks
  have passed. Link the merged PR or other evidence. An open PR is not done:
  leave the box unchecked and link the PR as **in review**.
- Before starting and with each task PR, reconcile merged work, update the
  affected items and this document's date, and record blockers or changed scope.
  Split an item into smaller checkboxes when necessary; keep their evidence.
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

### Current work - 2026-11-15

- P7-05a mobile navigation focus merged to master in
  [#53](https://github.com/yanxel18/animetron/pull/53).
- P7-01b generated API contracts and P7-04a review metadata queue reached
  master via [#54](https://github.com/yanxel18/animetron/pull/54) and
  [#55](https://github.com/yanxel18/animetron/pull/55). The combined frontend
  unit tests, production build, seven Chromium tests, API drift check and
  GitGuardian passed; an independent source review found stale report
  instructions, which were corrected before the owner merged #54.
- P7-03a is in progress on `task/p7-03a-run-monitor`. This read-only,
  run-ID-based monitor uses persisted status and event-replay endpoints;
  it does not create or cancel runs or invent progress.
P0-P9 and owner-involved P9 acceptance remain incomplete.
Slices not yet merged to master remain unchecked. No external publishing was done.

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
- [ ] P0-08 Establish private service networking, loopback gateway, retention,
  and tested backup/restore for metadata and artifacts.
- [ ] P0-09 Verify unauthenticated access, malformed uploads, secret redaction,
  transaction recovery and backup/restore with integration tests.
  - [x] P0-09a Add the owner's explicit local credential-file exclusion.
    Existing `*.env` protection remains intact; the local file is preserved.
    Names-only tracking and ignore checks passed. Merged in
    [#39](https://github.com/yanxel18/animetron/pull/39); this is not a fix
    for or clearance of the blocked auth scanner.
    [Credential exclusion evidence](development-report.md#hugging-face-credential-file-exclusion).

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
- [ ] P1-09 Implement authorized workflow CRUD, validation and idempotent run
  creation; persist node intents and outbox effects in one transaction.
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
- [ ] P1-10 Implement typed handlers, dispatch, fan-out/join and failure/skip
  behavior with deterministic sample nodes.
  - [x] P1-10a Derive immutable node dependencies from a validated workflow
    ([#15](https://github.com/yanxel18/animetron/pull/15); no scheduling or
    dispatch).
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
- [ ] P1-12 Verify restart, reconnect, concurrency and cancellation behavior
  end-to-end, including duplicate message handling.

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
  - Blocked: no workflow CRUD or validation routes exist in the generated
    backend contract; prerequisite P1-09 remains unchecked. Do not invent a
    frontend-only workflow schema or enable editing before those APIs exist.
- [ ] P7-03 Implement run monitoring, reconnect/replay, library and preview with
  truthful loading, errors, waiting and progress states.
  - [ ] P7-03a Add an owner-only run-ID monitor backed by persisted run status
    and bounded event replay. Poll durable state after reconnect; distinguish
    loading, live, stale/error and terminal states. No create/cancel controls or
    inferred progress. In progress on `task/p7-03a-run-monitor`.
    Library and artifact preview remain outside this slice. A failed later
    replay page previously advanced the cursor without preserving earlier
    events; the refresh now commits cursor and events together. Authorization
    loss clears previously displayed run details. Regression tests reproduced
    both issues before the fixes; Chromium also caught and verified a skip-link
    focus fix. Validation: 24 frontend unit tests, production build, API drift
    check and eight Chromium cases passed using local fixtures. Live
    authenticated backend and assistive-technology testing remain unverified.
- [ ] P7-04 Implement review, models, schedules, connections and publication
  screens against their authorized services; explain blocked actions.
  - [x] P7-04a Add the owner-only review metadata queue with truthful loading,
    empty, error and pagination states. Keep decisions unavailable until the
    exact artifact and caption can be previewed; depends on P7-01b API types.
    [#55](https://github.com/yanxel18/animetron/pull/55) merged to #54's
    branch and reached master in #54. Unit, production-build, API-drift and
    seven Chromium checks passed.
    See [P7-04a report](p7-04a-review-queue-report.md).
- [ ] P7-05 Test keyboard and non-drag alternatives, focus, announcements,
  200% zoom, reduced motion and 375/768/1024/1440px layouts.
  - [x] P7-05a Merged in
    [#53](https://github.com/yanxel18/animetron/pull/53): close the mobile
    Studio navigation on Escape and restore focus to its disclosure button.
    Regression test, typecheck/build and all six Chromium acceptance cases pass;
    this is a narrow keyboard interaction slice, not full P7-05 evidence. See
    the [mobile navigation report](p7-05a-mobile-nav-focus-report.md).
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
