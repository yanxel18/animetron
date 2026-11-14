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

Policy approved by the owner on November 14, 2026:

- Five-field cron: minute, hour, day of month, month, weekday. Use explicit IANA
  time zones and standard day-of-month OR weekday matching.
- Skip overlapping GPU generation and missed occurrences on restart, with no
  catch-up burst. Skipped slots remain observable and audited.
- Skip a nonexistent local time during spring-forward. For an ambiguous local
  time during fall-back, fire once at its earlier occurrence.
- Preview and dispatch use the same persisted local-slot identity. A schedule
  never grants publication approval.

The maintained croniter library documents OR matching, optional AND behavior,
and timezone-aware iteration; it also supports additional second/year fields.
Those extensions are outside this approved five-field policy. Its documentation
does not establish the exact approved gap/fold behavior. Verify the selected
version with real time-zone boundary cases and enforce the approved policy
rather than silently adopting library defaults.

The first implementation slice supplies internal next-five preview only:
`app.services.scheduling.preview.preview_occurrences`. It uses croniter 7.0.0
wall-clock candidates and explicit `zoneinfo` UTC round-trips, choosing fold 0.
Its POSIX-style syntax accepts numeric lists/ranges/steps, wildcards and
three-letter month/weekday names; croniter-specific macros, hashed/random,
`L`/`W`/`#`, seconds and years are outside this interface. A bounded
50-calendar-year search fails explicitly rather than returning partial results.
An offset-bearing local time, UTC due time and zone/wall-clock slot key are
returned. Future persistence/dispatch must reuse this calculation and namespace
slot keys by schedule identity. No authorized preview endpoint or persisted
dispatch exists yet. [Implementation findings](../tasks/scheduling-preview-report.md).

P6-02b adds internal schedule descriptors only. Enabled records calculate
`nextDueAt` from an explicitly supplied aware cursor using the same preview;
paused records store no next due time. Resume recalculates strictly after its
cursor without catch-up. Version-checked edits bind an existing immutable
workflow revision and leave existing runs unchanged. The stored overlap and
missed-run descriptors are `skip`, not an implementation of dispatch,
arbitration, slot identity, restart recovery, or skipped-slot audit.

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

## Scheduling evidence

[Maintainer README](https://github.com/pallets-eco/croniter#about-dst), checked
November 14, 2026. The day-of-month/day-of-week documentation states that
restricted fields use OR by default. DST iteration requires a timezone-aware
base. No croniter version pin or scheduler implementation is approved merely
by citing this page; selection and tests must substantiate the policy above.
