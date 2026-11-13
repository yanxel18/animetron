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
- **F-005: Authentication architecture remains undecided.** The draft permits
  either a trusted gateway or an identity provider. No authenticated session,
  CSRF defense, protected WebSocket, trusted-host policy, or authorized
  readiness endpoint exists. Security response headers do not provide these.
- **F-006: Byte-storage recovery remains incomplete.** On 2026-11-14 the owner
  approved a dedicated Linux service with a private Docker named volume, including
  the exception to project-directory-only storage for Docker-managed volumes.
  Native Windows byte storage remains unsupported. Internal byte publication and
  PostgreSQL metadata commits are not atomic; interruption can leave staged,
  double-linked or orphaned files. Explicit offline reconciliation, retention,
  aggregate quotas, media probing and coordinated backup/restore are still needed
  before exposing uploads/downloads or declaring Phase 0 complete.
