# P6-02c scheduling HTTP findings

Base: `b008e1c5c6d037c48a2fdacc346a820becf11028` (master / #46).
The approved scheduling specification now defines this bounded descriptor and
preview API. P6-02 is still incomplete: there is no dispatch or scheduler.

## Implementation

- Owner-only create, get, UUID-keyset list, full version-checked replacement
  and next-five preview use the existing authentication, descriptor store and
  preview calculation. The advancing PostgreSQL clock is used for writes.
- JSON bodies are capped at 4096 bytes by the minimally extracted review
  route guard; review-specific error codes and protections remain unchanged.
- Explicit preview cursors may be historical, but never alter scheduling state.
  Session authentication can update last-seen even on a preview.
- No delete, due-slot processing, run/outbox intent, GPU work or approval was
  introduced. Creation is not idempotent.

## Verification

- Interpreter: `D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe`;
  `app.__file__` resolved inside this worktree's `backend\app`. Used this backend
  as `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONTZPATH=''` and a
  disposable project-local mypy cache.
- Initial no-database RED: new routes returned 404 rather than fail-closed 503.
  Focused owned-database GREEN: 8 passed. A later year-1 preview regression
  reproduced `OverflowError` before the adapter returned 422 for it.
- Final `tests/run_auth_checks.py`: **450 passed, 20 skipped** (the existing
  Windows skips require Linux/POSIX artifact storage); Ruff clean, strict
  Linux-target mypy clean (37 source files), Alembic upgrade/check and
  downgrade/upgrade completed. `pip check` reported no broken requirements.
- A process-local mutation raising the scheduling body cap to 8192 was caught by
  the real fragmented ASGI streaming regression (1 expected failure, 3 passes).
  Existing review guards and extreme decimal lengths were exercised.
- The harness used `--pull=never`: PostgreSQL image
  `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`
  and Keycloak image
  `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.
  The harness removed its captured owned containers, anonymous volumes and
  network; their exact names were absent afterward. Only the verified
  worktree-local test temp and mypy cache directories were removed.

No independent review, production performance/SLO verification, dispatch or
Linux-only artifact coverage is claimed. No packages were installed, no shared
settings changed, and no push, PR or merge was performed.

## Independent final checkpoint

Independent QA verified HEAD `455296d41e17c7602c734b6d74ad9ffabc1795e0`
against base `b008e1c`. Full owned harness: **450 passed, 20 skipped**,
including all 8 scheduling and 34 review API cases, real fragmented ASGI
stream boundaries, PostgreSQL descriptor/security/DST parity, and existing
actual lock-expiry regressions. Ruff, strict Linux-target mypy (37 files),
migration upgrade/check/downgrade/re-upgrade and `pip check` passed.
Without database infrastructure: **5 passed, 3 skipped**.

An in-memory wrapper changed only pytest verbosity and captured resource
identities; checked-in harness/source and ownership guards were unchanged.
Imports resolved to this worktree and cached images used `--pull=never`.
Captured PostgreSQL/Keycloak containers, network and anonymous volume were
identity-checked and confirmed removed. Baseline Docker inventories and all
127 baseline files were unchanged, including parent documentation edits.
Only newly created project-local test/cache directories were removed.

Direct source review found no required correction. No formal GitHub approval
is implied; remote checks and merge are pending at this checkpoint. Dispatch,
P6 completion, live scheduling and full P9 remain excluded.
