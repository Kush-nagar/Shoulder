"""Player-recorded training and match sessions (ADR 0023, Block 09B W1)

Revision ID: 0016_training_sessions
Revises: 0015_demo_join

Only aggregates reach the server: distance, speeds, sprint count, durations,
a half-time split, and a 12x8 pitch-normalised heatmap with no geographic
reference. Raw GPS points never leave the browser. Rows are purged 365 days
after creation by the fenced retention sweep and cascade on player erasure.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0016_training_sessions"
down_revision = "0015_demo_join"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"
SWEEP_FUNCTION = "private.purge_expired_training_sessions(uuid,text,timestamptz)"
# Same fence as 0014: only the running sweep job holder may purge.
SWEEP_FENCE = """
    EXISTS (
        SELECT 1 FROM app.processing_job job
        WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
          AND job.status = 'running' AND job.locked_by = p_worker_id
    )
"""


def heatmap_check(column: str) -> str:
    """96 cells, one dimension, no nulls, each normalised 0..1000."""
    return (
        f"array_length({column}, 1) = 96 AND array_ndims({column}) = 1"
        f" AND array_position({column}, NULL) IS NULL"
        f" AND 0 <= ALL ({column}) AND 1000 >= ALL ({column})"
    )


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE app.training_session (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT training_session_kind
                    CHECK (kind IN ('training', 'match')),
            started_at timestamptz NOT NULL,
            ended_at timestamptz NOT NULL,
            duration_s integer NOT NULL
                CONSTRAINT training_session_duration
                    CHECK (duration_s BETWEEN 60 AND 14400),
            distance_m integer NOT NULL
                CONSTRAINT training_session_distance
                    CHECK (distance_m BETWEEN 0 AND 30000),
            top_speed_cms integer NOT NULL
                CONSTRAINT training_session_top_speed
                    CHECK (top_speed_cms BETWEEN 0 AND 1300),
            sprint_count integer NOT NULL
                CONSTRAINT training_session_sprints
                    CHECK (sprint_count BETWEEN 0 AND 500),
            half_split_s integer
                CONSTRAINT training_session_half_split
                    CHECK (half_split_s > 0),
            heatmap smallint[] NOT NULL
                CONSTRAINT training_session_heatmap
                    CHECK ({heatmap_check("heatmap")}),
            heatmap_second_half smallint[]
                CONSTRAINT training_session_heatmap_second_half
                    CHECK ({heatmap_check("heatmap_second_half")}),
            gps_quality text NOT NULL
                CONSTRAINT training_session_gps_quality
                    CHECK (gps_quality IN ('good', 'fair', 'poor')),
            note text
                CONSTRAINT training_session_note_length
                    CHECK (char_length(note) <= 280),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT training_session_time_order CHECK (ended_at > started_at)
        )
    """)
    op.execute(
        "CREATE INDEX training_session_player_idx"
        " ON app.training_session (player_id, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX training_session_created_idx"
        " ON app.training_session (created_at)"
    )

    table = "training_session"
    op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
    op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {table}_owner_maintenance ON app.{table}
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)
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
        CREATE POLICY {table}_player_delete ON app.{table}
            FOR DELETE TO {API_ROLE}
            USING (private.is_player_self(player_id))
    """)
    # The player's own team coach reads; never writes, never another team.
    op.execute(f"""
        CREATE POLICY {table}_coach_select ON app.{table}
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_coach(player_id))
    """)
    # No UPDATE: a session is immutable once recorded.
    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.{table} TO {API_ROLE}")

    op.execute(f"""
        CREATE FUNCTION private.purge_expired_training_sessions(
            p_job_id uuid, p_worker_id text, p_now timestamptz DEFAULT now()
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_count integer;
        BEGIN
            IF NOT {SWEEP_FENCE} THEN RETURN 0; END IF;
            DELETE FROM app.training_session s
            WHERE s.created_at <= p_now - interval '365 days';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            RETURN v_count;
        END;
        $$
    """)
    op.execute(f"ALTER FUNCTION {SWEEP_FUNCTION} OWNER TO {MIGRATION_ROLE}")
    op.execute(
        f"REVOKE ALL ON FUNCTION {SWEEP_FUNCTION} FROM PUBLIC, anon, authenticated,"
        f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {SWEEP_FUNCTION} TO {WORKER_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SWEEP_FUNCTION}")
    op.execute("DROP TABLE IF EXISTS app.training_session")
