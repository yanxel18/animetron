# P0-06: authenticated control-plane slice

Status: implemented for review; **not deployment or phase-completion evidence**.
Specification dependency [#27](https://github.com/yanxel18/animetron/pull/27)
merged at `5b151ecb33c724c6e46eb063c3aaa879949a2d26`.

## Decision and trust model

Use self-hosted **Keycloak 26.8.2** with **Authlib 1.9.5**, its HTTPX2
client and joserfc-backed OIDC validation. Keycloak owns credentials and login
UI. A custom password database, signed client session payload, gateway identity
header or local development principal is not an alternative.

Browser requests, callback parameters and provider responses are untrusted.
The protected assets are session authority, principal grants and audit history.
Only one explicitly configured issuer/client and HTTPS browser origin are
trusted. Authorization comes from local issuer/subject grants, never email,
provider role claims, a bearer token, or forwarded identity headers.

The backend retains no access/refresh/ID tokens. Session cookies contain only
256-bit random opaque handles; PostgreSQL stores their SHA-256 hashes.
`__Host-` cookies are Secure, HttpOnly, SameSite=Lax, Path=/, with no Domain.
Lax permits a top-level OIDC GET callback; a separate synchronizer CSRF token
plus exact Origin is mandatory for the only mutation, logout.

Authorization-code challenges have random state, nonce and S256 PKCE verifier.
State is browser-bound, unique, five-minute and atomically consumed before token
exchange, including failed exchanges. Authlib verifies RS256, exact issuer and
audience, nonce, exp/iat, azp and at_hash when present. Discovery must advertise
code, S256, RS256 and client_secret_basic; endpoints must exactly match the
configured Keycloak realm. Redirects, unsupported encodings, bodies above
256 KiB and metadata-directed alternative fetch destinations are rejected.
Unknown signing keys fail closed; each new callback fetches fresh keys.

## Explicit configuration

The application loads these process environment variables, not a dotenv file:

| Variable | Required value |
| --- | --- |
| `ANIMETRON_DATABASE_URL` | PostgreSQL+psycopg URL, host/database and least-privilege credentials |
| `ANIMETRON_OIDC_ISSUER` | Exact HTTPS Keycloak realm issuer, without trailing slash |
| `ANIMETRON_OIDC_CLIENT_ID` | Confidential OIDC client ID |
| `ANIMETRON_OIDC_CLIENT_SECRET` | Secret from a secret manager or protected process environment |
| `ANIMETRON_BROWSER_ORIGIN` | Exact lowercase HTTPS origin, optional port, no path/trailing slash |
| `ANIMETRON_OWNER_SUBJECT` | Exact stable Keycloak user subject, explicitly provisioned by the owner |
| `ANIMETRON_SUBJECT_GRANTS` | Optional JSON subject-to-`operator`/`viewer` map; default empty |

There is no default owner, issuer, origin, client or database. Missing, invalid
or partial configuration disables control endpoints; public liveness remains
available. Configuration changes invalidate previously issued sessions and
pending login challenges. Only test code can explicitly permit a loopback HTTP
provider; production environment loading has no such switch, and browser origin
and session cookies remain HTTPS/Secure even in tests.

In Keycloak, provision a dedicated realm and confidential client. Enable
standard authorization-code flow; disable direct access grants, implicit flow
and public registration. Require S256 PKCE. Register only:
`<browser-origin>/api/v1/auth/callback`, and the exact browser origin.
Do not use wildcard redirects or web origins. Provision the owner's user before
setting its subject. Provider infrastructure, TLS, PostgreSQL deployment,
backups and production credential provisioning are outside this slice.

Use direct TLS with a loopback-bound gateway and do not trust forwarded headers
from arbitrary peers. Disable raw request/access logs at the server and gateway
(`--no-access-log` for Uvicorn): callback URLs contain short-lived authorization
codes/state and must not be logged. If configuring a production ASGI server, bound WebSocket
frame/queue sizes and disable compression (for example `--ws-max-size 64
--ws-max-queue 4 --ws-per-message-deflate false`). This slice creates no server
deployment or provider service.

## Versioned API contract

FastAPI/Pydantic models provide a machine-readable `app.main.api.openapi()`
contract, including the common error envelope. Documentation/OpenAPI HTTP
routes are disabled. No control data is available through public schema routes.

| Route | Access and response |
| --- | --- |
| `GET /api/v1/health` | Public; only `{"status":"ok"}` |
| `GET /api/v1/auth/login` | Trusted target/origin; 302 to configured provider; no query/redirect input |
| `GET /api/v1/auth/callback` | Browser-bound single-use state plus validated code; 303 to fixed session endpoint |
| `GET /api/v1/auth/session` | Any explicitly granted principal; principalId, role, csrfToken, expiresAt |
| `POST /api/v1/auth/logout` | Same principal, exact Origin and X-CSRF-Token; local revocation, cookie clearing, 303 to Keycloak confirmation |
| `GET /api/v1/readiness` | Owner/operator; real session/database and discovery/JWKS checks |
| `GET /api/v1/audit-events` | Owner; ascending cursor, default limit 50, maximum 100; data and nextCursor |
| `WSS /api/v1/ws` | Same active principal, exact origin/target, no query token; authenticated handshake and ping/pong only |

Errors use `{"error":{"code":...,"message":...,"requestId":...}}`.
Correlation IDs are generated by the server, not copied from input.
401 means no active principal, 403 forbidden/CSRF/origin failure, 400 invalid
callback, 422 invalid pagination, 429 shared login quota, 503 unavailable or
disabled dependencies. Responses have no-store and existing browser security
headers, plus HTTPS HSTS. No credentialed CORS or arbitrary redirect is enabled.
The HTTP request origin may be absent on safe navigations; if present it must
match exactly. Origin is mandatory for mutation and WebSocket requests.

Login/callback exchanges must not be blindly retried: consumed state requires a
new login. Provider calls have five-second operation timeouts and total budgets
of ten seconds for discovery/login/readiness and fifteen seconds for callback.
No token-exchange retries or cross-provider fallback are performed. Production
database connections have a five-second connect timeout and three-second
statement/lock timeouts; the existing engine's bounded default pool wait remains
30 seconds. Authorized sessions remain usable without contacting the provider;
readiness never reports ready if its provider check fails.

## Persistence, audit and migration

Migration `0006_auth_sessions` adds only four independent auth tables after
`0005_artifact_metadata`. Login/session expiry and audit timestamp indexes
support cleanup; hashes and session principal IDs have unique constraints.
No existing workflow/outbox/artifact table is altered. Upgrade is additive;
run it before enabling configuration. Downgrade explicitly revokes all auth
state and removes audit data, so it is a destructive administrative rollback,
not a production procedure to run without preserving required records.

There is exactly one active browser session per principal; successful login
rotates/revokes the previous session under a PostgreSQL advisory transaction
lock. Absolute expiry is eight hours and idle expiry thirty minutes. HTTP
activity and actual WebSocket pings refresh idle activity; timer validation uses
`touch=False` and does not. Open sockets recheck authority on every frame and
after a fifteen-second receive timeout. Dependency/pool delays affect actual
close latency; this is not an end-to-end latency guarantee. No workflow/event
streaming has been added.

Audit rows contain a generated ID/time, stable event code, server request ID and
optional pseudonymous principal digest. No headers, cookies, query values,
passwords, provider tokens or email are recorded. Login success/session rotation
and local logout/audit are transactional. Denials and WebSocket acceptance are
also recorded. Active login quota is **30 starts per shared fifteen-minute
window**, across workers and new browser handles. This conservative global
quota can deny legitimate login during abuse; it is not per-user protection.

Subject IDs are pseudonymous personal data used only for authorization.
Nonce/verifier/CSRF fields are sensitive server-side state. Expired state and
sessions, prior quota buckets and audit records older than ninety days are
purged on successful login starts; expiry rejection does not depend on cleanup.
Operators must schedule cleanup during long periods without login and set
backup retention/deletion/export policy before production. Database TLS and
encryption at rest are deployment obligations, not implemented encryption here.

## Verification and limits

Run from a fresh worktree environment with dependencies from `pyproject.toml`:

```powershell
# Does not inherit any ANIMETRON_* URL or proxy into acceptance tests.
python tests/run_auth_checks.py
```

The harness owns only `animetron-oidc-478745d5-*` resources, creates a dedicated
bridge with loopback ephemeral host bindings and disposable PostgreSQL/Keycloak,
generates credentials in memory/environment, applies migrations and removes
specifically created containers (including anonymous volumes) and network in
`finally`. `--storage` runs the initial durable storage slice without Keycloak.
Windows browser tests use installed Edge with Playwright 1.65.1, a temporary
isolated profile under worktree data, no browser/OS installs and restricted
networking. Provider redirect responses are intercepted *before* navigation;
authorization codes are passed only to the in-process backend test client.

Evidence on 2026-11-14:

- Initial storage increment: **15 passed** against disposable PostgreSQL.
- Final full Windows suite: **278 passed, 20 skipped**; all **59 new auth tests**
  run. The twenty existing skips require Linux/POSIX artifact storage and were
  not changed or suppressed by this task.
- Direct review caught WebSocket timer checks extending idle activity. The
  added PostgreSQL-backed regression failed before the one-line router fix
  (**1 failed, 277 passed, 20 skipped**) and passed in the final suite. It
  verifies persisted timestamps before/after timeout remain unchanged and an
  actual ping updates activity. The user directed continuation after discovery.
- Ruff: **all checks passed**. Strict mypy `--platform linux`: **27 source files**.
- Real provider/browser cases prove login, validated session persistence across
  a new app/engine, rotation, authorized dependency readiness, actual Keycloak
  logout confirmation/completion, denied unlisted subjects and concurrent
  callback single-winner behavior. Adversarial token cases also exercise real
  Authlib verification with generated test signing keys, not production keys.
- Disposable migration upgrade, downgrade to `0005_artifact_metadata`, and
  re-upgrade passed. No existing internal foundation data was migrated away.
- pip-audit 2.10.1: **no known dependency vulnerabilities** after upgrading only
  worktree pip to 26.3. The unpublished local backend package cannot be matched
  to registry advisories. Auditing is not independent security certification;
  direct dependency pins are not a full transitive lockfile.
- Owned PostgreSQL image:
  `sha256:b9f6b8ff03b62f3cfd9d9ba3fe56226a9991c79d3fb46fd46536263bf02be553`.
  Owned Keycloak image:
  `sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0`.

One earlier failing browser traceback exposed a disposable test authorization
code, not a reusable provider credential. That provider/database were destroyed.
The harness now redacts traceback presentation, without skipping assertions.
No real project credentials or HF environment files were read.

Remaining boundaries: no back-channel logout or immediate provider-side account
disable propagation; local grants/configuration and session expiry remain the
authority until logout. No general perimeter/API rate limiter, scheduled audit
retention, production backup/restore, TLS deployment, browser engine matrix or
production SLO/load certification is claimed. A DB/provider outage denies
protected readiness, not liveness. Artifact HTTP, workflow CRUD, model/media,
review, scheduling, frontend and publishing are intentionally untouched.

## Official sources

- [Keycloak OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak Docker quickstart and production boundaries](https://www.keycloak.org/getting-started/getting-started-docker)
- [Authlib Starlette OIDC and logout](https://docs.authlib.org/en/latest/oauth2/client/web/starlette.html)
- [Authlib HTTPX2 and PKCE](https://docs.authlib.org/en/latest/oauth2/client/http/index.html#add-pkce-for-authorization-code)
- [OIDC ID-token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation)
- [OIDC RP-initiated logout](https://openid.net/specs/openid-connect-rpinitiated-1_0.html)
- [Keycloak 26.8.2 secure-context resolver](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/utils/SecureContextResolver.java)
- [Keycloak 26.8.2 cookie policy](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/cookie/DefaultCookieProvider.java)
- [Playwright installed Edge support](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)
- [Playwright request interception](https://playwright.dev/python/docs/network#handle-requests)
