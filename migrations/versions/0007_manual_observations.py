"""Manual coach observations with append-only RLS

Revision ID: 0007_manual_observations
Revises: 0006_media_playback

Task 14 adds only the manual observation surface. CV provenance columns and
foreign keys remain absent until the Phase D gate.
"""

from alembic import op

revision = "0007_manual_observations"
down_revision = "0006_media_playback"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
FUNCTION = "private.valid_manual_observation(uuid,uuid,integer,integer)"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.observation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            video_id uuid NOT NULL
                REFERENCES app.video (id) ON DELETE CASCADE,
            player_id uuid NOT NULL
                REFERENCES app.player (id) ON DELETE CASCADE,
            t_start_ms integer NOT NULL
                CONSTRAINT observation_start_non_negative CHECK (t_start_ms >= 0),
            t_end_ms integer NOT NULL,
            source text NOT NULL DEFAULT 'coach_manual'
                CONSTRAINT observation_manual_source
                    CHECK (source = 'coach_manual'),
            event_type text
                CONSTRAINT observation_event_type_length
                    CHECK (
                        event_type IS NULL
                        OR char_length(event_type) BETWEEN 1 AND 80
                    ),
            created_by uuid NOT NULL REFERENCES app.user_account (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT observation_time_order CHECK (t_end_ms > t_start_ms)
        )
    """)
    op.execute(
        "CREATE INDEX observation_video_player_time_idx"
        " ON app.observation (video_id, player_id, t_start_ms)"
    )
    op.execute(
        "CREATE INDEX observation_video_source_idx"
        " ON app.observation (video_id, source)"
    )
    op.execute("CREATE INDEX observation_player_idx ON app.observation (player_id)")
    op.execute(
        "CREATE INDEX observation_created_by_idx ON app.observation (created_by)"
    )

    # A CHECK constraint cannot compare another table's duration or team. This
    # definer helper makes those cross-table invariants part of the INSERT RLS
    # gate too, so a caller cannot bypass the service validation with raw SQL.
    op.execute("""
        CREATE FUNCTION private.valid_manual_observation(
            p_video_id uuid,
            p_player_id uuid,
            p_start_ms integer,
            p_end_ms integer
        ) RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.video v
                JOIN app.game g ON g.id = v.game_id
                JOIN app.player p ON p.team_id = g.team_id
                WHERE v.id = p_video_id
                  AND p.id = p_player_id
                  AND p.active
                  AND p.deleted_at IS NULL
                  AND p.deletion_pending_at IS NULL
                  AND v.status = 'ready'
                  AND v.duration_ms IS NOT NULL
                  AND p_start_ms >= 0
                  AND p_end_ms > p_start_ms
                  AND p_end_ms <= v.duration_ms
            )
        $$
    """)

    op.execute(f"ALTER TABLE app.observation OWNER TO {MIGRATION_ROLE}")
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {MIGRATION_ROLE}")
    op.execute("ALTER TABLE app.observation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.observation FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY observation_owner_maintenance ON app.observation
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)
    op.execute(f"""
        CREATE POLICY observation_coach_select ON app.observation
            FOR SELECT TO {API_ROLE}
            USING (private.is_video_coach(video_id))
    """)
    op.execute(f"""
        CREATE POLICY observation_coach_insert ON app.observation
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                source = 'coach_manual'
                AND created_by = private.current_user_id()
                AND private.is_video_coach(video_id)
                AND private.valid_manual_observation(
                    video_id, player_id, t_start_ms, t_end_ms
                )
            )
    """)

    op.execute(f"GRANT SELECT ON app.observation TO {API_ROLE}")
    op.execute(f"""
        GRANT INSERT (
            video_id, player_id, t_start_ms, t_end_ms, source, created_by
        ) ON app.observation TO {API_ROLE}
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {API_ROLE}")

    for role in ("PUBLIC", "anon", "authenticated"):
        op.execute(f"REVOKE ALL ON TABLE app.observation FROM {role}")
        op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM {role}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.observation")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
