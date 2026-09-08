-- CI-only stand-in for the Supabase-managed objects the Task 4 migration binds
-- to. It creates nothing the migration itself owns: the schema, tables, roles,
-- policies, and grants under test all come from Alembic.
--
-- The authoritative verification runs against the real local Supabase stack
-- through scripts/check-db.ps1. This fixture only lets the same isolation suite
-- gate every pull request on a plain Postgres service container.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY,
    instance_id uuid,
    aud text,
    role text,
    email text,
    raw_user_meta_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Supabase enforces one account per address; the suite relies on that shape.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_partial_key
    ON auth.users (email) WHERE email IS NOT NULL;

DO $$
BEGIN
    -- Browser-facing Data API roles. The migration revokes their access; they
    -- must exist for that revoke to be meaningful.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
    END IF;
END $$;
