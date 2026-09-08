# Task 4 verification record

Repository `D:\Shoulder`, branch `task-4-core-schema`, base `30fa84b` (merged
`main`); one writer. Date: 2026-09-08.
Status: **verified locally and in Shoulder Dev; not merged**. The linked
development project acceptance is satisfied by the deployment recorded below.

## Scope and contract

Read `CLAUDE.md`, the Task 4 entry in `docs/06-tasks.md`, the identity sections
and RLS matrix of `docs/03-schema.md`, the `/v1/me` and bootstrap rows of
`docs/04-api.md`, the role/grant rules in `docs/10-security-privacy.md`, the
Task 4 test rules in `docs/11-testing-quality.md`, and ADR 0006. Prerequisites
2 and 3 are merged, and the Postgres 17 contract (ADR 0015) is merged as PR #4.

Task 4 creates the `app` schema contents, the `private` helper boundary, the
four core identity tables, baseline RLS, separated database roles, the operator
bootstrap, and role-aware `/v1/me`. No observation, judgment, evidence,
publication, reflection, goal, clip, game, video, job, or retention table was
added. Task 5's full policy matrix and extended harness are not implemented.

## Schema

`migrations/versions/0001_core_identity_schema.py` creates, exactly as
`docs/03-schema.md` specifies:

- `app.user_account` — `id` is the Supabase subject: primary key, foreign key to
  `auth.users(id)` with `ON DELETE CASCADE`, and **no default**, so no second
  identity UUID can exist. Normalized unique `email`, 1–80 character
  `display_name`, `created_at`, `updated_at`.
- `app.team` — `name` 1–100, optional `age_group` 1–40, `season_label` 1–60,
  non-null `season_end_at`, `created_by` referencing `user_account` with
  `ON DELETE RESTRICT`, `created_at`.
- `app.team_membership` — primary key `(team_id, user_id)`, both foreign keys
  cascading, `role` checked against `coach`/`player`, `created_at`, and an index
  on `user_id`.
- `app.player` — `team_id` cascade, `display_name` 1–80, `jersey_number` 0–99,
  `position` 1–40, nullable `user_id` with `ON DELETE SET NULL`, `active`,
  `created_at`, `deleted_at`, `deletion_pending_at`; indexes on `team_id` and
  `user_id`; partial unique active jersey per team; partial unique
  `(team_id, user_id)` where `user_id` is not null.

A test asserts every `app` foreign key is covered by an index.

## Roles, ownership, and RLS

| Role | Purpose | Properties |
|---|---|---|
| `shoulder_migration` | Owns the schemas, tables, and helpers | `NOLOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`, `NOINHERIT` |
| `shoulder_api` | FastAPI runtime | `LOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`, `NOINHERIT`, `search_path = ''` |

Neither role has a password in version control. The migration creates them
idempotently; operators provision the runtime password out of band, and the two
local scripts generate a per-run password that is never written to disk.

Local `postgres` is not a superuser and cannot grant `auth` privileges, but it
does hold `REFERENCES`/`TRIGGER` on `auth.users`. Objects are therefore created
by the migration connection and then handed to `shoulder_migration`. Ownership
by a non-bypass role is what makes `FORCE ROW LEVEL SECURITY` real; because
forced RLS also binds the owner, each table carries one explicit
`*_owner_maintenance` policy scoped to `shoulder_migration` for migrations and
the definer helpers. `shoulder_api` owns nothing, holds no membership in any
`BYPASSRLS` or superuser role, and cannot disable RLS.

Helpers in `private`, all with `SET search_path = ''` and fully qualified
objects: `current_user_id()` (returns NULL for a missing or malformed
`app.user_id`, so a bad context selects no rows), `is_team_member(uuid)` and
`is_team_coach(uuid)` (SECURITY DEFINER, so membership policies do not recurse),
`bootstrap_initial_team(...)`, and `sync_user_account()`.

Baseline SELECT policies for `shoulder_api`: own account; teams where the caller
is a member; own memberships plus memberships of coached teams; players of
coached teams plus the caller's own linked row when it is neither soft-deleted
nor pending deletion and still has team membership. The runtime role is granted `SELECT` only, plus `EXECUTE`
on the three identity/membership helpers. ADR 0016 moves bootstrap execution
to the separate `shoulder_operator` role. Roster and product writes arrive with their own
policies in their owning tasks, so a self-signup identity cannot create a team
or a membership.

`PUBLIC`, `anon`, and `authenticated` are revoked from both schemas and from all
their tables, functions, and sequences, and `supabase/config.toml` still exposes
only `public` to the Data API. Both facts are asserted by tests.

## Identity synchronization and bootstrap

`private.sync_user_account()` runs `AFTER INSERT OR UPDATE OF email ON
auth.users`. It lowercases the address and takes `display_name` from
`display_name`/`full_name` metadata, falling back to the email local part; it
copies no authorization data, and team roles come only from `team_membership`.
The migration backfills existing Auth users. Deleting an Auth user removes the
profile through the cascade.

`private.bootstrap_initial_team()` takes an advisory transaction lock, refuses
to run when any team exists, validates the coach account, and inserts the team
and its coach membership in one transaction. `POST /v1/teams` gates it on an
`X-Operator-Token` header compared with `hmac.compare_digest` against
`OPERATOR_BOOTSTRAP_TOKEN`; an unset or short token disables the endpoint with
503. No session or signup path can reach coach privileges.

## API and web

- `GET /v1/me` opens one transaction as the runtime role, publishes the verified
  subject with transaction-local `set_config('app.user_id', ..., true)`, and
  returns the account, database-derived roles, team IDs, and linked player. An
  unlinked identity gets empty roles and teams and a null player.
- `services/api/db.py` owns the engine and the identity transaction. Because the
  setting is transaction-local, a pooled connection carries no identity.
- `apps/web/app/api/me/route.ts` is the same-origin BFF for that endpoint, and
  the proxy matcher now refreshes sessions for it. `apps/web/lib/api.ts` types
  the response from the generated OpenAPI contract, never by hand, and fails
  closed to "no product access" when the API is unavailable.
- `/auth/session` renders coach, player, and unlinked states from that data.
  Role-specific destinations do not exist until Tasks 6 and 7, so routing is
  role-aware content on the existing page rather than a redirect to a missing
  route.

## Dependencies

| Package | Version | Reason |
|---|---|---|
| `sqlalchemy` | 2.0.52 | Decided stack; runtime connection and transaction control |
| `alembic` | 1.19.2 | Decided stack; required migration tool |
| `psycopg[binary]` | 3.3.5 | Postgres driver for SQLAlchemy 2 |

No existing pin changed. `uv.lock` adds those three plus `greenlet`, `mako`,
`markupsafe`, and `tzdata`.

New server-only inputs: `DATABASE_URL` (runtime role), `MIGRATION_DATABASE_URL`
(Alembic only), `OPERATOR_DATABASE_URL` (bootstrap role only), and
`OPERATOR_BOOTSTRAP_TOKEN`. Examples contain loopback
addresses and blank placeholders only; no `NEXT_PUBLIC_` variable was added.

## Automated verification

| Command | Result |
|---|---|
| `alembic upgrade head` against the real local Supabase stack | Applied; Postgres 17.6 |
| `alembic downgrade base` then `upgrade head` | Both succeeded; asserted in `test_zz_downgrade_and_clean_reupgrade` |
| `.\scripts\check-db.ps1` | **34 passed** against real Supabase Postgres through the `shoulder_api` role |
| Same suite against a plain `postgres:17.6` container with the CI fixture | 34 passed, proving the CI path |
| `.\scripts\check-auth.ps1` | 6 real-stack browser tests passed (Chromium, Firefox, WebKit) |
| `.\scripts\check.ps1` | Passed in full; 43 Python tests with the database suite skipped when no database is configured |
| `git diff --check` | Passed; only the existing LF/CRLF notices |

The 34 database tests cover: migration downgrade and clean re-upgrade; profile
synchronization on insert, email change, and Auth deletion; display-name
fallback; duplicate active jersey rejection and jersey reuse after a player
leaves; duplicate linked player rejection; bounded-column checks; identity bound
to `auth.users` with no second UUID and no generated default; every foreign key
indexed; RLS enabled, forced, and owned by the non-bypass role; least-privileged
runtime role; `anon`/`authenticated` holding no schema, table, or function
privilege; definer helpers pinning an empty search path; the runtime role unable
to disable RLS; coach and player positive reads; cross-team and cross-player
reads empty; soft-deleted player losing their own row; INSERT, UPDATE, and
DELETE denial on all four tables; missing and malformed context reading nothing;
identity not surviving its transaction; membership revocation removing access on
the next request; operator bootstrap success, single-workspace rejection,
unknown-account rejection, and signup being unable to write teams or
memberships; and `/v1/me` for coach, player, unlinked, and unauthenticated
callers.

The isolation suite is mandatory in CI: `.github/workflows/ci.yml` now runs a
`postgres:17.6` service (digest pinned), applies `tests/fixtures/ci-auth-schema.sql`,
migrates, provisions a per-run runtime password, and runs the suite with
`REQUIRE_DATABASE_TESTS=1`. `ConfigurationTests` fails if that variable is set
without database URLs, so the suite cannot be skipped silently. The CI fixture
creates only the Supabase-managed objects Task 4 binds to (`auth.users` and the
browser-facing roles); everything under test still comes from the migration, and
the authoritative run is the real Supabase stack locally.

Task 3's browser suite was updated where Task 4 changed real behavior:
unauthenticated `/v1/me` is now 401 rather than a missing route, and the signed
-in unlinked account is asserted end to end through `/api/me` and the session
page. `scripts/check-auth.ps1` provisions the same per-run runtime credential so
that path runs against the real database.

## Failures investigated and repaired

- The first migration draft granted `auth` privileges to `shoulder_migration`.
  Local `postgres` is not a superuser and cannot grant them, so `CREATE TABLE`
  failed with `permission denied for schema auth`. Replaced with create-then-own,
  which needs no new `auth` grant at all.
- `pg_catalog.coalesce`/`nullif` are SQL constructs and cannot be schema
  qualified; the definer function now qualifies only real functions and calls
  `pg_catalog.now()` explicitly under its empty search path.
- Test fixtures deleted Auth users before product rows, which the intended
  `ON DELETE RESTRICT` on `team.created_by` correctly refused. Cleanup order was
  fixed rather than the constraint.
- `[System.Security.Cryptography.RandomNumberGenerator]::Fill` and
  `[Convert]::ToHexString` do not exist in Windows PowerShell 5.1; the scripts
  use `Create().GetBytes(...)` and `BitConverter` instead.
- Strict lint and typing findings (line length, `Any` returns) were fixed, and
  the deprecated Alembic `version_path_separator` was replaced with
  `path_separator`.

## Development Supabase project

**Provisioned, linked, deployed, and verified.**

| Fact | Value |
|---|---|
| Project | `Shoulder Dev`, created 2026-09-08 (no prior Shoulder project existed) |
| Organization | The account's only organization |
| Region | `us-east-1`, chosen by the owner |
| Cost | $0 per month; no plan change, purchase, or billing action |
| Status | `ACTIVE_HEALTHY` |
| Postgres | **17.6.1.166**, engine 17, `ga` release channel — matches ADR 0015 |
| Link | `supabase link --project-ref …` succeeded; the ref lives in git-ignored `supabase/.temp` |

`Cross` and `Cross.ai` were not used, altered, or read beyond listing them to
establish that no Shoulder project existed.

Pre-migration state of the linked project, checked before any schema change:
no `app` or `private` schema, no migration history, and zero Auth users. There
is nothing to conflict with and nothing that would justify a reset.

The migration runs as `postgres`, the only role holding `REFERENCES` and
`TRIGGER` on `auth.users`. Those privileges cannot be delegated: on the hosted
project `postgres` holds none of them *with grant option*, so no deploy role can
substitute, and Supabase refuses `ALTER ROLE postgres WITH PASSWORD` from SQL.
The owner supplied the database connection URL through git-ignored
`.env.remote`. This resolved the credential prerequisite; deployment then
proceeded as recorded below. No connection value is included here.

### Deployment, 2026-09-08

`alembic upgrade head` applied `0001_core_identity` and `0002_task4_privileges`
through the repository's normal workflow. Nothing was created by hand and no
dashboard SQL was used. Remote `app.alembic_version` reads
**`0002_task4_privileges`**, equal to the local head.

Remote schema: `app.user_account`, `app.team`, `app.team_membership`,
`app.player`, the five `private` helpers, and the
`sync_user_account_from_auth` trigger on `auth.users`.

Runtime and operator logins were provisioned with independently generated
credentials applied through the migration connection. They live only in
git-ignored `.env.remote`; no secret is in the repository, in documentation, in
a tracked `.env`, or in any browser-visible configuration.

Remote privilege state, read from the development database:

| Property | Result |
|---|---|
| Table ownership and RLS | All four tables owned by `shoulder_migration`, RLS enabled and forced |
| `shoulder_api` | `LOGIN`, `NOBYPASSRLS`, owns nothing in `app`/`private`, `SELECT` only |
| Role assumption | `shoulder_api` holds zero role memberships, so it cannot `SET ROLE` into the migration, operator, or any privileged role |
| `shoulder_operator` | Separate `LOGIN` role, `NOBYPASSRLS`, restricted to the bootstrap path |
| Helpers | `SECURITY DEFINER` where required, all owned by `shoulder_migration`, every one pinned to `search_path=""` |
| Browser-facing roles | `anon`, `authenticated`, and `PUBLIC` hold no grant and no schema `USAGE` on `app` or `private` |
| Data API | Live REST probes with the project's publishable key return **HTTP 406** for `app.user_account`, `app.player`, and `private.current_user_id`; neither schema is exposed |

Remote test run: 37 of the Task 4 tests against Shoulder Dev through the real
`shoulder_api` and `shoulder_operator` logins — profile synchronization,
duplicate active jersey rejection and reuse after a player leaves, duplicate
linked player rejection, revoked membership and revoked player linkage,
identity context isolation, runtime write denial, operator separation, and
`/v1/me` for coach, player, unlinked, and unauthenticated callers. All passed.
The migration downgrade test was deliberately excluded from the hosted project
and is proved locally instead. Disposable fixtures clean themselves up; the
project afterwards holds zero Auth users, accounts, teams, memberships, and
players.

### Defect found and repaired during deployment

Linking a hosted project makes the Supabase CLI adopt that project's Postgres
patch version locally: `supabase/.temp/postgres-version` became `17.6.1.166`,
so the next `scripts/infra.ps1 start` pulled an unpinned image instead of the
digest-pinned `17.6.1.165` and the local stack failed to come up. `start` now
discards a `postgres-version` override that disagrees with the pinned image, so
a linked project can never change the local image, and
`tests/repository.test.mjs` fails if that guard is removed. Reproduced by
planting the mismatched version file; the local stack then started on the pinned
image and the full suite passed.

## Remaining risks

- The CI fixture models `auth.users` rather than running Supabase, so a future
  Supabase change to that table would be caught locally rather than in CI.
- `/v1/me` returns 404 when a verified identity has no synchronized profile.
  The trigger and backfill make that state unreachable in normal operation.
- Coach and player destinations do not exist yet, so role routing is content on
  `/auth/session`. Tasks 6 and 7 own the real destinations.

## Independent Task 4 audit � 2026-09-08

Reviewed the actual diff from `main` at `e84edb2`, not the earlier result claims.
Task 4 explicitly owns baseline RLS, positive/negative isolation tests, revoked
membership, `/v1/me`, and `POST /v1/teams` operator bootstrap. No premature Task 5
implementation was found or removed. Its future full matrix and reusable
snapshot/mutation harness remain unstarted.

Confirmed defects and repairs:

- A revoked player still read their linked roster row because the policy omitted
  membership. Reproduced on real Supabase; migration 0002 requires membership,
  with database and `/v1/me` regression assertions.
- `shoulder_api` could execute the SECURITY DEFINER bootstrap directly, bypassing
  HTTP operator authorization. Reproduced its executable privilege. Migration
  0002 grants execution only to `shoulder_operator`; the endpoint requires a
  separately configured operator connection and rejects other connection roles.
  Tests cover runtime role separation and the narrow operator grants. ADR 0016
  documents provisioning and removal of this temporary credential.
- Base downgrade retained database roles, ownership and the migration CREATE
  grant. It now removes these, the private schema, helpers and Auth trigger.
  Only `app.alembic_version` bookkeeping remains; role absence is asserted and
  re-upgrade recreates roles without passwords. The destructive migration test
  now actually runs last, after all runtime/operator tests.
- Non-ASCII operator-token input caused `compare_digest` to raise TypeError.
  Compare encoded bytes so invalid input gets 401; a focused regression covers it.
- CI's fixed service password is replaced with a per-run disposable value;
  runtime/operator passwords are generated in-process. These are test-only
  credentials, with no production secret committed.

The SQL schema otherwise matches the four identity-table definitions: Auth UUID
FK without default, indexed FKs, bounded columns, cascade/restrict/set-null delete
behavior and both player partial unique indexes. Auth synchronization copies no
role metadata. All four tables retain enabled/forced RLS, owned by the non-bypass
migration role; helper ownership and empty search paths stay intact. Browser
roles cannot reach either schema. The BFF forwards only verified tokens, uses
no-store responses, and introduces no Supabase product-data client. The Task 3
404-to-401 assertion correctly follows the newly protected endpoint.

The plain PostgreSQL 17.6 fixture covers only Auth table/role dependencies;
it does not prove Supabase Auth behavior or remote Data API configuration.
Real local Supabase and browser authentication remain separate required checks.

At the earlier `a70ecc5` audit, external acceptance was blocked because no
project was linked. The Shoulder Dev deployment above supersedes that blocker
and satisfies the linked-development requirement. Task 5 remains unstarted.

Independent verification results (after repairs):

| Command / target | Result |
|---|---|
| `scripts/check-db.ps1`, real local Supabase PostgreSQL 17.6 | 38 passed |
| Alembic `upgrade head`, `downgrade base`, `upgrade head` on real Supabase | Passed; downgrade asserts zero product tables/helpers/Auth triggers and zero Shoulder roles |
| Exact CI image `postgres:17.6` at the workflow digest, fresh disposable database plus Auth fixture | 38 passed, including clean upgrade/downgrade/re-upgrade; container removed |
| `scripts/check-auth.ps1` | 6 passed across Chromium, Firefox and WebKit |
| `scripts/check.ps1` | Passed: formatting/lint/types, 6 Node tests, Python 47 collected (12 passed, 35 DB tests intentionally skipped here and run separately above), generated-contract drift, build, browser-secret scan and 3 browser smoke tests |
| `git diff --check` | Passed |

The first independent database run reproduced two failures (revoked-player row
visibility and runtime bootstrap execution); both pass after repair. A full-check
formatting failure in the new test code was corrected before the passing rerun.
That earlier audit included no project linking or Task 5 implementation. The
subsequent Shoulder Dev deployment is recorded above; neither change merges
the branch or introduces unrelated product work.

## Final delta review — 2026-09-08

Reviewed only `a70ecc5..c1b10a7` plus the focused repairs below.
Read-only checks targeted the locally linked project and confirmed its name is
Shoulder Dev, region `us-east-1`, hosted version `17.6.1.166` (engine 17), and
Alembic revision `0002_task4_privileges`. The runtime and operator credentials
both authenticated as their intended roles; no credential value was printed.
Live catalog queries confirmed all four tables retain forced RLS and migration
ownership, runtime SELECT-only grants, zero runtime/operator role memberships,
no runtime bootstrap execution, operator-only bootstrap execution, safe helper
ownership/search paths, the Auth trigger, and zero remaining fixture rows.
No other project was queried or changed in this review. Historical test counts
above are deployment-run evidence, not a claim that this review reran them.

The local guard itself needed no change: only a mismatched `postgres-version`
file is removed; image digest pinning and lifecycle commands remain intact.
The text-only regression accepted a commented-out removal command. Replaced it
with execution of the actual guard in disposable directories: mismatched state
is removed, matching/absent state is preserved, and project-ref, pooler and
unrelated temp files survive. Commenting out removal now makes the test fail;
the original source was restored after this mutation check. Secret-file checks
also explicitly cover `.env.remote` and linked-project temp files.

Corrected superseded deployment-blocked statements here and in `STATUS.md`.
No migration, role, product code, credential, remote configuration, or Task 5
change was made. The local startup guard was not modified by this review.


Delta-review verification: `node --test tests/repository.test.mjs` passed all
four tests; disabling the removal command caused the new regression to fail.
`scripts/check.ps1` passed formatting, lint, types, seven Node tests, Python
checks (12 passed, 35 database tests intentionally skipped), contract drift,
production build, browser-secret scan and all three browser smoke tests.
`git diff --check` passed. The initial formatting failure was corrected before
the successful full rerun. Unchanged expensive database/auth suites were not
rerun, and no hosted fixtures or migrations were executed in this review.
