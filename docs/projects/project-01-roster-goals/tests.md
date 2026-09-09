# Workstream — Isolation tests

# Objective

Extend the Task 5 isolation harness to cover the migration `0004` roster write path and
`app.development_goal`, proving every policy through the production-equivalent
`shoulder_api` runtime role.

# Allowed Files / Areas

- `tests/test_database_roster.py` (create)
- `tests/isolation_fixtures.py` (extend only — additive helpers; do not change the
  meaning of `World`, `Team`, `build_world`, `read_as`, `add_membership`, or
  `revoke_membership`, because `tests/test_database_isolation.py` depends on them)

# Forbidden Files / Areas

- `tests/test_database_isolation.py`, `tests/test_database.py`, `tests/test_auth.py`,
  `tests/test_health.py` — merged Task 4/5 evidence. Do not edit, reorder, or weaken.
- `tests/test_api_roster.py` — the backend lane owns it.
- `migrations/**`, `services/**`, `apps/**`, `packages/**`, `scripts/**`, `docs/**`.

# Contracts

Read `docs/projects/project-01-roster-goals.md`, section **Shared Contracts → Database**.
Policy names, helper signatures, and the grant list are frozen; assert against those exact
names.

# Inputs

Read only:

- `tests/isolation_fixtures.py` — `World`, `Team`, `IsolationHarness`, `read_as`,
  `admin_insert_player`, `add_membership`, `revoke_membership`.
- `tests/test_database_isolation.py` — the existing assertion style, how a write is
  attempted through the runtime role, how a denial is distinguished from an empty result,
  and how `ALLOW_POLICY_MUTATION` gates mutation checks. Read it; do not change it.
- `tests/test_database.py` — `DatabaseTestCase`, `create_auth_user`, `admin_insert_team`,
  `as_user`, and the `REQUIRE_DATABASE_TESTS` requirement.

# Expected Outputs

`tests/test_database_roster.py`, built on `IsolationHarness`, asserting through the
runtime role:

**`app.player` writes**

- Coach A inserts a player on team A. Coach A cannot insert on team B.
- An insert with a non-null `user_id` is refused; the runtime role has no INSERT
  privilege on that column, so linking is impossible outside
  `private.link_player_account`.
- Coach A updates `display_name`, `jersey_number`, `position`, `active`, and `deleted_at`
  on a team A row. Coach B cannot. A player cannot update their own row.
- An update of `team_id` or `user_id` is refused for every identity, including the coach
  who owns the row — column-level grants, not a policy predicate.
- A duplicate active jersey on the same team raises `23505`; the same number on the other
  team, or on an archived row, succeeds.
- No identity can `DELETE` from `app.player`.

**`private.link_player_account`**

- Coach A links an unlinked team A row to a new email: `player.user_id` is set and a
  `team_membership (team_id, user_id, 'player')` row exists after the same transaction.
- Coach A linking an existing account uses that account rather than creating a second one.
- Coach B cannot link a team A row. A player cannot call it for their own row.
- Linking an already-linked row, or linking an account that already holds a row on that
  team, raises `23505`.
- An unlinked account cannot call it at all.

**`app.development_goal`**

- Coach A inserts a goal for a team A player; Coach B cannot; a player cannot insert their
  own goal.
- `created_by` must equal the caller; a spoofed `created_by` is refused.
- A second `active` goal for the same player raises `23505`; a second goal is accepted once
  the first is not `active`.
- Coach A selects and updates goals for team A players only. Coach B sees none and cannot
  update.
- Player A1 selects only their own goals: not A2's, not B1's. A player cannot update or
  insert any goal.
- An unlinked account sees no goal.
- A player whose membership is revoked mid-test loses goal visibility.
- A player whose row is archived (`deleted_at` set) or `deletion_pending_at` set loses
  goal visibility, because `private.is_player_self` excludes those rows.
- No identity can `DELETE` a goal, and no identity can `UPDATE` `player_id` or
  `created_by`.
- Deleting the player row cascades the goal away (assert through the admin connection).

**Policy and grant snapshot**

Extend the existing Task 5 approach: assert the exact set of policies on `app.player` and
`app.development_goal`, and the exact column-level privilege set held by `shoulder_api`,
so a later migration cannot silently widen them. Assert that `PUBLIC`, `anon`, and
`authenticated` hold no privilege on `app.development_goal` or the three new functions.

# Required Targeted Tests

```
.\scripts\check-db.ps1
```

This runs migration `0004`, the existing 75 isolation tests, and your new suite through
the real `shoulder_api` role. Every existing test must still pass unchanged. If migration
`0004` is not yet in your checkout, write the suite, report it as `not run — 0004 pending`,
and do not weaken an assertion to make anything green.

# Dependencies

Migration `0004` from the database lane. Write against its frozen names without waiting.

# Completion Report Format

Report in at most 25 lines:

1. Files created or changed, with line counts and the new test count.
2. Any additive helper added to `tests/isolation_fixtures.py`, and confirmation that no
   existing helper's behavior changed.
3. A compact list of the assertions, grouped by the four headings above.
4. Exact commands run and their results, including the existing suite's pass count.
5. Any policy or grant in the frozen contract you could not prove, and why.
6. Confirmation, `yes` or the exact problem, that: no existing test was edited, skipped,
   or weakened; every assertion runs through the `shoulder_api` role, not the owner; a
   denial is distinguished from an empty result set.
