# Spec: creator-studio

Status: Approved for implementation on November 14, 2026.
Depends on: platform-core, model-registry, workflow-runtime,
human-review, social-publishing, scheduling.

## Objective

Provide a dark/cyan creator workspace that makes workflow editing, resource
readiness, execution, preview and approval understandable and accessible.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused component verification: `npm run test -- --run`.
Browser verification: `npx playwright test e2e/studio.spec.ts`.
Ownership: `frontend/src/features`, shared components, API client and store.

## Code style and consumer contracts

Inherit shared style and [UX direction](UX-DIRECTION.md). Use backend-generated
OpenAPI types and node definitions; avoid a separately maintained frontend schema.
Zustand editor draft state is distinct from immutable run snapshots and durable
server state. Subscribe to node-specific fields rather than whole graph updates.

Use node palette, canvas, inspector/preview and run timeline. Screen inventory:
Studio, Runs, Library, Review, Models, Schedules, Connections, Settings.

## Testing and acceptance criteria

1. Save/validate/run a sample graph; reconnect and reload recover server state.
   Errors, queueing, waiting review and per-platform outcomes are distinct;
   progress is determinate only when supplied by an engine.
2. Add/connect/reorder nodes without dragging using pointer menus and keyboard
   alternatives. Verify focus, accessible names, status announcements, 200% zoom,
   reduced motion and 375/768/1024/1440px layouts. Small screens offer list editing.
3. Measure text/control contrast in both implemented themes. Approve a real
   100-node/150-edge responsiveness benchmark before assigning a performance
   threshold; do not count static mock screenshots as runtime verification.

## Boundaries

Inherit shared boundaries. No external font request by default, autoplay audio,
decorative heavy motion, structural emoji icons or secrets stored in browser
state. Approval card displays exact caption/revision/destinations; disabled
publishing explains why. Browser verification happens during implementation,
not this document-only phase.
