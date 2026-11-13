# AnimeTron: Capability Map

Status: Approved by the user on November 13, 2026.

## Objective

A self-hosted creator studio that turns original story prompts into vertical
animated videos, obtains human approval through Telegram, and publishes approved
artifacts to selected social platforms.

This document defines module boundaries, not a production-readiness claim.
Module specifications were approved for implementation on November 14, 2026;
the [task checklist](../tasks/todo.md) records progress and remaining gates.

## Confirmed constraints

- Single creator using Windows with WSL2 and Docker.
- Local inference is required, with automatic Hugging Face model acquisition.
- Visual workflow editing, background execution and scheduling are required.
- Telegram review and publishing to multiple social platforms are required.
- Implementation is authorized within the project/repository; external-action
  and human-acceptance gates remain explicit.

## Approved assumptions

1. The product is a desktop-first web application, not a native desktop app.
2. Facebook means Facebook Page Reels, not personal-profile publishing.
3. Every publication requires approval of the exact output revision, caption and
   destination set. Changing any of these invalidates the approval.
4. Initial workflows are typed, acyclic graphs of allowlisted nodes. Arbitrary
   Python, shell commands, plugins and loops are excluded.
5. "3D characters" means rendered images and video with a 3D visual style.
   Flux/Wan do not deliver editable meshes, rigs or a true 3D scene pipeline.
6. Additional platforms are separate adapters gated by official API eligibility.
7. Model downloads require confirmed license/access acceptance and a storage
   check. Startup checks availability but does not silently download large models.

Approved destinations: Facebook Page Reels, Instagram Reels, YouTube Shorts and
TikTok. Facebook Page Reels is the first adapter. Approved visual direction:
dark creator studio with cyan accents.

## Module boundaries

Dependencies indicate providers used by a module. No provider depends on its
consumer; this avoids cycles.

| Stable module id | Responsibility | Depends on |
| --- | --- | --- |
| platform-core | Configuration, authenticated access, PostgreSQL, artifact storage, audit records | None |
| model-registry | Pinned model manifests, access/license checks, verified downloads and readiness | platform-core |
| workflow-runtime | Versioned DAG validation, run/node states, queue dispatch, events, cancellation | platform-core |
| media-generation | Story planning, character references, keyframes, animation, TTS, alignment, rendering through node handlers | model-registry, workflow-runtime |
| human-review | Telegram delivery, approve/reject decisions, immutable approval scope | workflow-runtime |
| social-publishing | Destination eligibility, per-platform publication intents, upload/status reconciliation | human-review |
| scheduling | Editable schedules, time zones, missed-run/overlap policy and run creation | workflow-runtime |
| creator-studio | React canvas, inspector, run monitor, artifact preview, review and destination screens | platform-core, model-registry, workflow-runtime, human-review, social-publishing, scheduling |
| mcp-bridge | Authenticated MCP tools wrapping existing application services; no independent approval authority | model-registry, workflow-runtime, human-review, social-publishing |

Media handlers implement the runtime's node-handler contract. The runtime owns
state and dispatch without importing generation-provider implementations.
Human review consumes a completed artifact revision through that same contract,
so it need not depend on any particular image/video model.

## Proposed build order

```text
platform-core
  -> model-registry + workflow-runtime
  -> media-generation
  -> human-review
  -> social-publishing

workflow-runtime -> scheduling
approved service contracts -> creator-studio slices alongside each capability
working application services -> mcp-bridge
```

Build vertical slices rather than finishing the entire backend before the UI:
save a workflow, run a deterministic sample, generate one scene, preview a reel,
review it, then publish it. These are build-order examples, not approved tasks.

## Proposed architecture direction

| Area | Recommendation | Reason |
| --- | --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind, React Flow, Zustand | Matches requested editor; typed contracts and selective state subscriptions |
| API | FastAPI, Pydantic, authenticated WebSockets | Async control plane with validated boundaries |
| Database | PostgreSQL, SQLAlchemy, Alembic | Avoid relying on the archived Prisma Client Python |
| Background work | Celery with Redis; separate CPU/I/O and single-concurrency GPU dispatch | Long-running jobs must not block API requests or compete for VRAM |
| Scheduler | One separate Beat process with persistent editable schedule support | Avoid duplicate scheduling and hardcoded daily-only configuration |
| Inference | Ollama for LLM; ComfyUI for image/video; local TTS and FFmpeg | One primary image/video execution path; direct Diffusers only if a benchmark justifies it |
| Artifacts | Local durable volume, database metadata, opaque artifact ids | Avoid user-controlled filesystem paths and binary payloads in queues |
| Telegram | Bot API adapter; outbound polling for initial local deployment | Human review without publicly exposing the workstation |
| MCP | Optional transport over the same service contracts | MCP is not the Telegram Bot API or a webhook security mechanism |
| Publishing | Official APIs, separate destination adapters | Platform capabilities and permissions differ |

These recommendations remain subject to specification approval and official
provider compatibility checks.

## Hardware feasibility gate

Do not promise generation throughput or model compatibility from GPU branding
alone. Before choosing checkpoints and runtimes:

- Inspect actual VRAM, driver, WSL2 CUDA access and supported PyTorch/CUDA build.
- Benchmark the smallest suitable image/video checkpoints with sequential model
  loading, quantization/offload where officially supported.
- Measure peak VRAM/RAM, disk consumption and elapsed time for one scene and one
  short reel; report visual quality separately from successful execution.
- Reserve space for downloads, temporary frames, outputs and the WSL virtual disk.
  Reject new work before resource exhaustion; never delete approved artifacts
  automatically to make space.
- Keep generation resolution and final encoding resolution separate. Upscaling
  does not recover native detail or guarantee character consistency.

## Corrections to the supplied draft

- An existing nonempty model directory is not proof of a complete download.
  Use pinned revisions, manifests, staging and atomic readiness transitions.
- A sample Celery task returning success without producing artifacts is a stub,
  not pipeline validation.
- Queue delivery is not exactly-once. Persist intents and enforce database
  uniqueness; reconcile unknown external outcomes instead of blind retries.
- Telegram delivery alone is not review. Authenticate reviewer identity,
  bind callbacks to an immutable review revision, deduplicate updates and audit.
- Publishing cannot be a synchronous continuation while a worker waits for
  approval. Persist a waiting state and resume through a separate authorized job.
- Binding `8000:8000` normally exposes all host interfaces. Default to a
  loopback-bound gateway; keep Redis, PostgreSQL and inference ports private.
- Extension allowlists alone do not secure uploads. Validate signatures,
  resource limits and actual media content; use generated storage names.
- Local inference does not mean zero external traffic: downloads, Telegram and
  publishing transmit data to their respective services.

## Approval gate

Module boundaries, assumptions, platform priority and visual direction are
approved. The owner separately approved module specifications for implementation
and version control on November 14, 2026. Model/license, provider, deployment and
human-acceptance gates remain in force.

## Sources

- [Prisma Client Python repository](https://github.com/RobertCraigie/prisma-client-py):
  archived April 15, 2025; checked November 13, 2026.
- [Celery FAQ](https://docs.celeryq.dev/en/stable/faq.html):
  task routing, scheduling and retry behavior; checked November 13, 2026.
