# Autonomous phase workflow

Implement the authorized work autonomously in verifiable slices, run appropriate
checks, fix failures, and continue to the next ready task. Use `tasks/todo.md`
as the project-wide scope and progress source. Ask the owner for a decision only
when the issue is complex and the AI cannot reasonably judge it, or when an
explicit external-action authorization or other essential information is needed.

For each completed task or slice, reconcile `tasks/todo.md` with the repository's
current default branch. Record the accomplished items, evidence, PR links and
remaining blockers, then recalculate the progress percentage and per-phase
counts using the tracker's stated counting method. Do this even if the
percentage remains unchanged.
Only mark items complete after merge and passing checks; keep open PRs unchecked
and in review.

For every task that changes the repository:

1. Work on a task-specific branch, not directly on the default branch.
2. Verify the change with appropriate checks; commit only task files with a
   descriptive subject and a body explaining the change and its purpose.
3. Push the branch and open a pull request with the problem, change, test
   evidence, limitations and integration dependencies. Target the repository's
   actual default branch (currently `master` for this repository; do not assume
   the branch is named `main`). For a stacked PR, make its dependency explicit
   and retarget it to the current default branch after its parent is merged.
4. Review the actual diff yourself for correctness, security, regressions and
   scope. Post a substantive self-review comment on the PR, including findings
   and unverified areas. Do not represent self-review as independent review or
   submit a misleading self-approval.
5. Resolve review findings, run the appropriate checks and merge to the current
   default branch without further owner approval when the change is ready.
   Respect branch protection and required checks; never bypass a protection or
   claim a failed or unrun check passed. If a required gate cannot be satisfied,
   leave the PR open, record the blocker and continue with independent work
   where possible.
6. Verify that the intended commit reached the default branch, update the
   tracker, and continue to the next ready task. Report PR links, merge status,
   checks and remaining blockers accurately.

The owner's 2026-11-22 instruction replaces the earlier requirement for an
independent human code review before routine merges. Historical review records
remain factual and are not retroactively reclassified. This development policy
does not authorize deployment, live publishing, model licenses or downloads,
or external transmission, and does not remove product-level human approval of
content. Follow the applicable external-action and acceptance gates in
`tasks/todo.md`. If a step cannot be completed, report the blocker and the
steps completed rather than claiming success.
