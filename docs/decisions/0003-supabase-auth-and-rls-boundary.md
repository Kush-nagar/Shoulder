# ADR 0003 — Supabase identity and RLS request boundary

- Status: Accepted
- Date: 2026-08-24

## Context

The browser needs Supabase Auth sessions while the application API is FastAPI. A separate application identity, privileged database runtime role, or request-scoped state left on pooled connections would weaken isolation.

## Decision

1. `user_account.id` is the corresponding `auth.users.id` UUID.
2. Next.js completes the supported server-side PKCE flow and owns Secure, HttpOnly session cookies.
3. Browser JSON is same-origin through a small Next.js BFF.
4. The BFF validates the current session and forwards the access token to FastAPI.
5. FastAPI independently validates JWT signature, issuer, audience, algorithm, expiry, and subject.
6. FastAPI opens one transaction and sets the verified subject in transaction-local `app.user_id` context.
7. All user-request queries use a dedicated `NOBYPASSRLS` role; memberships remain database records rather than editable token metadata.

## Consequences

- The Supabase subject is consistent across auth, API, and policies.
- RLS remains effective even when a service query forgets an ordinary filter.
- The BFF adds a small hop for JSON but not for media bytes.
- Tests must cover pooled-connection context clearing, revoked membership, missing context, and malformed/expired tokens.
- Migration and administrative roles must stay separate from the runtime role.
