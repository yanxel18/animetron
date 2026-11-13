# Spec: platform-core

Status: Approved for implementation on November 14, 2026. Depends on: none.

## Objective

Provide an authenticated, durable local control plane with PostgreSQL as source
of truth and filesystem artifacts addressed by opaque ids.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_platform_core.py -q`.
Primary ownership: `app/core`, `app/models`, `app/api`, `migrations`.

## Code style and provider contracts

Inherit [shared code style](SPECIFICATIONS.md).
Provide authenticated principal, artifact metadata and transactional outbox
contracts. Artifact metadata includes id, hash, media type, byte size, owner,
revision and relative internal storage location.

- `GET /api/v1/health`: minimal liveness without secrets.
- `GET /api/v1/readiness`: authorized dependency/resource readiness.
- `POST /api/v1/artifacts`: bounded streaming upload with generated names.
- `GET /api/v1/artifacts/{id}`: authorized metadata.
- `GET /api/v1/artifacts/{id}/content`: authorized bounded/range-capable delivery.
- `GET /api/v1/audit-events`: authorized paginated audit history.

For initial access, use authenticated sessions via one gateway or maintained
identity provider integration; reject spoofed identity headers outside the
trusted gateway. Use HttpOnly/SameSite cookies and CSRF defense for mutations.
WebSocket handshakes require the same principal and allowed-origin checks.

The owner selected a maintained identity-provider integration on November 14,
2026 and delegated provider selection. Custom password authentication is not
the selected approach. Provider configuration and real session acceptance must
be verified before authenticated readiness is claimed.

## Testing and acceptance criteria

1. Unauthenticated access to control data and artifact content is rejected.
   Secrets are absent from audit records, errors, logs and workflow exports.
2. Traversal names, deceptive extensions, unsupported signatures, oversized
   uploads and resource-exhausting media are rejected before becoming usable.
3. Transactional state/outbox records survive service restart; backup and restore
   recover metadata plus referenced artifacts with matching hashes.

## Boundaries

Inherit shared boundaries. Keep gateway loopback-bound by default; database,
Redis and inference services are private. Run untrusted media probing/rendering
under restricted privileges and bounded CPU/memory/time, without shell expansion.
Retention must respect referenced run/review/publication artifacts and offer
preview plus explicit confirmation before deletion.
