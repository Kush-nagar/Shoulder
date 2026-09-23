# ADR 0020 — Google OAuth alongside magic links

- Status: Accepted
- Date: 2026-09-22

## Context

Magic links were the only way into Shoulder. Every sign-in required leaving the
application, finding a message, and returning through a link. For a coach who
signs in before each session that is friction on every use, and it makes local
demonstration depend on the captured-mail container.

`AGENTS.md` named magic links as the authentication method in the decided stack,
so adding a provider is a stack amendment rather than an implementation detail.

Replacing magic links with Google was considered and rejected. The product's
players are minors. Children under 13 generally cannot hold a standard Google
account, and Family Link accounts are restricted. A Google-only door would
exclude a real share of the people the product exists for.

## Decision

1. Google OAuth is offered **alongside** magic links. Neither is removed and
   neither is privileged; the sign-in page offers both.
2. Google uses the same server-side PKCE flow and the same `/auth/callback`
   route as the magic link. ADR 0003 is unchanged: Next.js still completes the
   exchange and owns the session cookies.
3. `/auth/google` is POST-only and requires an exact same-origin `Origin`, the
   same trust boundary as `/auth/magic-link`. A cross-site link, image, or form
   cannot start a flow.
4. The Google client secret reaches GoTrue through the process environment only.
   It is never committed, never sent to the browser, and never read by the web
   or API service. `supabase/config.toml` references it as `env(...)`.
5. `skip_nonce_check` stays `false`. Disabling nonce validation would permit
   replay with a stolen ID token.
6. Absent Google credentials leave the provider inert and the local stack
   healthy. A checkout without a Google client still runs and still tests.

## Consequences

- No migration and no schema change. `private.sync_user_account()` already
  prefers `raw_user_meta_data ->> 'full_name'`, which Google populates, so
  Google accounts produce better display names than email local-parts.
- Only `email` and `display_name` cross into `app.user_account`. Google's
  `avatar_url` and `picture` remain in `auth.users` and are never read. The
  product stores no photograph of a minor, consistent with rule 6.
- Supabase links identities sharing a verified email address, so a coach who
  used a magic link and later uses Google at the same address remains one user
  with one set of team memberships. This is asserted manually against the cloud
  project rather than in CI.
- The Google round trip cannot be exercised end to end in CI without live
  Google credentials. Everything on this application's side of the redirect is
  tested: origin refusal, method refusal, the authorize redirect, and the
  code-verifier cookie. The round trip itself is verified manually.
- A second entry point on the sign-in screen amends `docs/05-ui.md`, which
  previously specified one primary action.
