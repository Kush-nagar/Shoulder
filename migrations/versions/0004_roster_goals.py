"""Roster write path and development goals

Revision ID: 0004_roster_goals
Revises: 0003_roster_display

Adds the coach roster write policies, `app.development_goal` with its own
row-level security, and the `private` helpers the invitation and goal paths
need.

The runtime role's write surface is bounded by column-level grants rather than
a `WITH CHECK` predicate: `app.player.team_id` and `app.player.user_id` are
simply not updatable by `shoulder_api`, so a coach cannot move a player to
another team and cannot self-link an account by writing the column directly.
`private.link_player_account` is therefore the only linking path, and it
authorizes on the caller's own coach membership. It links an address that
already has an account and never creates one; see ADR 0017.
"""

from alembic import op

revision = "0004_roster_goals"
down_revision = "0003_roster_display"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
FUNCTIONS = (
    "private.is_player_coach(uuid)",
    "private.is_player_self(uuid)",
    "private.link_player_account(uuid, text)",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.development_goal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id uuid NOT NULL
                REFERENCES app.player (id) ON DELETE CASCADE,
            title text NOT NULL
                CONSTRAINT development_goal_title_length
                    CHECK (char_length(title) BETWEEN 1 AND 100),
            description text
                CONSTRAINT development_goal_description_length
                    CHECK (description IS NULL OR char_length(description) <= 1000),
            ontology_key text
                CONSTRAINT development_goal_ontology_key_length
                    CHECK (
                        ontology_key IS NULL
                        OR char_length(ontology_key) BETWEEN 1 AND 80
                    ),
            status text NOT NULL DEFAULT 'active'
                CONSTRAINT development_goal_status_allowed
                    CHECK (status IN ('active', 'achieved', 'paused', 'retired')),
            created_by uuid NOT NULL REFERENCES app.user_account (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz,
            CONSTRAINT development_goal_closed_at_matches_status
                CHECK ((status = 'active') = (closed_at IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX development_goal_player_id_idx"
        " ON app.development_goal (player_id)"
    )
    op.execute(
        "CREATE INDEX development_goal_created_by_idx"
        " ON app.development_goal (created_by)"
    )
    # One active goal per player.
    op.execute("""
        CREATE UNIQUE INDEX development_goal_active_key
            ON app.development_goal (player_id)
            WHERE status = 'active'
    """)

    # Player-scoped membership lookups, SECURITY DEFINER so goal policies do not
    # need to read app.player through the caller's own policies.
    op.execute("""
        CREATE FUNCTION private.is_player_coach(p_player_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.player p
                WHERE p.id = p_player_id
                  AND private.is_team_coach(p.team_id)
            )
        $$;
    """)
    # Mirrors `player_visible_select` exactly, including the membership check
    # `0002` added: revoking a membership must also end the player's read of
    # their own goal, not just of their roster row.
    op.execute("""
        CREATE FUNCTION private.is_player_self(p_player_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.player p
                WHERE p.id = p_player_id
                  AND p.user_id = private.current_user_id()
                  AND private.is_team_member(p.team_id)
                  AND p.deleted_at IS NULL
                  AND p.deletion_pending_at IS NULL
            )
        $$;
    """)
    op.execute("""
        CREATE FUNCTION private.link_player_account(
            p_player_id uuid,
            p_email text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_email text := pg_catalog.lower(
                pg_catalog.btrim(coalesce(p_email, ''))
            );
            v_team_id uuid;
            v_user_id uuid;
        BEGIN
            -- Authorization is the caller's own coach membership on the player
            -- row, never an argument the caller supplies.
            IF NOT private.is_player_coach(p_player_id) THEN
                RAISE EXCEPTION 'player not visible to caller'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF v_email !~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
               OR pg_catalog.char_length(v_email) > 320 THEN
                RAISE EXCEPTION 'invalid email'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            -- Locks the row so two concurrent invitations cannot both see an
            -- unlinked player and overwrite each other.
            SELECT p.team_id INTO v_team_id
            FROM app.player p
            WHERE p.id = p_player_id
              AND p.user_id IS NULL
              AND p.deleted_at IS NULL
              AND p.deletion_pending_at IS NULL
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'player is already linked'
                    USING ERRCODE = 'unique_violation';
            END IF;

            -- Linking only. `app.user_account.id` references `auth.users`, so a
            -- profile row cannot exist before its Supabase Auth identity does,
            -- and this definer owns no privilege on `auth`. Creating the
            -- identity is deferred to Task 20 with email delivery; see
            -- `docs/decisions/0017-invitation-links-existing-accounts.md`.
            SELECT a.id INTO v_user_id
            FROM app.user_account a
            WHERE a.email = v_email;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'no account for this address yet'
                    USING ERRCODE = 'no_data_found';
            END IF;

            IF EXISTS (
                SELECT 1 FROM app.player p
                WHERE p.team_id = v_team_id AND p.user_id = v_user_id
            ) THEN
                RAISE EXCEPTION 'account is already linked on this team'
                    USING ERRCODE = 'unique_violation';
            END IF;

            UPDATE app.player SET user_id = v_user_id WHERE id = p_player_id;
            INSERT INTO app.team_membership (team_id, user_id, role)
            VALUES (v_team_id, v_user_id, 'player');
            RETURN v_user_id;
        END $$;
    """)

    op.execute(f"ALTER TABLE app.development_goal OWNER TO {MIGRATION_ROLE}")
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")

    op.execute("ALTER TABLE app.development_goal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.development_goal FORCE ROW LEVEL SECURITY")
    # Forced RLS binds the owner too, so migrations and definer helpers keep an
    # explicit maintenance policy.
    op.execute(f"""
        CREATE POLICY development_goal_owner_maintenance ON app.development_goal
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)

    op.execute(f"""
        CREATE POLICY player_coach_insert ON app.player
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_team_coach(team_id)
                AND user_id IS NULL
                AND deleted_at IS NULL
                AND deletion_pending_at IS NULL
            )
    """)
    op.execute(f"""
        CREATE POLICY player_coach_update ON app.player
            FOR UPDATE TO {API_ROLE}
            USING (private.is_team_coach(team_id))
            WITH CHECK (private.is_team_coach(team_id))
    """)

    op.execute(f"""
        CREATE POLICY development_goal_coach_select ON app.development_goal
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_coach(player_id))
    """)
    op.execute(f"""
        CREATE POLICY development_goal_coach_insert ON app.development_goal
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_player_coach(player_id)
                AND created_by = private.current_user_id()
            )
    """)
    op.execute(f"""
        CREATE POLICY development_goal_coach_update ON app.development_goal
            FOR UPDATE TO {API_ROLE}
            USING (private.is_player_coach(player_id))
            WITH CHECK (private.is_player_coach(player_id))
    """)
    op.execute(f"""
        CREATE POLICY development_goal_player_select ON app.development_goal
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_self(player_id))
    """)

    # Column-level write grants, not a predicate: team_id and user_id are not
    # writable by the runtime role at all. There is no DELETE grant on either
    # table; roster and goal removal are soft.
    op.execute(f"""
        GRANT INSERT (team_id, display_name, jersey_number, position)
            ON app.player TO {API_ROLE}
    """)
    op.execute(f"""
        GRANT UPDATE (display_name, jersey_number, position, active, deleted_at)
            ON app.player TO {API_ROLE}
    """)
    op.execute(f"GRANT SELECT, INSERT ON app.development_goal TO {API_ROLE}")
    op.execute(f"""
        GRANT UPDATE (title, description, ontology_key, status, closed_at)
            ON app.development_goal TO {API_ROLE}
    """)
    op.execute(f"""
        GRANT EXECUTE ON FUNCTION
            private.is_player_coach(uuid),
            private.is_player_self(uuid),
            private.link_player_account(uuid, text)
        TO {API_ROLE}
    """)

    # New objects are unreachable from the Data API roles, matching 0001.
    for role in ("PUBLIC", "anon", "authenticated"):
        op.execute(f"REVOKE ALL ON TABLE app.development_goal FROM {role}")
        for function in FUNCTIONS:
            op.execute(f"REVOKE ALL ON FUNCTION {function} FROM {role}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS player_coach_update ON app.player")
    op.execute("DROP POLICY IF EXISTS player_coach_insert ON app.player")
    op.execute(f"""
        REVOKE INSERT (team_id, display_name, jersey_number, position)
            ON app.player FROM {API_ROLE}
    """)
    op.execute(f"""
        REVOKE UPDATE (display_name, jersey_number, position, active, deleted_at)
            ON app.player FROM {API_ROLE}
    """)
    # Dropping the table removes its policies, indexes, and grants with it.
    op.execute("DROP TABLE IF EXISTS app.development_goal")
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
