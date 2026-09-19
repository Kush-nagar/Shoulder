"""Player-only evidence clips and atomic review publication

Revision ID: 0010_player_publications
Revises: 0009_draft_recovery
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0010_player_publications"
down_revision = "0009_draft_recovery"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"

TABLES = ("review_publication", "evidence_clip", "review_publication_item")
# Authorization helpers a player or coach reads through. `player_evidence` is
# the only path to a player's game label and coach name: `app.game` and
# `app.user_account` stay closed to a player under RLS, so the projection is
# assembled inside a definer helper that re-checks the current pointer chain.
PLAYER_HELPERS = (
    "private.is_review_publication_coach(uuid)",
    "private.is_current_publication_for_player(uuid)",
    "private.is_current_publication_item_for_player(uuid,uuid)",
    "private.is_current_evidence_clip_for_player(uuid)",
    "private.player_evidence(uuid)",
    "private.player_clip_for_signing(uuid,uuid)",
)
COACH_TRANSITIONS = (
    "private.request_review_publication(uuid,uuid,uuid,uuid,text,uuid[],bigint[])",
    "private.retry_review_publication(uuid)",
    "private.cancel_review_publication(uuid)",
    "private.withdraw_judgment(uuid)",
)
WORKER_FUNCTIONS = (
    "private.clip_export_input(uuid,text)",
    "private.complete_evidence_clip(uuid,text,integer,bigint,text)",
)
FUNCTIONS = PLAYER_HELPERS + COACH_TRANSITIONS + WORKER_FUNCTIONS


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.review_publication (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            game_id uuid NOT NULL REFERENCES app.game (id) ON DELETE CASCADE,
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            goal_id uuid NOT NULL REFERENCES app.development_goal (id),
            requested_by uuid NOT NULL REFERENCES app.user_account (id),
            idempotency_key text NOT NULL UNIQUE
                CONSTRAINT review_publication_idempotency_length
                    CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
            status text NOT NULL DEFAULT 'exporting'
                CONSTRAINT review_publication_status_allowed CHECK (status IN (
                    'exporting', 'published', 'failed', 'cancelled',
                    'superseded', 'withdrawn'
                )),
            replaces_publication_id uuid
                REFERENCES app.review_publication (id),
            first_terminal_failure_at timestamptz,
            cancelled_at timestamptz,
            private_exports_expires_at timestamptz,
            requested_count smallint NOT NULL
                CONSTRAINT review_publication_count CHECK (requested_count BETWEEN 3 AND 6),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz
        )
    """)
    op.execute(
        "CREATE INDEX review_publication_game_idx ON app.review_publication (game_id)"
    )
    op.execute(
        "CREATE INDEX review_publication_player_idx"
        " ON app.review_publication (player_id, published_at DESC)"
    )
    op.execute(
        "CREATE INDEX review_publication_goal_idx ON app.review_publication (goal_id)"
    )
    op.execute(
        "CREATE INDEX review_publication_requested_by_idx"
        " ON app.review_publication (requested_by)"
    )
    op.execute(
        "CREATE INDEX review_publication_replaces_idx"
        " ON app.review_publication (replaces_publication_id)"
    )
    op.execute("""
        CREATE UNIQUE INDEX review_publication_one_current_idx
            ON app.review_publication (game_id, player_id)
            WHERE status = 'published'
    """)
    op.execute("""
        CREATE UNIQUE INDEX review_publication_one_exporting_idx
            ON app.review_publication (game_id, player_id)
            WHERE status = 'exporting'
    """)

    op.execute("""
        CREATE TABLE app.evidence_clip (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            judgment_id uuid NOT NULL REFERENCES app.judgment (id) ON DELETE CASCADE,
            judgment_revision_id uuid NOT NULL
                REFERENCES app.judgment_revision (id) ON DELETE CASCADE,
            version bigint NOT NULL
                CONSTRAINT evidence_clip_version_positive CHECK (version > 0),
            storage_key text NOT NULL
                CONSTRAINT evidence_clip_storage_key_length
                    CHECK (char_length(storage_key) BETWEEN 1 AND 500),
            duration_ms integer
                CONSTRAINT evidence_clip_duration_positive CHECK (duration_ms > 0),
            size_bytes bigint
                CONSTRAINT evidence_clip_size_positive CHECK (size_bytes > 0),
            sha256 text
                CONSTRAINT evidence_clip_sha256_format
                    CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            status text NOT NULL DEFAULT 'pending'
                CONSTRAINT evidence_clip_status_allowed
                    CHECK (status IN ('pending', 'ready', 'failed', 'deleted')),
            delete_after timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            ready_at timestamptz,
            deleted_at timestamptz,
            CONSTRAINT evidence_clip_ready_metadata CHECK (
                status <> 'ready'
                OR (duration_ms IS NOT NULL AND size_bytes IS NOT NULL
                    AND sha256 IS NOT NULL AND ready_at IS NOT NULL)
            ),
            CONSTRAINT evidence_clip_unique_version UNIQUE (judgment_id, version)
        )
    """)
    op.execute(
        "CREATE INDEX evidence_clip_judgment_idx ON app.evidence_clip (judgment_id)"
    )
    op.execute(
        "CREATE INDEX evidence_clip_revision_idx"
        " ON app.evidence_clip (judgment_revision_id)"
    )
    op.execute(
        "CREATE INDEX evidence_clip_delete_after_idx ON app.evidence_clip (delete_after)"
    )

    op.execute("""
        CREATE TABLE app.review_publication_item (
            publication_id uuid NOT NULL
                REFERENCES app.review_publication (id) ON DELETE CASCADE,
            judgment_id uuid NOT NULL REFERENCES app.judgment (id) ON DELETE CASCADE,
            judgment_revision_id uuid NOT NULL
                REFERENCES app.judgment_revision (id) ON DELETE CASCADE,
            ordinal smallint NOT NULL
                CONSTRAINT review_publication_item_ordinal CHECK (ordinal BETWEEN 1 AND 6),
            requested_clip_version bigint NOT NULL
                CONSTRAINT review_publication_item_clip_version CHECK (
                    requested_clip_version > 0
                ),
            evidence_clip_id uuid REFERENCES app.evidence_clip (id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (publication_id, judgment_id),
            CONSTRAINT review_publication_item_order_unique
                UNIQUE (publication_id, ordinal)
        )
    """)
    op.execute(
        "CREATE INDEX review_publication_item_judgment_idx"
        " ON app.review_publication_item (judgment_id)"
    )
    op.execute(
        "CREATE INDEX review_publication_item_revision_idx"
        " ON app.review_publication_item (judgment_revision_id)"
    )
    op.execute(
        "CREATE INDEX review_publication_item_clip_idx"
        " ON app.review_publication_item (evidence_clip_id)"
    )

    # Circular publication pointers arrive after their target tables.
    op.execute("""
        ALTER TABLE app.judgment
            ADD COLUMN current_publication_id uuid
                REFERENCES app.review_publication (id),
            ADD COLUMN current_clip_id uuid UNIQUE
                REFERENCES app.evidence_clip (id)
    """)
    op.execute(
        "CREATE INDEX judgment_current_publication_idx"
        " ON app.judgment (current_publication_id)"
    )
    op.execute(
        "CREATE INDEX judgment_current_clip_idx ON app.judgment (current_clip_id)"
    )
    op.execute("""
        ALTER TABLE app.judgment ADD CONSTRAINT judgment_publication_pointers_whole
        CHECK (
            (publication_status = 'published'
             AND current_publication_id IS NOT NULL
             AND current_revision_id IS NOT NULL
             AND current_clip_id IS NOT NULL)
            OR
            (publication_status <> 'published'
             AND current_publication_id IS NULL
             AND current_revision_id IS NULL
             AND current_clip_id IS NULL)
        )
    """)

    op.execute("""
        ALTER TABLE app.processing_job
            ADD COLUMN judgment_id uuid REFERENCES app.judgment (id) ON DELETE CASCADE,
            ADD COLUMN review_publication_id uuid
                REFERENCES app.review_publication (id) ON DELETE CASCADE
    """)
    op.execute(
        "CREATE INDEX processing_job_judgment_idx ON app.processing_job (judgment_id)"
    )
    op.execute(
        "CREATE INDEX processing_job_publication_idx"
        " ON app.processing_job (review_publication_id)"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_kind_allowed"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT"
        " processing_job_video_target_required"
    )
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_kind_allowed
            CHECK (kind IN ('transcode', 'thumbnail', 'clip_export'))
    """)
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_target_required
            CHECK (
                (kind IN ('transcode', 'thumbnail')
                 AND video_id IS NOT NULL
                 AND judgment_id IS NULL
                 AND review_publication_id IS NULL)
                OR
                (kind = 'clip_export'
                 AND video_id IS NULL
                 AND judgment_id IS NOT NULL
                 AND review_publication_id IS NOT NULL)
            )
    """)

    # Authorization helpers. Player predicates require all current pointers to
    # agree, so no mix of old text and new media can pass RLS.
    op.execute("""
        CREATE FUNCTION private.is_review_publication_coach(p_publication_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.review_publication p
                WHERE p.id = p_publication_id
                  AND private.is_player_coach(p.player_id)
            )
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.is_current_publication_for_player(p_publication_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.review_publication p
                WHERE p.id = p_publication_id
                  AND p.status = 'published'
                  AND private.is_player_self(p.player_id)
                  AND EXISTS (
                      SELECT 1 FROM app.judgment j
                      WHERE j.current_publication_id = p.id
                        AND j.publication_status = 'published'
                  )
            )
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.is_current_publication_item_for_player(
            p_publication_id uuid, p_judgment_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.review_publication_item i
                JOIN app.review_publication p ON p.id = i.publication_id
                JOIN app.judgment j ON j.id = i.judgment_id
                JOIN app.evidence_clip c ON c.id = i.evidence_clip_id
                JOIN app.observation o ON o.id = j.observation_id
                JOIN app.video v ON v.id = o.video_id
                WHERE i.publication_id = p_publication_id
                  AND i.judgment_id = p_judgment_id
                  AND p.status = 'published'
                  AND j.publication_status = 'published'
                  AND j.current_publication_id = i.publication_id
                  AND j.current_revision_id = i.judgment_revision_id
                  AND j.current_clip_id = i.evidence_clip_id
                  AND c.judgment_id = j.id
                  AND c.judgment_revision_id = i.judgment_revision_id
                  AND c.version = i.requested_clip_version
                  AND c.status = 'ready'
                  AND (c.delete_after IS NULL OR c.delete_after > now())
                  AND v.status = 'ready'
                  AND v.derivatives_expires_at > now()
                  AND private.is_player_self(p.player_id)
            )
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.is_current_evidence_clip_for_player(p_clip_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.review_publication_item i
                WHERE i.evidence_clip_id = p_clip_id
                  AND private.is_current_publication_item_for_player(
                      i.publication_id, i.judgment_id
                  )
            )
        $$
    """)
    # The player evidence projection. `app.game` has no player policy and
    # `app.user_account` stays self-only, so a player cannot join them directly;
    # this definer helper reads them but returns a row only when the item is the
    # caller's own current published pointer. It exposes no storage key, video
    # ID, or draft text.
    op.execute("""
        CREATE FUNCTION private.player_evidence(p_goal_id uuid)
        RETURNS TABLE (
            publication_id uuid, game_label text, published_at timestamptz,
            ordinal smallint, judgment_id uuid, published_revision_id uuid,
            verdict text, comment_text text, duration_ms integer,
            coach_display_name text
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT p.id,
                   CASE WHEN g.opponent IS NULL THEN initcap(g.kind)
                        ELSE 'vs ' || g.opponent END,
                   p.published_at, i.ordinal, j.id, r.id, r.verdict,
                   r.comment_text, c.duration_ms, a.display_name
            FROM app.review_publication p
            JOIN app.game g ON g.id = p.game_id
            JOIN app.review_publication_item i ON i.publication_id = p.id
            JOIN app.judgment j ON j.id = i.judgment_id
            JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
            JOIN app.evidence_clip c ON c.id = i.evidence_clip_id
            JOIN app.user_account a ON a.id = r.author_user_id
            WHERE p.goal_id = p_goal_id
              AND private.is_current_publication_item_for_player(p.id, j.id)
            ORDER BY g.played_at DESC, p.id, i.ordinal
        $$
    """)
    # The API role has SELECT but not UPDATE on `app.judgment`, and a row-locking
    # clause needs UPDATE, so the lock lives in this definer helper. It re-checks
    # the exact current pointer chain for the caller before naming the object, so
    # a player still cannot be handed a coach playback key or another player's
    # clip. VOLATILE is required because the body takes a row lock.
    op.execute("""
        CREATE FUNCTION private.player_clip_for_signing(
            p_judgment_id uuid, p_expected_revision_id uuid
        ) RETURNS TABLE (storage_key text, published_revision_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
            SELECT c.storage_key, r.id
            FROM app.judgment j
            JOIN app.review_publication_item i
              ON i.publication_id = j.current_publication_id
             AND i.judgment_id = j.id
            JOIN app.judgment_revision r ON r.id = j.current_revision_id
            JOIN app.evidence_clip c ON c.id = j.current_clip_id
            WHERE j.id = p_judgment_id
              AND r.id = p_expected_revision_id
              AND private.is_current_publication_item_for_player(
                  i.publication_id, i.judgment_id
              )
            FOR SHARE OF j
        $$
    """)
    # Tighten the Task 15 revision helper now that the complete pointer chain exists.
    op.execute("""
        CREATE OR REPLACE FUNCTION private.is_published_revision_for_player(
            p_judgment_id uuid, p_revision_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.judgment j
                JOIN app.review_publication_item i
                  ON i.publication_id = j.current_publication_id
                 AND i.judgment_id = j.id
                WHERE j.id = p_judgment_id
                  AND j.current_revision_id = p_revision_id
                  AND i.judgment_revision_id = p_revision_id
                  AND private.is_current_publication_item_for_player(
                      i.publication_id, i.judgment_id
                  )
            )
        $$
    """)

    # Content edits are blocked only while their exact snapshot is reserved.
    op.execute("""
        CREATE FUNCTION private.block_reserved_judgment_edit() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.version IS DISTINCT FROM OLD.version AND EXISTS (
                SELECT 1 FROM app.review_publication_item i
                JOIN app.review_publication p ON p.id = i.publication_id
                WHERE i.judgment_id = OLD.id AND p.status = 'exporting'
            ) THEN
                RAISE EXCEPTION 'judgment is reserved for export'
                    USING ERRCODE = 'P1701';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER judgment_reserved_edit
        BEFORE UPDATE OF version ON app.judgment
        FOR EACH ROW EXECUTE FUNCTION private.block_reserved_judgment_edit()
    """)

    _create_finalize_function()
    _create_request_function()
    _create_retry_cancel_withdraw_functions()
    _create_worker_functions()
    _create_job_failure_trigger()

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    op.execute(f"""
        CREATE POLICY review_publication_coach_select ON app.review_publication
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_coach(player_id))
    """)
    op.execute(f"""
        CREATE POLICY review_publication_player_select ON app.review_publication
            FOR SELECT TO {API_ROLE}
            USING (private.is_current_publication_for_player(id))
    """)
    op.execute(f"""
        CREATE POLICY review_publication_item_coach_select
            ON app.review_publication_item FOR SELECT TO {API_ROLE}
            USING (private.is_review_publication_coach(publication_id))
    """)
    op.execute(f"""
        CREATE POLICY review_publication_item_player_select
            ON app.review_publication_item FOR SELECT TO {API_ROLE}
            USING (private.is_current_publication_item_for_player(
                publication_id, judgment_id
            ))
    """)
    op.execute(f"""
        CREATE POLICY evidence_clip_coach_select ON app.evidence_clip
            FOR SELECT TO {API_ROLE}
            USING (private.is_judgment_coach(judgment_id))
    """)
    op.execute(f"""
        CREATE POLICY evidence_clip_player_select ON app.evidence_clip
            FOR SELECT TO {API_ROLE}
            USING (private.is_current_evidence_clip_for_player(id))
    """)

    # Clip jobs are inserted only by the definer publication function. Coaches
    # may still read their aggregate state through the existing queue surface.
    op.execute("DROP POLICY processing_job_coach_select ON app.processing_job")
    op.execute(f"""
        CREATE POLICY processing_job_coach_select ON app.processing_job
            FOR SELECT TO {API_ROLE}
            USING (
                (video_id IS NOT NULL AND private.is_video_coach(video_id))
                OR (review_publication_id IS NOT NULL
                    AND private.is_review_publication_coach(review_publication_id))
            )
    """)

    for table in TABLES:
        op.execute(f"GRANT SELECT ON app.{table} TO {API_ROLE}")
    op.execute(f"""
        GRANT INSERT (judgment_id, review_publication_id, kind,
                      idempotency_key, payload, max_attempts)
            ON app.processing_job TO {API_ROLE}
    """)
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated")
    op.execute(
        "ALTER FUNCTION private.block_reserved_judgment_edit()"
        f" OWNER TO {MIGRATION_ROLE}"
    )
    op.execute(
        "ALTER FUNCTION private.mark_failed_clip_export()"
        f" OWNER TO {MIGRATION_ROLE}"
    )
    op.execute(
        "ALTER FUNCTION private.finalize_review_publication(uuid)"
        f" OWNER TO {MIGRATION_ROLE}"
    )
    for function in (
        "private.block_reserved_judgment_edit()",
        "private.mark_failed_clip_export()",
        "private.finalize_review_publication(uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}, {WORKER_ROLE}"
        )
    for function in PLAYER_HELPERS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {API_ROLE}")
    for function in COACH_TRANSITIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {API_ROLE}")
    for function in WORKER_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA private TO {WORKER_ROLE}")

    for role in ("PUBLIC", "anon", "authenticated"):
        for table in TABLES:
            op.execute(f"REVOKE ALL ON TABLE app.{table} FROM {role}")


def _create_request_function() -> None:
    op.execute("""
        CREATE FUNCTION private.request_review_publication(
            p_game_id uuid, p_player_id uuid, p_goal_id uuid,
            p_replaces_publication_id uuid, p_idempotency_key text,
            p_judgment_ids uuid[], p_versions bigint[]
        ) RETURNS app.review_publication
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_publication app.review_publication%ROWTYPE;
            v_existing app.review_publication%ROWTYPE;
            v_current uuid;
            v_revision uuid;
            v_clip app.evidence_clip%ROWTYPE;
            v_clip_version bigint;
            v_count integer;
            v_index integer;
        BEGIN
            v_count := coalesce(array_length(p_judgment_ids, 1), 0);
            IF v_count NOT BETWEEN 3 AND 6 OR array_length(p_versions, 1) <> v_count
               OR p_idempotency_key IS NULL
               OR char_length(p_idempotency_key) NOT BETWEEN 1 AND 200
               OR EXISTS (
                    SELECT 1 FROM unnest(p_versions) version WHERE version < 1
               )
               OR (SELECT count(DISTINCT id) FROM unnest(p_judgment_ids) id) <> v_count
            THEN
                RAISE EXCEPTION 'invalid publication request' USING ERRCODE = '22023';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('review-key:' || p_idempotency_key, 0)
            );
            SELECT * INTO v_existing FROM app.review_publication
            WHERE idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_existing.game_id IS DISTINCT FROM p_game_id
                   OR v_existing.player_id IS DISTINCT FROM p_player_id
                   OR v_existing.goal_id IS DISTINCT FROM p_goal_id
                   OR v_existing.replaces_publication_id
                        IS DISTINCT FROM p_replaces_publication_id
                   OR (SELECT array_agg(i.judgment_id ORDER BY i.ordinal)
                       FROM app.review_publication_item i
                       WHERE i.publication_id = v_existing.id)
                        IS DISTINCT FROM p_judgment_ids
                   OR (SELECT array_agg(r.version ORDER BY i.ordinal)
                       FROM app.review_publication_item i
                       JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
                       WHERE i.publication_id = v_existing.id)
                        IS DISTINCT FROM p_versions
                THEN
                    RAISE EXCEPTION 'idempotency key payload mismatch'
                        USING ERRCODE = 'P1702';
                END IF;
                RETURN v_existing;
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('review:' || p_game_id::text || ':' || p_player_id::text, 0)
            );
            PERFORM 1 FROM app.judgment
            WHERE id = ANY(p_judgment_ids) ORDER BY id FOR UPDATE;

            IF NOT EXISTS (
                SELECT 1 FROM app.player p
                JOIN app.game g ON g.team_id = p.team_id
                JOIN app.development_goal goal ON goal.player_id = p.id
                WHERE p.id = p_player_id AND g.id = p_game_id
                  AND goal.id = p_goal_id AND goal.status = 'active'
                  AND p.active AND p.deleted_at IS NULL
                  AND p.deletion_pending_at IS NULL
                  AND private.is_player_coach(p.id)
            ) THEN
                RAISE EXCEPTION 'publication context is unavailable'
                    USING ERRCODE = '42501';
            END IF;

            SELECT id INTO v_current FROM app.review_publication
            WHERE game_id = p_game_id AND player_id = p_player_id
              AND status = 'published' FOR UPDATE;
            IF v_current IS DISTINCT FROM p_replaces_publication_id THEN
                RAISE EXCEPTION 'stale predecessor' USING ERRCODE = 'P1702';
            END IF;
            IF v_current IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.review_publication
                WHERE id = v_current AND goal_id = p_goal_id
            ) THEN
                RAISE EXCEPTION 'replacement goal mismatch' USING ERRCODE = 'P1702';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.review_publication
                WHERE game_id = p_game_id AND player_id = p_player_id
                  AND status = 'exporting'
            ) THEN
                RAISE EXCEPTION 'publication already exporting' USING ERRCODE = 'P1702';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM unnest(p_judgment_ids, p_versions) requested(judgment_id, version)
                LEFT JOIN app.judgment j ON j.id = requested.judgment_id
                LEFT JOIN app.judgment_revision r
                  ON r.judgment_id = j.id AND r.version = requested.version
                LEFT JOIN app.observation o ON o.id = j.observation_id
                LEFT JOIN app.video v ON v.id = o.video_id
                WHERE j.id IS NULL OR r.id IS NULL OR j.version <> requested.version
                  OR j.goal_id <> p_goal_id OR o.player_id <> p_player_id
                  OR v.game_id <> p_game_id OR v.status <> 'ready'
                  OR v.playback_key IS NULL OR v.derivatives_expires_at <= now()
                  OR r.verdict = 'not_relevant'
                  OR r.comment_text IS NULL OR btrim(r.comment_text) = ''
            ) THEN
                RAISE EXCEPTION 'judgment snapshot cannot be published'
                    USING ERRCODE = 'P1702';
            END IF;

            INSERT INTO app.review_publication (
                game_id, player_id, goal_id, requested_by, idempotency_key,
                status, replaces_publication_id, requested_count
            ) VALUES (
                p_game_id, p_player_id, p_goal_id, private.current_user_id(),
                p_idempotency_key, 'exporting', p_replaces_publication_id, v_count
            ) RETURNING * INTO v_publication;

            FOR v_index IN 1..v_count LOOP
                SELECT id INTO v_revision FROM app.judgment_revision
                WHERE judgment_id = p_judgment_ids[v_index]
                  AND version = p_versions[v_index];
                SELECT * INTO v_clip FROM app.evidence_clip
                WHERE judgment_id = p_judgment_ids[v_index]
                  AND judgment_revision_id = v_revision
                  AND status = 'ready'
                  AND (delete_after IS NULL OR delete_after > now())
                ORDER BY version DESC LIMIT 1;
                IF NOT FOUND THEN
                    SELECT coalesce(max(version), 0) + 1 INTO v_clip_version
                    FROM app.evidence_clip
                    WHERE judgment_id = p_judgment_ids[v_index];
                    INSERT INTO app.evidence_clip (
                        judgment_id, judgment_revision_id, version, storage_key
                    ) VALUES (
                        p_judgment_ids[v_index], v_revision, v_clip_version,
                        'clips/' || p_judgment_ids[v_index]::text || '/'
                            || v_clip_version::text || '.mp4'
                    ) RETURNING * INTO v_clip;
                ELSE
                    UPDATE app.evidence_clip SET delete_after = NULL
                    WHERE id = v_clip.id;
                END IF;

                INSERT INTO app.review_publication_item (
                    publication_id, judgment_id, judgment_revision_id, ordinal,
                    requested_clip_version, evidence_clip_id
                ) VALUES (
                    v_publication.id, p_judgment_ids[v_index], v_revision, v_index,
                    v_clip.version,
                    CASE WHEN v_clip.status = 'ready' THEN v_clip.id ELSE NULL END
                );
                IF v_clip.status <> 'ready' THEN
                    INSERT INTO app.processing_job (
                        judgment_id, review_publication_id, kind,
                        idempotency_key, payload, max_attempts
                    ) VALUES (
                        p_judgment_ids[v_index], v_publication.id, 'clip_export',
                        'clip-export:' || v_publication.id::text || ':'
                            || p_judgment_ids[v_index]::text,
                        '{}'::jsonb, 5
                    );
                END IF;
            END LOOP;

            IF NOT EXISTS (
                SELECT 1 FROM app.review_publication_item
                WHERE publication_id = v_publication.id AND evidence_clip_id IS NULL
            ) THEN
                PERFORM private.finalize_review_publication(v_publication.id);
            END IF;
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = v_publication.id;
            RETURN v_publication;
        END;
        $$
    """)


def _create_finalize_function() -> None:
    op.execute("""
        CREATE FUNCTION private.finalize_review_publication(p_publication_id uuid)
        RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_publication app.review_publication%ROWTYPE;
            v_current uuid;
        BEGIN
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id;
            IF NOT FOUND THEN RETURN false; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'review:' || v_publication.game_id::text || ':'
                    || v_publication.player_id::text, 0
            ));
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id FOR UPDATE;
            IF v_publication.status <> 'exporting' THEN RETURN false; END IF;

            PERFORM 1 FROM app.judgment j
            JOIN app.review_publication_item i ON i.judgment_id = j.id
            WHERE i.publication_id = p_publication_id ORDER BY j.id FOR UPDATE OF j;
            SELECT id INTO v_current FROM app.review_publication
            WHERE game_id = v_publication.game_id
              AND player_id = v_publication.player_id
              AND status = 'published' FOR UPDATE;

            IF v_current IS DISTINCT FROM v_publication.replaces_publication_id
               OR NOT EXISTS (
                    SELECT 1 FROM app.player p
                    JOIN app.development_goal g ON g.player_id = p.id
                    JOIN app.team_membership m
                      ON m.team_id = p.team_id
                     AND m.user_id = v_publication.requested_by
                     AND m.role = 'coach'
                    WHERE p.id = v_publication.player_id
                      AND p.active AND p.deleted_at IS NULL
                      AND p.deletion_pending_at IS NULL
                      AND g.id = v_publication.goal_id AND g.status = 'active'
               )
               OR EXISTS (
                    SELECT 1 FROM app.review_publication_item i
                    JOIN app.judgment j ON j.id = i.judgment_id
                    JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
                    JOIN app.evidence_clip c ON c.id = i.evidence_clip_id
                    JOIN app.observation o ON o.id = j.observation_id
                    JOIN app.video v ON v.id = o.video_id
                    WHERE i.publication_id = p_publication_id
                      AND (j.version <> r.version
                        OR j.goal_id <> v_publication.goal_id
                        OR o.player_id <> v_publication.player_id
                        OR v.game_id <> v_publication.game_id
                        OR v.status <> 'ready'
                        OR v.derivatives_expires_at <= now()
                        OR c.judgment_id <> j.id
                        OR c.judgment_revision_id <> r.id
                        OR c.version <> i.requested_clip_version
                        OR c.status <> 'ready'
                        OR c.delete_after IS NOT NULL)
               )
               OR EXISTS (
                    SELECT 1 FROM app.review_publication_item
                    WHERE publication_id = p_publication_id
                      AND evidence_clip_id IS NULL
               )
            THEN
                UPDATE app.review_publication SET
                    status = 'failed',
                    first_terminal_failure_at = coalesce(first_terminal_failure_at, now()),
                    private_exports_expires_at = coalesce(
                        private_exports_expires_at, now() + interval '7 days'
                    ),
                    updated_at = now()
                WHERE id = p_publication_id AND status = 'exporting';
                UPDATE app.processing_job SET cancel_requested_at = now()
                WHERE review_publication_id = p_publication_id
                  AND status IN ('queued', 'running');
                RETURN false;
            END IF;

            IF v_current IS NOT NULL THEN
                UPDATE app.judgment j SET
                    publication_status = 'withdrawn', current_publication_id = NULL,
                    current_revision_id = NULL, current_clip_id = NULL,
                    published_at = NULL, updated_at = now()
                WHERE j.current_publication_id = v_current
                  AND NOT EXISTS (
                      SELECT 1 FROM app.review_publication_item i
                      WHERE i.publication_id = p_publication_id
                        AND i.judgment_id = j.id
                  );
                UPDATE app.review_publication SET status = 'superseded', updated_at = now()
                WHERE id = v_current;
            END IF;

            UPDATE app.judgment j SET
                publication_status = 'published',
                current_publication_id = i.publication_id,
                current_revision_id = i.judgment_revision_id,
                current_clip_id = i.evidence_clip_id,
                published_at = now(), updated_at = now()
            FROM app.review_publication_item i
            WHERE i.publication_id = p_publication_id AND i.judgment_id = j.id;

            UPDATE app.review_publication SET
                status = 'published', published_at = now(), updated_at = now()
            WHERE id = p_publication_id;

            UPDATE app.evidence_clip c SET
                delete_after = coalesce(c.delete_after, now() + interval '24 hours')
            WHERE c.status = 'ready'
              AND c.judgment_id IN (
                  SELECT i.judgment_id FROM app.review_publication_item i
                  WHERE i.publication_id IN (p_publication_id, v_current)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM app.judgment j WHERE j.current_clip_id = c.id
              );
            RETURN true;
        END;
        $$
    """)


def _create_retry_cancel_withdraw_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.retry_review_publication(p_publication_id uuid)
        RETURNS app.review_publication
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_publication app.review_publication%ROWTYPE;
            v_current uuid;
        BEGIN
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id;
            IF NOT FOUND OR NOT private.is_player_coach(v_publication.player_id) THEN
                RAISE EXCEPTION 'publication unavailable' USING ERRCODE = '42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'review:' || v_publication.game_id::text || ':'
                    || v_publication.player_id::text, 0
            ));
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id FOR UPDATE;
            IF v_publication.status <> 'failed'
               OR v_publication.private_exports_expires_at <= now() THEN
                RAISE EXCEPTION 'publication cannot be retried' USING ERRCODE = 'P1702';
            END IF;
            SELECT id INTO v_current FROM app.review_publication
            WHERE game_id = v_publication.game_id
              AND player_id = v_publication.player_id
              AND status = 'published' FOR UPDATE;
            IF v_current IS DISTINCT FROM v_publication.replaces_publication_id
               OR EXISTS (
                    SELECT 1 FROM app.review_publication_item i
                    JOIN app.judgment j ON j.id = i.judgment_id
                    JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
                    WHERE i.publication_id = p_publication_id
                      AND j.version <> r.version
               )
               OR EXISTS (
                    SELECT 1 FROM app.review_publication
                    WHERE game_id = v_publication.game_id
                      AND player_id = v_publication.player_id
                      AND status = 'exporting'
               )
            THEN
                RAISE EXCEPTION 'publication retry is stale' USING ERRCODE = 'P1702';
            END IF;
            PERFORM 1 FROM app.judgment j
            JOIN app.review_publication_item i ON i.judgment_id = j.id
            WHERE i.publication_id = p_publication_id ORDER BY j.id FOR UPDATE OF j;

            UPDATE app.evidence_clip c SET status = 'pending', delete_after = NULL
            FROM app.review_publication_item i
            WHERE i.publication_id = p_publication_id
              AND i.evidence_clip_id IS NULL
              AND c.judgment_id = i.judgment_id
              AND c.version = i.requested_clip_version
              AND c.status = 'failed';
            UPDATE app.processing_job SET
                status = 'queued', attempts = 0, progress = 0,
                available_at = now(), cancel_requested_at = NULL,
                locked_at = NULL, locked_by = NULL, heartbeat_at = NULL,
                error_code = NULL, error_message = NULL, finished_at = NULL
            WHERE review_publication_id = p_publication_id
              AND status IN ('failed', 'cancelled');
            UPDATE app.review_publication SET status = 'exporting', updated_at = now()
            WHERE id = p_publication_id RETURNING * INTO v_publication;
            IF NOT EXISTS (
                SELECT 1 FROM app.review_publication_item
                WHERE publication_id = p_publication_id AND evidence_clip_id IS NULL
            ) THEN
                PERFORM private.finalize_review_publication(p_publication_id);
            END IF;
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id;
            RETURN v_publication;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.cancel_review_publication(p_publication_id uuid)
        RETURNS app.review_publication
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_publication app.review_publication%ROWTYPE;
        BEGIN
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id;
            IF NOT FOUND OR NOT private.is_player_coach(v_publication.player_id) THEN
                RAISE EXCEPTION 'publication unavailable' USING ERRCODE = '42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'review:' || v_publication.game_id::text || ':'
                    || v_publication.player_id::text, 0
            ));
            SELECT * INTO v_publication FROM app.review_publication
            WHERE id = p_publication_id FOR UPDATE;
            IF v_publication.status NOT IN ('exporting', 'failed', 'cancelled') THEN
                RAISE EXCEPTION 'publication cannot be cancelled' USING ERRCODE = 'P1702';
            END IF;
            UPDATE app.review_publication SET
                status = 'cancelled', cancelled_at = coalesce(cancelled_at, now()),
                private_exports_expires_at = coalesce(
                    private_exports_expires_at, now() + interval '7 days'
                ), updated_at = now()
            WHERE id = p_publication_id RETURNING * INTO v_publication;
            UPDATE app.processing_job SET
                cancel_requested_at = now(),
                status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END
            WHERE review_publication_id = p_publication_id
              AND status IN ('queued', 'running');
            UPDATE app.evidence_clip c SET delete_after = coalesce(
                c.delete_after, now() + interval '7 days'
            ) FROM app.review_publication_item i
            WHERE i.publication_id = p_publication_id
              AND i.judgment_id = c.judgment_id
              AND i.requested_clip_version = c.version
              AND NOT EXISTS (
                  SELECT 1 FROM app.judgment j WHERE j.current_clip_id = c.id
              );
            RETURN v_publication;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.withdraw_judgment(p_judgment_id uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_judgment app.judgment%ROWTYPE;
            v_game uuid;
            v_player uuid;
            v_publication uuid;
            v_clip uuid;
        BEGIN
            SELECT j.* INTO v_judgment
            FROM app.judgment j
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            WHERE j.id = p_judgment_id;
            IF NOT FOUND OR NOT private.is_judgment_coach(p_judgment_id) THEN
                RAISE EXCEPTION 'judgment unavailable' USING ERRCODE = '42501';
            END IF;
            SELECT v.game_id, o.player_id INTO v_game, v_player
            FROM app.observation o
            JOIN app.video v ON v.id = o.video_id
            WHERE o.id = v_judgment.observation_id;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'review:' || v_game::text || ':' || v_player::text, 0
            ));
            SELECT * INTO v_judgment FROM app.judgment
            WHERE id = p_judgment_id FOR UPDATE;
            v_publication := v_judgment.current_publication_id;
            v_clip := v_judgment.current_clip_id;
            UPDATE app.judgment SET
                publication_status = 'withdrawn', current_publication_id = NULL,
                current_revision_id = NULL, current_clip_id = NULL,
                published_at = NULL, updated_at = now()
            WHERE id = p_judgment_id AND publication_status = 'published';
            IF v_publication IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.judgment
                WHERE current_publication_id = v_publication
                  AND publication_status = 'published'
            ) THEN
                UPDATE app.review_publication SET status = 'withdrawn', updated_at = now()
                WHERE id = v_publication AND status = 'published';
            END IF;
            UPDATE app.review_publication SET
                status = 'cancelled', cancelled_at = coalesce(cancelled_at, now()),
                private_exports_expires_at = coalesce(
                    private_exports_expires_at, now() + interval '7 days'
                ), updated_at = now()
            WHERE game_id = v_game AND player_id = v_player
              AND status IN ('exporting', 'failed');
            UPDATE app.processing_job SET cancel_requested_at = now(),
                status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END
            WHERE review_publication_id IN (
                SELECT id FROM app.review_publication
                WHERE game_id = v_game AND player_id = v_player AND status = 'cancelled'
            ) AND status IN ('queued', 'running');
            UPDATE app.evidence_clip SET
                delete_after = coalesce(delete_after, now() + interval '24 hours')
            WHERE id = v_clip AND NOT EXISTS (
                SELECT 1 FROM app.judgment WHERE current_clip_id = v_clip
            );
        END;
        $$
    """)


def _create_worker_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.clip_export_input(p_job_id uuid, p_worker_id text)
        RETURNS TABLE (
            publication_id uuid, judgment_id uuid, evidence_clip_id uuid,
            source_key text, target_key text, clip_start_ms integer,
            clip_end_ms integer
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT p.id, j.id, c.id, v.playback_key, c.storage_key,
                   r.clip_start_ms, r.clip_end_ms
            FROM app.processing_job job
            JOIN app.review_publication p ON p.id = job.review_publication_id
            JOIN app.review_publication_item i
              ON i.publication_id = p.id AND i.judgment_id = job.judgment_id
            JOIN app.judgment j ON j.id = i.judgment_id
            JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
            JOIN app.evidence_clip c
              ON c.judgment_id = i.judgment_id
             AND c.version = i.requested_clip_version
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            JOIN app.player player ON player.id = p.player_id
            WHERE job.id = p_job_id AND job.kind = 'clip_export'
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND p.status = 'exporting' AND c.status = 'pending'
              AND player.active AND player.deleted_at IS NULL
              AND player.deletion_pending_at IS NULL
              AND v.status = 'ready' AND v.playback_key IS NOT NULL
              AND v.derivatives_expires_at > now()
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.complete_evidence_clip(
            p_job_id uuid, p_worker_id text, p_duration_ms integer,
            p_size_bytes bigint, p_sha256 text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_input record;
            v_expected integer;
        BEGIN
            SELECT * INTO v_input FROM private.clip_export_input(p_job_id, p_worker_id);
            IF NOT FOUND THEN RETURN false; END IF;
            v_expected := v_input.clip_end_ms - v_input.clip_start_ms;
            IF p_duration_ms <= 0 OR abs(p_duration_ms - v_expected) > 100
               OR p_size_bytes <= 0 OR p_sha256 !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'clip output failed verification' USING ERRCODE = '22023';
            END IF;
            UPDATE app.evidence_clip SET
                duration_ms = p_duration_ms, size_bytes = p_size_bytes,
                sha256 = p_sha256, status = 'ready', ready_at = now(),
                delete_after = NULL
            WHERE id = v_input.evidence_clip_id AND status = 'pending';
            IF NOT FOUND THEN RETURN false; END IF;
            UPDATE app.review_publication_item SET
                evidence_clip_id = v_input.evidence_clip_id, updated_at = now()
            WHERE publication_id = v_input.publication_id
              AND judgment_id = v_input.judgment_id
              AND evidence_clip_id IS NULL;
            IF NOT EXISTS (
                SELECT 1 FROM app.review_publication_item
                WHERE publication_id = v_input.publication_id
                  AND evidence_clip_id IS NULL
            ) THEN
                PERFORM private.finalize_review_publication(v_input.publication_id);
            END IF;
            RETURN true;
        END;
        $$
    """)


def _create_job_failure_trigger() -> None:
    op.execute("""
        CREATE FUNCTION private.mark_failed_clip_export() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.kind = 'clip_export' AND NEW.status = 'failed'
               AND OLD.status IS DISTINCT FROM 'failed' THEN
                UPDATE app.evidence_clip c SET status = 'failed'
                FROM app.review_publication_item i
                WHERE i.publication_id = NEW.review_publication_id
                  AND i.judgment_id = NEW.judgment_id
                  AND c.judgment_id = i.judgment_id
                  AND c.version = i.requested_clip_version
                  AND c.status = 'pending';
                UPDATE app.review_publication SET
                    status = 'failed',
                    first_terminal_failure_at = coalesce(first_terminal_failure_at, now()),
                    private_exports_expires_at = coalesce(
                        private_exports_expires_at, now() + interval '7 days'
                    ), updated_at = now()
                WHERE id = NEW.review_publication_id AND status = 'exporting';
                UPDATE app.processing_job SET cancel_requested_at = now()
                WHERE review_publication_id = NEW.review_publication_id
                  AND id <> NEW.id AND status IN ('queued', 'running');
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER processing_job_clip_failure
        AFTER UPDATE OF status ON app.processing_job
        FOR EACH ROW EXECUTE FUNCTION private.mark_failed_clip_export()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS processing_job_clip_failure ON app.processing_job")
    op.execute("DROP FUNCTION IF EXISTS private.mark_failed_clip_export()")
    op.execute("DROP TRIGGER IF EXISTS judgment_reserved_edit ON app.judgment")
    op.execute("DROP FUNCTION IF EXISTS private.block_reserved_judgment_edit()")
    # Worker functions carry no policy; the coach transitions call finalize.
    for function in reversed(WORKER_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP FUNCTION IF EXISTS private.finalize_review_publication(uuid)")
    # Restore the Task 15 predicate before its Task 17 helpers disappear.
    op.execute("""
        CREATE OR REPLACE FUNCTION private.is_published_revision_for_player(
            p_judgment_id uuid, p_revision_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.judgment j
                WHERE j.id = p_judgment_id
                  AND j.current_revision_id = p_revision_id
                  AND j.publication_status = 'published'
                  AND private.is_goal_player_self(j.goal_id)
            )
        $$
    """)
    # Detach every pointer into the tables before the tables are dropped.
    op.execute("ALTER TABLE app.judgment DROP CONSTRAINT judgment_publication_pointers_whole")
    op.execute("ALTER TABLE app.judgment DROP COLUMN current_clip_id")
    op.execute("ALTER TABLE app.judgment DROP COLUMN current_publication_id")
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_target_required"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_kind_allowed"
    )
    # The Task 17 queue policy and the target check both name the columns that
    # are about to go, so they are removed before the columns are dropped.
    op.execute("DROP POLICY processing_job_coach_select ON app.processing_job")
    op.execute(f"""
        CREATE POLICY processing_job_coach_select ON app.processing_job
            FOR SELECT TO {API_ROLE}
            USING (video_id IS NOT NULL AND private.is_video_coach(video_id))
    """)
    op.execute("ALTER TABLE app.processing_job DROP COLUMN review_publication_id")
    op.execute("ALTER TABLE app.processing_job DROP COLUMN judgment_id")
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_kind_allowed
            CHECK (kind IN ('transcode', 'thumbnail'))
    """)
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_video_target_required
            CHECK (video_id IS NOT NULL)
    """)
    # The coach transitions return `app.review_publication`, so the table's
    # composite type holds them until they are gone.
    for function in reversed(COACH_TRANSITIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    # Dropping each table drops the policies that reference the helpers, so the
    # helpers can be removed afterwards without a dependent-object error.
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS app.{table}")
    for function in reversed(PLAYER_HELPERS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute(f"REVOKE USAGE ON SCHEMA private FROM {WORKER_ROLE}")
