## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.

## Git and GitHub workflow

- Make repository changes on a task-specific branch, never directly on the
  default branch.
- After pushing a task branch, open a pull request to the repository's actual
  default branch. The default branch for this repository is currently
  `master`; verify it if the repository configuration changes. Do not assume
  it is named `main`.
- Before merging, inspect the complete diff and post a substantive self-review
  on the pull request. State findings and unverified areas; do not call a
  self-review an independent review or self-approve.
- Run the appropriate checks, address review findings, and merge the pull
  request only when required checks pass and branch protection allows it. Never
  bypass protections or claim an unrun check passed. The owner has authorized
  routine PR self-review and merge without waiting for a separate human review.
- After merge, verify the commit reached the default branch, update
  `tasks/todo.md` with the PR and check evidence, and report remaining limits.
- This workflow does not authorize deployment, live publishing, model downloads
  or license acceptance, or external transmission. Keep product-level content
  approval gates in place.
