# Project 01 verification — Roster and development goals

Evidence index for the project block covering **Task 6** and **Task 7**. It
replaces per-task narrative records for these two tasks.

- Base `main`: `cf7d0a08265691c11531afae07d77b38af59661e`
- Branch: `project-01-roster-goals`
- Verified: 2026-09-08
- Remote development project: `Shoulder Dev` (`gzbwlancwxhtausyokxt`), PostgreSQL 17

## Task requirements to evidence

| Task / requirement | Implementation | Test / evidence | Local | Remote | Status |
|---|---|---|---|---|---|
| **T6** team/roster API | `services/api/routes.py` | `tests/test_api_roster.py` | 25 passed | 25 passed | Done |
| **T6** bulk preview and commit | `routes.py` bulk route, `apps/web/lib/roster.ts` | `test_api_roster.py` bulk cases; `tests/roster.test.mjs` (8) | passed | passed | Done |
| **T6** bulk all-or-nothing | one transaction; preview writes nothing | row-count assertions before/after preview and rejected commit | passed | passed | Done |
| **T6** single-player edits | `PATCH /v1/players/{id}` | 409 duplicate jersey, 422 empty patch | passed | passed | Done |
| **T6** archive | `POST /v1/players/{id}/archive` | idempotent twice, row retained, number reusable | passed | passed | Done |
| **T6** invitation/link transaction | `private.link_player_account` | link + membership asserted in one transaction | passed | passed | Done, scoped by ADR 0017 |
| **T6** API 401/403/404/409/422 | `services/api/problems.py` | all five asserted across the ten routes | passed | passed | Done |
| **T6** keyboard and screen-reader form flow | `apps/web/app/coach/roster/**` | `tests/roster.spec.mjs` 9 tests × 3 engines | 9 passed | n/a | Done |
| **T6** done: 20 players, no emails | bulk paste → preview → commit | bulk commit of 20 rows; no address in any roster response or DOM | passed | passed | Done |
| **T7** goal schema | `migrations/versions/0004_roster_goals.py` | `tests/test_database_roster.py` | 30 passed | passed | Done |
| **T7** one active goal per player | `development_goal_active_key` partial unique index | second active goal → `23505` → 409 | passed | passed | Done |
| **T7** explicit status transitions | `TRANSITIONS` in `routes.py` | four invalid transitions → 409; `closed_at` coherence `23514` | passed | passed | Done |
| **T7** player reads only own goal | `development_goal_player_select`, `private.is_player_self` | player A1 vs A2 vs B1; hidden goal reads as a random UUID does | passed | passed | Done |
| **T7** coach outside team denied | `development_goal_coach_*`, `private.is_player_coach` | other coach: 0 rows, unchanged row, 404 at the API | passed | passed | Done |
| **T7** goal UI | `apps/web/app/coach/players/[player_id]/**` | `roster.spec.mjs` set-a-goal flow | passed | n/a | Done |

## Shared contracts frozen for this block

- Migration `0004_roster_goals`: `app.development_goal`; `private.is_player_coach`,
  `private.is_player_self`, `private.link_player_account`; policies
  `player_coach_insert`, `player_coach_update`, `development_goal_coach_select`,
  `_coach_insert`, `_coach_update`, `development_goal_player_select`.
- Column-level write grants, not a policy predicate, bound the roster write surface.
  Verified on `Shoulder Dev`: `player` INSERT is `(team_id, display_name,
  jersey_number, position)` and UPDATE is `(display_name, jersey_number, position,
  active, deleted_at)`, so `user_id` and `team_id` are not writable by the runtime
  role at all; `development_goal` UPDATE excludes `player_id` and `created_by`.
- Ten API routes with RFC 9457 problem details and the 401/403/404/409/422 table.
- `RosterPlayer.account_name` comes only from `private.team_roster`.
- Generated TypeScript types only; no hand-written parallel API types.

## Workstreams

Four parallel subagents, one writer per area: database (`0004`), backend (routes,
schemas, problem details, API tests), isolation tests, frontend. The coordinator
froze contracts, reviewed every diff, applied two post-freeze contract amendments,
resolved the defects below, regenerated contracts, and ran all verification.

## Coordinator repairs during integration

1. **`private.is_player_self` omitted the membership check.** Migration `0002`
   exists solely to add that check to `player_visible_select` after a Task 4
   review found revoked-player access. The frozen contract reproduced the bug one
   table over: a player whose membership was revoked would have kept reading their
   coach-authored goals. Fixed in `0004`; asserted by
   `test_revoked_membership_hides_the_goal`.
2. **Invitation could not create an account.** `app.user_account.id` references
   `auth.users(id)`, so no profile row can exist before its Auth identity, and the
   definer holds no privilege on `auth`. The create branch could only ever fail.
   Scoped to linking, recorded in
   [ADR 0017](../decisions/0017-invitation-links-existing-accounts.md); an unknown
   address returns 422 `invitation-account-not-found` and writes nothing.
3. **`apps/web/proxy.ts` did not cover `/` or `/coach/**`.** Both render verified
   sessions, so a refreshed token was never written back and the session would have
   expired silently mid-use. Matcher extended.
4. **Client action state lost across server-driven layout swaps.** The roster and
   goal forms unmounted when the content they created appeared, taking their own
   confirmation with them and leaving a screen reader with silence. Each form now
   holds a stable slot; the goal panel and its form are one mounted component.
5. **Content outside a landmark.** The team and season line below 1280px was a bare
   paragraph; axe flagged it. Now a labelled `section`.
6. **Merged Task 4/5 constants predated a runtime write surface.** Widened the
   reviewed policy, function, and grant snapshots; replaced
   `assertIsNone(row.with_check)` — which encoded "no runtime policy may authorize a
   write" — with a per-verb shape check requiring INSERT to carry a check and UPDATE
   to carry both halves, per `docs/03-schema.md`. Stricter than what it replaced.
7. **The API suite was outside the database discovery pattern.** `test_database*.py`
   would have skipped `tests/test_api_roster.py` silently. `scripts/check-db.ps1` and
   CI now discover `test_*.py`.
8. **Task 1 brand evidence had no public page.** `/` is now a redirect, so the
   approved wordmark and mark moved to `/auth/sign-in`, the public entry, keeping
   `tests/smoke.spec.mjs` at full strength.

## Commands and results

| Command | Result |
|---|---|
| `.\scripts\check.ps1` | passed — Biome, TypeScript, 15 Node tests, Ruff, mypy, contract drift, production build, browser-secret scan, 3 smoke browsers, `git diff --check` |
| `.\scripts\check-db.ps1` | **139 passed**, 0 skipped where required |
| `.\scripts\check-roster.ps1` | **9 passed** (3 tests × Chromium, Firefox, WebKit) |
| Alembic `upgrade head` → `downgrade base` → `upgrade head` | passed; at base: 0 tables, 0 private functions, 0 triggers, no Shoulder roles |
| `git diff --check` | clean |

## Remote verification — Shoulder Dev

Pre-deployment revision `0003_roster_display`, as expected. `0004` applied through
the repository Alembic workflow, never the dashboard. The project was not
downgraded; reversibility is proven locally.

| Check | Result |
|---|---|
| Revision after deployment | `0004_roster_goals` |
| Isolation suites through the real runtime login | **104 of 105 passed**, 4 mutation checks excluded |
| Destructive downgrade test | refused, as designed: "Destructive database tests require literal local URLs" |
| API roster suite | **25 passed** |
| Policies / private helpers / forced-RLS tables | 15 / 9 / 5 |
| `anon`, `authenticated`, `PUBLIC` grants on `app` and `private` | **0** |
| Column-level write grants | match the contract exactly |
| Fixtures after the run | 0 Auth users, accounts, teams, memberships, players, goals |

No secret value was printed, logged, or committed. `.env.remote` and
`supabase/.temp` remain ignored.

## Remaining risks

- Invitation cannot onboard an address that has never signed in. Deliberate and
  recorded in ADR 0017; Task 20 owns identity creation with email delivery.
- `PATCH /v1/players/{player_id}` has no web consumer yet: the coach detail page
  offers no player edit form in this block. The route is covered by API tests.
- `scripts/check-roster.ps1` is not yet wired into CI; it needs the loopback auth
  stack, like `scripts/check-auth.ps1`, which is also local-only today.
- The roster list calls `private.team_roster` once per row. Correct and bounded at
  40 rows; a player-scoped helper is the upgrade path if a team ever grows.

## Deferred to later blocks

`game`, `video`, upload, queue, observation, judgment, publication, evidence clip,
reflection, email, retention, and deletion. No Block 02 work is present in this
diff.

## Environment note

Docker Desktop 4.90.0 failed to start three times with the stale-socket fault
already recorded in `docs/task-2-verification.md`
(`rename ... .stale: The file cannot be accessed by the system`). Repaired the
documented non-destructive way — the orphaned socket directories were renamed to
timestamped backups while Docker was stopped — not by "Reset to factory defaults",
which Docker offered and which would have destroyed the local volumes. No Shoulder
data was touched. Roughly a dozen such backup directories have now accumulated
under `%LOCALAPPDATA%`; they are outside the repository and safe to delete.
