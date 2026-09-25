"""Opt-in team leaderboard of tracking totals (ADR 0023, Block 09B W2)

Revision ID: 0019_team_leaderboard
Revises: 0018_training_plans

A player opts in under a nickname; leaving deletes the row. The table is
player-self only. Teammates and the team coach read the board through one
definer function that returns nickname, a whole-number total, and whether the
row is the caller's own: never a player id, display name, or another team.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0019_team_leaderboard"
down_revision = "0018_training_plans"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"
FUNCTION = "private.team_leaderboard(uuid,text,timestamptz)"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.leaderboard_member (
            player_id uuid PRIMARY KEY
                REFERENCES app.player (id) ON DELETE CASCADE,
            nickname text NOT NULL
                CONSTRAINT leaderboard_member_nickname
                    CHECK (nickname ~ '^[A-Za-z0-9 ]{2,20}$'),
            joined_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    table = "leaderboard_member"
    op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
    op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {table}_owner_maintenance ON app.{table}
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)
    # Player self only. Nobody else, the coach included, reads the table.
    op.execute(f"""
        CREATE POLICY {table}_player_select ON app.{table}
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_self(player_id))
    """)
    op.execute(f"""
        CREATE POLICY {table}_player_insert ON app.{table}
            FOR INSERT TO {API_ROLE}
            WITH CHECK (private.is_player_self(player_id))
    """)
    op.execute(f"""
        CREATE POLICY {table}_player_update ON app.{table}
            FOR UPDATE TO {API_ROLE}
            USING (private.is_player_self(player_id))
            WITH CHECK (private.is_player_self(player_id))
    """)
    op.execute(f"""
        CREATE POLICY {table}_player_delete ON app.{table}
            FOR DELETE TO {API_ROLE}
            USING (private.is_player_self(player_id))
    """)
    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.{table} TO {API_ROLE}")
    op.execute(f"GRANT UPDATE (nickname) ON app.{table} TO {API_ROLE}")

    # Callable only by a member of the team (player or coach). Rows are
    # opted-in, linked, live players of that team who still hold the player
    # membership. Unknown metrics return nothing. Best first; ties by nickname.
    op.execute("""
        CREATE FUNCTION private.team_leaderboard(
            p_team_id uuid, p_metric text, p_since timestamptz
        ) RETURNS TABLE (nickname text, value integer, is_me boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT board.nickname, board.value, board.is_me
            FROM (
                SELECT m.nickname,
                       (CASE p_metric
                           WHEN 'distance' THEN coalesce(sum(s.distance_m), 0)
                           WHEN 'sprints' THEN coalesce(sum(s.sprint_count), 0)
                           WHEN 'top_speed' THEN coalesce(max(s.top_speed_cms), 0)
                           WHEN 'sessions' THEN count(s.id)
                       END)::integer AS value,
                       coalesce(p.user_id = private.current_user_id(), false) AS is_me
                FROM app.leaderboard_member m
                JOIN app.player p ON p.id = m.player_id
                LEFT JOIN app.training_session s
                    ON s.player_id = p.id AND s.started_at >= p_since
                WHERE p.team_id = p_team_id
                  AND private.is_team_member(p_team_id)
                  AND p_metric IN ('distance', 'sprints', 'top_speed', 'sessions')
                  AND p_since IS NOT NULL
                  AND p.active
                  AND p.deleted_at IS NULL
                  AND p.deletion_pending_at IS NULL
                  AND EXISTS (
                      SELECT 1 FROM app.team_membership tm
                      WHERE tm.team_id = p.team_id AND tm.user_id = p.user_id
                        AND tm.role = 'player'
                  )
                GROUP BY m.player_id, m.nickname, p.user_id
            ) board
            ORDER BY board.value DESC, board.nickname
        $$
    """)
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {MIGRATION_ROLE}")
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, anon, authenticated,"
        f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {API_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
    op.execute("DROP TABLE IF EXISTS app.leaderboard_member")
