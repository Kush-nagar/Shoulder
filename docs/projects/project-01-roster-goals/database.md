# Workstream — Database

# Objective

Write Alembic migration `0004_roster_goals`: roster write policies and column-level
grants on `app.player`, the `app.development_goal` table with RLS and grants, and the
`private` helpers named in the project's Shared Contracts. The downgrade must restore the
exact `0003_roster_display` state.

# Allowed Files / Areas

- `migrations/versions/0004_roster_goals.py` (create)

# Forbidden Files / Areas

- Any existing migration. `0001`, `0002`, and `0003` are merged and immutable.
- `services/**`, `apps/**`, `tests/**`, `packages/**`, `scripts/**`, `docs/**`.
- Any table, column, policy, or function not named in the project's Shared Contracts.
  No `game`, `video`, `observation`, `judgment`, `evidence_clip`, `review_publication`,
  `player_reflection`, `processing_job`, `product_event`.

# Contracts

Read `docs/projects/project-01-roster-goals.md`, section **Shared Contracts → Database**.
It is frozen. Implement it exactly: object names, columns, checks, index names, policy
names, helper signatures, and the grant list. Do not add, rename, or "improve" any of it.
If something in it is wrong or impossible, stop and report rather than deviating.

# Inputs

Read only these, and only for the patterns you must match:

- `migrations/versions/0001_core_identity_schema.py` — role constants, ownership moves,
  `ENABLE`/`FORCE` RLS, owner-maintenance policy, `SECURITY DEFINER` helper style,
  `REVOKE` from `PUBLIC`/`anon`/`authenticated`, and the downgrade shape.
- `migrations/versions/0003_roster_display.py` — the compact single-purpose migration
  style and its function ownership/grant/revoke sequence.

# Expected Outputs

- One migration file with `revision = "0004_roster_goals"` and
  `down_revision = "0003_roster_display"`.
- A short module docstring saying what the migration adds and why the write path is
  constrained by column-level grants rather than a `WITH CHECK` predicate.
- `upgrade()` creating, in order: `app.development_goal` with its checks and indexes; the
  three `private` helpers; ownership moves to `shoulder_migration`; `ENABLE` + `FORCE`
  RLS and the owner-maintenance policy on `app.development_goal`; the new policies on
  `app.player` and `app.development_goal`; the grants; the `PUBLIC`/`anon`/`authenticated`
  revokes for the new objects.
- `downgrade()` dropping every object this migration created, in reverse dependency
  order, including the new `app.player` policies and the column-level grants, so the
  database returns to exactly the `0003` state.
- Comments only where a reader would otherwise ask "why": the authorization-on-caller
  rule in the helpers, and the column-grant rationale.

# Required Targeted Tests

You do not write tests. The isolation-test lane owns them. Before reporting, confirm by
inspection that:

- `private.link_player_account` authorizes on `private.is_player_coach(p_player_id)` and
  never on an argument.
- Every new function is `SECURITY DEFINER SET search_path = ''` with all referenced
  objects schema-qualified.
- No new grant reaches `PUBLIC`, `anon`, or `authenticated`.
- There is no DELETE policy or DELETE grant on `app.player` or `app.development_goal`.
- `downgrade()` drops everything `upgrade()` created and nothing it did not.

# Dependencies

None. Start immediately.

# Completion Report Format

Report in at most 20 lines:

1. File created and its revision/down-revision.
2. Objects created, as a flat list of names.
3. Objects dropped by `downgrade()`, as a flat list.
4. Any place the frozen contract was ambiguous and the reading you chose.
5. Anything you believe is wrong in the frozen contract.
6. Confirmation of the five inspection points above, each `yes` or the exact problem.
