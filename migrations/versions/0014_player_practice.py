"""Player-owned practice videos and AI coach feedback (ADR 0021)

Revision ID: 0014_player_practice
Revises: 0013_retention_deletion
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0014_player_practice"
down_revision = "0013_retention_deletion"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"
TABLES = ("practice_video", "ai_coach_feedback")
WORKER_FUNCTIONS = (
    "private.expired_practice_videos(uuid,text,timestamptz)",
    "private.purge_practice_video(uuid,text,uuid)",
)
# Fencing matches the Task 22 ledger cleanup: only the running sweep job
# holder may list or purge.
SWEEP_FENCE = """
    EXISTS (
        SELECT 1 FROM app.processing_job job
        WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
          AND job.status = 'running' AND job.locked_by = p_worker_id
    )
"""
# A ready video expires at its persisted clock; an upload never completed is
# abandoned after seven days, like coach uploads.
EXPIRED = """
    (v.status = 'ready' AND v.expires_at <= p_now)
    OR (v.status <> 'ready' AND v.created_at <= p_now - interval '7 days')
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.practice_video (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            created_by_user_id uuid NOT NULL,
            object_key text NOT NULL UNIQUE,
            content_type text NOT NULL
                CONSTRAINT practice_video_content_type
                    CHECK (content_type IN ('video/mp4', 'video/quicktime', 'video/webm')),
            size_bytes bigint NOT NULL
                CONSTRAINT practice_video_size
                    CHECK (size_bytes BETWEEN 1 AND 524288000),
            duration_ms integer
                CONSTRAINT practice_video_duration
                    CHECK (duration_ms BETWEEN 1 AND 600000),
            status text NOT NULL DEFAULT 'uploading'
                CONSTRAINT practice_video_status
                    CHECK (status IN ('uploading', 'ready', 'deleted')),
            title text
                CONSTRAINT practice_video_title_length
                    CHECK (char_length(title) <= 80),
            created_at timestamptz NOT NULL DEFAULT now(),
            upload_completed_at timestamptz,
            expires_at timestamptz,
            CONSTRAINT practice_video_ready_shape CHECK (
                status <> 'ready'
                OR (upload_completed_at IS NOT NULL AND expires_at IS NOT NULL
                    AND expires_at <= upload_completed_at + interval '90 days')
            )
        )
    """)
    op.execute(
        "CREATE INDEX practice_video_player_idx ON app.practice_video (player_id)"
    )
    op.execute(
        "CREATE INDEX practice_video_expires_idx ON app.practice_video (expires_at)"
    )

    op.execute("""
        CREATE TABLE app.ai_coach_feedback (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            practice_video_id uuid NOT NULL
                REFERENCES app.practice_video (id) ON DELETE CASCADE,
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            development_goal_id uuid
                REFERENCES app.development_goal (id) ON DELETE SET NULL,
            features jsonb NOT NULL
                CONSTRAINT ai_coach_feedback_features_shape
                    CHECK (jsonb_typeof(features) = 'object'
                           AND octet_length(features::text) <= 4096),
            model text NOT NULL
                CONSTRAINT ai_coach_feedback_model_length
                    CHECK (char_length(model) BETWEEN 1 AND 200),
            body text NOT NULL
                CONSTRAINT ai_coach_feedback_body_length
                    CHECK (char_length(body) BETWEEN 1 AND 1200),
            drills jsonb NOT NULL
                CONSTRAINT ai_coach_feedback_drills_shape
                    CHECK (jsonb_typeof(drills) = 'array'
                           AND jsonb_array_length(drills) <= 3),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    for column in ("practice_video_id", "player_id", "development_goal_id"):
        op.execute(
            f"CREATE INDEX ai_coach_feedback_{column}_idx"
            f" ON app.ai_coach_feedback ({column})"
        )

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)
        # Player self only. No coach policy exists on purpose (ADR 0021).
        op.execute(f"""
            CREATE POLICY {table}_player_select ON app.{table}
                FOR SELECT TO {API_ROLE}
                USING (private.is_player_self(player_id))
        """)
        op.execute(f"""
            CREATE POLICY {table}_player_delete ON app.{table}
                FOR DELETE TO {API_ROLE}
                USING (private.is_player_self(player_id))
        """)

    op.execute(f"""
        CREATE POLICY practice_video_player_insert ON app.practice_video
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_player_self(player_id)
                AND created_by_user_id = private.current_user_id()
                AND status = 'uploading'
            )
    """)
    op.execute(f"""
        CREATE POLICY practice_video_player_update ON app.practice_video
            FOR UPDATE TO {API_ROLE}
            USING (private.is_player_self(player_id))
            WITH CHECK (private.is_player_self(player_id))
    """)
    op.execute(f"""
        CREATE POLICY ai_coach_feedback_player_insert ON app.ai_coach_feedback
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_player_self(player_id)
                AND EXISTS (
                    SELECT 1 FROM app.practice_video v
                    WHERE v.id = ai_coach_feedback.practice_video_id
                      AND v.player_id = ai_coach_feedback.player_id
                      AND v.status = 'ready'
                )
                AND (
                    development_goal_id IS NULL OR EXISTS (
                        SELECT 1 FROM app.development_goal g
                        WHERE g.id = ai_coach_feedback.development_goal_id
                          AND g.player_id = ai_coach_feedback.player_id
                    )
                )
            )
    """)

    op.execute(f"""
        CREATE FUNCTION private.expired_practice_videos(
            p_job_id uuid, p_worker_id text, p_now timestamptz DEFAULT now()
        ) RETURNS TABLE (id uuid, object_key text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT v.id, v.object_key
            FROM app.practice_video v
            WHERE {SWEEP_FENCE} AND ({EXPIRED})
            ORDER BY v.created_at, v.id
        $$
    """)
    op.execute(f"""
        CREATE FUNCTION private.purge_practice_video(
            p_job_id uuid, p_worker_id text, p_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            p_now timestamptz := now();
        BEGIN
            IF NOT {SWEEP_FENCE} THEN RETURN false; END IF;
            DELETE FROM app.practice_video v WHERE v.id = p_id AND ({EXPIRED});
            RETURN FOUND;
        END;
        $$
    """)

    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.practice_video TO {API_ROLE}")
    op.execute(
        "GRANT UPDATE (status, duration_ms, upload_completed_at, expires_at)"
        f" ON app.practice_video TO {API_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.ai_coach_feedback TO {API_ROLE}")
    for function in WORKER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")


def downgrade() -> None:
    for function in WORKER_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS app.ai_coach_feedback")
    op.execute("DROP TABLE IF EXISTS app.practice_video")
