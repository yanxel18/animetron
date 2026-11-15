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
slot keys by schedule identity. No persisted dispatch exists yet.
[Implementation findings](../tasks/scheduling-preview-report.md).

P6-02b adds internal schedule descriptors only. Enabled records calculate
`nextDueAt` from an explicitly supplied aware cursor using the same preview;
paused records store no next due time. Resume recalculates strictly after its
cursor without catch-up. Version-checked edits bind an existing immutable
workflow revision and leave existing runs unchanged. The stored overlap and
missed-run descriptors are `skip`, not an implementation of dispatch,
arbitration, slot identity, restart recovery, or skipped-slot audit.

### P6-02c HTTP descriptor contract

All endpoints require a fresh opaque owner session on every request. Mutations
and previews additionally require the exact configured Origin and CSRF token;
the existing origin, security-header and error-envelope rules apply. Missing
auth configuration or persistence fails closed. Inputs are strict camelCase,
reject unknown fields, and JSON request bodies are limited to 4096 bytes.

- `POST /api/v1/schedules` creates a UUID4 descriptor and returns 201.
- `GET /api/v1/schedules/{id}` reads a descriptor.
- `GET /api/v1/schedules?limit=50&cursor=<uuid4>` returns `data` and
  `nextCursor`, ordered by UUID with an exclusive cursor. Limit is 1–100.
  A full page supplies a cursor even if the following page is empty.
- `PUT /api/v1/schedules/{id}` replaces the descriptor using `expectedVersion`.
  Pause and resume are versioned replacements, not deletion.
- `POST /api/v1/schedules/{id}/previews` returns `occurrences`, exactly five
  `localTime`, `dueAt`, and `slotKey` values from the existing preview logic.
  Its body is `{}` or `{"after":"<offset-bearing ISO datetime>"}`. If omitted,
  `after` uses the database clock. An explicit historical cursor is permitted
  for preview only; it does not change the descriptor or create work.
  Authentication can still update the session's last-seen timestamp.

Create and replacement bodies require `workflowId`, `revision`, `expression`,
`timeZone`, `enabled`, `overlapPolicy`, and `missedRunPolicy`; policies must
both explicitly be `skip`. Responses contain those fields plus `id`,
`nextDueAt`, `version`, `createdAt`, and `updatedAt`. The immutable revision
must already exist. Create and replacement use PostgreSQL's advancing
`clock_timestamp()` as the calculation cursor; no write accepts a client
cursor. Create is not idempotent and must not be blindly retried.

Unknown or repeated query parameters are rejected. Invalid IDs, queries or
inputs yield 422; absent schedules or revisions 404;
version collisions 409; missing sessions 401; forbidden role/origin/CSRF 403;
unavailable auth/persistence 503. No endpoint dispatches, creates a run or
outbox intent, or grants approval. P6-02 remains incomplete until dispatch.

### P6-02d internal durable observation contract

`app.services.scheduling.due_slots` is a narrow caller-transactional ledger,
not a scheduler or an execution/admission claim:

- `record_due_slot(connection, schedule_id, expected_version=...,
  occurrence=ScheduleOccurrence(...))` records one **observed cron candidate**.
  It does not assert that the candidate is now due, enabled, dispatched,
  skipped, completed, or eligible for GPU/model/publishing work. Historical or
  future candidates and paused descriptors can be observed; this operation
  neither advances `nextDueAt` nor changes any descriptor.
- Identity is the PostgreSQL composite primary key `(schedule_id, slot_key)`.
  The key is exactly the existing preview's IANA-zone/local-minute key, not
  UTC, a random attempt ID, descriptor version, or workflow revision.
  Different schedules may observe the same local key independently.
- Before a first insert, lock the descriptor against concurrent edits, require
  its current version, validate the candidate using the existing preview
  calculation (including gap skip/earlier fold/OR matching), integrity-check
  the referenced workflow revision, and bind `schedule_version`, `workflow_id`,
  `revision`, UTC `due_at`, and database `created_at`. Offset-equivalent due
  instants are normalized to UTC. `local_time` must match preview including its
  offset; it is not separately persisted because the key and due time bind it.
- Exact replay returns the original frozen record, including its timestamp,
  even after descriptor edits, revision changes, or pause. The same identity
  with a different expected version or due instant raises `DueSlotConflict`;
  it never rebinds or repairs the row. An inconsistent local-time representation
  raises `ValueError`. New observations with a stale version also conflict.
  Missing descriptors/records raise `ScheduleNotFound`/`DueSlotNotFound`.
- `get_due_slot(connection, schedule_id, slot_key)` reads one observation.
  There is no HTTP exposure, background process, scan loop, retention purge,
  run/outbox creation, or transition/skip API. No reason/status field is
  fabricated: missed and GPU-overlap reasons require actual scheduler decisions
  and remain unimplemented. An observation must never be treated as proof that
  a slot has already been handled; future dispatch needs a separate atomic
  decision/run-intent/outbox contract.
- Writers require an explicit non-autocommit psycopg PostgreSQL transaction.
  They do not commit, roll back, retry, or open independent transactions.
  Concurrent observers serialize on the descriptor; the unique key also
  arbitrates independent inserts. In READ COMMITTED, an in-flight duplicate
  waits for the transaction to resolve: committed matches replay, rolled-back
  writes leave no observation. Higher-isolation serialization failures,
  deadlocks, lock/statement timeouts and uncertain commit results propagate;
  the caller must resolve/retry the **whole** transaction with the same intent.
  Callers must set bounded transaction/lock/statement budgets.
- Migration `p6_02d_due_slots` is additive after
  `p1_09c_workflow_revision_list`. Foreign keys prevent orphan schedules and
  revisions; an UPDATE/DELETE trigger protects identity, binding and timestamp.
  The service validates historical descriptor association under lock; the
  database does not reconstruct past descriptor versions or verify cron syntax
  for arbitrary direct SQL inserts. Only trusted internal persistence callers
  may insert; no new role/grant or bypass of existing authorization is provided.
  Privileged DDL/TRUNCATE can defeat retention and is outside this contract.
  There is no TTL: removing identity would permit later duplicates. Downgrade
  drops this evidence and requires explicit authorization/recovery planning on
  a populated deployment; rolling back application code can leave the table.

The stored fields are internal scheduling metadata, with no prompt, personal
data, arbitrary reason text, credential, model acceptance or publication
authority. PostgreSQL unique/FK/check/immutable guards, actual lock races,
rollback, preview validation and migration/metadata consistency are covered by
`tests/test_due_slots.py`. P6-02/P6-03 and durable skipped-slot observability
remain incomplete; this ledger establishes no exactly-once run or readiness.

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
