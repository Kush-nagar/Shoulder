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
TABLES = ("practice_video", "ai_coach_feedback", "ai_coach_usage")
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
# abandoned after seven days, like coach uploads. A deleted row is kept one
# hour, past the 15-minute PUT URL lifetime, so a late re-PUT is deleted too.
EXPIRED = """
    (v.status = 'ready' AND v.expires_at <= p_now)
    OR (v.status = 'uploading' AND v.created_at <= p_now - interval '7 days')
    OR (v.status = 'deleted' AND v.deleted_at <= p_now - interval '1 hour')
"""
# 0013's seed body, verbatim. 0014 appends practice objects so player erasure
# and season expiry delete them before `app.player` cascades the rows away.
SEED_0013 = """
        CREATE OR REPLACE FUNCTION private.seed_deletion_manifest_objects(p_manifest_id uuid)
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest app.deletion_manifest%ROWTYPE;
        BEGIN
            SELECT * INTO v_manifest FROM app.deletion_manifest
            WHERE id = p_manifest_id;
            IF NOT FOUND THEN RETURN; END IF;

            INSERT INTO app.deletion_manifest_object (
                manifest_id, object_key, object_kind, multipart_upload_id
            )
            SELECT v_manifest.id, v.original_key, 'original', v.multipart_upload_id
            FROM app.video v JOIN app.game g ON g.id = v.game_id
            WHERE (
                v_manifest.kind IN ('season_expiry', 'player_erasure')
                AND g.team_id = v_manifest.team_id
            ) OR (
                v_manifest.kind IN ('video_source', 'video_all')
                AND v.id = v_manifest.video_id
            )
            ON CONFLICT (manifest_id, object_key) DO NOTHING;

            IF v_manifest.kind <> 'video_source' THEN
                INSERT INTO app.deletion_manifest_object (
                    manifest_id, object_key, object_kind
                )
                SELECT v_manifest.id, coalesce(
                           v.playback_key,
                           'playback/' || v.id::text || '/coach-720p.mp4'
                       ), 'playback'
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                WHERE (
                    v_manifest.kind IN ('season_expiry', 'player_erasure')
                    AND g.team_id = v_manifest.team_id
                ) OR (v_manifest.kind = 'video_all' AND v.id = v_manifest.video_id)
                ON CONFLICT (manifest_id, object_key) DO NOTHING;

                INSERT INTO app.deletion_manifest_object (
                    manifest_id, object_key, object_kind
                )
                SELECT v_manifest.id,
                       'thumbs/' || v.id::text || '/' || name.value, 'thumbnail'
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                CROSS JOIN (VALUES
                    ('index.json'), ('sprite-0.jpg'), ('sprite-1.jpg'),
                    ('sprite-2.jpg'), ('sprite-3.jpg')
                ) AS name(value)
                WHERE (
                    v_manifest.kind IN ('season_expiry', 'player_erasure')
                    AND g.team_id = v_manifest.team_id
                ) OR (v_manifest.kind = 'video_all' AND v.id = v_manifest.video_id)
                ON CONFLICT (manifest_id, object_key) DO NOTHING;
            END IF;

            INSERT INTO app.deletion_manifest_object (
                manifest_id, object_key, object_kind
            )
            SELECT v_manifest.id, clip.storage_key, 'evidence_clip'
            FROM app.evidence_clip clip
            JOIN app.judgment judgment ON judgment.id = clip.judgment_id
            JOIN app.observation observation ON observation.id = judgment.observation_id
            JOIN app.video video ON video.id = observation.video_id
            JOIN app.game game ON game.id = video.game_id
            WHERE (
                v_manifest.kind IN ('season_expiry', 'player_erasure')
                AND game.team_id = v_manifest.team_id
            ) OR (
                v_manifest.kind = 'video_all' AND video.id = v_manifest.video_id
            ) OR (
                v_manifest.kind = 'export_cleanup'
                AND clip.id = v_manifest.evidence_clip_id
            )
            ON CONFLICT (manifest_id, object_key) DO NOTHING;
        END;
        $$
"""
PRACTICE_SEED = """
            INSERT INTO app.deletion_manifest_object (
                manifest_id, object_key, object_kind
            )
            SELECT v_manifest.id, practice.object_key, 'practice'
            FROM app.practice_video practice
            JOIN app.player player ON player.id = practice.player_id
            WHERE (
                v_manifest.kind = 'player_erasure'
                AND player.id = v_manifest.player_id
            ) OR (
                v_manifest.kind = 'season_expiry'
                AND player.team_id = v_manifest.team_id
            )
            ON CONFLICT (manifest_id, object_key) DO NOTHING;
        END;
        $$
"""
SEED_TAIL = """
        END;
        $$
"""
SEED_0014 = SEED_0013[: SEED_0013.rindex(SEED_TAIL)] + PRACTICE_SEED
OBJECT_KINDS_0013 = (
    "'original', 'playback', 'thumbnail', 'evidence_clip', 'research_artifact'"
)


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
            deleted_at timestamptz,
            CONSTRAINT practice_video_deleted_shape
                CHECK ((status = 'deleted') = (deleted_at IS NOT NULL)),
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

    # Quota survives video deletion: a counter, not a count of feedback rows.
    # ponytail: rows are never purged (one tiny row per player per day); they
    # cascade on player erasure. Add a sweep if the table ever matters.
    op.execute("""
        CREATE TABLE app.ai_coach_usage (
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            used_on date NOT NULL,
            count integer NOT NULL
                CONSTRAINT ai_coach_usage_count CHECK (count BETWEEN 0 AND 10),
            PRIMARY KEY (player_id, used_on)
        )
    """)

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
        if table == "ai_coach_usage":
            continue
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
        CREATE POLICY ai_coach_usage_player_insert ON app.ai_coach_usage
            FOR INSERT TO {API_ROLE}
            WITH CHECK (private.is_player_self(player_id))
    """)
    op.execute(f"""
        CREATE POLICY ai_coach_usage_player_update ON app.ai_coach_usage
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
        "GRANT UPDATE (status, duration_ms, upload_completed_at, expires_at,"
        " deleted_at)"
        f" ON app.practice_video TO {API_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.ai_coach_feedback TO {API_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON app.ai_coach_usage TO {API_ROLE}")
    op.execute(f"GRANT UPDATE (count) ON app.ai_coach_usage TO {API_ROLE}")
    op.execute(
        "ALTER TABLE app.deletion_manifest_object"
        " DROP CONSTRAINT deletion_object_kind_allowed"
    )
    op.execute(
        "ALTER TABLE app.deletion_manifest_object"
        " ADD CONSTRAINT deletion_object_kind_allowed"
        f" CHECK (object_kind IN ({OBJECT_KINDS_0013}, 'practice'))"
    )
    op.execute(SEED_0014)
    for function in WORKER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")


def downgrade() -> None:
    op.execute(SEED_0013)
    op.execute(
        "DELETE FROM app.deletion_manifest_object WHERE object_kind = 'practice'"
    )
    op.execute(
        "ALTER TABLE app.deletion_manifest_object"
        " DROP CONSTRAINT deletion_object_kind_allowed"
    )
    op.execute(
        "ALTER TABLE app.deletion_manifest_object"
        " ADD CONSTRAINT deletion_object_kind_allowed"
        f" CHECK (object_kind IN ({OBJECT_KINDS_0013}))"
    )
    for function in WORKER_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS app.ai_coach_usage")
    op.execute("DROP TABLE IF EXISTS app.ai_coach_feedback")
    op.execute("DROP TABLE IF EXISTS app.practice_video")
