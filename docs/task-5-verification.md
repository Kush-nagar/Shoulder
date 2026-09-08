# Task 5 verification record

Repository `D:\Shoulder`, branch `task-5-rls-isolation`, base `86773f0` (merged
`main`); one writer. Date: 2026-09-08.
Status: **verified locally and in Shoulder Dev; not merged**.

## Scope and contract

Read `CLAUDE.md`, the Task 5 entry in `docs/06-tasks.md`, the RLS access matrix
and identity sections of `docs/03-schema.md`, the role/grant rules in
`docs/10-security-privacy.md`, the isolation-matrix rules in
`docs/11-testing-quality.md`, and ADR 0006. Task 4 is merged as PR #5, and its
schema, roles, and ownership are treated as accepted.

Task 5 extends Task 4's policies and mandatory runtime-role harness: reusable
fixtures for later schema tasks, the completed access matrix, mutation checks,
pooled-context regressions, and policy/grant/role snapshots. It introduces no
first protection for an existing table and adds no Task 6 schema — no goal,
observation, judgment, publication, evidence, clip, reflection, or retention
object exists on this branch.

## Migration

`migrations/versions/0003_roster_account_display.py`, revision
**`0003_roster_display`** from `0002_task4_privileges`.

The matrix grants a coach "self; limited linked roster display through safe
query" on `user_account`, while direct table access stays self-only. That is the
one matrix element Task 4 left open. It ships here as a single narrowly scoped
helper rather than a broader policy:

`private.team_roster(uuid)` returns `(player_id, player_name, account_name)` for
one team. It is `SECURITY DEFINER`, owned by `shoulder_migration`, pinned to
`search_path = ''`, revoked from `PUBLIC`/`anon`/`authenticated`, granted only to
`shoulder_api`, and authorizes on `private.is_team_coach(p_team_id)` — the
caller's own membership, never an argument. It exposes no address, and it skips
soft-deleted and deletion-pending rows. Downgrade drops it.

No policy, grant, role, or ownership from Task 4 was widened. The runtime role
remains `LOGIN`, `NOBYPASSRLS`, owner of nothing, `SELECT`-only, with no role
membership, and cannot execute the operator bootstrap.

## Harness

`tests/isolation_fixtures.py` is the reusable fixture module later schema tasks
extend. It builds one `World` through the admin connection and exposes
`read_as`, `add_membership`, and `revoke_membership` helpers:

| Identity | Role |
|---|---|
| Coach A | coach of team A |
| Player A1, Player A2 | linked players on team A |
| Coach B | coach of team B |
| Player B1 | linked player on team B |
| Unlinked | authenticated account with no membership and no player row |
| Unlinked roster row | team A roster row with no linked account |

`tests/test_database_isolation.py` holds the Task 5 suite. Every authorization
assertion runs through the real `shoulder_api` login, never as owner or
superuser. Refused reads assert an **empty result** rather than an error, so an
unauthorized identity cannot learn whether a row exists; refused writes assert
`42501`.

### Policy, grant, and role snapshots

- The exact set of eight policies (table, name, command, roles) must match; any
  added, removed, or renamed policy fails.
- Every runtime policy must consult the caller's identity directly or through a
  membership helper, must not be `true`, and must carry no `WITH CHECK`.
- All four tables: RLS enabled, forced, owned by `shoulder_migration`.
- Runtime grants are exactly `SELECT` on the four tables; runtime `EXECUTE` is
  exactly `current_user_id`, `is_team_member`, `is_team_coach`, `team_roster`;
  operator `EXECUTE` is exactly `bootstrap_initial_team`.
- Every `private` helper is owned by `shoulder_migration` with `search_path=""`,
  and that owner is neither superuser nor `BYPASSRLS`.
- `SET ROLE` to `shoulder_operator`, `shoulder_migration`, and `postgres` is
  refused with `42501`.

### Access matrix

Positive: coach A reads exactly team A, its three roster rows, its memberships,
and their own account; player A1 reads exactly their own player row, team,
membership, and account; coach A's roster display returns all three team A
players including the unlinked roster row; an account that coaches team A and
plays for team B reads both teams and only its own rows in each.

Negative: cross-team reads of `team`, `player`, `team_membership`, and
`user_account` by known UUID are empty for both a coach and a player; a player
cannot read a teammate's roster row or account; an unlinked identity reads only
its own account and nothing else; a known unauthorized identifier returns
exactly what an unknown identifier returns, so existence is not disclosed;
`INSERT`, `UPDATE`, and `DELETE` on all four tables are denied for both a coach
and a player identity (24 cases); the runtime cannot call the operator
bootstrap; the roster display returns nothing for another team, a player, an
unlinked identity, or a missing context.

### Revocation

Revoking a coach's membership empties `team`, `team_membership`, `player`, and
the roster display on the next transaction. Revoking a player's membership
removes their own roster row and team. Revocation also takes effect on an
already-open pooled connection, so no cached connection keeps stale access.

### Context and pooling

Identity is transaction-local: it is absent in the next transaction on the same
connection, and a rolled-back transaction leaves none behind. A reused
connection switching between coach A, coach B, an unlinked account, and player
A1 returns each identity's own rows. Missing, empty, malformed, injection-shaped,
and truncated `app.user_id` values read nothing from every table rather than
raising. Three concurrent connections with different identities do not interfere.

### Mutation checks

Three checks temporarily weaken live policies and prove the suite notices:
broadening `team_member_select` to `true` breaks cross-team isolation, dropping
`player_visible_select` removes a coach's own roster, and broadening
`team_membership_visible_select` exposes another team's memberships. Each
restores the original policy. They run only when `ALLOW_POLICY_MUTATION=1`,
which `scripts/check-db.ps1` sets for the disposable local database; the hosted
project is never mutated.

## Harness defect repaired

PR #5 flagged that `DatabaseTestCase` skipped on `ADMIN_URL and RUNTIME_URL`
while `setUpClass` also opened an operator engine, so a two-of-three
configuration failed inside `create_engine("None")` instead of skipping.
`database_urls_configured()` now gates both database suites on all three URLs,
and a regression test asserts the guard's truth table for all eight
combinations and that both suites carry it. The `REQUIRE_DATABASE_TESTS` guard
still fails when it is set without a complete configuration, so CI cannot skip
silently.

A second real defect surfaced while running both suites together: the migration
test downgrades to base, which drops the login roles, leaving later suites
unable to authenticate. The migration test now restores the configured logins
after its final upgrade, quoting the credential through Postgres `format`
without interpolating or logging it.

## Verification

| Command | Result |
|---|---|
| Local Task 4 head → `upgrade head` → isolation suite | applied `0003_roster_display`; 28 isolation tests passed |
| Local `downgrade 0002_task4_privileges` | `private.team_roster` gone, revision back to `0002_task4_privileges` |
| Local `upgrade head` again → isolation suite | helper restored, revision `0003_roster_display`, 28 tests passed |
| `.\scripts\check-db.ps1` | **67 passed** (38 Task 4 + 29 Task 5, including three mutation checks and full base downgrade/re-upgrade) |
| `.\scripts\check-auth.ps1` | 6 real-stack browser tests passed (Chromium, Firefox, WebKit) |
| `.\scripts\check.ps1` | passed; 76 Python tests with the database suites skipping cleanly when unconfigured |
| `git diff --check` | passed |

CI runs the isolation suite as a required step: the workflow's discovery
pattern is now `test_database*.py`, so both suites gate every pull request
against the pinned Postgres service.

## Shoulder Dev

Deployed to the already-linked development project (`Shoulder Dev`, region
`us-east-1`, PostgreSQL 17). No project was created, reset, or altered by hand,
and no unrelated project was touched. Pre-deployment revision was
`0002_task4_privileges` as expected; post-deployment revision is
**`0003_roster_display`**, equal to the local head. The hosted project was not
downgraded.

Remote results:

| Check | Result |
|---|---|
| Isolation suite against Shoulder Dev through the real runtime login | **25 passed** (snapshots, access matrix, roster display, revocation, context isolation); mutation checks deliberately excluded |
| Policy set | Exactly the eight expected policies; zero permissive runtime policies |
| Helpers | Six `private` helpers, all `search_path=""`, owned by `shoulder_migration` |
| Browser-facing roles | `anon`, `authenticated`, `PUBLIC` hold zero grants on `app`/`private` |
| Data API | REST probes with the project's publishable key return **HTTP 406** for `app.user_account` and for `private.team_roster` |
| Fixtures | Cleaned up: zero Auth users, accounts, teams, memberships, players |

## Remaining risks

- The roster display helper has no API consumer yet; Task 6 owns the roster
  endpoints that will call it. Its authorization is covered by tests today.
- Mutation checks prove the harness detects three specific weakenings, not every
  possible one; the snapshot tests cover the rest of the policy surface.
