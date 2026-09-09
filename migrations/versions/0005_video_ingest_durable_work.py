"""Games, video multipart ingest, and the durable processing queue

Revision ID: 0005_video_ingest
Revises: 0004_roster_goals

Adds `app.game`, `app.video`, `app.video_upload_part`, and `app.processing_job`
with their row-level security, plus the `shoulder_worker` runtime role the
claim loop connects as. See `docs/decisions/0018-worker-database-role.md`.

Two runtime roles now reach these tables and they authorize differently.
`shoulder_api` answers an HTTP request and is bounded by the caller's coach
membership through `private.is_game_coach` / `private.is_video_coach`.
`shoulder_worker` has no user identity at all: it sees every job row, and the
row it may act on is bounded by the claim query's lease, not by a predicate.
Keeping them apart means `app.user_id` never has to be authorized when absent.

Object keys are never written by a caller. `app.video.original_key` is granted
to the API role on INSERT only, and the service derives it from the generated
`video.id`; there is no UPDATE grant for it on either runtime role.
"""

from alembic import op

revision = "0005_video_ingest"
down_revision = "0004_roster_goals"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
TABLES = ("game", "video", "video_upload_part", "processing_job")
FUNCTIONS = (
    "private.is_game_coach(uuid)",
    "private.is_video_coach(uuid)",
)


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{WORKER_ROLE}'
            ) THEN
                CREATE ROLE {WORKER_ROLE} LOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOBYPASSRLS NOINHERIT;
            END IF;
        END $$;
    """)
    op.execute(f"ALTER ROLE {WORKER_ROLE} SET search_path = ''")

    op.execute("""
        CREATE TABLE app.game (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id uuid NOT NULL REFERENCES app.team (id) ON DELETE CASCADE,
            opponent text
                CONSTRAINT game_opponent_length
                    CHECK (opponent IS NULL OR char_length(opponent) BETWEEN 1 AND 100),
            played_at timestamptz NOT NULL,
            kind text NOT NULL DEFAULT 'match'
                CONSTRAINT game_kind_allowed CHECK (kind IN ('match', 'scrimmage')),
            notes text
                CONSTRAINT game_notes_length
                    CHECK (notes IS NULL OR char_length(notes) <= 1000),
            created_by uuid NOT NULL REFERENCES app.user_account (id),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX game_team_played_idx ON app.game (team_id, played_at DESC)")
    op.execute("CREATE INDEX game_created_by_idx ON app.game (created_by)")

    # Nullable probe columns stay nullable until Task 11 runs ffprobe. The
    # status list is the full contract from `docs/03-schema.md`; this block
    # writes only `uploading`, `uploaded`, and `failed`.
    op.execute("""
        CREATE TABLE app.video (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            game_id uuid NOT NULL REFERENCES app.game (id) ON DELETE CASCADE,
            original_key text NOT NULL
                CONSTRAINT video_original_key_length
                    CHECK (char_length(original_key) BETWEEN 1 AND 500),
            playback_key text
                CONSTRAINT video_playback_key_length
                    CHECK (
                        playback_key IS NULL
                        OR char_length(playback_key) BETWEEN 1 AND 500
                    ),
            original_filename text NOT NULL
                CONSTRAINT video_original_filename_length
                    CHECK (char_length(original_filename) BETWEEN 1 AND 255),
            content_type text NOT NULL
                CONSTRAINT video_content_type_length
                    CHECK (char_length(content_type) BETWEEN 1 AND 100),
            size_bytes bigint NOT NULL
                CONSTRAINT video_size_bytes_positive CHECK (size_bytes > 0),
            sha256 text
                CONSTRAINT video_sha256_format
                    CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
            multipart_upload_id text
                CONSTRAINT video_multipart_upload_id_length
                    CHECK (
                        multipart_upload_id IS NULL
                        OR char_length(multipart_upload_id) BETWEEN 1 AND 500
                    ),
            duration_ms integer
                CONSTRAINT video_duration_ms_non_negative
                    CHECK (duration_ms IS NULL OR duration_ms >= 0),
            width integer
                CONSTRAINT video_width_positive CHECK (width IS NULL OR width > 0),
            height integer
                CONSTRAINT video_height_positive CHECK (height IS NULL OR height > 0),
            fps numeric(7, 3)
                CONSTRAINT video_fps_positive CHECK (fps IS NULL OR fps > 0),
            status text NOT NULL DEFAULT 'uploading'
                CONSTRAINT video_status_allowed CHECK (status IN (
                    'uploading', 'uploaded', 'processing', 'ready',
                    'failed', 'deletion_pending', 'deleted'
                )),
            uploaded_by uuid NOT NULL REFERENCES app.user_account (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            ready_at timestamptz,
            deleted_at timestamptz,
            upload_completed_at timestamptz,
            first_terminal_failure_at timestamptz,
            source_expires_at timestamptz,
            derivatives_expires_at timestamptz,
            -- The retention clock cannot start before the upload finished.
            CONSTRAINT video_source_expiry_needs_completion
                CHECK (source_expires_at IS NULL OR upload_completed_at IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX video_game_id_idx ON app.video (game_id)")
    op.execute("CREATE INDEX video_uploaded_by_idx ON app.video (uploaded_by)")
    op.execute("CREATE INDEX video_status_idx ON app.video (status)")
    op.execute(
        "CREATE INDEX video_source_expires_at_idx ON app.video (source_expires_at)"
    )
    op.execute(
        "CREATE INDEX video_derivatives_expires_at_idx"
        " ON app.video (derivatives_expires_at)"
    )

    # The authoritative resume record. `docs/03-schema.md`: the browser copy is
    # only a cache, so every column here is reconciled from storage.
    op.execute("""
        CREATE TABLE app.video_upload_part (
            video_id uuid NOT NULL REFERENCES app.video (id) ON DELETE CASCADE,
            part_number integer NOT NULL
                CONSTRAINT video_upload_part_number_range
                    CHECK (part_number BETWEEN 1 AND 10000),
            etag text NOT NULL
                CONSTRAINT video_upload_part_etag_length
                    CHECK (char_length(etag) BETWEEN 1 AND 200),
            size_bytes bigint NOT NULL
                CONSTRAINT video_upload_part_size_positive CHECK (size_bytes > 0),
            completed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (video_id, part_number)
        )
    """)

    # Later target columns (`judgment_id`, `review_publication_id`, `player_id`,
    # `cv_run_id`) and their kinds arrive with the tables they reference, per
    # `docs/03-schema.md`.
    op.execute("""
        CREATE TABLE app.processing_job (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            video_id uuid REFERENCES app.video (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT processing_job_kind_allowed
                    CHECK (kind IN ('transcode', 'thumbnail')),
            idempotency_key text NOT NULL UNIQUE
                CONSTRAINT processing_job_idempotency_key_length
                    CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
            status text NOT NULL DEFAULT 'queued'
                CONSTRAINT processing_job_status_allowed CHECK (status IN (
                    'queued', 'running', 'succeeded', 'failed', 'cancelled'
                )),
            available_at timestamptz NOT NULL DEFAULT now(),
            attempts integer NOT NULL DEFAULT 0
                CONSTRAINT processing_job_attempts_non_negative CHECK (attempts >= 0),
            max_attempts integer NOT NULL DEFAULT 5
                CONSTRAINT processing_job_max_attempts_positive
                    CHECK (max_attempts BETWEEN 1 AND 20),
            progress numeric(4, 3) NOT NULL DEFAULT 0
                CONSTRAINT processing_job_progress_range
                    CHECK (progress >= 0 AND progress <= 1),
            locked_at timestamptz,
            locked_by text
                CONSTRAINT processing_job_locked_by_length
                    CHECK (locked_by IS NULL OR char_length(locked_by) BETWEEN 1 AND 100),
            heartbeat_at timestamptz,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb
                CONSTRAINT processing_job_payload_is_object
                    CHECK (jsonb_typeof(payload) = 'object'),
            error_code text
                CONSTRAINT processing_job_error_code_length
                    CHECK (
                        error_code IS NULL
                        OR char_length(error_code) BETWEEN 1 AND 60
                    ),
            error_message text
                CONSTRAINT processing_job_error_message_length
                    CHECK (
                        error_message IS NULL
                        OR char_length(error_message) BETWEEN 1 AND 300
                    ),
            cancel_requested_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT processing_job_attempts_bounded
                CHECK (attempts <= max_attempts),
            -- Every kind in this block acts on a video. A kind whose target is
            -- a later table extends this check in its own migration.
            CONSTRAINT processing_job_video_target_required
                CHECK (video_id IS NOT NULL),
            -- A lease is all three columns or none of them; half a lease would
            -- make the sweeper's staleness comparison meaningless.
            CONSTRAINT processing_job_lease_is_whole CHECK (
                (locked_at IS NULL AND locked_by IS NULL AND heartbeat_at IS NULL)
                OR (
                    locked_at IS NOT NULL
                    AND locked_by IS NOT NULL
                    AND heartbeat_at IS NOT NULL
                )
            ),
            CONSTRAINT processing_job_running_holds_a_lease
                CHECK (status <> 'running' OR locked_by IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX processing_job_video_id_idx ON app.processing_job (video_id)")
    # The claim query's index: only queued rows are ever scanned for work.
    op.execute("""
        CREATE INDEX processing_job_claimable_idx
            ON app.processing_job (available_at, created_at)
            WHERE status = 'queued'
    """)

    # Membership helpers for the new tables, SECURITY DEFINER for the same
    # reason `private.is_player_coach` is: a policy on `app.video` must not
    # depend on the caller's own policy for `app.game`.
    op.execute("""
        CREATE FUNCTION private.is_game_coach(p_game_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.game g
                WHERE g.id = p_game_id AND private.is_team_coach(g.team_id)
            )
        $$;
    """)
    op.execute("""
        CREATE FUNCTION private.is_video_coach(p_video_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.video v
                WHERE v.id = p_video_id AND private.is_game_coach(v.game_id)
            )
        $$;
    """)

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    # --- API role policies. Coach-only; `docs/03-schema.md` gives players no
    # access at all to any of these four tables.
    op.execute(f"""
        CREATE POLICY game_coach_select ON app.game
            FOR SELECT TO {API_ROLE}
            USING (private.is_team_coach(team_id))
    """)
    op.execute(f"""
        CREATE POLICY game_coach_insert ON app.game
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_team_coach(team_id)
                AND created_by = private.current_user_id()
            )
    """)
    op.execute(f"""
        CREATE POLICY video_coach_select ON app.video
            FOR SELECT TO {API_ROLE}
            USING (private.is_game_coach(game_id))
    """)
    op.execute(f"""
        CREATE POLICY video_coach_insert ON app.video
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_game_coach(game_id)
                AND uploaded_by = private.current_user_id()
                AND status = 'uploading'
            )
    """)
    op.execute(f"""
        CREATE POLICY video_coach_update ON app.video
            FOR UPDATE TO {API_ROLE}
            USING (private.is_game_coach(game_id))
            WITH CHECK (private.is_game_coach(game_id))
    """)
    op.execute(f"""
        CREATE POLICY video_upload_part_coach_select ON app.video_upload_part
            FOR SELECT TO {API_ROLE}
            USING (private.is_video_coach(video_id))
    """)
    op.execute(f"""
        CREATE POLICY video_upload_part_coach_insert ON app.video_upload_part
            FOR INSERT TO {API_ROLE}
            WITH CHECK (private.is_video_coach(video_id))
    """)
    op.execute(f"""
        CREATE POLICY video_upload_part_coach_update ON app.video_upload_part
            FOR UPDATE TO {API_ROLE}
            USING (private.is_video_coach(video_id))
            WITH CHECK (private.is_video_coach(video_id))
    """)
    # Abandoning an upload removes its part rows; the video row is retained
    # with a terminal status so the retention sweeper can find it.
    op.execute(f"""
        CREATE POLICY video_upload_part_coach_delete ON app.video_upload_part
            FOR DELETE TO {API_ROLE}
            USING (private.is_video_coach(video_id))
    """)
    op.execute(f"""
        CREATE POLICY processing_job_coach_select ON app.processing_job
            FOR SELECT TO {API_ROLE}
            USING (video_id IS NOT NULL AND private.is_video_coach(video_id))
    """)
    op.execute(f"""
        CREATE POLICY processing_job_coach_insert ON app.processing_job
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                video_id IS NOT NULL
                AND private.is_video_coach(video_id)
                AND status = 'queued'
                AND attempts = 0
                AND locked_by IS NULL
            )
    """)

    # --- Worker role policies. ADR 0018: no user identity, so no membership
    # predicate; the claim query's `FOR UPDATE SKIP LOCKED` lease is the bound.
    op.execute(f"""
        CREATE POLICY processing_job_worker_select ON app.processing_job
            FOR SELECT TO {WORKER_ROLE} USING (true)
    """)
    op.execute(f"""
        CREATE POLICY processing_job_worker_update ON app.processing_job
            FOR UPDATE TO {WORKER_ROLE} USING (true) WITH CHECK (true)
    """)
    op.execute(f"""
        CREATE POLICY video_worker_select ON app.video
            FOR SELECT TO {WORKER_ROLE} USING (true)
    """)
    op.execute(f"""
        CREATE POLICY video_worker_update ON app.video
            FOR UPDATE TO {WORKER_ROLE} USING (true) WITH CHECK (true)
    """)

    # --- Grants. Column-level where a column must never be caller-writable.
    op.execute(f"GRANT SELECT, INSERT ON app.game TO {API_ROLE}")
    op.execute(f"GRANT SELECT ON app.video TO {API_ROLE}")
    # `id` and `original_key` are insert-only and never updatable: the service
    # generates the id, derives the key from it, and nothing afterwards can
    # retarget an existing row at a different object.
    op.execute(f"""
        GRANT INSERT (
            id, game_id, original_key, original_filename, content_type,
            size_bytes, sha256, multipart_upload_id, uploaded_by, status
        ) ON app.video TO {API_ROLE}
    """)
    op.execute(f"""
        GRANT UPDATE (
            status, multipart_upload_id, upload_completed_at,
            first_terminal_failure_at, source_expires_at, derivatives_expires_at
        ) ON app.video TO {API_ROLE}
    """)
    op.execute(
        f"GRANT SELECT, INSERT, DELETE ON app.video_upload_part TO {API_ROLE}"
    )
    op.execute(f"GRANT UPDATE (etag, size_bytes, completed_at)"
               f" ON app.video_upload_part TO {API_ROLE}")
    op.execute(f"""
        GRANT INSERT (video_id, kind, idempotency_key, payload, max_attempts)
            ON app.processing_job TO {API_ROLE}
    """)
    op.execute(f"GRANT SELECT ON app.processing_job TO {API_ROLE}")
    op.execute(f"""
        GRANT EXECUTE ON FUNCTION
            private.is_game_coach(uuid), private.is_video_coach(uuid)
        TO {API_ROLE}
    """)

    # The worker sees `app` only. It has no `private` execute grant because it
    # authorizes nothing on a user's behalf, and no INSERT or DELETE on the
    # queue: enqueue is the API's, and terminal rows are retained.
    op.execute(f"GRANT USAGE ON SCHEMA app TO {WORKER_ROLE}")
    op.execute(f"GRANT SELECT ON app.processing_job TO {WORKER_ROLE}")
    op.execute(f"""
        GRANT UPDATE (
            status, attempts, progress, locked_at, locked_by, heartbeat_at,
            available_at, error_code, error_message, started_at, finished_at
        ) ON app.processing_job TO {WORKER_ROLE}
    """)
    op.execute(f"GRANT SELECT ON app.video TO {WORKER_ROLE}")
    # Task 11 widens this to the probe and playback columns it actually writes.
    op.execute(f"GRANT UPDATE (status, ready_at) ON app.video TO {WORKER_ROLE}")

    for role in ("PUBLIC", "anon", "authenticated"):
        for table in TABLES:
            op.execute(f"REVOKE ALL ON TABLE app.{table} FROM {role}")
        for function in FUNCTIONS:
            op.execute(f"REVOKE ALL ON FUNCTION {function} FROM {role}")


def downgrade() -> None:
    # Dropping the tables removes their policies, indexes, and grants with them.
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS app.{table}")
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute(f"REVOKE ALL ON SCHEMA app FROM {WORKER_ROLE}")
    op.execute(f"ALTER ROLE {WORKER_ROLE} RESET search_path")
    op.execute(f"DROP ROLE IF EXISTS {WORKER_ROLE}")
