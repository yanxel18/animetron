# PR #33 required-review repairs

The owner requested these bounded same-PR repairs after review of
`0ecea006d54acb6d5cb0d72151b1a62c88ea3482`. No unrelated rebase, new ingress
rate policy, scan exclusion, waiver, approval or merge is authorized here.

## Ordered implementation / acceptance plan

1. **Fixture material:** generate test client/access/CSRF/bearer values at
   runtime; construct the unsigned negative-test header from public JSON.
   Generated RSA/HMAC keys remain generated. Prove a source-literal regression
   fails before correction and passes afterward. GitGuardian must succeed on
   the resulting head; do not print its matched values.
2. **Database reset authority:** a harness-created random capability, database
   marker and immutable owned-container identity must agree before every auth
   fixture reset, within the same transaction as deletion. Missing/foreign
   proof must fail loudly. Real owned-database tests must preserve a sentinel
   on rejected foreign/missing proof. No shared database is tested.
3. **Denial audit:** use PostgreSQL atomic shared counters for exactly
   `access_denied` and `login_failed`, with 96 fifteen-minute slots per kind
   (at most 192 rows), a twenty-four-hour window and owner-visible counts.
   No principal/origin/request-value cardinality enters counter keys.
   Preserve HTTP rejection and the existing 30-start login quota. Add an
   additive migration and real repeated-request, retention, slot-reuse and
   concurrency regressions; keep other audit history unchanged.
4. **Verification / publication:** run guarded PostgreSQL/Keycloak acceptance
   and quality gates, commit scoped increments with the required trailer,
   push the same PR, await GitGuardian success and ask the existing reviewer
   for same-task reassessment. Stop after at most three meaningful QA
   correction iterations if a blocker remains.

Database-authority verification precedes destructive database regression work.
The denial contract is additive to owner-only audit history: existing `data`
and cursor fields remain, with a bounded `denials` collection.

## Evidence

- GitGuardian check `132184402506`: failure; zero API annotations. Masked check
  output identifies `backend/tests/test_auth_api.py` and a generic high-entropy
  detection. Matched values were withheld.
- Source-literal fixture regression: **1 expected failure** before replacement.
- Fixture/ownership repair committed and pushed as
  `c3b7d9bb7b8bb36d8a70902dfc1b9c68d9c452ee`. Its scanner check
  `132201491115` still fails with zero annotations, the same file/category.
  No matched values are printed. The exact remaining detector location or
  historical-commit scope cannot be established from those annotations.
- GitHub reported `mergeable=false`, `mergeable_state=dirty`; only then was
  current master incorporated at `8f98ca3906a14b9f31b62d3ccbcfa89797725db5`,
  preserving both auth and master scheduling dependencies. No unrelated
  master implementation was edited.
- Real denial-growth regression: **1 expected failure, 17 passed** before fix.
- QA iteration 1: **283 passed, 20 skipped**, mypy 27 files; one import-format
  failure corrected. QA iteration 2: **314 passed, 20 skipped**, mypy 29 files;
  one guard-helper import-format failure corrected. Final iteration 3:
  **314 passed, 20 skipped**, Ruff app/tests/migrations and strict Linux mypy
  **29 files passed**. Auth selection: **70 tests**, including **3 live
  Keycloak/browser acceptance cases**. No assertions/tests were suppressed.
- `alembic upgrade head`, `check` (no new operations), downgrade to
  `0005_artifact_metadata`, and re-upgrade succeeded on the owned disposable
  database. Dependency audit after master incorporation: **no known
  vulnerabilities**; unpublished local backend package is not auditable.
- Harness cleanup removed its captured owned container IDs including anonymous
  volumes and network. Exact-name verification confirms absence of owned
  PostgreSQL, Keycloak and earlier port-probe containers and both owned networks.
  Only harness-created `data/oidc-test-temp` was removed after checking its
  worktree containment and refusal of reparse-point targets. Worktree venv retained.
- Final-head scanner and independent-review results remain required. No
  additional implementation/QA correction iteration is authorized after these
  three; a remaining scanner/reviewer issue must be handed off as a blocker.

## Deployment boundaries

The fixed-slot bound is a logical row/cardinality bound, not a guarantee about
PostgreSQL WAL, dead tuples or filesystem capacity. Vacuum/WAL/backup controls
remain deployment obligations. Legacy per-request denial records are preserved
until existing audit retention removes them; all workers must receive the new
code to stop legacy append behavior. No new public route or ingress rate policy
is introduced.
