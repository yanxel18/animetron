# P1-08a internal execution snapshot values

## Scope and exact core

- Worktree: `D:\animetron\.worktrees\workflow-execution-pins`.
- Branch: `feature/workflow-execution-pins`.
- Base: `d5f7f43e3ccaafdc2f4b24dc294633158c29bf69` (#48).
- Tested implementation core: `bad060a85ce66cf651b1b04eea63a5f8f30bbd12`.
- Core changes only the new workflow value module, one new focused test file,
  the existing workflow spec and backend README. The internal contract was
  written before implementation. This report is a separate evidence commit.
- The parent's dirty `todo.md`, `development-report.md` and
  `run-request-records-report.md` were read, never edited/staged/committed.
  No root/shared code, dependencies, migrations or harness files changed.

## Delivered contract

`create_execution_snapshot(data, catalog, limits, max_bytes=...)` accepts only
the existing v1 graph document plus a trusted backend-selected typed catalog.
Each `ExecutionNodeDefinition` supplies a `NodeDefinition`, an opaque bounded
`HandlerArtifact` ID/exact SHA-256 and a tuple of existing `ModelManifest` values.
It returns a distinct frozen `ExecutionSnapshot` containing only canonical
bytes; its SHA-256 is derived from those bytes.

The graph/revision, materialized configuration, per-node exact handler identity,
and full model reference/engine/license/files/estimate values are all included
in the canonical digest. Explicit model-less pins carry an empty manifest list.
Backend Pydantic models validate strict types with extras forbidden; materialized
nested defaults are validated again using field names. Serialization aliases
apply consistently, including validation-alias choices/paths. Explicit value
transformations fail rather than silently changing supplied values. Actual
model fields are serialized, so excluded fields/custom serializers cannot
conceal non-JSON or non-finite defaults. Only finite JSON-native values survive.
Input and expanded canonical output are independently bounded by exact bytes.

The legacy create/parse/save/run implementation files are unchanged. New bytes
are distinguished by their internal kind and cannot be parsed as legacy v1
documents. No legacy snapshot is automatically promoted.

**Trust/limits:** selected catalogs, validators and default factories are
trusted backend code, required to be deterministic and side-effect free.
This is not a sandbox, authorization or proof of installed handler artifacts.
Future runtime enforcement must verify installed artifact identity and model
readiness. No decoder/runtime loader, generic registry, HTTP/auth, DB binding,
node intents, migration, dynamic imports, network/downloads, model readiness,
GPU or external effects were added. Durable binding and enforcement remain
subsequent P1-08 work; the parent checklist remains untouched and unchecked.

## Verification

All Python commands used:

```powershell
$py = 'D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe'
Set-Location D:\animetron\.worktrees\workflow-execution-pins\backend
$env:PYTHONPATH = (Get-Location).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONTZPATH = ''
$env:MYPY_CACHE_DIR = 'D:\animetron\.worktrees\workflow-execution-pins\data\execution-pins-mypy'
$env:PYTEST_ADDOPTS = '-p no:cacheprovider'
```

Pure tests removed inherited `ANIMETRON_*` variables. Full harness invocations
used its existing environment stripping and DB ownership marker/capability
checks, sequentially, with cached images and its existing `--pull=never`.
No dependency was installed.

| Command / check | Result |
| --- | --- |
| `& $py -m pytest tests/test_execution_snapshot.py::test_materializes_defaults_and_pins_full_metadata -q -p no:cacheprovider` | Genuine RED: 1 failed at builder `NotImplementedError` |
| `& $py -m pytest tests/test_execution_snapshot.py -k 'normalization or bytearray' -q -p no:cacheprovider` | Genuine additional RED: 2 failed, missing rejection |
| `& $py -m pytest tests/test_execution_snapshot.py tests/test_workflow_snapshot.py tests/test_workflow_document.py -q -p no:cacheprovider` | Early GREEN: 66 passed |
| `& $py -m pytest tests/test_execution_snapshot.py tests/test_workflow_snapshot.py tests/test_workflow_document.py tests/test_workflow_runtime.py -q -p no:cacheprovider` | Preservation-fix GREEN: 99 passed |
| `& $py -m pytest tests/test_execution_snapshot.py -q -p no:cacheprovider` | Completed focused suite: 53 passed |
| `& $py tests/run_auth_checks.py` | Final: **536 passed, 20 skipped**, 47.44s; exit 0 |
| Harness `ruff check --no-cache app tests migrations` | Passed |
| Harness `mypy --platform linux app` | Strict: passed, **39 source files** |
| Harness Alembic upgrade/check and downgrade to `0005_artifact_metadata`/reupgrade | Passed; unchanged migration head, no new upgrade operations |
| `& $py -m pip check` | No broken requirements found |
| `git diff --cached --check`, scoped source/spec/test/secret review | Passed |

The 20 skips are the existing Windows-inapplicable Linux filesystem cases;
no new test skips or weakened assertions/checks were introduced. The completed
53 new cases account exactly for the increase from the known 483-pass base.
They cover default drift, exact explicit values, aliases/nested defaults,
strict extras/type checks, unsafe defaults, every serialized model field,
handler identity drift, caller mutation, all-node pins, legacy compatibility
and exact input/output caps including Unicode/default expansion.

Three correction groups: initial mistyped legacy test filename/import order;
the test-proven explicit-normalization and mutable-bytearray rejection gaps;
and the expanded Pydantic import formatting. The first full run passed all
536 tests and strict mypy but failed Ruff on that final formatting issue.
After correction, the complete owned harness passed. No blocker remains.

### Mutation evidence

1. Replaced output check `len(encoded) > max_bytes` with
   `len(encoded) > max_bytes + 1`.
   `test_exact_output_byte_boundary_includes_default_and_unicode_expansion`
   failed: **1 failed**, missing the expected byte-limit exception.
2. Restored the cap and replaced the serialized handler SHA with a constant.
   `test_handler_artifact_identity_is_digest_bound` produced
   **1 failed, 1 passed**: digest drift was no longer bound.
3. Restored exact source before the full harness. SHA-256 before mutations,
   after restoration and at final verification matched:
   `7c2fb1f16ffd26b824e3d92b064639c7684cd41aec1ff598bec05200b063ffa0`.

Final test-file SHA-256:
`70c40daa729c084b152603750abb66168ea71d4dade78d32459d0f44da5ec9f5`.

## Resource cleanup and unchanged baselines

Both harness runs were wrapped with in-memory file hashes and Docker inventory
comparisons, plus live capture of owned container IDs, volumes and network IDs.
The harness removed resources by captured identity. All captured IDs below
were confirmed absent afterward, and Docker inventories returned exactly to
the baseline: **4 containers, 4 networks, 78 volumes**.

| Run | PostgreSQL container | Keycloak container |
| --- | --- | --- |
| First | `5697a8a81ca8274e482be7e8c5e6c00bf3270b55ec0e916b6bf269e65ae1c1d6` | `127f7e427308d76a0b166024ea13814c7b1cb46cf76b1480667fa6d3a0a57f05` |
| Final | `bde280421074327a14edfac32c9b52178b6ac7f4b9d2eceea9d720e5e6d99a21` | `b78a3aff518d06b5b2d995914772824d0529151d32cbed0936ff2f2c3dc5aab2` |

- First network: `a97567f78891ae3079083f8a5ad0715a0eedf14575a816b079e9a20979113603`.
- First volume: `9417ec4fe8f60d35a9feddda230a5bb0212d41ae1e0d3b0b9dc211304eea1549`.
- Final network: `2a10acc3a7c100a3a86e3889769af26c22bb69ac4d040f76d663e85dd37e75f6`.
- Final volume: `97bf5e415c61101d42ddcdfb46cae186e039acf3464d1991859cea91374dea80`.
- Cached PostgreSQL image:
  `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`.
- Cached Keycloak image:
  `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.

All **132 root baseline files** (tracked files plus the pre-existing untracked
`tasks/findings.md`) and **133 final target baseline files** (tracked plus the
new source/test) were hash-identical across the final harness. The root
aggregate hash also matched the first run:
`f8725064c93c6882c6a00907f79ef3a1d68d83d5543d8f2b34489159492efc5d`.

Parent-owned dirty target file SHA-256 values matched initial/final readings:

- `tasks/todo.md`: `42ceed1b476c58e9a35d127b05b84f05ba55005b7602bb258704e1451d20e830`.
- `tasks/development-report.md`: `ddcf0ee20c9e56c82affe59e7d8cede2a395c899fbd7b253d4cc102c12952840`.
- `tasks/run-request-records-report.md`: `40d312dca70e7d0b9ef66bc4484796dd489db4a10c45bea17988294b89c5ce64`.

Only the worktree-local generated `data/execution-pins-mypy` and
`data/oidc-test-temp` directories were deleted; both were verified absent.
No unrelated container, volume, process, shared venv or global setting changed.
No push, PR, merge or remote publication was performed.
