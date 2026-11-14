# Auth/review integration findings - 2026-11-14

Status: locally repaired and verified; pushed to `origin`, but not opened as a
PR, independently reviewed or merged. Branch:
`fix/auth-review-migration-integration`.

## Remote reconciliation

The owner's merge of #33 is present in `origin/master` at
`c39d4851dda89c9aa07f617a7e6d90a62a0eb371`. Root master was fast-forwarded
with autostash; its pre-existing report edit and empty findings file remain.
The assistant did not perform this merge.

Read-only GitHub REST verification found one final-head check at
`8b8a63277084d1ca962067af25bf5c2ac9e759a1`:
GitGuardian Security Checks, completed/failure. There were zero commit-status
entries. No matched secret or credential-file contents were read. A merged
PR is not evidence that this scanner finding was resolved.

## Reproduced integration defects

1. `alembic heads` returned independent auth and review heads, so the ordinary
   `upgrade head` path was ambiguous. The new migration graph regression
   failed before correction.
2. Merge resolution retained the review metadata import but replaced its
   target-list entry with auth metadata. After joining the heads, the owned
   disposable database harness's `alembic check` reported removal of both
   review tables and their index. No destructive generated migration was
   applied.

The repair restores both metadata collections and adds the Alembic-generated
`0008_auth_review_merge` revision with no schema operations. Original
migrations and existing table data are not rewritten.

## Verification

Using the existing auth-worktree interpreter, with task-backend PYTHONPATH:

- Full owned PostgreSQL/Keycloak/browser harness: **330 passed, 20 unchanged
  Windows skips**, including both migration regressions.
- Fresh upgrade/check, downgrade to `0005_artifact_metadata`, and re-upgrade
  succeeded. Offline migrations remain unsupported.
- Strict Linux-target mypy: **30 source files passed**.
- Generated migration lint initially failed. Ruff's scoped automatic fixes
  and formatting resolved it; full app/tests/migrations lint then passed.
- Post-format graph regression: **1 passed, 1 database case skipped** outside
  the harness; that database case passed in the full harness above.
- Dependency consistency and whitespace checks passed.

No new dependencies, model downloads, publishing or deployment occurred.
The harness removed its captured task-owned PostgreSQL and Keycloak containers
and network. Exact-name container query confirmed no matching containers.

## Remaining blockers

The GitGuardian finding needs finding-level triage, not another speculative
fixture edit or scan exclusion. This repair has no independent review or
remote checks. The branch was pushed with the owner's source-control
authorization. PR creation and remote review verification are blocked in this
session: GitHub MCP returned 404/422 and the integrated browser is signed out
and returns 404.

Schedule persistence remains verified only on local `feature/schedule-records`
at `52b2b491dba50849d7f246fa5c3906dbecac24f9`; its integration depends on this
repair. Model capacity, live-provider authorization, recovery and owner-involved
P9 acceptance remain incomplete. Local tests do not certify the entire system.
