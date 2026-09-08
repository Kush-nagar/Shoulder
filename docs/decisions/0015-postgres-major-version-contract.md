# ADR 0015 — Postgres major version contract

- Status: accepted
- Date: 2026-09-07
- Supersedes the production Postgres 16 target in ADR 0013 and the earlier
  architecture, schema, and task documents.

Task 4 may not author migrations while local and production claim different
Postgres major versions. Investigation shows the mismatch is a stale target,
not a defect: Postgres 16 is not a version Supabase offers.

Evidence, all re-verified on 2026-09-07:

- The pinned CLI 2.116.0 refuses the configured target. With
  `db.major_version = 16` in an isolated copy of `supabase/config.toml`, the CLI
  exits non-zero with `Failed reading config: Invalid db.major_version: 16.`
- Requesting 16 selects no 16 image. `supabase services` on that same copy still
  resolves `supabase/postgres:17.6.1.165`.
- The hosted platform has no 16 major. Supabase's upgrade documentation
  describes Postgres 15 to Postgres 17 `pg_upgrade` paths only, and hosted
  projects on this account report `postgres_engine: 17`, `release_channel: ga`,
  running 17.6.1.x.

Adopt Postgres 17 as the single contract for local development and production.
The local image stays the CLI-pinned `supabase/postgres:17.6.1.165`; a hosted
project is provisioned on the platform's Postgres 17 GA release channel. This
removes the divergence rather than defending it: migrations authored and tested
locally now run on the same major version in production.

`scripts/infra.ps1 health` fails when the running server is not 17.6.x, and
`tests/repository.test.mjs` fails when `supabase/config.toml`, that runtime
check, and the documented stack contract stop agreeing. Local infrastructure
checks are therefore evidence for the production major version, which they were
not under ADR 0013.

Provisioning a hosted project, its region, and its exact patch level remain
owner inputs. Confirm the project reports `postgres_engine: 17` before the first
production migration; a future platform major requires a new ADR and a migration
plan, not a silent pin change.
