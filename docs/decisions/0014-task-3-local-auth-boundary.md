# ADR 0014 — Task 3 local auth boundary and session revocation

- Date: 2026-09-07
- Status: local scope authorized by the owner's Task 3 request; deployment deferred

Task 3 is verified identity only under ADR 0006. Expose a narrow
`GET /v1/auth/identity` returning only the verified `user_id`, with the same-origin
`GET /api/auth/identity` BFF counterpart. Neither grants roles or product access.
Do not implement `/v1/me` until Task 4's protected membership schema exists.

The owner authorized complete local implementation, then explicitly authorized
final review, commit, branch push, and PR creation on 2026-09-07. Domains and
deployment remain deferred. The production-domain acceptance
in Task 3 remains unverified; local completion is not production completion.
Task 4 remains unstarted, with the Postgres 17/16 follow-up still required.

All Supabase access is server-side. Use official SSR PKCE storage, cookie chunking,
refresh, and code exchange, with HttpOnly, SameSite=Lax, host-only, path `/`
cookies. Secure is mandatory for HTTPS; HTTP is accepted only for an explicitly
configured loopback origin with `AUTH_ALLOW_LOCAL_HTTP=true`, including local
production-build tests. Keep the SDK's cookie lifetime; token expiry, refresh
revocation, and live session checks control authentication, not cookie expiry.

The SDK's `getSession()` retrieves the access token and can refresh it; its user
object is never trusted. `getClaims(token)` verifies that exact token, followed
by explicit issuer, audience, algorithm, expiry, subject, and session-ID checks.
`getUser(token)` additionally rejects revoked sessions. FastAPI independently
verifies JWKS signatures and claims and calls Auth `/user` with the publishable
key to enforce immediate session revocation. Offline JWT verification alone
failed the copied-cookie-after-logout test. This live check adds an Auth network
hop per verification and fails closed on Auth outages; it introduces no application schema or
privileged key. Reverify provider session-revocation behavior on deployment.
The current identity BFF request checks Auth in both proxy and handler, then
FastAPI checks independently: three live Auth calls, plus JWKS fetches on cache
miss. This deliberate local foundation tradeoff is not a measured production
latency claim or a requirement to duplicate calls in later product routes.

Use only ES256/RS256 public-key algorithms. Local Auth gets a generated, ignored
ES256 key through the pinned CLI, rather than sharing a JWT secret with FastAPI.
JWKS are cached for five minutes and refreshed on an unknown key ID.
Unknown/unusable keys return generic 401; malformed key objects are normalized
without exposing exceptions. JWKS connection failures and Auth service outages
return 503 and never grant identity. Tests exercise both upstream outage paths.

All mutation routes require the exact configured Origin and Host, reject
cross-site Fetch Metadata, and use SameSite cookies. No arbitrary redirect is
accepted; callback routing is fixed. Supabase enforces email cooldown/rate
limits; request responses are generic. Auth responses are not cached, including
SDK-provided refresh cache headers. Next.js development callback request logging
is excluded because query strings contain one-time codes. Provider access-log
redaction must be verified before deployment.

Dependencies: `@supabase/ssr` 0.12.6 and `@supabase/supabase-js` 2.115.0 implement
the specified supported auth protocol; `server-only` 0.0.1 provides Next.js's
compile-time client-import guard. `PyJWT[crypto]` 2.13.0 supplies maintained JOSE,
JWKS, and signature validation absent from Python's standard library and the
existing API dependencies. Its crypto extra resolves cryptography 50.0.1,
cffi 2.1.1, and pycparser 3.0. No unrelated dependency upgrade is intended.

Sources inspected alongside installed package source:

- [Supabase SSR clients](https://supabase.com/docs/guides/auth/server-side/creating-a-client)
- [Supabase SSR advanced guide](https://supabase.com/docs/guides/auth/server-side/advanced-guide)
- [Signing keys](https://supabase.com/docs/guides/auth/signing-keys)
- [Pinned Auth session validation](https://github.com/supabase/auth/blob/v2.196.0/internal/api/auth.go)
- [PyJWT verification](https://pyjwt.readthedocs.io/en/stable/usage.html)
