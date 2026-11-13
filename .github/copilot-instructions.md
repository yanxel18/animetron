# Git workflow

For every task that changes the repository:

1. Work on a task-specific branch, not directly on `master`.
2. Verify the changes with appropriate checks, and commit only files belonging to the task.
3. Push the branch to the remote.
4. Open a pull request targeting `master`, or update the existing pull request for the task.
5. Report the pull request link and verification results to the user.

Do not merge the pull request; the user will merge it. Respect explicit instructions to skip or change this workflow. If a step cannot be completed, report the blocker and the steps completed rather than claiming success.
