# AnimeTron: Specification Index and Shared Conventions

Status: Approved for implementation and version control on November 14, 2026,
preserving the duration revision and explicit acceptance/external-action gates.
Scope map: [CAPABILITY-MAP.md](CAPABILITY-MAP.md).
UX direction: [UX-DIRECTION.md](UX-DIRECTION.md).

## Objective and approval scope

For one creator, generate locally inferred, original vertical animated content,
review it in Telegram and publish approved revisions through official APIs.
Support Facebook Page Reels first, then Instagram Reels, YouTube Shorts and
TikTok. A platform that lacks account/API eligibility remains explicitly blocked;
browser automation or unofficial publishing is not a fallback.

Approval of these specifications authorizes implementation and version control,
not public publishing, model/license acceptance or production deployment.
The owner separately permits required library downloads and project-scoped
Docker/container use; explicit model and external-transmission gates still apply.

## Module index

| Module | Specification | Key success condition |
| --- | --- | --- |
| platform-core | [SPEC-platform-core.md](SPEC-platform-core.md) | Durable authenticated control plane and safe artifact storage |
| model-registry | [SPEC-model-registry.md](SPEC-model-registry.md) | No partial or unaccepted model is marked ready |
| workflow-runtime | [SPEC-workflow-runtime.md](SPEC-workflow-runtime.md) | Validated versioned graphs run durably without duplicate node effects |
| media-generation | [SPEC-media-generation.md](SPEC-media-generation.md) | One coherent reel with voice and aligned subtitles passes media checks |
| human-review | [SPEC-human-review.md](SPEC-human-review.md) | Only the authorized reviewer can approve the exact revision |
| social-publishing | [SPEC-social-publishing.md](SPEC-social-publishing.md) | Per-destination intents are reconciled without blind duplicate publishing |
| scheduling | [SPEC-scheduling.md](SPEC-scheduling.md) | One persisted intent per due schedule slot |
| creator-studio | [SPEC-creator-studio.md](SPEC-creator-studio.md) | Canvas and review workflows remain usable without dragging |
| mcp-bridge | [SPEC-mcp-bridge.md](SPEC-mcp-bridge.md) | MCP exposes service capabilities without bypassing authorization |

## Shared project structure

Proposed future project root is the parent of this document's directory:

```text
AnimeTron/
  docs/                         approved map and module specifications
  backend/
    pyproject.toml              dependency manifest and tool configuration
    app/
      api/                      FastAPI routes and transport schemas
      core/                     configuration, authentication and persistence
      models/                   SQLAlchemy entities
      services/                 business rules and durable intents
      engines/                  local inference and media adapters
      integrations/             Telegram and social adapters
      mcp/                      MCP transport and tool schemas
      tasks/                    Celery dispatch and scheduler entrypoints
    migrations/                 Alembic revisions
    tests/                      focused unit and integration tests
  frontend/
    src/
      features/                 studio, runs, library, review, models, schedules
      components/               shared UI primitives
      api/                      generated client and transport handling
      store/                    editor state and selective subscriptions
    e2e/                        browser acceptance tests
  compose.yaml                  private services and loopback gateway
  data/                         models, uploads, outputs, temporary staging
  tasks/plan.md                 created after specification approval
  tasks/todo.md                 sole implementation task checklist
```

The backend foundations already exist. Follow [implementation progress](../tasks/todo.md)
and the [backend commands](../backend/README.md), rather than assuming every
proposed directory or command below exists.

## Commands

Proposed commands below must be made executable by the future foundation tasks.
They are not existing verified project commands. Frontend commands run from
`frontend`; backend commands run from `backend` in its environment. Celery and
GPU services run in Linux containers/WSL2, not native Windows workers.

```powershell
# Future frontend scripts
npm run dev -- --host 127.0.0.1
npm run build
npm run typecheck
npm run lint
npm run test -- --run
npx playwright test

# Future backend checks and local API
python -m pytest tests -q
python -m ruff check app tests
python -m mypy app
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Future root Compose deployment
docker compose config --quiet
docker compose up -d --build
```

A specification's focused pytest selector refers to tests to be implemented,
not passing evidence today. Live provider tests are explicitly opted in and use
authorized test accounts; do not upload or publish as part of routine unit tests.

## Code style and contracts

- Python snake_case internally; public JSON camelCase via explicit Pydantic
  aliases. TypeScript strict mode; generated types follow backend OpenAPI.
- Discriminated unions for node configs and transport states; no arbitrary
  Python or shell strings in node parameters.
- UTC timestamps with explicit time zones for schedule input.
- Resource ids are opaque; file paths and credentials are never transport ids.
- Preserve validation failures and provider errors; redact sensitive details.

Illustrative public contract, not implementation:

```typescript
type NodeState =
  | "PENDING" | "QUEUED" | "RUNNING" | "SUCCEEDED"
  | "FAILED" | "SKIPPED" | "CANCELLED";

interface RunEvent {
  sequence: number;
  runId: string;
  nodeId: string | null;
  state: NodeState | null;
  occurredAt: string;
  message: string;
}

interface ApiError {
  error: {
    code: string;
    message: string;
    requestId: string;
    details?: Record<string, string[]>;
  };
}
```

Implemented control APIs must use one error envelope: 401 unauthenticated,
403 unauthorized, 404 absent,
409 concurrency/state conflict, 422 invalid input or mismatched idempotency
payload, 429 quota/rate limit, 5xx server/upstream failure with redacted details.
Lists have cursor pagination and capped page size.

## Shared testing strategy

- pytest: domain rules, failure paths, DAG validation and adapter response parsing.
- PostgreSQL/Redis integration tests: uniqueness, transactions, outbox delivery,
  concurrent callbacks, reconnect recovery and crash reconciliation.
- Vitest/Testing Library: user-visible state and accessible component behavior.
- Playwright: complete editor/sample-run/review flows and keyboard alternatives.
- Hardware benchmarks: real inference compatibility, resource peaks, quality
  samples and elapsed time. No synthetic mock can certify model performance.
- Live provider checks: credential eligibility and approved test publication,
  separately authorized and never enabled by default.
- No arbitrary coverage threshold is specified. Tests must prove introduced
  behavior and failure modes; percentage coverage does not replace acceptance.

## Boundaries

- Always: validate external data, enforce authorization, preserve immutable run
  revisions, audit decisions and run focused checks before task completion.
- Ask first: new external transmission, model licenses, paid services, dependency
  selection/version pins, public exposure, destructive cleanup or live publishing.
- Never: commit secrets, bypass review, silently substitute cloud inference,
  execute LLM-generated commands, suppress failing tests or invent success.

## Release success criteria

- A short original 9:16 reel is generated with local inference, narration and
  aligned burned-in subtitles, then reviewed and published to an eligible Page.
- Rejection, stale approvals, unauthorized callbacks and cancellation cannot
  trigger new publications.
- Each additional platform passes its own eligibility, review and publication
  acceptance tests before being marked enabled.
- Worker restart, duplicate queue delivery, network loss and unknown publication
  outcomes leave durable visible states, not success-shaped fallbacks.
- UI and services meet the module acceptance criteria, with evidence attached to
  the future implementation tasks. This draft is not production certification.

## Open decisions and gates

- Exact checkpoint revisions, TTS/alignment engines and licenses: benchmark and
  approve before implementation pins.
- GPU VRAM and driver/CUDA/PyTorch compatibility: inspect and measure.
- Approved reel duration: target 30-60 seconds, hard maximum 90 seconds.
  English and one narrator remain proposed defaults; voice selection and visual
  quality targets must be settled before media benchmarking.
- Proposed export baseline: 1080x1920 H.264 video, AAC audio, 24fps; validate each
  destination's current constraints before enabling its adapter.
- Character consistency is an evaluated visual outcome, not guaranteed by seed
  reuse. Approve representative reference and motion samples.
- Approval expiry, retention and missed-schedule defaults are proposed in the
  module specs; changes must remain explicit.
- TikTok's current audit/account restrictions may prevent the desired fully
  unattended flow. Treat this as a release gate, not a guaranteed capability.

## Implementation approval

On November 14, 2026, the owner explicitly approved all nine module
specifications for implementation and adding them to this repository. The owner
selected a maintained identity-provider integration and delegated its selection.
The [task checklist](../tasks/todo.md) remains the single progress source.
Approval does not settle model licenses/revisions, platform eligibility, live
publication, deployment, or owner-involved media/system acceptance. Scheduling
semantics and measured studio targets retain their explicit approval gates.
