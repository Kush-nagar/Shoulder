# Project 01 — Roster and development goals

# Goal

A coach builds a real roster without collecting any player email, links accounts only as
a separate explicit action, and gives a player exactly one active development goal.

# Included Tasks

- **Task 6 — Roster workflows** (`docs/06-tasks.md`)
- **Task 7 — Development goals** (`docs/06-tasks.md`)

# Dependencies

Tasks 1–5, merged at `470dc77`. This block consumes, and does not redesign:

- `app.user_account`, `app.team`, `app.team_membership`, `app.player` (migration `0001`)
- `shoulder_migration` / `shoulder_api` / `shoulder_operator` role separation (`0002`)
- `private.team_roster(uuid)` (`0003`)
- `private.current_user_id()`, `private.is_team_member(uuid)`, `private.is_team_coach(uuid)`
- `tests/isolation_fixtures.py` `IsolationHarness` / `World`
- `services/api/db.py` `user_transaction` / `operator_transaction`

# Existing Contracts

- The API connects as `shoulder_api` (`NOBYPASSRLS`) and publishes the verified subject
  transaction-locally as `app.user_id`. No route may use `operator_transaction` except
  the existing bootstrap.
- Every protected table has `ENABLE` + `FORCE ROW LEVEL SECURITY`, an owner-maintenance
  policy for `shoulder_migration`, and separate policies per command when predicates
  differ.
- `PUBLIC`, `anon`, and `authenticated` hold no privilege in `app` or `private`.
- Public TypeScript API types are generated from FastAPI's OpenAPI document only.
- `player.user_id` is intentionally nullable. Linking is a separate explicit action that
  creates the matching player membership in the same transaction.

# Scope

Database:

- Migration `0004`: roster write policies, column-level write grants, `app.development_goal`,
  its RLS and grants, and the invitation and archive helpers.
- Downgrade restores the exact `0003` state.

API:

- `GET /v1/teams`
- `GET /v1/teams/{team_id}/players`
- `POST /v1/teams/{team_id}/players`
- `POST /v1/teams/{team_id}/players/bulk`
- `PATCH /v1/players/{player_id}`
- `POST /v1/players/{player_id}/invite`
- `POST /v1/players/{player_id}/archive`
- `POST /v1/players/{player_id}/goals`
- `GET /v1/players/{player_id}/goals`
- `PATCH /v1/goals/{goal_id}`
- RFC 9457 problem-details error bodies for every route in the service.

Web:

- `/coach/roster`, `/coach/players/[player_id]`, and the coach shell they need.
- Role-aware redirect from `/` after a verified session and role lookup.

# Out of Scope

- `game`, `video`, `observation`, `judgment`, `evidence_clip`, `review_publication`,
  `player_reflection`, `processing_job`, `product_event`, `cv_run`, `player_track`.
- `/coach/upload`, `/coach/games/*`, `/player/*`, `/coach` dashboard content beyond the
  navigation the roster screens require, and the evidence timeline on the player detail
  page (Blocks 03–06 own those).
- Email sending. `POST /v1/players/{player_id}/invite` links or creates the account row
  and membership; Resend delivery is Block 06 / Task 20.
- Deletion, retention, and erasure. `archive` is soft removal only and must not claim
  erasure.
- Cursor pagination. Rosters are capped at 40 rows per bulk request and one team per
  workspace; add pagination when a list can actually exceed 100 rows.

# Shared Contracts

Frozen by the coordinator before any parallel work. No workstream may change these.

## Database — migration `0004_roster_goals`

New table:

```
app.development_goal
  id             uuid  PK  default gen_random_uuid()
  player_id      uuid  not null  FK app.player(id) on delete cascade
  title          text  not null  check length 1..100
  description    text  null      check length <= 1000
  ontology_key   text  null      check length 1..80
  status         text  not null  default 'active'
                                 check in ('active','achieved','paused','retired')
  created_by     uuid  not null  FK app.user_account(id)
  created_at     timestamptz not null default now()
  closed_at      timestamptz null
  check (status = 'active') = (closed_at is null)
```

Indexes: `development_goal_player_id_idx (player_id)`,
`development_goal_created_by_idx (created_by)`,
`development_goal_active_key` unique on `(player_id)` where `status = 'active'`.

New `private` helpers, all `STABLE SECURITY DEFINER SET search_path = ''`, owned by
`shoulder_migration`, revoked from `PUBLIC`/`anon`/`authenticated`, executable by
`shoulder_api`:

- `private.is_player_coach(p_player_id uuid) returns boolean` — the caller coaches the
  team of that player row.
- `private.is_player_self(p_player_id uuid) returns boolean` — the caller's account is
  linked to that player row, the caller still holds a membership on that team, and the
  row is neither deleted nor deletion-pending. It mirrors `player_visible_select`
  exactly, including the membership check migration `0002` added: revoking a membership
  must end the player's read of their own goal, not only of their roster row.
- `private.link_player_account(p_player_id uuid, p_email text) returns uuid` —
  `VOLATILE SECURITY DEFINER`. Authorizes on `private.is_player_coach(p_player_id)`,
  never on an argument. In one transaction: resolves the `app.user_account` row for the
  normalized email, sets `player.user_id`, and inserts the matching
  `team_membership (team_id, user_id, 'player')`. Returns the account ID. Raises
  `23505` when the player is already linked or the account is linked to another row on
  that team, `22023` when the email is unusable, `P0002` when no account exists for that
  address yet, and `42501` when the caller does not coach that player.

  It **links only; it never creates an account.** `app.user_account.id` references
  `auth.users(id)`, so a profile row cannot exist before its Supabase Auth identity, and
  this definer holds no privilege on `auth`. Creating the identity would require a
  service-role credential inside FastAPI, which bypasses RLS and contradicts
  `services/api/db.py`. Identity creation moves to Task 20 with email delivery. See
  [ADR 0017](../decisions/0017-invitation-links-existing-accounts.md).

Policies on `app.player` for `shoulder_api` (the existing SELECT policy is unchanged):

- `player_coach_insert` — `FOR INSERT WITH CHECK (private.is_team_coach(team_id) AND user_id IS NULL AND deleted_at IS NULL AND deletion_pending_at IS NULL)`
- `player_coach_update` — `FOR UPDATE USING (private.is_team_coach(team_id)) WITH CHECK (private.is_team_coach(team_id))`

No DELETE policy and no DELETE grant: roster removal is soft.

Policies on `app.development_goal` for `shoulder_api`:

- `development_goal_coach_select` / `_insert` / `_update` — coach of that player's team,
  `USING` and `WITH CHECK` both `private.is_player_coach(player_id)`; INSERT also
  requires `created_by = private.current_user_id()`.
- `development_goal_player_select` — `FOR SELECT USING (private.is_player_self(player_id))`.

No goal DELETE policy or grant.

Grants to `shoulder_api`:

```
GRANT INSERT (team_id, display_name, jersey_number, position)      ON app.player TO shoulder_api;
GRANT UPDATE (display_name, jersey_number, position, active, deleted_at)
                                                                    ON app.player TO shoulder_api;
GRANT SELECT, INSERT ON app.development_goal TO shoulder_api;
GRANT UPDATE (title, description, ontology_key, status, closed_at)
                                                    ON app.development_goal TO shoulder_api;
```

Column-level grants, not a `WITH CHECK` predicate, are what stop a coach moving a player
between teams or self-linking an account: `team_id` and `user_id` are simply not
updatable by the runtime role, so `private.link_player_account` is the only link path.

## API

`snake_case` bodies. Creates return `201`. Every error body is RFC 9457 problem details
with `type`, `title`, `status`, `detail`, `instance` and no names, emails, SQL, tokens,
or provider errors. Problem `type` values live under `https://shoulder.local/problems/`.

Status contract for this block:

| Case | Status |
|---|---|
| No or invalid bearer token | 401 |
| Authenticated, resource visible, wrong role for the action | 403 |
| Resource absent or hidden by RLS | 404 |
| Duplicate active jersey, already-linked player, second active goal, invalid status transition | 409 |
| Field validation, bulk row validation | 422 |

Response models (Pydantic, `services/api/schemas.py`):

```
TeamSummary       team_id, name, age_group, season_label, role
RosterPlayer      id, team_id, display_name, jersey_number, position, active,
                  account_name (str | None), active_goal (GoalSummary | None)
PlayerCreate      display_name (1..80), jersey_number (0..99 | None), position (1..40 | None)
PlayerPatch       display_name?, jersey_number?, position?      (all optional, >=1 set)
BulkRow           display_name, jersey_number, position
BulkRequest       commit (bool, default false), rows (1..40 BulkRow)
BulkRowResult     index, display_name, jersey_number, position, errors (list[str])
BulkResult        committed (bool), rows (list[BulkRowResult]), created (list[uuid])
InviteRequest     email
InviteResult      player_id, user_id
GoalCreate        title (1..100), description (<=1000 | None), ontology_key (1..80 | None)
GoalPatch         title?, description?, status?                  (all optional, >=1 set)
GoalSummary       id, title, status
Goal              id, player_id, title, description, ontology_key, status,
                  created_by, created_at, closed_at
```

`ontology_key` is accepted but never rendered by the web app.

`RosterPlayer.account_name` is the linked account's display name and comes only from
`private.team_roster(team_id)`, the Task 5 helper built for exactly this consumer. It is
`null` for an unlinked roster row. No email ever appears in a roster response. The roster
list is one query:

```sql
SELECT p.id, p.team_id, p.display_name, p.jersey_number, p.position, p.active,
       r.account_name, g.id AS goal_id, g.title AS goal_title, g.status AS goal_status
FROM app.player p
LEFT JOIN private.team_roster(:team_id) r ON r.player_id = p.id
LEFT JOIN app.development_goal g ON g.player_id = p.id AND g.status = 'active'
WHERE p.team_id = :team_id AND p.deleted_at IS NULL AND p.deletion_pending_at IS NULL
ORDER BY p.jersey_number NULLS LAST, p.display_name
```

Goal status transitions: `active → achieved | paused | retired`, `paused → active |
retired`. `achieved` and `retired` are terminal. Any other pair is `409`. Leaving
`active` sets `closed_at = now()`; entering `active` clears it and is refused with `409`
when another active goal exists for that player.

Bulk semantics: validate all rows, including duplicate jersey numbers inside the request
and against the existing active roster. `commit=false` returns `200` with per-row
results and writes nothing. `commit=true` with any invalid row returns `422` with the
same per-row results and writes nothing. `commit=true` with all rows valid writes them
in one transaction and returns `201`. Never write a valid subset.

## Web

- Types come only from `@shoulder/contracts`; no hand-written request/response interfaces.
- Server Components by default. Client components only for the bulk paste parser, inline
  add row, and the confirm dialogs.
- `/` resolves the session, calls `/v1/me`, and redirects `coach → /coach/roster`,
  `player → /player`, no role → the existing neutral signed-in state. `/player` is not
  built in this block; the redirect target for a player is the neutral signed-in page
  until Block 06.
- Authorization is never inferred from route or client state.

# Parallel Workstreams

| Lane | File | Writes |
|---|---|---|
| Database | `project-01-roster-goals/database.md` | `migrations/versions/0004_*.py` |
| Backend | `project-01-roster-goals/backend.md` | `services/api/{schemas,routes,problems}.py`, `tests/test_api_roster.py` |
| Frontend | `project-01-roster-goals/frontend.md` | `apps/web/app/coach/**`, `apps/web/app/page.tsx`, `apps/web/lib/api.ts` |
| Isolation tests | `project-01-roster-goals/tests.md` | `tests/test_database_roster.py`, `tests/isolation_fixtures.py` |

The coordinator owns `packages/contracts/*` (generated), `STATUS.md`, and this directory.

# Dependency Graph

- **Database** and **Frontend** start immediately. The frontend codes against the frozen
  response models above and the generated contract, not a running database.
- **Backend** starts immediately against the frozen migration `0004` object names; it is
  integrated after the database lane so its tests can run against a real migration.
- **Isolation tests** start immediately: the policy matrix above is frozen, so the suite
  is written against policy names and expected outcomes.
- Contract regeneration (`export_openapi` + `contracts`) happens once, in the
  coordinator's integration pass, after the backend lane lands.

# Integration Order

1. Database (`0004`), verified by `scripts/check-db.ps1` upgrade/downgrade/upgrade.
2. Isolation tests, run against `0004`.
3. Backend, then regenerate `packages/contracts/*`.
4. Frontend, against the regenerated contract.
5. Coordinator integration pass: cross-lane review, `scripts/check.ps1`.

# Verification

- `.\scripts\check-db.ps1` — migration upgrade, existing 75 isolation tests, and the new
  roster/goal isolation tests, all through the `shoulder_api` runtime role.
- Alembic `upgrade head` → `downgrade 0003_roster_display` → `upgrade head`, proving the
  `0004` downgrade restores exactly the `0003` state.
- `uv run python -m unittest tests.test_api_roster` — 401/403/404/409/422 cases,
  bulk preview, bulk all-or-nothing, invitation transaction, archive, goal transitions.
- `.\scripts\check.ps1` — Biome, TypeScript, Node tests, Ruff, mypy, Python tests,
  generated-contract drift, production build, Playwright smoke, `git diff --check`.
- Playwright: keyboard and screen-reader flow through the bulk paste, preview, and
  confirm path, plus the inline add row, at the widths named in
  `docs/09-frontend-design-system.md`.
- Timed acceptance: 20 players added in under five minutes with no email collected.

# Remote Verification

`Shoulder Dev` (`gzbwlancwxhtausyokxt`) only.

- Confirm the remote Alembic revision is `0003_roster_display` before any change.
- Apply `0004` through the repository migration workflow, never through the dashboard.
- Confirm `0004` policies, column-level grants, and role separation read back correctly.
- Exercise the roster and goal paths with disposable fixtures, then remove them.
- Do not downgrade `Shoulder Dev`; reversibility is proven locally.
- No secret value is printed or committed.

# Definition of Done

- Task 6: a coach adds 20 players in under five minutes without collecting player emails;
  API returns the correct 401/403/404/409/422; bulk is all-or-nothing; the keyboard and
  screen-reader form flow passes.
- Task 7: a roster player has an active goal in the coach interface; a player reads only
  their own goal; a second active goal is rejected; a coach outside the team is denied.
- `0004` upgrade, downgrade, and re-upgrade pass locally; `0004` is applied to
  `Shoulder Dev`.
- `scripts/check-db.ps1` and `scripts/check.ps1` pass with no suite skipped.
- `docs/projects/project-01-roster-goals-verification.md` maps both tasks to evidence.
- No Block 02 work, no secrets, no machine-specific state in the diff.
