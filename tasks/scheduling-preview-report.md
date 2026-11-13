# Schedule preview findings - 2026-11-14

Scope: P6-02a internal next-five calculation only, not complete scheduling.
Baseline reconciled against master `9019044`, including merged approval
records #30/#31 and scoped model consent/foundation verification #32.
Implementation merged in [#35](https://github.com/yanxel18/animetron/pull/35)
after direct complete source/test review and successful GitGuardian checks.
Only this internal preview slice is complete; scheduling remains unfinished.

## Verified behavior

- Exactly five strictly future, offset-bearing local times with UTC due times
  and deterministic zone/local-minute identities.
- Approved five-field OR matching, including a valid weekday despite an
  impossible restricted day/month combination.
- Spring-forward gaps skipped, earlier fall-back occurrence once, and no
  offering an already missed earlier occurrence from inside the repeated hour.
- Non-hour Lord Howe transitions, Apia's skipped calendar date, Kathmandu's
  fractional UTC offset and leap days across the non-leap century 2100.
- Invalid/unapproved cron, impossible dates, non-IANA zones and naive cursors
  fail explicitly. No schedule or publication side effects exist.

## Verification

- RED: focused test import failed before the implementation existed.
- Initial focused run: 24 passed; one additional OR edge case was added during
  review. Repository formatter corrected import ordering and a literal-list
  simplification without suppressing checks.
- Mutation experiment: selecting fold 1 instead of fold 0 caused four of six
  selected boundary cases to fail. The mutation was immediately restored.
- Final native suite: **187 passed, 77 skipped**. The unchanged skips require
  PostgreSQL or Linux byte-storage environments, not weakened tests. Their
  separate earlier checks are recorded in [development-report.md](development-report.md).
- Ruff over application/tests/migrations passed; formatting check passed;
  strict Linux-target mypy passed for **25 source files**; `pip check` passed.
- Used a fresh project-contained virtual environment, binary-only dependency
  downloads and project-contained pip/temp/type-check caches. The shared root
  environment was not modified. No containers or background processes were
  created for this task.

## Dependency and implementation findings

Croniter **7.0.0** is maintained by Pallets-Eco and its
[pinned README](https://github.com/pallets-eco/croniter/blob/7.0.0/README.rst)
documents `day_or`, iteration and search bounds. Its
[license](https://github.com/pallets-eco/croniter/blob/7.0.0/LICENSE) is MIT.
Types-croniter **6.2.4.20261006** covers the stable interfaces used here and
strict checking passed. Time-zone fallback data is pinned to **2026.6**.
Its [source license](https://github.com/python/tzdata/blob/2026.6/LICENSE)
is Apache-2.0.
Public PyPI metadata reported no advisories for the selected croniter/tzdata
versions; this is not a whole-environment vulnerability audit.

Do not replace the explicit gap/fold policy with timezone-aware croniter
iteration. Do not enable strict day/month cross-validation that rejects valid
OR weekday matches. The preview rejects extra croniter syntax rather than
silently widening the owner's approved policy.

ZoneInfo prefers host tzdb unless `PYTHONTZPATH=""` selects the pinned package.
Tests used that process-local setting; scheduler replicas must use consistent
time-zone data. A 50-calendar-year preview search limit fails loudly and is a
computational bound, not permission to catch up missed runs.

## Still required

Authorized CRUD/preview endpoints, immutable revision ownership, persisted
schedule/slot uniqueness and atomic run-intent/outbox creation, pause/resume,
overlap, restart/missed-slot observability and Beat integration remain open.
An in-memory slot key cannot prove duplicate dispatch prevention.
Neither P6 nor P9 is complete; generation licenses, real providers, recovery
and owner-involved narrated-reel/system acceptance remain separate gates.
