# ADR 0017 — Invitation links an existing account

- Status: Accepted
- Date: 2026-09-08

`docs/04-api.md` describes `POST /v1/players/{player_id}/invite` as "creates or
links account safely". The create half is not reachable from the database.
`app.user_account.id` references `auth.users(id)` (migration `0001`), so no
profile row can exist before its Supabase Auth identity does, and
`shoulder_migration` — the definer that owns `private.link_player_account` —
holds no privilege on the `auth` schema. Minting the identity would require a
Supabase service-role credential inside FastAPI, which bypasses row-level
security entirely and contradicts `services/api/db.py`: the API connects as the
dedicated `NOBYPASSRLS` role, "never as a table owner or service credential".

Project Block 01 implements linking only. `private.link_player_account`
authorizes on the caller's own coach membership, resolves the normalized address
against `app.user_account`, and in one transaction sets `player.user_id` and
inserts the matching `team_membership` row. An address with no account yet
raises `no_data_found`, which the API returns as `422` with the problem type
`invitation-account-not-found`. Nothing is partially written.

Task 20 owns Resend delivery and therefore owns identity creation: sending an
invitation is what creates the Auth user, through the existing publishable-key
magic-link path rather than a service-role key. Until that task lands, a coach
can link a player who has signed in at least once, and can use the entire roster
workflow without collecting any email — which is what Task 6's definition of
done actually requires, and what `docs/05-ui.md` means by "Invitations are
secondary".

No dependency, secret, or privileged role is added. When Task 20 revisits this,
the decision to re-open is whether identity creation happens through the
magic-link path or a service credential; this ADR rejects the service credential
for the API process, not for a separate future component with its own boundary.
