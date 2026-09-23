"""Public demo self-join onto the synthetic demo team (ADR 0021)

Revision ID: 0015_demo_join
Revises: 0014_player_practice

`private.demo_join` is the only path by which a signed-in account can create
its own membership. It is bounded three ways: the team must carry the
reserved `age_group = 'DEMO'` marker (set only by `scripts/seed_demo.py`), the
caller must have no membership and no player row anywhere, and the only role
it ever writes is `player`. The API calls it only when `DEMO_MODE=on`.
"""

from alembic import op

revision = "0015_demo_join"
down_revision = "0014_player_practice"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"
FUNCTION = "private.demo_join(uuid)"
DEMO_LOCK_CLASS = 8115


def upgrade() -> None:
    op.execute(f"""
        CREATE FUNCTION private.demo_join(p_team_id uuid) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_user_id uuid := private.current_user_id();
            v_coach_id uuid;
            v_name text;
            v_player_id uuid;
        BEGIN
            IF v_user_id IS NULL THEN
                RETURN NULL;
            END IF;
            -- The reserved marker is the guard: no real team can be joined.
            SELECT t.created_by INTO v_coach_id
            FROM app.team t
            WHERE t.id = p_team_id AND t.age_group = 'DEMO';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'not a demo team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            -- One join per account even under concurrent requests.
            PERFORM pg_catalog.pg_advisory_xact_lock(
                {DEMO_LOCK_CLASS}, pg_catalog.hashtext(v_user_id::text)
            );
            IF EXISTS (
                SELECT 1 FROM app.team_membership m WHERE m.user_id = v_user_id
            ) OR EXISTS (
                SELECT 1 FROM app.player p WHERE p.user_id = v_user_id
            ) THEN
                SELECT p.id INTO v_player_id FROM app.player p
                WHERE p.user_id = v_user_id
                ORDER BY p.created_at, p.id LIMIT 1;
                RETURN v_player_id;
            END IF;
            SELECT pg_catalog.left(
                coalesce(
                    nullif(pg_catalog.btrim(a.display_name), ''),
                    nullif(pg_catalog.split_part(a.email, '@', 1), ''),
                    'Player'
                ), 80
            ) INTO v_name
            FROM app.user_account a WHERE a.id = v_user_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            INSERT INTO app.team_membership (team_id, user_id, role)
            VALUES (p_team_id, v_user_id, 'player');
            INSERT INTO app.player (team_id, display_name, user_id)
            VALUES (p_team_id, v_name, v_user_id)
            RETURNING id INTO v_player_id;
            INSERT INTO app.development_goal (player_id, title, created_by)
            VALUES (
                v_player_id, 'Check your shoulder before you receive', v_coach_id
            );
            RETURN v_player_id;
        END $$
    """)
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {MIGRATION_ROLE}")
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, anon, authenticated,"
        f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {API_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
