"""Core identity schema, baseline RLS, and runtime role

Revision ID: 0001_core_identity
Revises:
Create Date: 2026-09-08

Creates the non-exposed `app` schema contents, the `private` helper boundary,
the separated migration/runtime roles, and baseline row-level-security policies
for the four core identity tables. Task 5 extends this policy harness; later
product tables arrive with their own policies in their owning tasks.

Objects are created by the migration connection, which holds the `auth.users`
privileges needed for the identity foreign key and synchronization trigger, and
are then owned by `shoulder_migration`. That owner is `NOBYPASSRLS`, so forced
row-level security is real for every role that can reach these tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_core_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
TABLES = ("user_account", "team", "team_membership", "player")
FUNCTIONS = (
    "private.current_user_id()",
    "private.is_team_member(uuid)",
    "private.is_team_coach(uuid)",
    "private.bootstrap_initial_team(uuid, text, text, timestamptz, text)",
    "private.sync_user_account()",
)


def upgrade() -> None:
    # Roles are cluster-level. Create them idempotently and never store a
    # password here; the operator sets the runtime password out of band.
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{MIGRATION_ROLE}'
            ) THEN
                CREATE ROLE {MIGRATION_ROLE} NOLOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOBYPASSRLS NOINHERIT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{API_ROLE}'
            ) THEN
                CREATE ROLE {API_ROLE} LOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOBYPASSRLS NOINHERIT;
            END IF;
            -- Membership lets this connection hand ownership over; CREATE on
            -- the database is required of a schema's new owner.
            EXECUTE format('GRANT {MIGRATION_ROLE} TO %I', CURRENT_USER);
            EXECUTE format(
                'GRANT CREATE ON DATABASE %I TO {MIGRATION_ROLE}',
                pg_catalog.current_database()
            );
        END $$;
    """)
    # The runtime role resolves nothing implicitly; every object it touches is
    # schema-qualified by the API and by the policies below.
    op.execute(f"ALTER ROLE {API_ROLE} SET search_path = ''")

    op.execute("""
        CREATE TABLE app.user_account (
            id uuid PRIMARY KEY
                REFERENCES auth.users (id) ON DELETE CASCADE,
            email text NOT NULL
                CONSTRAINT user_account_email_normalized
                    CHECK (email = lower(email) AND char_length(email) BETWEEN 3 AND 320),
            display_name text NOT NULL
                CONSTRAINT user_account_display_name_length
                    CHECK (char_length(display_name) BETWEEN 1 AND 80),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX user_account_email_key ON app.user_account (email)"
    )

    op.execute("""
        CREATE TABLE app.team (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL
                CONSTRAINT team_name_length CHECK (char_length(name) BETWEEN 1 AND 100),
            age_group text
                CONSTRAINT team_age_group_length
                    CHECK (age_group IS NULL OR char_length(age_group) BETWEEN 1 AND 40),
            season_label text NOT NULL
                CONSTRAINT team_season_label_length
                    CHECK (char_length(season_label) BETWEEN 1 AND 60),
            season_end_at timestamptz NOT NULL,
            created_by uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX team_created_by_idx ON app.team (created_by)")

    op.execute("""
        CREATE TABLE app.team_membership (
            team_id uuid NOT NULL
                REFERENCES app.team (id) ON DELETE CASCADE,
            user_id uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            role text NOT NULL
                CONSTRAINT team_membership_role_allowed
                    CHECK (role IN ('coach', 'player')),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (team_id, user_id)
        )
    """)
    op.execute(
        "CREATE INDEX team_membership_user_id_idx ON app.team_membership (user_id)"
    )

    op.execute("""
        CREATE TABLE app.player (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id uuid NOT NULL REFERENCES app.team (id) ON DELETE CASCADE,
            display_name text NOT NULL
                CONSTRAINT player_display_name_length
                    CHECK (char_length(display_name) BETWEEN 1 AND 80),
            jersey_number smallint
                CONSTRAINT player_jersey_number_range
                    CHECK (jersey_number IS NULL OR jersey_number BETWEEN 0 AND 99),
            position text
                CONSTRAINT player_position_length
                    CHECK (position IS NULL OR char_length(position) BETWEEN 1 AND 40),
            user_id uuid REFERENCES app.user_account (id) ON DELETE SET NULL,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            deleted_at timestamptz,
            deletion_pending_at timestamptz
        )
    """)
    op.execute("CREATE INDEX player_team_id_idx ON app.player (team_id)")
    op.execute("CREATE INDEX player_user_id_idx ON app.player (user_id)")
    # One active shirt number per team, and one linked account per team.
    op.execute("""
        CREATE UNIQUE INDEX player_active_jersey_key
            ON app.player (team_id, jersey_number)
            WHERE jersey_number IS NOT NULL AND active AND deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX player_linked_account_key
            ON app.player (team_id, user_id)
            WHERE user_id IS NOT NULL
    """)

    # `app.user_id` is set transaction-locally by the API. A missing or
    # malformed value resolves to NULL, which selects no rows.
    op.execute("""
        CREATE FUNCTION private.current_user_id() RETURNS uuid
        LANGUAGE plpgsql STABLE SET search_path = '' AS $$
        DECLARE
            raw text := pg_catalog.current_setting('app.user_id', true);
        BEGIN
            IF raw IS NULL OR raw = '' THEN
                RETURN NULL;
            END IF;
            RETURN raw::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RETURN NULL;
        END $$;
    """)
    # Membership lookups are SECURITY DEFINER so policies on team_membership do
    # not recurse. Both read only the caller's own memberships.
    op.execute("""
        CREATE FUNCTION private.is_team_member(p_team_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.team_membership m
                WHERE m.team_id = p_team_id
                  AND m.user_id = private.current_user_id()
            )
        $$;
    """)
    op.execute("""
        CREATE FUNCTION private.is_team_coach(p_team_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.team_membership m
                WHERE m.team_id = p_team_id
                  AND m.user_id = private.current_user_id()
                  AND m.role = 'coach'
            )
        $$;
    """)
    # Operator-only bootstrap. Signup can never reach this path: the runtime
    # role has no INSERT privilege on team or team_membership.
    op.execute("""
        CREATE FUNCTION private.bootstrap_initial_team(
            p_coach_user_id uuid,
            p_name text,
            p_season_label text,
            p_season_end_at timestamptz,
            p_age_group text DEFAULT NULL
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            new_team_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(8104);
            IF EXISTS (SELECT 1 FROM app.team) THEN
                RAISE EXCEPTION 'initial workspace already exists'
                    USING ERRCODE = 'unique_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.user_account a WHERE a.id = p_coach_user_id
            ) THEN
                RAISE EXCEPTION 'unknown account'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            INSERT INTO app.team (name, age_group, season_label, season_end_at, created_by)
            VALUES (p_name, p_age_group, p_season_label, p_season_end_at, p_coach_user_id)
            RETURNING id INTO new_team_id;
            INSERT INTO app.team_membership (team_id, user_id, role)
            VALUES (new_team_id, p_coach_user_id, 'coach');
            RETURN new_team_id;
        END $$;
    """)
    # Profile synchronization copies contact and display data only. Team roles
    # never come from editable Auth metadata.
    op.execute("""
        CREATE FUNCTION private.sync_user_account() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.email IS NULL THEN
                RETURN NEW;
            END IF;
            INSERT INTO app.user_account (id, email, display_name)
            VALUES (
                NEW.id,
                pg_catalog.lower(NEW.email),
                pg_catalog.left(
                    -- COALESCE and NULLIF are SQL constructs, not qualifiable.
                    coalesce(
                        nullif(
                            pg_catalog.btrim(
                                NEW.raw_user_meta_data ->> 'display_name'
                            ), ''
                        ),
                        nullif(
                            pg_catalog.btrim(
                                NEW.raw_user_meta_data ->> 'full_name'
                            ), ''
                        ),
                        pg_catalog.split_part(NEW.email, '@', 1)
                    ), 80
                )
            )
            ON CONFLICT (id) DO UPDATE
                SET email = excluded.email, updated_at = pg_catalog.now();
            RETURN NEW;
        END $$;
    """)

    # Ownership moves to the non-bypass migration role: the runtime role can
    # never disable row-level security, and forced RLS binds the owner too.
    op.execute(f"ALTER SCHEMA app OWNER TO {MIGRATION_ROLE}")
    op.execute(f"ALTER SCHEMA private OWNER TO {MIGRATION_ROLE}")
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        # Forced RLS also applies to the owner, so the schema owner keeps an
        # explicit maintenance policy for migrations and definer helpers.
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    op.execute(f"""
        CREATE POLICY user_account_self_select ON app.user_account
            FOR SELECT TO {API_ROLE}
            USING (id = private.current_user_id())
    """)
    op.execute(f"""
        CREATE POLICY team_member_select ON app.team
            FOR SELECT TO {API_ROLE}
            USING (private.is_team_member(id))
    """)
    op.execute(f"""
        CREATE POLICY team_membership_visible_select ON app.team_membership
            FOR SELECT TO {API_ROLE}
            USING (
                user_id = private.current_user_id()
                OR private.is_team_coach(team_id)
            )
    """)
    op.execute(f"""
        CREATE POLICY player_visible_select ON app.player
            FOR SELECT TO {API_ROLE}
            USING (
                private.is_team_coach(team_id)
                OR (
                    user_id = private.current_user_id()
                    AND deleted_at IS NULL
                    AND deletion_pending_at IS NULL
                )
            )
    """)

    # Read-only runtime grants. Roster and product writes arrive with their own
    # policies in their owning tasks.
    op.execute(f"GRANT USAGE ON SCHEMA app, private TO {API_ROLE}")
    op.execute(f"""
        GRANT SELECT ON
            app.user_account, app.team, app.team_membership, app.player
        TO {API_ROLE}
    """)
    op.execute(f"""
        GRANT EXECUTE ON FUNCTION
            private.current_user_id(),
            private.is_team_member(uuid),
            private.is_team_coach(uuid),
            private.bootstrap_initial_team(uuid, text, text, timestamptz, text)
        TO {API_ROLE}
    """)

    # The Data API must not reach these objects even if a schema is exposed by
    # mistake: no browser-facing role holds any privilege here.
    for role in ("PUBLIC", "anon", "authenticated"):
        op.execute(f"REVOKE ALL ON SCHEMA app, private FROM {role}")
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA app, private FROM {role}")
        op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app, private FROM {role}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA app, private FROM {role}")

    op.execute("""
        INSERT INTO app.user_account (id, email, display_name)
        SELECT
            u.id,
            lower(u.email),
            left(
                coalesce(
                    nullif(btrim(u.raw_user_meta_data ->> 'display_name'), ''),
                    nullif(btrim(u.raw_user_meta_data ->> 'full_name'), ''),
                    split_part(u.email, '@', 1)
                ), 80
            )
        FROM auth.users u
        WHERE u.email IS NOT NULL
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        CREATE TRIGGER sync_user_account_from_auth
            AFTER INSERT OR UPDATE OF email ON auth.users
            FOR EACH ROW EXECUTE FUNCTION private.sync_user_account()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sync_user_account_from_auth ON auth.users")
    op.execute("DROP FUNCTION IF EXISTS private.sync_user_account()")
    op.execute("""
        DROP FUNCTION IF EXISTS
            private.bootstrap_initial_team(uuid, text, text, timestamptz, text)
    """)
    op.execute("DROP TABLE IF EXISTS app.player")
    op.execute("DROP TABLE IF EXISTS app.team_membership")
    op.execute("DROP TABLE IF EXISTS app.team")
    op.execute("DROP TABLE IF EXISTS app.user_account")
    op.execute("DROP FUNCTION IF EXISTS private.is_team_coach(uuid)")
    op.execute("DROP FUNCTION IF EXISTS private.is_team_member(uuid)")
    op.execute("DROP FUNCTION IF EXISTS private.current_user_id()")
    op.execute(f"REVOKE ALL ON SCHEMA app, private FROM {API_ROLE}")
    op.execute(f"ALTER ROLE {API_ROLE} RESET search_path")
    # Schemas and cluster-level roles survive: the Alembic version table lives
    # in `app`, and the roles may hold operator-provisioned credentials.
