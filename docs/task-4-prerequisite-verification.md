# Task 4 prerequisite verification record — Postgres major version

Repository `D:\Shoulder`, branch `task-4-postgres-compatibility`, base
`4376d20` (merged `main`); one writer. Date: 2026-09-07.
Status: **prerequisite resolved**. Task 4 is not started; no product table,
migration, RLS policy, membership, or application schema was added.

## Scope

Resolve only the documented local Postgres 17 versus production Postgres 16
prerequisite recorded in ADR 0013, ADR 0014, and STATUS.md. Auth, session,
frontend, API, and dependency behavior are untouched.

## Previous mismatch

`AGENTS.md`, `docs/02-architecture.md`, `docs/03-schema.md`, `docs/06-tasks.md`,
and `README.md` contracted **production Postgres 16**, while `supabase/config.toml`
sets `major_version = 17` and `scripts/infra.ps1 health` requires a running
17.6.x server under ADR 0013's local-only exception. Task 4 authors the first
migrations, so migrations would have been written and tested on one major
version and deployed to another that was never verified.

## Investigation

The mismatch is a stale target, not a compatibility defect. Postgres 16 is not a
version Supabase offers. Evidence gathered on 2026-09-07:

| Check | Result |
|---|---|
| Pinned CLI 2.116.0 against `db.major_version = 16` in an isolated copy of `supabase/config.toml` (`supabase --workdir <scratch> status`) | Exit 1, `Failed reading config: Invalid db.major_version: 16.` |
| `supabase --workdir <scratch> services` with that same 16 configuration | Still resolves `supabase/postgres:17.6.1.165`; no 16 image exists in the pinned set |
| Supabase platform upgrade documentation | Documents Postgres 15 to Postgres 17 `pg_upgrade` paths only; no 16 major on the platform |
| Hosted Supabase projects readable from this account | Report `postgres_engine: 17`, `release_channel: ga`, versions 17.6.1.x |

The probe used a scratch copy; the repository configuration was never set to 16.

## Decision

[ADR 0015](decisions/0015-postgres-major-version-contract.md) contracts
**Postgres 17** for local development and production, superseding ADR 0013's
production Postgres 16 target. Local stays on the CLI-pinned
`supabase/postgres:17.6.1.165`; a hosted project is provisioned on Postgres 17
GA. No image, pin, CLI version, or dependency was upgraded or downgraded: the
running stack already matched the new contract, and only the stale documented
target changed.

Provisioning the hosted project, its region, and its patch level remain owner
inputs. Confirm the project reports `postgres_engine: 17` before the first
production migration.

## Actual runtime version

```text
SELECT current_setting('server_version'), current_setting('server_version_num');
17.6|170006

SELECT version();
PostgreSQL 17.6 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 15.2.0, 64-bit
```

## Files changed

```text
AGENTS.md
README.md
STATUS.md
docs/02-architecture.md
docs/03-schema.md
docs/06-tasks.md
docs/decisions/0013-local-supabase-postgres-version.md
docs/decisions/0015-postgres-major-version-contract.md   (created)
docs/task-4-prerequisite-verification.md                 (created)
tests/repository.test.mjs
```

`supabase/config.toml`, `scripts/infra.ps1`, `infra/supabase-images.json`, and
every dependency pin are unchanged.

## Verification

| Command | Result |
|---|---|
| `supabase --workdir <scratch> status` with `major_version = 16` | Reproduced `Invalid db.major_version: 16.` before the fix |
| `node --test tests/repository.test.mjs` | 3 passed, including the new major-version agreement test |
| New test against drifted inputs (16 in config, infra pin, AGENTS.md, schema doc) | All four assertions reject the drift, so the check is not vacuous |
| `.\scripts\infra.ps1 start` / `health` | Auth, Postgres, mail, MinIO healthy; loopback-only ports; digest-pinned images |
| `docker exec … psql -Atc "SELECT version();"` | PostgreSQL 17.6 (`170006`) |
| `.\scripts\check.ps1` | Passed in full |
| `git diff --check` | Passed |
| `git status --short` | Clean after commit |

`tests/repository.test.mjs` now fails if `supabase/config.toml`, the
`scripts/infra.ps1` runtime version check, `AGENTS.md`, and `docs/03-schema.md`
stop agreeing on the contracted major version, so the local and production
contract cannot silently diverge again.
