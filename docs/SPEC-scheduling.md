# Spec: scheduling

Status: Approved for implementation on November 14, 2026.
Depends on: workflow-runtime.

## Objective

Let the creator schedule immutable workflow revisions without duplicate due
slots, overlapping GPU runs or implicit approval of publications.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_scheduling.py -q`.
Ownership: schedule entities/services and separate Beat scheduler integration.

## Code style and provider contracts

Inherit shared style. Schedule has workflowRevision, cron expression, IANA
timeZone, enabled, nextDueAt and explicit overlap/missed-run policies.

- Create/read/update endpoints under `/api/v1/schedules`.
- `POST /api/v1/schedules/{id}/previews`: next five occurrences with offsets.
- Internal dispatch creates the runtime run intent, not a direct inference call.

Default proposal: skip overlapping generation, skip missed occurrences on
restart, and permit no catch-up burst. A recurring local time is fired once per
local schedule slot on fall-back and skipped if nonexistent on spring-forward;
document exact cron-library behavior before approval of implementation.

## Testing and acceptance criteria

1. Two due-dispatch attempts produce one persisted run intent using a unique
   schedule/slot key and atomic outbox; schedule edits cannot mutate existing runs.
2. Tests cover pause/resume, restart, overlap, daylight-saving ambiguity and
   nonexistence with matching preview and execution behavior.
3. Scheduler failure/recovery and skipped slots are visible and audited. Every
   generated output still waits for its own human approval.

## Boundaries

Inherit shared boundaries. One Beat process; no worker-embedded duplicate Beat.
Do not hardcode a daily schedule into worker code. Schedule persistence is
PostgreSQL-backed; select one maintained integration or narrowly scoped scheduler,
not a second parallel scheduling system.
