# AnimeTron project progress

This is the single project-wide implementation checklist. Last reconciled with
`master` and GitHub pull requests on 2026-11-14. The owner approved the
[module specifications](../docs/SPECIFICATIONS.md) for implementation and version
control on 2026-11-14. Their explicit provider, model, scheduling, performance
and human-acceptance gates still apply. This checklist does not replace them.

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
  - [x] P0-06a Apply browser security headers to API responses, including
    unhandled errors ([#19](https://github.com/yanxel18/animetron/pull/19);
    not authentication or CSRF protection).
  - [ ] P0-06b Bounded Keycloak/Authlib OIDC browser sessions, principal roles,
    CSRF logout, audit history, authorized readiness and origin-checked
    WebSocket handshake. **In review**
    ([#33](https://github.com/yanxel18/animetron/pull/33)) on
    `feature/oidc-browser-sessions`;
    dependency [#27](https://github.com/yanxel18/animetron/pull/27) is merged.
    See [auth contract and acceptance evidence](../backend/AUTH.md).
    Final suite: 278 passed / 20 existing Linux-only skips, including the
    PostgreSQL-backed WebSocket idle-timeout regression.
    No deployment, artifact/workflow HTTP, provider publishing, back-channel
    logout or phase-completion certification is included.
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
- [ ] P1-09 Implement authorized workflow CRUD, validation and idempotent run
  creation; persist node intents and outbox effects in one transaction.
- [ ] P1-10 Implement typed handlers, dispatch, fan-out/join and failure/skip
  behavior with deterministic sample nodes.
  - [x] P1-10a Derive immutable node dependencies from a validated workflow
    ([#15](https://github.com/yanxel18/animetron/pull/15); no scheduling or
    dispatch).
- [ ] P1-11 Implement cancellation, safe recovery, event replay and
  authenticated live updates; distinguish unknown external effects.
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
    experiment. In review in [#34](https://github.com/yanxel18/animetron/pull/34)
    on `benchmark/wan-ti2v-5b`; see
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
    The partial feasibility report is in review in
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
- [ ] P4-02 Persist review requests, delivery states, expiry and immutable
  decisions; supersede prior approval when its scope changes.
- [ ] P4-03 Enforce role, scope, expiry and transactional single-winner checks;
  persist decisions and outbox effects atomically.
- [ ] P4-04 Add authorized paginated review and decision APIs and a valid
  approval lookup for publication; reject stale, unauthorized and replayed actions.
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
  - [x] P6-02a Internal next-five preview core merged in
    [#35](https://github.com/yanxel18/animetron/pull/35): approved
    five-field/OR/IANA matching, gap skip, earlier fold only and deterministic
    zone/local-slot keys. Native suite 187 passed/77 existing integration skips,
    Ruff/strict Linux mypy and GitGuardian passed. Tests do not
    establish persistence, authorized CRUD, overlap/restart or dispatch.
    [Preview verification and findings](scheduling-preview-report.md).
- [ ] P6-03 Implement a single scheduler process with observable recovery and
  skipped slots; test pause, restart, overlap, DST and duplicate dispatch.

## Phase 7 - Creator studio

Depends on: corresponding authorized backend services; build usable slices
alongside the phases above. Complete when the real browser flows and
accessibility checks pass, not merely when mock screens exist.

- [ ] P7-01 Establish the dark/cyan workspace, local/system typography,
  responsive layout and accessible component foundations. Implementation is in
  review: [PR #36](https://github.com/yanxel18/animetron/pull/36). Keep unchecked
  until merged.
- [ ] P7-02 Implement workflow editing, inspector, validation and saved draft
  versus immutable revision using backend-owned contracts.
- [ ] P7-03 Implement run monitoring, reconnect/replay, library and preview with
  truthful loading, errors, waiting and progress states.
- [ ] P7-04 Implement review, models, schedules, connections and publication
  screens against their authorized services; explain blocked actions.
- [ ] P7-05 Test keyboard and non-drag alternatives, focus, announcements,
  200% zoom, reduced motion and 375/768/1024/1440px layouts.
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
