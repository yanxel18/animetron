# AnimeTron

AnimeTron is intended to be a self-hosted creator studio for turning original
story ideas into short vertical animated videos using local AI models. It is
designed for one creator using Windows with WSL2 and Docker. The target video
length is 30–60 seconds, with a 90-second maximum. A 3D visual style means
rendered images and animation, not editable 3D meshes or rigs.

**Status: development, not an end-to-end production system.** As of the last
recorded checklist snapshot, 18 of 57 top-level tasks are complete (31.6%). This
is an unweighted task count, not a measure of working functionality. See
[the project checklist](tasks/todo.md) for the current evidence, open PRs and
acceptance gates; its status supersedes this snapshot.

## Intended creator workflow

1. Build or reuse a visual workflow that plans a story and creates scenes,
   animation, narration, subtitles and a final video.
2. Run the workflow locally, or schedule it, and monitor its progress.
3. Review the finished video, caption and destinations, including through the
   planned Telegram review flow. A person must approve the exact revision,
   caption and destination set; changes require fresh approval.
4. Publish approved content through eligible official platform APIs. Facebook
   Page Reels comes first; Instagram Reels, YouTube Shorts and TikTok are planned
   separately, subject to account and API eligibility.

## Planned models and tools

The architecture proposes Ollama for a local story-planning language model and
ComfyUI for image and video generation workflows. A specific story-planning
LLM, image-generation model, voice model and alignment engine have not been
selected as final defaults. Flux is mentioned as an image-model example.

Wan 2.2 TI2V 5B is an approved candidate for a bounded video-generation
feasibility test, not a proven or final production model. The recorded test
verified CUDA kernels but stopped before model acquisition because the RAM
capacity gate was not met; no model was loaded and no scene was generated.
See the [Wan feasibility report](tasks/wan-benchmark-report.md) for the exact
approved files, conditions and evidence.

## What exists

- A FastAPI backend with liveness, workflow draft/revision and run-status
  boundaries, schedule descriptors, review decisions, and artifact metadata.
  Several routes require an explicitly configured owner session and database.
- A React creator studio with workflow, run, review, schedule and artifact
  metadata screens. Some actions are read-only or limited to known IDs.
- PostgreSQL migrations, focused service/API tests, and fixture-backed browser
  tests. Individual slices and their limitations are tracked in the checklist.

This does **not** yet provide a complete authenticated deployment, durable
workflow execution, real media generation, automatic schedule dispatch,
Telegram review or social publication. Model feasibility and resource capacity
remain open. A successful health check or fixture-backed test does not establish
end-to-end readiness.

## Repository map

| Path | Purpose |
| --- | --- |
| [backend/](backend/) | FastAPI app, persistence, migrations, tests and backend documentation |
| [frontend/](frontend/) | React/TypeScript studio, generated API types and browser tests |
| [docs/](docs/) | Approved capability map, module specifications and UX direction |
| [tasks/todo.md](tasks/todo.md) | Project-wide task checklist, evidence and blockers |
| [tasks/](tasks/) | Development, benchmark and verification reports |
| `data/` | Local project data; do not commit credentials or generated model artifacts |

The [specification index](docs/SPECIFICATIONS.md) describes the intended system;
some paths and commands there are proposals rather than implemented services.

## Local preview

The following starts a loopback-only **development preview** on Windows. It
provides the UI and API liveness; it does not configure a login or make the
application ready for real workflow execution.

Prerequisites: Python 3.12 or newer, and the Node.js/npm versions specified by
[`frontend/package.json`](frontend/package.json) (currently Node 26.3.0 and
npm 11.16.0). Use separate PowerShell terminals:

```powershell
# Terminal 1: API
cd D:\animetron\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
# Terminal 2: studio
cd D:\animetron\frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173/](http://127.0.0.1:5173/). Vite proxies `/api`
to the backend. [http://127.0.0.1:5173/api/v1/health](http://127.0.0.1:5173/api/v1/health)
should return `{"status":"ok"}`. If the checkout is elsewhere, replace the
example paths above. Stop each process with `Ctrl+C` in its terminal.

Authenticated endpoints fail closed until an HTTPS browser origin, TLS
boundary, PostgreSQL, Keycloak and the required server environment are
configured. See [backend authentication](backend/AUTH.md) and the
[backend README](backend/README.md); do not create a development identity or
disable authorization to make the preview appear functional. No production
Compose deployment is included as a prerequisite of this preview.

## Verification

From `frontend`:

```powershell
npm test
npm run build
npm run e2e
```

Playwright browser cases use fixtures for many API responses. They do not
replace an authenticated live-backend test or assistive-technology testing.
See [frontend guidance](frontend/README.md) for the preview and editor handoff.

From `backend`, use the environment and commands in
[backend/README.md](backend/README.md). The authentication harness creates
disposable resources and has explicit database-ownership guards; do not point
it at a shared database or bypass those guards. Backend tests may require
Docker, PostgreSQL, Keycloak and browser prerequisites, depending on scope.

## Configuration and data

The backend reads its configuration from process environment variables. The
required identity, origin, database and secret settings are documented in
[backend/AUTH.md](backend/AUTH.md). Do not commit secrets, tokens, credentials,
private user data, or model files. Preserve existing data and follow the
project's explicit consent and capacity gates for model acquisition, external
transmission and publishing.

## Continuing development

1. Check the current branch, working tree and [task checklist](tasks/todo.md).
2. Read the relevant [module specification](docs/SPECIFICATIONS.md) and existing
   implementation before choosing a bounded slice.
3. Record tests, limitations, review status and handoff details in the affected
   task and documentation. An open PR or a merged slice with unmet gates is not
   automatically a completed top-level task.
4. Keep external publishing, deployment and model acquisition within the
   project's documented authorizations and acceptance requirements.

For repository changes, follow the [development workflow](.github/copilot-instructions.md):
use a detailed commit and PR, post a self-review, run appropriate checks, and
merge to `master` when ready and allowed by branch protections. The product's
human content-approval gates remain separate from code review.

The checklist is the source of truth for remaining work and verification;
the [development report](tasks/development-report.md) and
[model benchmark report](tasks/wan-benchmark-report.md) contain historical
evidence and should be read with their dates and stated limitations.
