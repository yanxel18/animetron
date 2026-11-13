# Development findings

This report records unresolved findings; implementation progress remains in
[todo.md](todo.md). Findings are not evidence of production readiness.

## Open

- **F-001: Execution is not ready.** Workflow snapshots do not pin handler
  implementations, configuration defaults or models; node dispatch and
  authenticated control APIs remain incomplete. Do not enqueue real work.
- **F-002: Model readiness is not established.** Identity, file hashes and
  manifest metadata do not authorize a download or establish license acceptance,
  repository allowlisting, secure file access, capacity or model readiness.
- **F-003: End-to-end acceptance remains outstanding.** Artifact storage,
  media generation, human decisions, official publishing, scheduler, studio
  and MCP are incomplete. Live model/provider use and final system acceptance
  require the relevant consent and owner involvement.
- **F-004: Specifications are not shared yet.** The current specification
  drafts are local and untracked; they need owner approval before adding them
  to version control.
