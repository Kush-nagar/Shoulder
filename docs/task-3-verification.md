# Task 3 verification record

Repository `D:\Shoulder`, branch `task-3-application-foundation`, base
`76486c5822aa426402945f64be41b9b9c353ab32`; one writer. Date: 2026-09-07.
Status: **passed for the owner-authorized local scope**. The owner subsequently
authorized final review, commit, branch push, and PR creation on 2026-09-07;
production-domain acceptance and deployment remain deferred.

## Scope and contract

Read AGENTS.md, STATUS.md, product, current build order, architecture, API,
security, governing decisions, ADRs 0003/0006/0012/0013, current configuration,
tests, and Task 1/2 verification records. Tasks 1 and 2 are merged prerequisites.
The checkout was clean and exactly at the supplied base before implementation.

Current Task 3 is verified authentication and session identity. The API and
ADR 0006 explicitly defer `/v1/me` to Task 4, so it remains absent (404).
The narrow `/v1/auth/identity` returns only `user_id`; it grants no product role.
Its TypeScript schema is generated from FastAPI OpenAPI, not handwritten.
No application table, migration, RLS policy, membership, team permission, upload,
worker feature, video feature, ML, or player-facing authored content was added.

The task document's production-domain Done criterion remains deferred under
the owner's explicit local-only instruction. ADR 0014 records the distinction;
do not call production authentication verified or Task 4 prerequisites complete.

## Implementation and security decisions

- `POST /auth/magic-link`: validates email, requires exact configured Origin and
  Host plus non-cross-site Fetch Metadata, calls Supabase `signInWithOtp`, and
  returns a generic redirect. Supabase enforces recipient cooldown and project
  rate limits. No forwarded client IP or editable identity header is trusted.
- `GET /auth/callback`: validates code cardinality/bounds and the current SDK's
  optional `sb_flow_id`; calls `exchangeCodeForSession(code, {flowId})`, verifies
  identity, and redirects only to `/auth/session`. Invalid/expired/reused state
  clears auth cookies and returns a generic sign-in error. Arbitrary `next` is
  never used. The SDK owns PKCE cryptography, per-flow storage, and replay checks.
- `proxy.ts`: owns session refresh for `/auth/session` and `/api/auth/identity`.
  Updated cookies reach both the downstream request and browser response.
  Each request gets its own SSR client; sessions are not shared across requests.
- `getSession()` reads only the access token (and may refresh it). The embedded
  user object is never used as identity. `getClaims(token)` verifies that exact
  token, and explicit policy checks constrain issuer/audience/algorithm/expiry
  and UUIDs. `getUser(token)` additionally checks live session validity.
- `GET /api/auth/identity`: obtains the verified token from cookies and forwards
  only a Bearer header to the fixed FastAPI identity endpoint. No generic proxy,
  browser-to-FastAPI authenticated product calls, or client Supabase SDK exists.
- FastAPI centrally verifies ES256/RS256 signatures against the configured Auth
  JWKS, exact issuer, authenticated audience, expiry, subject, and session UUID.
  JWKS caching lasts five minutes and an unknown key ID triggers refresh. The
  token cannot supply the JWKS URL. `/user` with the publishable key then rejects
  revoked sessions; mismatched/invalid identity fails closed. No JWT secret is
  used. Missing/wrong-scheme/malformed/unverified credentials return generic 401.
- `POST /auth/sign-out`: revokes the local Supabase session, clears all matching
  session/chunk/PKCE cookies, and returns to sign-in. Infrastructure errors still
  clear browser cookies and return 503. Replaying copied valid cookies or access
  tokens after successful logout is rejected by live Auth session checks.
- Cookies are HttpOnly, SameSite=Lax, host-only, path `/`, with SDK-managed
  lifetime/chunking. HTTPS always sets Secure. Local HTTP requires explicit
  `AUTH_ALLOW_LOCAL_HTTP=true` and a loopback APP_ORIGIN. This applies equally
  to local production-build tests; NODE_ENV does not silently weaken cookies.
- Auth responses use private/no-store and preserve SDK refresh cache headers.
  Session responses use Referrer-Policy same-origin so form Origin survives.
  Development callback request logging is excluded. No credential logging was
  added. Production provider request-log redaction remains a deployment check.
- Live Auth checks intentionally add a network dependency to enforce immediate
  logout. Outages do not become authenticated sessions. Details: ADR 0014.

## Dependencies and environment

Existing Next.js 16.3.4, React 19.2.8, FastAPI 0.141.1, and all unrelated pins
remain unchanged. Added exact production pins:

| Package | Version | Reason |
|---|---|---|
| `@supabase/ssr` | 0.12.6 | Supported PKCE cookie storage/refresh and Next.js integration |
| `@supabase/supabase-js` | 2.115.0 | Supported Auth client, claims verification, code exchange |
| `server-only` | 0.0.1 | Next.js build guard against importing auth implementation into clients |
| `PyJWT[crypto]` | 2.13.0 | Maintained JOSE/JWKS verification absent from the existing API stack |

`pnpm-lock.yaml` adds only the Supabase/guard graph. `uv.lock` adds PyJWT and its
crypto graph: cryptography 50.0.1, cffi 2.1.1, pycparser 3.0. Dependency audits
found no known vulnerabilities.

Server-only web inputs: APP_ORIGIN, AUTH_ALLOW_LOCAL_HTTP, SUPABASE_URL,
SUPABASE_PUBLISHABLE_KEY, API_BASE_URL. FastAPI inputs: SUPABASE_AUTH_ISSUER and
SUPABASE_PUBLISHABLE_KEY. No NEXT_PUBLIC variable was introduced. Examples
contain loopback addresses and blank key placeholders only.

Local bootstrap generates ES256 private material in ignored
`supabase/.env.signing-keys.json`, and writes only the local publishable key to
ignored `apps/web/.env.local`. The API has no private signing key. Local CLI
status output is captured, never printed. Integration cleanup reads the local
service-role credential in the test process only, never in application config,
client code, files, traces, or test assertion output.

## Automated verification

| Command | Result |
|---|---|
| `node --test tests/auth-policy.test.mjs` | 3 passed: HTTP/HTTPS config, CSRF origin/host, verified-claim policy |
| `.\.tools\uv.exe run --locked python -m unittest discover -s tests -p test_auth.py` | 7 passed, with parameterized rejection cases; real production route/dependency |
| `.\scripts\check.ps1` | Passed in full after the independent JWKS failure-handling repair |
| `.\scripts\check-auth.ps1` | All 6 real-stack tests passed after final review: Chromium 2, Firefox 2, WebKit 2; health and finally-stop passed |
| `node --test tests/auth-bundle.test.mjs` | Passed against production static JavaScript |
| `npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm audit --audit-level=low` | No known vulnerabilities |
| `.\.tools\uv.exe run --locked pip-audit` | No known vulnerabilities |
| `git diff --check` | Passed; only existing Git LF/CRLF conversion notices |

The complete check covers Biome format/lint, TypeScript, 5 Node policy/repository
tests, Ruff format/lint, strict mypy, 8 Python tests including health, generated
OpenAPI/type drift, production build, browser bundle scan, and three unchanged
health/font/SVG/accessibility browser tests.

`tests/auth.spec.mjs` has two tests run in Chromium, Firefox, and WebKit against
the real local Supabase Auth, production Next.js server, and FastAPI server:

1. Browser magic-link form, captured Mailpit email, real Supabase verify/PKCE
   exchange, neutral rendering, rate-limited resend survival, fixed redirect,
   cookie attributes/propagation, BFF forwarding, exact identity-only response,
   expired access-token rejection, real refresh, sign-out, copied cookie/token
   rejection, revoked refresh rejection, and reused callback rejection.
2. Missing/cross-site/null Origin, invalid email, missing/invalid/duplicate code
   and flow parameters, open-redirect attempts, malformed cookies, signed-out
   rendering/BFF, and missing FastAPI credentials.

The expired-token fixture uses the real session claims and the ignored local
ES256 key to set a past expiry, while retaining the real refresh grant. FastAPI
rejects that signed expired token; Supabase itself performs the refresh and the
real proxy/BFF propagates its new cookies/token. This is deterministic without
waiting an hour; no service is mocked. Cryptographic lower-level tests use
fresh in-memory EC keys and a loopback JWKS/live-user fixture, including rotation.

Auth browser tests disable traces, video, and screenshots. Callback exchange is
made through the browser context's shared-cookie HTTP client to inspect actual
Set-Cookie headers before following the fixed redirect. Form submission,
rendering, and sign-out still run in the browser. This avoids the documented
Windows WebKit SameSite-reporting limitation; all projects assert actual
HttpOnly/SameSite=Lax/path attributes on the wire. Browser JavaScript cannot read
the HttpOnly cookies. No test is skipped, weakened to accept None, or marked
expected-failure. [Playwright's own Windows WebKit cookie tests](https://github.com/microsoft/playwright/blob/main/tests/library/browsercontext-cookies.spec.ts)
document the reporting limitation.

## Failures investigated and repaired

- Docker's pre-existing stale AF_UNIX runtime sockets prevented startup.
  Stopped the failed Desktop app and preserved only verified socket directories
  (`Docker/run`, `docker-secrets-engine`) under unique `.shoulder-task3-*` backup
  names before restarting. No factory reset, security-policy change, image
  deletion, or volume deletion. Existing earlier backup names were preserved.
- A later continuation observed Docker Desktop 4.90.0 (the earlier run was
  4.89.0); this run did not install the update. Its same confirmed stale-socket
  failure was repaired by the same data-preserving procedure.
- CLI signing-key generation initially read a config referring to the not-yet
  existing key. Generate under ignored `.tools` before writing the configured
  ignored key path. Existing keys are never overwritten by bootstrap.
- Initial sign-out form failed CSRF because no-referrer suppressed its Origin.
  Same-origin referrer policy preserves the form's Origin without cross-origin
  referrer disclosure; the actual browser sign-out regression passes.
- Offline JWT checks accepted copied pre-logout cookies. Added live session
  checks in both boundaries and verified rejection without Task 4 schema.
- Windows WebKit misreported SameSite and could not fulfill intercepted 303
  responses. Removed interception entirely and assert the real callback wire
  headers through the browser's shared-cookie request context instead.
- A reused-callback assertion matched Next.js's accessibility announcer too;
  scoped it to the main content's actual alert. No product behavior was hidden.
- Strict formatting/lint findings were fixed and checks rerun.
- A rapid resend correctly hit Supabase's email cooldown but the SDK had already
  prepared replacement PKCE cookies. Discard those unsuccessful-request writes
  so the first link remains usable; the generic response does not reveal account
  existence. Optional `sb_flow_id` is validated and passed to the SDK when
  present; its experimental redirect-appending option remains disabled.

## Final review and deferred work

Final source/diff review found only Task 3 changes, with no privileged browser
key, static credential/token, unverified authorization, open redirect, Task 4
schema, generated local state, disabled test, or unrelated dependency upgrade.
Production static-JavaScript scanning found no server auth configuration,
refresh-token/session SDK, or auth cookie implementation in browser bundles.
`git diff --check` passed. Earlier untracked files were included in the source
review and secret scan, not just the tracked Git diff.

Final cleanup removed five synthetic Auth accounts left by early diagnostic
runs, using the exact UUID-shaped `task3-…@example.test` pattern against the
verified loopback project. Current tests clean their own accounts and captured
emails even on failure. Final Auth user count was **0**; `app` schema count was
**0**. No user data or application schema was erased. Supabase and MinIO start,
health, pinned-image/loopback-port checks, and stop passed; final `docker ps`
returned **no running containers**. Engine version remained **29.7.2**.

Required case results: valid session **pass**; refreshed-expired **pass**;
malformed **pass**; invalid signature **pass**; wrong issuer **pass**; wrong
audience **pass**; wrong/unsigned algorithm **pass**; reused callback **pass**;
CSRF/origin and safe redirects **pass**; cookie propagation **pass**; signed-out
and copied stale session/token rejection **pass**. No local owner-input blocker
remains.

Production APP_ORIGIN, callback allowlist, Supabase project URL/publishable key,
FastAPI origin/issuer, deployment accounts/approval, provider log redaction, and
real HTTPS/phone acceptance remain owner/operator inputs. No hostname was
invented and no resource was created. No external messages were sent; local
Auth emails remained in Mailpit. Local Postgres stays 17.6.1.165 under ADR 0013;
the production 16 compatibility decision is still required before Task 4.

The initial implementation handoff was uncommitted. The subsequent finalization
request authorizes committing this reviewed diff and opening a PR into `main`.
No merge, deployment, or Task 4 implementation is authorized by this handoff.

## Independent finalization review

Fetched origin and verified HEAD, main, and origin/main all matched the supplied
base, with no Task 3 remote branch or intervening Task 4 work. Reviewed every
tracked diff and all 22 new files, including both complete lockfile additions.
All 41 files have a Task 3 purpose: auth routes/services, neutral forms, local
Auth setup, generated identity contracts, exact dependencies, tests, or records.
No existing dependency was upgraded; `server-only` deliberately guards the auth
implementation against client imports. No accidental artifact was staged.

ADR 0014 is consistent with ADRs 0003/0006 and the current task/API contracts.
Clarified the accepted cost: a BFF identity request performs three live Auth
checks (proxy, handler, API). Immediate logout rejection is intentional; provider
behavior must be reverified for production. FastAPI still verifies signatures
independently and never reads browser cookies. `/v1/me` remains Task 4 only.

Final review reproduced an unhandled AttributeError from a non-object JWKS key.
The repair normalizes that narrow library error to a generic authentication
failure and distinguishes JWKS connection outages as 503, matching Auth outages.
Added real HTTP fixture regressions for unknown kid, empty/non-object/unusable
keys, and both JWKS and live-user service failures. The regressions failed before
the repair and pass afterward. A fixture type annotation was corrected after
strict mypy rejected its deliberately malformed data; no check was weakened.

The real refresh test preserves a legitimate refresh grant and exercises the
proxy, Supabase refresh endpoint, cookie propagation, and FastAPI verification.
The replay test restores the original verifier cookies and retries the actual
consumed callback after logout; it cannot establish a fresh session. Fixed
redirects, exact mutation Origin/Host checks, HttpOnly/Lax cookie attributes,
explicit loopback HTTP opt-in, and production bundle isolation remain intact.

Finalization reran the complete quality script, seven focused authentication
tests (eight Python tests with health), all six real-stack browser tests, both
dependency audits, source and production bundle scans, and diff whitespace
checks. All passed. Hosted CI runs the shared quality script and audits; the
Docker-backed authentication suite is separately verified locally in this task.
After a continuation, Docker's same stale-socket failure recurred; its two
verified socket-only directories were preserved under unique
`.shoulder-task3-final-20260907-2100` backup names. No settings, volumes, or
Windows security policy were changed.

## Complete final file inventory

PR #3 follow-up: Copilot identified missing `Cache-Control: private, no-store`
on Auth HTTP/network outage responses. Added the header there and on the matching
missing-configuration path. Regression tests reproduced the omissions before
repair; the Python suite now contains nine tests. The BFF field-growth suggestion
is speculative: its fixed trusted upstream has an explicit AuthIdentity response
model, and real integration asserts that only user_id reaches the browser.
WebKit initially exited before test execution; its isolated retry passed without
changing Windows security policy or browser configuration. The full quality
script is rerun before the repair is committed.

19 existing files changed:

```text
.env.example
README.md
STATUS.md
apps/web/.env.example
apps/web/next.config.ts
apps/web/package.json
docs/04-api.md
package.json
packages/contracts/api.d.ts
packages/contracts/openapi.json
pnpm-lock.yaml
pyproject.toml
scripts/bootstrap-infra.ps1
scripts/check.ps1
services/api/.env.example
services/api/main.py
supabase/config.toml
tests/repository.test.mjs
uv.lock
```

22 files created:

```text
apps/web/app/api/auth/identity/route.ts
apps/web/app/auth/callback/route.ts
apps/web/app/auth/magic-link/route.ts
apps/web/app/auth/session/page.tsx
apps/web/app/auth/sign-in/page.tsx
apps/web/app/auth/sign-out/route.ts
apps/web/lib/auth/policy.ts
apps/web/lib/auth/route.ts
apps/web/lib/auth/server.ts
apps/web/proxy.ts
docs/decisions/0014-task-3-local-auth-boundary.md
docs/task-3-verification.md
playwright.auth.config.mjs
scripts/bootstrap-auth.ps1
scripts/check-auth.ps1
services/api/auth.py
services/api/routes.py
services/api/schemas.py
tests/auth-bundle.test.mjs
tests/auth-policy.test.mjs
tests/auth.spec.mjs
tests/test_auth.py
```

Before staging, `git status --short --untracked-files=all` contained exactly
these 19 modified and 22 new files; HEAD was the supplied merged base.
Ignored runtime environments, generated local signing material, caches, browser
artifacts, and tools are not part of this 41-file diff.
