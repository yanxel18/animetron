# P1-11a run read/replay verification

Implemented on `feature/run-read-replay-api`, based at
`a871aaaf32120207c3876ba93739ddde04191dcc`.

## Result

Added authenticated owner-only `GET /api/v1/runs/{id}` and
`GET /api/v1/runs/{id}/events` using existing session/origin/role dependencies
and durable run/event storage. Status exposes stored state/sequence only.
Replay validates bounded ASCII decimal cursors before integer conversion,
rejects unknown/duplicate query keys, fetches at most `limit + 1`, and retains
the input cursor on empty pages. No execution, readiness, cancellation,
recovery, WebSocket, schema, or migration behavior was added. Contract and
limitations are in `docs/SPEC-workflow-runtime.md` and `backend/README.md`.

## Verification

Python 3.12.10 from the supplied OIDC worktree environment:

| Command/check | Result |
|---|---:|
| Initial owned RED run, `tests/run_auth_checks.py --pytest-file tests/test_runs_api.py` | 38 failed, 1 passed; representative expected `200`, got absent-route `404`; initial Ruff also flagged two test-import issues, fixed before GREEN |
| Focused owned PostgreSQL/Keycloak run after implementation | 39 passed |
| Full owned PostgreSQL/Keycloak harness | 622 passed, 20 skipped |
| Full `ruff check --no-cache app tests migrations` | Passed |
| Full Linux-platform `mypy app` | Passed, 41 files |
| Owned Alembic upgrade/check and downgrade/upgrade regression | Passed |
| `python -m pip check` | No broken requirements |
| Database-less `tests/test_runs_api.py` | 1 passed, 38 skipped (database-backed cases) |
| Database-less full suite attempt | 290 passed, 301 skipped, 3 failed, 48 errors; existing auth/ownership tests require the owned DB harness |
| Pagination mutation (`events[:limit]` changed to omit the last row) | 3 failed, 36 passed; reverted, then focused owned suite passed again (39 passed) |

The mutation was restored to `events[:limit]`; the final `runs.py` SHA-256 is
`62D57F88095B9238E55B38079641EBC7A0CB1773AEFF218E0DA9E81E4D8786EB`.
No dependencies were added or installed.

## Disposable resource audit

All five harness invocations used only preloaded images:
PostgreSQL `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`
and Keycloak
`sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.
Each row has `animetron.session=478745d5` and the listed
`animetron.oidc.owner` label. Keycloak had no volume.

| Invocation | Owner label | Network ID | PostgreSQL ID | PostgreSQL anonymous volume | Keycloak ID |
|---|---|---|---|---|---|
| RED | `e3ab20068e614d8d4a8a81f0d1811e2d` | `c823127c99725ef2e65645832bcb57b72f3060084b568ff2979d5328eff07559` | `8fbfe3151562dfd22ec234b7efd8d220948f9998a45251f3e4a46c19daece100` | `3f83ea1c3c5c848a71099552b2f19b3f8294b6bfc71087bef2405ba4e4f4e0ae` | `f52e0ad57531bdf82a75b14d9c44b2a92c8b8750fbd5ddd69395902d01b5d9b4` |
| Focused GREEN | `966f85bd96c90d0e0fde8cc39969bb7a` | `be2350a11bfe7d7eb1e9fb850a3b55b285d38a2afb9e569c1d50a9f334dd72ae` | `93401d8d989968e41545a6981e8b3184c4e2701965fb168d40450304b4708bc7` | `f98f515fcc4148b5800ec0c50191bc7221131b1dfa6246df8bc72087a4a3cca3` | `803d81fed11f4832d8281542ea117973c034d75ee043693cc986f97da459cfb0` |
| Full suite | `59f68733f3dfb63f6c4d56ea92fbcddd` | `cd222690a9a52476ba44dbc943e24de12c8eb079ecc84844611472628c5636f8` | `bccf211a450c2f8e2d36ba99d98e53ebccb0bf5c6c6108e6e2fc822e774db124` | `cc9dd568d10aaceb10adfcb82abdb85e4989b3bf7efe1fc6ab4bb0ac0ff95689` | `fdcee9c18eed9debf39954d5e61ea561441a5777ed508adcb46b36b54a2e2cac` |
| Mutation | `e9bb2a1435a09cf5d266e9566032d803` | `170bf4c8547c389662ac4ed331ca2d82d9d0c24e061f87ed060f48a45b5706e0` | `081ff1f4782091867aa7d44be0d8edd9c226109b3b0592cd7530b9dbdef22bf3` | `69109189a77ed3e07039f92b6c2dedca4a84b71b684092a3ec1200c5229a94b4` | `fd65e05f04ea7dd1d437caf30e5a330843c91d77904920a3f5a7fd93d9048692` |
| Restored final focused run | `eec5fc237df5a72544f48572b5751043` | `be7d8e9f78e972ce62951450596e93f6e2957882b7205384ebfbdfeee4771726` | `10ebfcc16a02e3282df1b6a9fab7e49dbef969229098844900b383ca3f9d0f87` | `88475100ab31edd151acca5928954f1e45930186c4076bf8bb8c706c4a2cc83d` | `0ed150bfd29f937b63394633eb8194b16fd6b7c728f0f2b04ec936cf55c14aa6` |

The harness verified each container/network owner label before cleanup and
removed every listed container (including PostgreSQL anonymous volume) and
network. Final prefix-filtered checks found no owned containers, networks, or
volumes. Pre/post Docker inventory counts and SHA-256 hashes matched exactly:
containers `4 / 9122584ca5779c969d9cdba176f7e209d9744dae135d65b1b5026faed257b389`,
networks `4 / b5fae1ce811232b5153ab441cabaf4cb447bc88613d885d2d8e4e4102190fed2`,
volumes `78 / aa4a4529f8effc053e6e1bca25565a9137f17205f79de48b1ab557461402bc4f`,
images `54 / eb92ddcee4151af18bc2ea5c459b52718f7d51c897152fcf1ef05c5b074adc9c`.
The test-created
`backend/.pytest_cache`, `backend/.mypy_cache`, and
`data/oidc-test-temp` directories were absent at baseline and removed by exact
path. Parent-owned `tasks/todo.md`, `tasks/development-report.md`, and
`tasks/execution-revision-bindings-report.md` were not edited or staged.

No push, PR, or merge was performed.
