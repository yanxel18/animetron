# P1-08b execution revision binding

- Base: `65bd2daff2483ed214c62bc0e403c734ad3c1b4d`; branch:
  `feature/execution-revision-bindings`.
- Added a checked, immutable, uniquely claimed execution binding; no run,
  outbox, runtime, authorization, model acquisition or legacy API changes.
  P1-08 remains incomplete until runtime enforcement.
- PostgreSQL RED: first run had 25 missing-module setup errors; with an explicit
  unimplemented function, 24 failed and 1 passed. Final focused run: 30 passed.
- Removing the execution digest comparison caused
  `test_corrupt_binding_fails_without_repair[execution_sha256]` to fail:
  1 failed, 27 passed. The original source was restored.
- Final full owned PostgreSQL/Keycloak harness: 583 passed, 20 Windows skips;
  Ruff passed; Linux-target mypy passed (40 files); Alembic upgrade/check and
  downgrade/reupgrade passed. `python -m pip check`: no broken requirements.
- From `backend`, with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONTZPATH=''`,
  `PYTHONPATH` set to the target backend, and `MYPY_CACHE_DIR` under the target
  worktree `data/oidc-test-temp`, commands were:
  `D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe tests/run_auth_checks.py --storage --pytest-file tests/test_execution_bindings.py`,
  the same command with the digest check temporarily removed, and
  `D:\animetron\.worktrees\oidc-auth\backend\.venv\Scripts\python.exe tests/run_auth_checks.py`.
  The harness strips inherited application/proxy settings, uses capability
  markers and cached images with `--pull=never`; no raw database URL was used.
- Docker inventory returned to baseline (4 containers, 4 networks, 78 volumes).
  Every captured resource below was verified absent. No Keycloak volume was
  attached. The initially absent `data/oidc-test-temp` and its empty `data`
  parent were removed after path and reparse-point checks. Other resources and
  the three parent-owned task files were not cleaned, edited or staged.

## Captured harness ownership and resources

Each row records owner label, network ID, PostgreSQL container ID, volume ID,
and optional Keycloak container ID; all IDs are full length.

| Owner | Network | PostgreSQL | Volume | Keycloak |
|---|---|---|---|---|
| ddf6e0e464a6cb4ad89094ddffd10940 | 7343cb1707cd96afa73aff50111b222181f4cb21e07f054e84f3ee2023a3fbb0 | d5fbac68ddb591866332f802b90e724eed50a6dbf1f3d147b87657fc87392e22 | 564602072abd34a0da33e1532afb43fe31618bba0de4d5e5f6fc2ad80113647b | — |
| f25a6cea0812eb04376f064726043a89 | aebfd5013421e39b636c0f77227b78c28740654ffab9a2c420a71ca2ffff208a | 09eac525a0bb1a1fd944f3ff669f4955ae2db154994c356e2614b82f3d45fbb3 | adda03bf3672b3983cfb255d6f8e634cc04cf7ed6a73bcdc2a223aedf8835f90 | — |
| bb1d272585e8e460d58901eb10ad311e | 614aa7e1912903717c53054ce2a668461ed72e5786aa754c1f0148019a2e74a9 | 109fd9f1b283fb4540ffb4b67c7390ab68f54e6ea0b11e6d37b262bfe1ff3704 | 750f716ed7b47e9ef8560b68e8503773e30b3818bb1c43c7e7fa1df566ae69f9 | — |
| 5fb7df4c03c2a52fb32feb1e06778faa | 394ec502a07c332536bdac422cde03cad71edc67c0bfbe67fb7135c2b5b6df29 | 7be1c4de0a3673c59eae8137bfe01e9afd0d1cbcc76b55198af6f691984e621a | 5bafd49eb512fbd6fe44268e2b75fc45ad1eacc5da41353d54cad972b74fe15f | — |
| 9ad3394e4631f1a333449ca47fa11db2 | 34dfdfd646b4c77c638b7e455a56458b5d30f4667276a3d6b81dca4fa66c9322 | 9dc196567c12d60654e9982fc06fcc00723fad33a8b9036c76f097f1e6d3be25 | 792dcc53381fceefb423ec8745bf1c7a16df98c2fd590e9ef22b20aff2bd593f | — |
| 3ca3d81ea7e20f5f23373e68dfd615bf | 0ee6e1d4146744bcd55783e862a2ebce799520d45935e33ee70921f947bfbf60 | c2e168c3d2de5edc2d619fa3912fda0e55823f3d74bcabaa09f60d0e75e1408e | ccbe579a20698ff45e7ce13f3961aff8367b851f55ff41dd2b8e59183ba187a7 | 136926eec9329c9ef53a4b18878bb9f029f10de9ecc3d9f1244ebda0e797522c |
| 76e7687d51176a9dea5a7743622f9869 | c8dc382c7a16060a4b319048685d6e211467e198bedfa0f3dcb1577300e50d48 | ab333471175110b450f7a8f0b37e74ed8345d1b7d13d8fb55a10fd74f1a0d2c2 | 6f71d8504d613feb9a9fbe24697e7269c641c46cf0726308e2262addb0c96971 | — |
| 10dff9e5e899a02a7f5d50792a618efd | 3f27c8b9f5d3986b26c141782e70ab3799c7ccd5ac0e0b6a94e86576d34b92f3 | 618fe431aa6d805cbd198ee6a0cd24f2735c8c8a3a1debe71836d24d54e4bc53 | 6cc34e22e9bc0ed076dacf9af257797a0b80e306d3897b06ca2991ebbfdf9259 | 6c74ad15a6e72baf78114f44e3a6df28f64d8fd4692059b8de045acc4c3c0eb5 |

## Independent final execution - 2026-11-14

Direct source/test/migration/harness review found no required correction.
Independent QA verified core `19213f60d45fd1f9fac054b7faa85db1d0020a0d`,
base `65bd2da`, target import provenance and HEAD blob identity.

- Full owned harness: **583 passed, 20 existing Windows filesystem skips**.
- Focused owned harness: **30 passed**, including real unique-key contention,
  actual late SQL rejection/outer rollback and all catalog-drift cases.
- No-DB migration/binding tests: **1 passed, 33 skipped**.
- Ruff, strict Linux-target mypy (**40 source files**), migration lifecycle/
  metadata parity and dependency consistency passed. Historical RED/mutation
  results remain author evidence; QA did not mutate source.
- Source SHA: `0e815fe554da8553b774aefcd2ca0bf724e796e511eff34eb98168125b17d317`.
- Test SHA: `f07be799cf987d7007dc199c5d1820707d403e31e7a5f31a15ebbd8c6f70714e`.

QA captured and verified absent these exact resource identities:

| Run | Network | PostgreSQL | Anonymous volume | Keycloak |
| --- | --- | --- | --- | --- |
| Storage | 63a26da6629eaa64c819fde31d32dc83610665077674b3905feaa8c1651960a7 | 4fb3d30c1175481c59b29d748b4a513e7988e627e2708412ec71c5bb7035459b | ddb96b1a82533512392ee0cfcbcc471d16f7b7befaa4cfc6c35aff5a15a9dd10 | none |
| Full | 85b5084ec85517e982b86060fdb00be6ea83493be1e1c00a6c65f4e0737f5a4c | 855ed2baf42a34534c3f10c0e861b4295c7470737f0c9c192f2bc3b3bc66cdd9 | f52edc56265309d1053e11f3f14c808e23d1cf1850cc9838f9262e146e362a62 | e9fe73514d8e534c95d7952f676789645aa98993d722440a04b6b9dc77ee6028 |

No Keycloak volume was attached. Exact Docker inventories returned to baseline;
135 root and 138 target Git-listed files/status remained unchanged, including
three parent-owned task files and existing user edits. Only the newly generated
cache and its initially absent, empty parent were removed. A verifier's
case-sensitive not-found classification was corrected; cleanup did not fail.

This verifies persistence only. Remote checks and normal merge remain pending.

## Verified merge checkpoint

Merged normally in [#50](https://github.com/yanxel18/animetron/pull/50) at
`a871aaaf32120207c3876ba93739ddde04191dcc` after direct review and
independent execution above. Exact-head GitGuardian passed at
`711e78ab2b840d833f800cf0c023ec952d5613e0`; clean mergeability, no outstanding
requested reviews or branch rules. No self-approval or check/protection waiver.
Root master was pulled and tested source/tests/migrations/spec matched.
Prior pending statements are historical. [todo.md](todo.md) is the sole
current checklist; only P1-08b is complete, not runtime readiness or P9.
