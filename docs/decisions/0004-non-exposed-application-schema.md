# ADR 0004 — Non-exposed Supabase application schema

- Status: Accepted
- Date: 2026-08-24

## Context

Shoulder uses Supabase Auth but sends product requests through a same-origin Next.js BFF to FastAPI. The product does not need Supabase's browser Data API. Leaving youth-sports tables in an exposed schema would add another reachable surface and blur the distinction between Data API grants and RLS.

## Decision

1. Product tables live in an `app` schema that is absent from Supabase Data API exposed schemas.
2. FastAPI connects directly to Postgres through a least-privilege `NOBYPASSRLS` role with an explicit search path.
3. RLS remains enabled and forced where designed as defense in depth.
4. Auth synchronization and policy helpers live in `private`, use safe search paths and qualified names, and have explicit execution grants.
5. Migration and administrative roles remain separate from the user-request runtime role.

## Consequences

- The browser cannot bypass FastAPI by addressing product tables through the Data API.
- RLS still constrains missed service filters and direct runtime-role queries.
- SQLAlchemy models and migrations must specify the application schema consistently.
- Local and deployed tests must verify exposed-schema settings, grants, ownership, and RLS together.
