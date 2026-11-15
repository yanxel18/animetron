# Autonomous phase workflow

Complete the in-scope work for an entire phase autonomously in one continuous
run. Implement each task, run its checks, fix failures, and continue to the next
task without waiting for earlier pull requests to be merged or closed. Use
`tasks/todo.md` as the project-wide scope and progress source. Stop only when a
required specification approval, external-action authorization, or genuine
blocker prevents safe progress.

For each completed task or slice, reconcile `tasks/todo.md` with `master`,
record the accomplished items, evidence, PR links and remaining blockers, and
recalculate the progress percentage and per-phase counts using the tracker's
stated counting method. Do this even if the percentage remains unchanged.
Only mark items complete after merge and passing checks; keep open PRs unchecked
and in review.

For every task that changes the repository:

1. Work on a task-specific branch, not directly on `master`.
2. Verify the changes with appropriate checks, and commit only files belonging
   to the task.
3. Push the branch to the remote.
4. Open a separate pull request targeting `master` for each task, or update
   that task's existing pull request. If a task depends on changes in an
   unmerged pull request, base its branch on the appropriate prior branch and
   make the dependency clear.
5. Continue with the next task while pull requests remain open.
6. The owner has authorized the assistant to merge reviewed, verified pull
   requests without additional owner approval. Merge only after all required
   independent reviews and checks pass; never approve your own pull request,
   bypass branch protections, or waive required checks. If the required gates
   cannot be satisfied, leave the pull request open and report the blocker.
7. Report pull request link(s), merge status, verification results, and any
   blockers to the user.

Autonomous implementation and pull request handling do not waive specification
approval or authorize deployment, live publishing, model licenses or downloads,
or external transmission. Follow the approval and external-action gates in
`tasks/todo.md`. If a step cannot be completed, report the blocker and the
steps completed rather than claiming success.
