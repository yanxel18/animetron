# P7-01b TypeScript API Contracts Report

Status: implemented on `task/p7-01b-api-contracts`; awaiting pull request
[#54](https://github.com/yanxel18/animetron/pull/54) is open and awaiting
independent review, required checks and merge. P7-01b remains unchecked until
those gates pass.

## Scope and implementation

- Export the FastAPI OpenAPI schema using the local backend Python environment;
  the frontend script invokes the exporter as a child process with a minimal
  environment and does not fetch a schema or pass application credentials.
- Generate committed TypeScript-only contracts with
  `@hey-api/openapi-ts@0.99.0` and the `@hey-api/typescript` plugin. The output
  contains `types.gen.ts` and a type-only `index.ts` re-export; no runtime
  client, new screen, or live service call is added.
- `npm run check:api-types` generates into a unique ignored directory under
  `frontend/.tmp`, compares file names and contents with committed output, and
  removes the temporary directory.

## Findings and decisions

1. The earlier `openapi-typescript@7.13.0` option could not install beside the
   frontend's TypeScript 7.0.2. The Hey API generator supports in-memory OpenAPI
   input and a TypeScript-only plugin, matching this slice's requirements.
2. Hey API 0.97.0 reported moderate advisory
   [GHSA-hhx9-57xq-r5rw](https://github.com/advisories/GHSA-hhx9-57xq-r5rw).
   Version 0.97.3 removed that finding but brought in vulnerable parser/YAML
   dependencies. The selected 0.99.0 dependency set uses parser 1.4.4; its
   exact `js-yaml` dependency was found vulnerable by npm audit. A scoped
   override pins only that parser's `js-yaml` dependency to 4.3.2. The resulting
   full `npm audit` reports zero vulnerabilities, and `npm audit signatures`
   verifies all installed package signatures.
3. TypeScript 7.0.2 crashes the generator at runtime (`SyntaxKind` is undefined)
   despite the generator's declared peer range. TypeScript 5.9.3 restores the
   required compiler API. The frontend typecheck, unit tests and production
   build pass with this pin; revalidate generator compatibility before a
   future TypeScript upgrade.
4. The repository has an existing Python OpenAPI export test. Its focused
   Windows run passes, including checks for run/event routes and absence of a
   public `/openapi.json` route. Ruff required removal of two extra blank lines
   around the intentionally delayed app import; import timing remains unchanged.

Official generator references:

- [Input configuration](https://heyapi.dev/docs/openapi/typescript/configuration/input)
- [TypeScript plugin](https://heyapi.dev/docs/openapi/typescript/plugins/typescript)
- [Hey API 0.99.0 release notes](https://github.com/hey-api/hey-api/releases/tag/2026-06-22)

The 0.99.0 release notes list breaking changes. This implementation uses only
the programmatic input/output configuration and TypeScript plugin; generation,
drift checking, typechecking and build were verified against the pinned
version.

## Verification

| Check | Result |
| --- | --- |
| `npm ci --ignore-scripts` | Passed; frozen lockfile install, scripts disabled |
| `npm run generate:api-types` | Passed; generated two type-only files |
| `npm run check:api-types` | Passed; generated output matches committed files |
| Drift probes | Passed; stale content was rejected, CRLF line endings were accepted, and restored files passed |
| `npm run build` | Passed |
| `npm run test` | Passed; 3 tests |
| Backend `tests/test_openapi_export.py` | Passed; 1 test |
| Targeted backend Ruff and mypy | Passed |
| `npm audit` | Passed; 0 vulnerabilities |
| `npm audit signatures` | Passed; 151 packages have verified registry signatures |
| `git diff --check` | Passed |

This type-contract slice does not complete P7 or P9. It does not validate
browser workflows, accessibility, live services, model/provider operation, or
owner-involved end-to-end acceptance.
