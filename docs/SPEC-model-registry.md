# Spec: model-registry

Status: Approved for implementation on November 14, 2026.
Depends on: platform-core.

## Objective

Resolve local models safely and reproducibly without equating a nonempty folder
with readiness or silently starting multi-gigabyte startup downloads.

## Commands and structure

Inherit [shared commands and layout](SPECIFICATIONS.md).
Focused verification: `python -m pytest tests/test_model_registry.py -q`.
Ownership: `app/services/models`, `app/engines/model_downloader`, model metadata.

## Code style and provider contracts

Inherit shared style. `ModelManifest` identifies provider/repository, immutable
revision, expected files/integrity metadata, compatible engine, license/access
status and estimated storage requirements.

- `GET /api/v1/models`: paginated manifests and readiness.
- `POST /api/v1/models/{id}/downloads`: confirmed acquisition intent; 202 + job id.
- `GET /api/v1/model-downloads/{id}`: status, bytes and actionable failures.
- Internal `resolveReadyModel(modelId, revision)`: ready local handle or typed
  readiness failure; never a fallback model.

States: MISSING, BLOCKED_LICENSE, BLOCKED_ACCESS, QUEUED, DOWNLOADING, VERIFYING,
READY, FAILED. Workflow-triggered automatic acquisition is allowed only for
previously accepted, pinned manifests within resource limits.

## Testing and acceptance criteria

1. Concurrent requests for one revision produce one acquisition; downloads use
   staging and atomic readiness transitions after verification.
2. Interrupted, corrupt, inaccessible or disk-constrained downloads remain
   explicitly non-ready and can resume or fail with a visible reason.
3. Registry keys include provider/repository/revision, so repositories with the
   same final path segment cannot collide. Workflow snapshots pin the model.

## Boundaries

Inherit shared boundaries. No arbitrary repository URL, remote-code execution
or pickle-based unsafe loading. Prefer safe formats, allowlisted repositories
and trusted reviewed ComfyUI nodes. Credentials stay server-side. License
acceptance and restricted model access are never inferred from an HF token.
