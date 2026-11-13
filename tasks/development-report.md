# Development findings

This report records unresolved findings; implementation progress remains in
[todo.md](todo.md). Findings are not evidence of production readiness.

## Findings

- **F-001: Execution is not ready.** Workflow snapshots do not pin handler
  implementations, configuration defaults or models; node dispatch and
  authenticated control APIs remain incomplete. Do not enqueue real work.
- **F-002: Model readiness is not established.** Identity, file hashes and
  manifest metadata do not authorize a download or establish license acceptance,
  repository allowlisting, secure file access, capacity or model readiness.
- **F-003: End-to-end acceptance remains outstanding.** Artifact storage,
  media generation, human decisions, official publishing, scheduler, studio
  and MCP are incomplete. Live model/provider use and final system acceptance
  require the relevant consent and owner involvement.
- **F-004: Resolved - specifications are shared.** Owner-approved module
  specifications are merged in [#27](https://github.com/yanxel18/animetron/pull/27).
- **F-005: Authentication implementation remains incomplete.** The owner chose
  a maintained identity-provider integration and delegated provider selection.
  Implementation/verification is in progress; no merged authenticated session,
  CSRF defense, protected WebSocket, trusted-host policy, or authorized
  readiness endpoint exists. Security response headers do not provide these.
- **F-006: Byte-storage recovery remains incomplete.** On 2026-11-14 the owner
  approved a dedicated Linux service with a private Docker named volume, including
  the exception to project-directory-only storage for Docker-managed volumes.
  Native Windows byte storage remains unsupported. Internal byte publication and
  PostgreSQL metadata commits are not atomic; interruption can leave staged,
  double-linked or orphaned files. Explicit offline reconciliation, retention,
  aggregate quotas, media probing and coordinated backup/restore are still needed
  before exposing uploads/downloads or declaring Phase 0 complete.

## P0-P9 readiness assessment - 2026-11-14

**Status: BLOCKED, not complete or production-ready.** Reconciled against
`origin/master` at `9ea20baf89feda8bfa34553e8b6d5f2a4b01a7c3`.
The autonomous workflow instructions are merged in
[#25](https://github.com/yanxel18/animetron/pull/25). No open PRs were returned
by the authenticated GitHub REST query at assessment time.

The request to work autonomously through P9 permits implementation and normal
PR handling, but explicitly preserves specification and external-action gates.
The first required stop is P0-01: module specifications are still drafts and
authentication architecture remains undecided. P0-02 separately requires
permission to commit the local specifications. No approval was inferred from
the request to finish the phases.

### Verification performed

Existing commands ran from `backend` using its existing virtual environment;
no dependencies were installed and no source code or tests were changed.

| Check | Result | Limits |
| --- | --- | --- |
| `python -m pytest tests -q -rs -p no:cacheprovider` | 162 passed, 77 skipped | 20 Linux filesystem tests and 57 PostgreSQL cases did not execute |
| `python -m ruff check --no-cache app tests migrations` | Passed | Static lint only |
| `python -m mypy --cache-dir .mypy_cache app` | 15 errors in Linux-only byte storage on Windows | Wrong platform target for that module, not a newly introduced regression |
| `python -m mypy --platform linux --cache-dir .mypy_cache app` | Passed, 23 source files | Documented deployment target; does not verify Linux runtime behavior |

Database URL environment variables were removed only in the test subprocess
to prevent accidental writes to an inherited/shared database. Test temporary
storage was directed inside the repository. The existing skip conditions were
not modified. These results are a partial local baseline, not integration or
end-to-end acceptance evidence.

### Phase gaps and required gates

| Phase | Remaining evidence or implementation |
| --- | --- |
| P0 | Specification/access decisions, authenticated control plane, authorized artifact lifecycle, private networking and coordinated backup/restore |
| P1 | Handler/model pinning, authorized workflow/run services, durable dispatch, cancellation and recovery |
| P2 | Verified hardware/runtime capacity, allowlisting, explicit license/access records, acquisition and real benchmarks |
| P3 | Local generation, narration/alignment/rendering, measured media boundaries and human quality review |
| P4 | Durable review decisions, authorization/expiry/race protection and separately consented Telegram delivery |
| P5 | Approval-bound publication intents, eligible official adapters and separately authorized live acceptance |
| P6 | Owner-approved cron/time-zone/overlap/missed-run/DST policy before scheduling implementation |
| P7 | Backend-connected studio and real browser/accessibility/performance evidence; no frontend currently exists |
| P8 | Authorized bounded MCP tools and service parity tests |
| P9 | Authenticated end-to-end/recovery acceptance, real-model/provider evidence and owner readiness review |

The ui-ux-pro-max skill was loaded. The existing local UX direction records
approved dark/cyan styling but proposed tokens and interaction targets. It also
records two off-topic design-system matches; those recommendations must not be
treated as verified studio designs. No mock screen or calculated token palette
was substituted for P7 browser evidence.

### Decisions needed to resume

1. Approve the remaining draft module specifications for implementation and
   explicitly permit adding them to version control (P0-01/P0-02).
2. Select the trusted-gateway or maintained identity-provider session strategy,
   including the trusted boundary and initial reviewer/principal setup.
3. Approve scheduling semantics and the measured studio responsiveness target
   when their tasks are reached; these are not silently chosen defaults.
4. Explicitly confirm any Docker-volume exception to the current
   project-directory-only boundary before creating persistent artifact/model
   volumes. The earlier storage decision exists, but this run created none.
5. Supply separate model/license/access and Telegram/provider acceptance
   permissions when their gates are reached. General library download or
   internet-search permission does not authorize these actions.

### Environment and PR safety

All file changes are confined to this repository. Existing untracked
specifications and the empty `tasks/findings.md` were preserved and not staged.
No containers, services, migrations, model downloads, live publishing, operating
system changes or destructive cleanup were performed.

The GitHub MCP read returned 404 for the repository. The existing Git credential
helper worked with authenticated GitHub REST; credentials were neither printed
nor written to files. Branch metadata reported `master` unprotected. This is
not permission to skip reviews or waive checks; branch protection/CI policy
should be addressed before treating merges as independently enforced gates.

This assessment is documentation-only. No phase checkbox was marked complete.
Final system testing and owner-involved P3/P9 acceptance remain outstanding.

## Approval update - 2026-11-14

After the readiness assessment was merged in
[#26](https://github.com/yanxel18/animetron/pull/26), the owner explicitly approved
all nine local module specifications for implementation and version control.
F-004's permission gate and the implementation-approval portion of P0-01 are
therefore resolved; version-control publication remains incomplete until its
PR is merged. The owner chose a maintained identity-provider integration and
delegated provider selection. F-005's gateway-versus-provider decision is
resolved, but authenticated implementation and acceptance remain outstanding.

The earlier readiness assessment is historical evidence, not the current
approval state. Continue using [todo.md](todo.md); remaining external-action,
scheduling/performance and owner-involved acceptance gates are unchanged.

## Hardware evidence - 2026-11-14

Specification publication is merged in
[#27](https://github.com/yanxel18/animetron/pull/27); F-004 is resolved.
Host/resource inspection and a bounded Linux-container NVIDIA probe produced:

| Measurement | Observed value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| Total reported VRAM | 16,303 MiB |
| Free reported VRAM at inspection | 14,103 MiB; volatile, not reserved capacity |
| NVIDIA driver | 621.01 |
| GPU compute capability | 12.0 |
| Host physical memory | 34,055,766,016 bytes |
| Project drive D free space | 240,320,303,104 bytes; volatile, not reserved capacity |
| WSL | 2.7.8.0, default version 2, default distribution docker-desktop |
| WSL kernel | 6.18.33.1-1 |
| Docker server | 29.7.2, Linux x86_64 |
| Existing Python test image ID | `sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` |

The existing `python:3.12-slim` image ran only the NVIDIA hardware query, with
`--rm`, no network, read-only root filesystem, all capabilities dropped,
no-new-privileges, 32-process/128-MiB/one-CPU limits and the unique name
`animetron-hardware-478745d5`. It reported the same GPU, VRAM, driver and compute
capability inside Linux. The exact-name container query after exit returned
no container. No image was downloaded and no GPU inference was launched.

**This verifies driver/device visibility, not a working CUDA compute kernel,
PyTorch build, ComfyUI compatibility or model throughput.** Project-drive free
space also does not prove free space in Docker-managed artifact/model volumes.
No capacity reservation, inference engine, model default or checkpoint pin is
established by these measurements.

### Runtime and benchmark next steps

- Use Linux GPU containers through WSL2 as the candidate inference runtime;
  secure byte storage remains Linux-only. Do not install a Linux NVIDIA driver
  into WSL or change the host driver as part of this project.
- Select an officially compatible framework/CUDA build for compute capability
  12.0, then verify device enumeration and a small synchronized real tensor
  operation in an isolated bounded test before marking CUDA compute ready.
- Confirm free space and staging/output headroom at the actual model/artifact
  storage location. Enforce a single GPU admission slot; the currently free
  VRAM figure is not permission to consume other workloads' capacity.
- After explicit checkpoint/license/access approval, benchmark one small scene
  before a 30-60-second reel. Record immutable revisions and file hashes,
  framework/CUDA/ComfyUI/FFmpeg versions, peak GPU/RAM/disk use and elapsed time.
- Validate 9:16, decodability, audio, subtitles and the hard 90-second maximum.
  Obtain owner review of character consistency, voice rights and alignment;
  do not substitute deterministic fixtures for model or visual-quality evidence.

### Documentation evidence and unresolved compatibility

- [NVIDIA CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html#nvidia-gpu-computing-on-wsl):
  WSL2 is required; container GPU use is supported, while WSL `nvidia-smi`
  exposes a limited feature set. Hardware visibility alone is insufficient.
- [PyTorch local installation page](https://docs.pytorch.org/get-started/locally/):
  the retrieved selector showed an old stable label alongside newer CUDA options.
  This inconsistent page was not used to choose a version pin. Verify current
  official release/build support and a real kernel before accepting compatibility.

P2-02 remains incomplete pending compute/storage compatibility evidence; P2-06
and P3/P9 real-model acceptance remain explicitly gated.

## Scheduling-policy approval - 2026-11-14

The owner approved five-field cron with explicit IANA zones and standard
day-of-month OR weekday semantics, skipped overlapping GPU generation, skipped
missed occurrences without catch-up, skipped spring-forward gaps and one
execution at the earlier fall-back occurrence. Preview and dispatch must share
the persisted slot identity. The [scheduling specification](../docs/SPEC-scheduling.md)
records the decision and the maintainer documentation limits.

This resolves the policy-choice portion of P6-01, not P6-02/P6-03. No scheduler,
library pin, due-slot transaction or DST runtime behavior was implemented or
certified by the documentation change. Hardware evidence is merged in
[#28](https://github.com/yanxel18/animetron/pull/28); P2-02a is reconciled while
P2-02 remains incomplete.

The owner identified a project-local Hugging Face environment file. Metadata
confirmed that it was untracked; its contents were not read. Ignore rules for
`*.env` and `.worktrees/` were verified and merged in
[#29](https://github.com/yanxel18/animetron/pull/29). No credential value was
printed, staged or transmitted. An available token is not evidence of model
license acceptance, repository approval or inference compatibility.

## Studio responsiveness approval - 2026-11-14

The owner approved a real 100-node/150-edge workflow benchmark in Chromium on
the reference computer at 1440px width: p95 keyboard/click node-selection time
to the correctly updated inspector at most 200ms across 100 measurements after
warm-up. The [studio specification](../docs/SPEC-creator-studio.md) and
[UX direction](../docs/UX-DIRECTION.md) now record the same target.

This is an approved acceptance target, **not an enforced or passing check**:
no frontend or browser measurement command exists yet. P7 implementation must
add the actual runtime test and verify that a deliberately over-budget control
fails; static screenshots or a standalone mock do not satisfy the requirement.
Accessibility, responsive layouts, 200% zoom, reduced motion and composed color
contrast remain separate acceptance criteria.

Constraint-driven development is floor-only during this autonomous run:
no new suppressions, unfinished success-shaped stubs, weakened checks or
unexplained skipped/deleted tests. No coverage percentage, CI security policy
or extra performance budget was silently invented or marked enforced.

## Pinned-model consent - 2026-11-14

The owner explicitly accepted the applicable model license terms and authorized
acquisition and a local test of this candidate, conditional on capacity,
integrity and framework safety checks. This consent does not authorize other
models, voices, cloud inference, content transmission or publication.

Repository: `Comfy-Org/Wan-2.2`.
Revision: `ee6f4a40737a995bf5818954cfce6d59443b0f04`.
Public API metadata reported an ungated repository and Apache-2.0 license.
The older Comfy-Org repository alias redirects to this canonical identity.

| File within the pinned repository | Bytes | Published SHA-256 |
| --- | ---: | --- |
| `split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` | 9,999,658,848 | `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e` |
| `split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6,735,906,897 | `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| `split_files/vae/wan2.2_vae.safetensors` | 1,409,400,960 | `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156` |

Total: 18,144,966,705 bytes, before staging, runtime packages or output headroom.
Public metadata was retrieved without accessing the local Hugging Face key.
Published hashes are trusted expectations for subsequent byte verification,
not proof that any files have been acquired or are ready.

Official evidence:

- [ComfyUI native Wan2.2 workflow](https://docs.comfy.org/tutorials/video/wan/wan2_2):
  identifies all three files and says 5B should fit 8GB with native offloading.
- [ComfyUI maintainer example](https://comfyanonymous.github.io/ComfyUI_examples/wan22/):
  provides native text/image-to-video examples and the required encoder/VAE.
- [Pinned repository metadata](https://huggingface.co/api/models/Comfy-Org/Wan-2.2/revision/ee6f4a40737a995bf5818954cfce6d59443b0f04?blobs=true):
  provides file sizes and LFS SHA-256 values.
- [Wan model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) and
  [UMT5 model card](https://huggingface.co/google/umt5-xxl):
  declare Apache-2.0 licensing. These records are not legal advice or a
  performance/voice-rights guarantee.

A bounded independent feasibility task is in progress on
`benchmark/wan-ti2v-5b`. It must establish safe runtime compatibility before
loading the approved models. A short scene does not satisfy the final
30-60-second narrated reel, human visual review or P9 acceptance.

Scheduling-policy documentation and the studio target are merged in
[#30](https://github.com/yanxel18/animetron/pull/30) and
[#31](https://github.com/yanxel18/animetron/pull/31); only their approval
checklist items are reconciled, not runtime implementation.

## Isolated foundation verification - 2026-11-14

Previously skipped boundary checks were exercised separately without modifying
application source or weakening tests:

- **Linux artifact storage: 21 tests passed** in the existing
  `python:3.12-slim` image, including 20 Linux-only tests and the native-refusal
  case. Real process-crash, concurrent-write, permission, symlink/hardlink and
  integrity boundaries were exercised. Code was mounted read-only, network was
  disabled, CPU/RAM/process counts were bounded and a fresh private test volume
  used service UID 10001. Exact owned container/volume removal was confirmed.
- **PostgreSQL foundations: 92 selected tests passed** after
  `alembic upgrade head`; `alembic check` reported no new upgrade operations.
  The selected files cover database, artifact metadata, outbox, run events,
  run/revision binding and workflow revisions, including previously skipped
  integration cases. This is not a single Linux-plus-database full-suite run.
- The isolated official PostgreSQL 17 image was downloaded only after its
  absence was confirmed, and executed at digest
  `sha256:846a7ddaa67a4b354ae1d21087b683901aa6113a4ed626d3787cfbf6c85e3e07`.
  The service used an ephemeral loopback port, generated disposable credentials,
  read-only root, bounded CPU/RAM/processes and tmpfs database storage.
  No inherited database URLs or real user database were used.

The first disposable DB attempt omitted the documented migrations and produced
50 failures/42 passes from missing tables. This was test setup error, not a
new product regression. Its cleanup also encountered Windows native-argument
quoting in a Docker Go-template expression. The exact session-labeled container
was subsequently identified and removed. The corrected attempt applied the
documented migrations and read label JSON instead of using quoted index syntax;
all 92 selected tests passed and its exact container removal was confirmed.

These checks strengthen foundation evidence but do not complete P0-09:
authenticated APIs, malformed-media handling, coordinated backup/restore and
full pipeline recovery are still outstanding. Approved benchmark outputs and
owner-involved system acceptance remain separate.
