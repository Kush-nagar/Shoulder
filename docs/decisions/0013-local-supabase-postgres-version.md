# ADR 0013 — Local Supabase Postgres compatibility

- Status: local-only exception under the Task 2 incompatibility clause
- Date: 2026-09-05

Task 2 requires CLI-managed Auth/Postgres and explicitly permits an ADR when
the local image cannot match Postgres 16. The checksum-verified official CLI
2.116.0 rejects `db.major_version = 16` with `Invalid db.major_version: 16`.
Its generated configuration uses 17; `supabase services` resolves
`supabase/postgres:17.6.1.165` and `supabase/gotrue:v2.196.0`.

Use this supported Postgres 17 image for the local infrastructure only. Do not
run a second database or replace the Supabase image with vanilla Postgres 16.
The production Postgres 16 target and product schema contract remain unchanged.
Resolve production/local major-version compatibility before Task 4 migrations;
passing local infrastructure checks is not evidence of Postgres 16 compatibility.
Task 2 adds no product tables, roles, RLS policies, or application migrations.

Evidence: official [CLI release](https://github.com/supabase/cli/releases/tag/v2.116.0),
executed `init`, `services`, and invalid-version probe. The current
[Supabase changelog](https://supabase.com/changelog) also records the self-hosted
default transition from Postgres 15 to 17; it does not establish Postgres 16 support.
