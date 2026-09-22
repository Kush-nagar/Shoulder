"""Retention, verified deletion, and content-free product events

Revision ID: 0013_retention_deletion
Revises: 0012_email_delivery
"""

# ruff: noqa: E501 -- security-reviewed SQL stays readable as complete statements.

from alembic import op

revision = "0013_retention_deletion"
down_revision = "0012_email_delivery"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"
TABLES = (
    "retention_policy_confirmation",
    "deletion_manifest",
    "deletion_manifest_object",
    "product_event",
)


def upgrade() -> None:
    _add_lifecycle_columns()
    _create_tables()
    _extend_queue()
    _create_policy_confirmation_functions()
    _create_event_functions()
    _create_deletion_functions()
    _strengthen_worker_fencing()
    _create_policies_and_grants()


def _add_lifecycle_columns() -> None:
    op.execute("""
        ALTER TABLE app.team
            ADD COLUMN media_deletion_pending_at timestamptz
    """)
    op.execute("""
        ALTER TABLE app.video
            ADD COLUMN abandoned_at timestamptz,
            ADD COLUMN rejected_at timestamptz,
            ADD COLUMN source_deleted_at timestamptz,
            ADD CONSTRAINT video_failure_clock_shape CHECK (
                abandoned_at IS NULL OR rejected_at IS NULL
            ),
            ADD CONSTRAINT video_source_deleted_after_completion CHECK (
                source_deleted_at IS NULL OR upload_completed_at IS NOT NULL
            )
    """)
    op.execute("CREATE INDEX video_abandoned_at_idx ON app.video (abandoned_at)")
    op.execute("CREATE INDEX video_rejected_at_idx ON app.video (rejected_at)")
    op.execute(
        "CREATE INDEX video_source_deleted_at_idx ON app.video (source_deleted_at)"
    )

    # Existing failed rows predate the explicit classification. Treat them by
    # the earlier 24-hour clock. This can delete early; it can never retain late.
    op.execute("""
        UPDATE app.video SET rejected_at = first_terminal_failure_at
        WHERE status = 'failed' AND upload_completed_at IS NULL
          AND first_terminal_failure_at IS NOT NULL
    """)


def _create_tables() -> None:
    op.execute("""
        CREATE TABLE app.retention_policy_confirmation (
            team_id uuid PRIMARY KEY REFERENCES app.team (id) ON DELETE CASCADE,
            confirmed_by uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE RESTRICT,
            operator_user_id uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE RESTRICT,
            confirmed_season_end_at timestamptz NOT NULL,
            provider_backup_max_days smallint NOT NULL
                CONSTRAINT retention_backup_days_range CHECK (
                    provider_backup_max_days BETWEEN 1 AND 30
                ),
            notice_confirmed_at timestamptz NOT NULL,
            collateral_deletion_confirmed_at timestamptz NOT NULL,
            provider_backup_confirmed_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX retention_confirmation_confirmed_by_idx"
        " ON app.retention_policy_confirmation (confirmed_by)"
    )
    op.execute(
        "CREATE INDEX retention_confirmation_operator_idx"
        " ON app.retention_policy_confirmation (operator_user_id)"
    )

    # IDs and exact object keys only. No names, notes, reflections, signed URLs,
    # filenames, JSON payload, or provider error text belongs in these tables.
    op.execute("""
        CREATE TABLE app.deletion_manifest (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind text NOT NULL
                CONSTRAINT deletion_manifest_kind_allowed CHECK (kind IN (
                    'video_source', 'video_all', 'export_cleanup',
                    'season_expiry', 'player_erasure', 'reflection_erasure'
                )),
            scope_key text NOT NULL UNIQUE
                CONSTRAINT deletion_manifest_scope_key_length CHECK (
                    char_length(scope_key) BETWEEN 1 AND 220
                ),
            team_id uuid NOT NULL,
            player_id uuid,
            video_id uuid,
            evidence_clip_id uuid,
            reflection_id uuid,
            requested_by uuid,
            operator_user_id uuid,
            status text NOT NULL DEFAULT 'pending'
                CONSTRAINT deletion_manifest_status_allowed CHECK (status IN (
                    'pending', 'running', 'awaiting_backup',
                    'completed', 'unresolved'
                )),
            deadline_at timestamptz NOT NULL,
            requested_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            first_sweep_at timestamptz,
            active_cleanup_verified_at timestamptz,
            backup_expires_at timestamptz NOT NULL,
            backup_verified_at timestamptz,
            unrelated_reviewed_at timestamptz,
            restore_replayed_at timestamptz,
            completed_at timestamptz,
            expires_at timestamptz,
            failure_code text
                CONSTRAINT deletion_manifest_failure_code_allowed CHECK (
                    failure_code IS NULL OR failure_code IN (
                        'worker_drain_pending', 'storage_delete_failed',
                        'storage_verify_failed', 'database_cleanup_failed',
                        'unrelated_data_review_pending',
                        'auth_account_delete_failed', 'backup_expiry_pending',
                        'suppression_record_failed',
                        'worker_attempts_exhausted'
                    )
                ),
            video_count integer NOT NULL DEFAULT 0
                CONSTRAINT deletion_manifest_video_count CHECK (video_count >= 0),
            other_player_clip_count integer NOT NULL DEFAULT 0
                CONSTRAINT deletion_manifest_clip_count CHECK (
                    other_player_clip_count >= 0
                ),
            CONSTRAINT deletion_manifest_target_shape CHECK (
                (kind IN ('video_source', 'video_all')
                 AND video_id IS NOT NULL AND player_id IS NULL
                 AND evidence_clip_id IS NULL AND reflection_id IS NULL)
                OR
                (kind = 'export_cleanup'
                 AND evidence_clip_id IS NOT NULL AND player_id IS NULL
                 AND video_id IS NULL AND reflection_id IS NULL)
                OR
                (kind = 'season_expiry'
                 AND player_id IS NULL AND video_id IS NULL
                 AND evidence_clip_id IS NULL AND reflection_id IS NULL)
                OR
                (kind = 'player_erasure'
                 AND player_id IS NOT NULL AND video_id IS NULL
                 AND evidence_clip_id IS NULL AND reflection_id IS NULL)
                OR
                (kind = 'reflection_erasure'
                 AND reflection_id IS NOT NULL AND player_id IS NULL
                 AND video_id IS NULL AND evidence_clip_id IS NULL)
            ),
            CONSTRAINT deletion_manifest_completion_shape CHECK (
                (status = 'completed'
                 AND active_cleanup_verified_at IS NOT NULL
                 AND backup_verified_at IS NOT NULL
                 AND completed_at IS NOT NULL
                 AND expires_at IS NOT NULL
                 AND failure_code IS NULL)
                OR status <> 'completed'
            )
        )
    """)
    op.execute(
        "CREATE INDEX deletion_manifest_team_idx"
        " ON app.deletion_manifest (team_id, requested_at DESC)"
    )
    op.execute(
        "CREATE INDEX deletion_manifest_player_idx"
        " ON app.deletion_manifest (player_id) WHERE player_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX deletion_manifest_video_idx"
        " ON app.deletion_manifest (video_id) WHERE video_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX deletion_manifest_reflection_idx"
        " ON app.deletion_manifest (reflection_id) WHERE reflection_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX deletion_manifest_due_idx"
        " ON app.deletion_manifest (deadline_at)"
        " WHERE status IN ('pending', 'unresolved')"
    )
    op.execute(
        "CREATE INDEX deletion_manifest_expiry_idx"
        " ON app.deletion_manifest (expires_at) WHERE expires_at IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE app.deletion_manifest_object (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            manifest_id uuid NOT NULL
                REFERENCES app.deletion_manifest (id) ON DELETE CASCADE,
            object_key text NOT NULL
                CONSTRAINT deletion_object_key_length CHECK (
                    char_length(object_key) BETWEEN 1 AND 500
                ),
            object_kind text NOT NULL
                CONSTRAINT deletion_object_kind_allowed CHECK (object_kind IN (
                    'original', 'playback', 'thumbnail', 'evidence_clip',
                    'research_artifact'
                )),
            multipart_upload_id text
                CONSTRAINT deletion_object_upload_id_length CHECK (
                    multipart_upload_id IS NULL
                    OR char_length(multipart_upload_id) BETWEEN 1 AND 500
                ),
            status text NOT NULL DEFAULT 'pending'
                CONSTRAINT deletion_object_status_allowed CHECK (status IN (
                    'pending', 'deleted', 'failed'
                )),
            attempts integer NOT NULL DEFAULT 0
                CONSTRAINT deletion_object_attempts_non_negative CHECK (attempts >= 0),
            last_attempt_at timestamptz,
            deleted_at timestamptz,
            error_code text
                CONSTRAINT deletion_object_error_code_allowed CHECK (
                    error_code IS NULL OR error_code IN (
                        'storage_delete_failed', 'storage_verify_failed'
                    )
                ),
            UNIQUE (manifest_id, object_key)
        )
    """)
    op.execute(
        "CREATE INDEX deletion_object_manifest_idx"
        " ON app.deletion_manifest_object (manifest_id, status)"
    )

    op.execute("""
        CREATE TABLE app.product_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type text NOT NULL
                CONSTRAINT product_event_type_allowed CHECK (event_type IN (
                    'review_started', 'clip_marked', 'draft_saved',
                    'publish_requested', 'clip_ready', 'player_opened',
                    'reflection_saved', 'reflection_removed'
                )),
            actor_user_id uuid
                REFERENCES app.user_account (id) ON DELETE SET NULL,
            team_id uuid NOT NULL REFERENCES app.team (id) ON DELETE CASCADE,
            player_id uuid REFERENCES app.player (id) ON DELETE CASCADE,
            game_id uuid REFERENCES app.game (id) ON DELETE CASCADE,
            video_id uuid REFERENCES app.video (id) ON DELETE CASCADE,
            judgment_id uuid REFERENCES app.judgment (id) ON DELETE CASCADE,
            publication_id uuid
                REFERENCES app.review_publication (id) ON DELETE CASCADE,
            dedupe_key text UNIQUE
                CONSTRAINT product_event_dedupe_length CHECK (
                    dedupe_key IS NULL OR char_length(dedupe_key) BETWEEN 1 AND 240
                ),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL DEFAULT (now() + interval '180 days'),
            CONSTRAINT product_event_retention_bounded CHECK (
                expires_at <= occurred_at + interval '180 days'
            ),
            CONSTRAINT product_event_shape CHECK (
                (event_type = 'review_started'
                 AND player_id IS NOT NULL AND game_id IS NOT NULL
                 AND video_id IS NOT NULL)
                OR
                (event_type = 'clip_marked'
                 AND player_id IS NOT NULL AND game_id IS NOT NULL
                 AND video_id IS NOT NULL)
                OR
                (event_type IN ('draft_saved', 'clip_ready',
                                'reflection_saved', 'reflection_removed')
                 AND player_id IS NOT NULL AND game_id IS NOT NULL
                 AND video_id IS NOT NULL AND judgment_id IS NOT NULL)
                OR
                (event_type IN ('publish_requested', 'player_opened')
                 AND player_id IS NOT NULL AND game_id IS NOT NULL
                 AND publication_id IS NOT NULL)
            )
        )
    """)
    op.execute(
        "CREATE INDEX product_event_expiry_idx ON app.product_event (expires_at)"
    )
    op.execute(
        "CREATE INDEX product_event_review_idx"
        " ON app.product_event (team_id, game_id, player_id, occurred_at)"
    )
    op.execute(
        "CREATE INDEX product_event_actor_idx ON app.product_event (actor_user_id)"
    )
    op.execute("CREATE INDEX product_event_player_idx ON app.product_event (player_id)")
    op.execute("CREATE INDEX product_event_game_idx ON app.product_event (game_id)")
    op.execute("CREATE INDEX product_event_video_idx ON app.product_event (video_id)")
    op.execute(
        "CREATE INDEX product_event_judgment_idx ON app.product_event (judgment_id)"
    )
    op.execute(
        "CREATE INDEX product_event_publication_idx"
        " ON app.product_event (publication_id, event_type, occurred_at)"
    )


def _create_policy_confirmation_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.enforce_season_cutoff() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.season_end_at IS DISTINCT FROM OLD.season_end_at AND (
                EXISTS (SELECT 1 FROM app.player p WHERE p.team_id = OLD.id)
                OR EXISTS (SELECT 1 FROM app.game g WHERE g.team_id = OLD.id)
                OR EXISTS (
                    SELECT 1 FROM app.development_goal goal
                    JOIN app.player p ON p.id = goal.player_id
                    WHERE p.team_id = OLD.id
                )
            ) THEN
                RAISE EXCEPTION 'season cutoff cannot change after product data exists'
                    USING ERRCODE = 'P2201';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.retention_policy_confirmation c
                WHERE c.team_id = OLD.id
            ) AND NEW.season_end_at IS DISTINCT FROM OLD.season_end_at THEN
                RAISE EXCEPTION 'confirmed season cutoff is immutable'
                    USING ERRCODE = 'P2201';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER team_season_cutoff_immutable
        BEFORE UPDATE OF season_end_at ON app.team
        FOR EACH ROW EXECUTE FUNCTION private.enforce_season_cutoff()
    """)

    op.execute("""
        CREATE FUNCTION private.confirm_retention_policy(
            p_team_id uuid, p_provider_backup_max_days smallint,
            p_season_cutoff_confirmed boolean,
            p_provider_backup_expiry_confirmed boolean,
            p_notice_confirmed boolean, p_collateral_confirmed boolean,
            p_operator_confirmed boolean
        ) RETURNS app.retention_policy_confirmation
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_team app.team%ROWTYPE;
            v_result app.retention_policy_confirmation%ROWTYPE;
        BEGIN
            SELECT * INTO v_team FROM app.team WHERE id = p_team_id FOR UPDATE;
            IF NOT FOUND OR v_team.created_by IS DISTINCT FROM private.current_user_id()
               OR NOT private.is_team_coach(p_team_id) THEN
                RAISE EXCEPTION 'retention confirmation unavailable'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT coalesce(p_season_cutoff_confirmed, false)
               OR NOT coalesce(p_provider_backup_expiry_confirmed, false)
               OR NOT coalesce(p_notice_confirmed, false)
               OR NOT coalesce(p_collateral_confirmed, false)
               OR NOT coalesce(p_operator_confirmed, false)
               OR p_provider_backup_max_days NOT BETWEEN 1 AND 30 THEN
                RAISE EXCEPTION 'all retention confirmations are required'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.retention_policy_confirmation (
                team_id, confirmed_by, operator_user_id,
                confirmed_season_end_at, provider_backup_max_days,
                notice_confirmed_at, collateral_deletion_confirmed_at,
                provider_backup_confirmed_at
            ) VALUES (
                p_team_id, private.current_user_id(), private.current_user_id(),
                v_team.season_end_at, p_provider_backup_max_days,
                now(), now(), now()
            ) ON CONFLICT (team_id) DO NOTHING
            RETURNING * INTO v_result;
            IF NOT FOUND THEN
                SELECT * INTO v_result FROM app.retention_policy_confirmation
                WHERE team_id = p_team_id;
            END IF;
            UPDATE app.deletion_manifest SET
                requested_by = coalesce(requested_by, v_result.confirmed_by),
                operator_user_id = coalesce(
                    operator_user_id, v_result.operator_user_id
                )
            WHERE team_id = p_team_id
              AND (requested_by IS NULL OR operator_user_id IS NULL);
            RETURN v_result;
        END;
        $$
    """)


def _create_event_functions() -> None:
    # Single internal writer. No arbitrary JSON or text argument exists.
    op.execute("""
        CREATE FUNCTION private.insert_product_event(
            p_event_type text, p_actor_user_id uuid, p_team_id uuid,
            p_player_id uuid, p_game_id uuid, p_video_id uuid,
            p_judgment_id uuid, p_publication_id uuid, p_dedupe_key text,
            p_occurred_at timestamptz DEFAULT now()
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            INSERT INTO app.product_event (
                event_type, actor_user_id, team_id, player_id, game_id,
                video_id, judgment_id, publication_id, dedupe_key,
                occurred_at, expires_at
            ) VALUES (
                p_event_type, p_actor_user_id, p_team_id, p_player_id, p_game_id,
                p_video_id, p_judgment_id, p_publication_id, p_dedupe_key,
                p_occurred_at, p_occurred_at + interval '180 days'
            ) ON CONFLICT (dedupe_key) DO NOTHING;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.capture_observation_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_game uuid; v_team uuid;
        BEGIN
            SELECT v.game_id, g.team_id INTO v_game, v_team
            FROM app.video v JOIN app.game g ON g.id = v.game_id
            WHERE v.id = NEW.video_id;
            PERFORM private.insert_product_event(
                'clip_marked', NEW.created_by, v_team, NEW.player_id, v_game,
                NEW.video_id, NULL, NULL, 'clip-marked:' || NEW.id::text,
                NEW.created_at
            );
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER observation_product_event
        AFTER INSERT ON app.observation
        FOR EACH ROW EXECUTE FUNCTION private.capture_observation_event()
    """)

    op.execute("""
        CREATE FUNCTION private.capture_judgment_revision_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_player uuid; v_video uuid; v_game uuid; v_team uuid;
        BEGIN
            SELECT o.player_id, o.video_id, v.game_id, g.team_id
            INTO v_player, v_video, v_game, v_team
            FROM app.judgment j
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            JOIN app.game g ON g.id = v.game_id
            WHERE j.id = NEW.judgment_id;
            PERFORM private.insert_product_event(
                'draft_saved', NEW.author_user_id, v_team, v_player, v_game,
                v_video, NEW.judgment_id, NULL,
                'draft-saved:' || NEW.id::text, NEW.created_at
            );
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER judgment_revision_product_event
        AFTER INSERT ON app.judgment_revision
        FOR EACH ROW EXECUTE FUNCTION private.capture_judgment_revision_event()
    """)

    op.execute("""
        CREATE FUNCTION private.capture_publication_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_team uuid;
        BEGIN
            SELECT g.team_id INTO v_team FROM app.game g WHERE g.id = NEW.game_id;
            PERFORM private.insert_product_event(
                'publish_requested', NEW.requested_by, v_team, NEW.player_id,
                NEW.game_id, NULL, NULL, NEW.id,
                'publish-requested:' || NEW.id::text, NEW.created_at
            );
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER review_publication_product_event
        AFTER INSERT ON app.review_publication
        FOR EACH ROW EXECUTE FUNCTION private.capture_publication_event()
    """)

    op.execute("""
        CREATE FUNCTION private.capture_clip_ready_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_player uuid; v_video uuid; v_game uuid; v_team uuid;
        BEGIN
            IF NEW.status = 'ready' AND OLD.status IS DISTINCT FROM 'ready' THEN
                SELECT o.player_id, o.video_id, v.game_id, g.team_id
                INTO v_player, v_video, v_game, v_team
                FROM app.judgment j
                JOIN app.observation o ON o.id = j.observation_id
                JOIN app.video v ON v.id = o.video_id
                JOIN app.game g ON g.id = v.game_id
                WHERE j.id = NEW.judgment_id;
                PERFORM private.insert_product_event(
                    'clip_ready', NULL, v_team, v_player, v_game, v_video,
                    NEW.judgment_id, NULL, 'clip-ready:' || NEW.id::text,
                    coalesce(NEW.ready_at, now())
                );
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER evidence_clip_product_event
        AFTER UPDATE OF status ON app.evidence_clip
        FOR EACH ROW EXECUTE FUNCTION private.capture_clip_ready_event()
    """)

    op.execute("""
        CREATE FUNCTION private.capture_reflection_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_row app.player_reflection%ROWTYPE;
            v_actor uuid; v_video uuid; v_game uuid; v_team uuid;
            v_type text; v_when timestamptz; v_manifest uuid;
            v_operator uuid; v_backup_days integer;
        BEGIN
            v_row := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            v_type := CASE WHEN TG_OP = 'DELETE'
                THEN 'reflection_removed' ELSE 'reflection_saved' END;
            v_when := CASE WHEN TG_OP = 'DELETE' THEN now() ELSE v_row.updated_at END;
            SELECT p.user_id, o.video_id, v.game_id, g.team_id
            INTO v_actor, v_video, v_game, v_team
            FROM app.player p
            JOIN app.judgment j ON j.id = v_row.judgment_id
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            JOIN app.game g ON g.id = v.game_id
            WHERE p.id = v_row.player_id;
            -- A reflection removed by a parent-row retention cascade has no
            -- surviving content context and must not create fresh history.
            IF v_team IS NULL THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            PERFORM private.insert_product_event(
                v_type, v_actor, v_team, v_row.player_id, v_game, v_video,
                v_row.judgment_id, NULL,
                v_type || ':' || v_row.id::text || ':'
                    || CASE WHEN TG_OP = 'DELETE' THEN 'deleted'
                            ELSE v_row.etag::text END,
                v_when
            );
            IF TG_OP = 'DELETE'
               AND coalesce(current_setting('app.retention_delete', true), '') <> '1'
            THEN
                SELECT confirmation.operator_user_id,
                       confirmation.provider_backup_max_days
                INTO v_operator, v_backup_days
                FROM app.retention_policy_confirmation confirmation
                WHERE confirmation.team_id = v_team;
                INSERT INTO app.deletion_manifest (
                    kind, scope_key, team_id, reflection_id, requested_by,
                    operator_user_id, deadline_at, backup_expires_at
                ) VALUES (
                    'reflection_erasure',
                    'reflection-erasure:' || v_row.id::text,
                    v_team, v_row.id, v_actor, v_operator, now(),
                    now() + pg_catalog.make_interval(
                        days => coalesce(v_backup_days, 30)
                    )
                ) ON CONFLICT (scope_key) DO UPDATE
                    SET scope_key = EXCLUDED.scope_key
                RETURNING id INTO v_manifest;
                PERFORM private.enqueue_manifest_job(v_manifest);
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER player_reflection_saved_product_event
        AFTER INSERT OR UPDATE OF text ON app.player_reflection
        FOR EACH ROW EXECUTE FUNCTION private.capture_reflection_event()
    """)
    op.execute("""
        CREATE TRIGGER player_reflection_removed_product_event
        BEFORE DELETE ON app.player_reflection
        FOR EACH ROW EXECUTE FUNCTION private.capture_reflection_event()
    """)

    op.execute("""
        CREATE FUNCTION private.record_review_started(
            p_video_id uuid, p_player_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_game uuid; v_team uuid; v_now timestamptz := now();
        BEGIN
            SELECT v.game_id, g.team_id INTO v_game, v_team
            FROM app.video v JOIN app.game g ON g.id = v.game_id
            JOIN app.player p ON p.team_id = g.team_id AND p.id = p_player_id
            WHERE v.id = p_video_id AND private.is_video_coach(v.id)
              AND v.status = 'ready' AND v.derivatives_expires_at > v_now
              AND p.deletion_pending_at IS NULL;
            IF NOT FOUND THEN RETURN false; END IF;
            PERFORM private.insert_product_event(
                'review_started', private.current_user_id(), v_team, p_player_id,
                v_game, p_video_id, NULL, NULL,
                'review-started:' || private.current_user_id()::text || ':'
                    || p_video_id::text || ':' || p_player_id::text || ':'
                    || to_char(date_trunc('hour', v_now), 'YYYYMMDDHH24'),
                v_now
            );
            RETURN true;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.record_player_opened(p_goal_id uuid) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_count integer;
        BEGIN
            INSERT INTO app.product_event (
                event_type, actor_user_id, team_id, player_id, game_id,
                publication_id, dedupe_key, occurred_at, expires_at
            )
            SELECT 'player_opened', private.current_user_id(), player.team_id,
                   player.id, publication.game_id, publication.id,
                   'player-opened:' || publication.id::text || ':' || player.id::text,
                   now(), now() + interval '180 days'
            FROM app.review_publication publication
            JOIN app.player player ON player.id = publication.player_id
            JOIN app.judgment judgment
              ON judgment.current_publication_id = publication.id
             AND judgment.publication_status = 'published'
            WHERE publication.goal_id = p_goal_id
              AND publication.status = 'published'
              AND private.is_player_self(player.id)
            GROUP BY publication.id, player.team_id, player.id, publication.game_id
            ON CONFLICT (dedupe_key) DO NOTHING;
            GET DIAGNOSTICS v_count = ROW_COUNT;
            RETURN v_count;
        END;
        $$
    """)


def _create_deletion_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.seed_deletion_manifest_objects(p_manifest_id uuid)
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
    """)

    op.execute("""
        CREATE FUNCTION private.cancel_manifest_work(p_manifest_id uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest app.deletion_manifest%ROWTYPE;
        BEGIN
            SELECT * INTO v_manifest FROM app.deletion_manifest
            WHERE id = p_manifest_id;
            IF NOT FOUND THEN RETURN; END IF;
            UPDATE app.processing_job job SET
                cancel_requested_at = coalesce(job.cancel_requested_at, now()),
                status = CASE WHEN job.status = 'queued' THEN 'cancelled'
                              ELSE job.status END,
                finished_at = CASE WHEN job.status = 'queued' THEN now()
                                   ELSE job.finished_at END
            WHERE job.status IN ('queued', 'running') AND job.kind <> 'retention_sweep'
              AND job.deletion_manifest_id IS DISTINCT FROM p_manifest_id
              AND (
                (v_manifest.kind IN ('season_expiry', 'player_erasure') AND (
                    job.video_id IN (
                        SELECT v.id FROM app.video v JOIN app.game g ON g.id = v.game_id
                        WHERE g.team_id = v_manifest.team_id
                    ) OR job.review_publication_id IN (
                        SELECT p.id FROM app.review_publication p
                        JOIN app.game g ON g.id = p.game_id
                        WHERE g.team_id = v_manifest.team_id
                    ) OR job.judgment_id IN (
                        SELECT j.id FROM app.judgment j
                        JOIN app.observation o ON o.id = j.observation_id
                        JOIN app.video v ON v.id = o.video_id
                        JOIN app.game g ON g.id = v.game_id
                        WHERE g.team_id = v_manifest.team_id
                    )
                ))
                OR (v_manifest.kind IN ('video_source', 'video_all')
                    AND job.video_id = v_manifest.video_id)
                OR (v_manifest.kind = 'export_cleanup' AND EXISTS (
                    SELECT 1
                    FROM app.review_publication_item item
                    JOIN app.evidence_clip clip
                      ON clip.judgment_id = item.judgment_id
                     AND clip.version = item.requested_clip_version
                    WHERE clip.id = v_manifest.evidence_clip_id
                      AND job.kind = 'clip_export'
                      AND job.review_publication_id = item.publication_id
                      AND job.judgment_id = item.judgment_id
                ))
                OR (v_manifest.kind IN ('season_expiry', 'player_erasure')
                    AND job.email_delivery_id IN (
                        SELECT delivery.id
                        FROM app.email_delivery delivery
                        LEFT JOIN app.review_publication publication
                          ON publication.id = delivery.publication_id
                        LEFT JOIN app.video video ON video.id = delivery.video_id
                        LEFT JOIN app.game publication_game
                          ON publication_game.id = publication.game_id
                        LEFT JOIN app.game video_game ON video_game.id = video.game_id
                        LEFT JOIN app.player delivery_player
                          ON delivery_player.id = delivery.player_id
                        WHERE publication_game.team_id = v_manifest.team_id
                           OR video_game.team_id = v_manifest.team_id
                           OR delivery_player.team_id = v_manifest.team_id
                    ))
              );
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.enqueue_manifest_job(p_manifest_id uuid) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest app.deletion_manifest%ROWTYPE; v_job uuid;
        BEGIN
            SELECT * INTO v_manifest FROM app.deletion_manifest
            WHERE id = p_manifest_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            INSERT INTO app.processing_job (
                player_id, deletion_manifest_id, kind, idempotency_key,
                payload, max_attempts
            ) VALUES (
                CASE WHEN v_manifest.kind = 'player_erasure'
                     THEN v_manifest.player_id ELSE NULL END,
                v_manifest.id,
                CASE WHEN v_manifest.kind = 'player_erasure'
                     THEN 'player_data_delete' ELSE 'video_retention_delete' END,
                'delete-manifest:' || v_manifest.id::text, '{}'::jsonb, 20
            ) ON CONFLICT (idempotency_key) DO UPDATE
                SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING id INTO v_job;
            RETURN v_job;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.ensure_retention_manifest(
            p_kind text, p_scope_key text, p_team_id uuid, p_player_id uuid,
            p_video_id uuid, p_evidence_clip_id uuid, p_deadline_at timestamptz,
            p_backup_days integer
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            INSERT INTO app.deletion_manifest (
                kind, scope_key, team_id, player_id, video_id, evidence_clip_id,
                requested_by, operator_user_id, deadline_at, backup_expires_at
            ) VALUES (
                p_kind, p_scope_key, p_team_id, p_player_id, p_video_id,
                p_evidence_clip_id,
                (SELECT confirmed_by FROM app.retention_policy_confirmation
                 WHERE team_id = p_team_id),
                (SELECT operator_user_id FROM app.retention_policy_confirmation
                 WHERE team_id = p_team_id),
                p_deadline_at,
                now() + pg_catalog.make_interval(days => p_backup_days)
            ) ON CONFLICT (scope_key) DO UPDATE
                SET scope_key = EXCLUDED.scope_key
            RETURNING id INTO v_manifest;
            PERFORM private.seed_deletion_manifest_objects(v_manifest);
            PERFORM private.cancel_manifest_work(v_manifest);
            PERFORM private.enqueue_manifest_job(v_manifest);
            RETURN v_manifest;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.enqueue_retention_sweep(p_now timestamptz DEFAULT now())
        RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_job uuid;
        BEGIN
            INSERT INTO app.processing_job (kind, idempotency_key, payload, max_attempts)
            VALUES (
                'retention_sweep',
                'retention-sweep:' || to_char(
                    date_trunc('minute', p_now), 'YYYYMMDDHH24MI'
                ),
                '{}'::jsonb, 5
            ) ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id INTO v_job;
            RETURN v_job;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.prepare_retention_sweep(
            p_job_id uuid, p_worker_id text, p_now timestamptz DEFAULT now()
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_now timestamptz := p_now; v_row record; v_count integer := 0;
        BEGIN
            IF v_now > now() THEN
                RAISE EXCEPTION 'retention sweep clock cannot be in the future'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
                  AND job.status = 'running' AND job.locked_by = p_worker_id
            ) THEN RETURN 0; END IF;

            DELETE FROM app.player_reflection_request WHERE expires_at <= v_now;
            DELETE FROM app.product_event WHERE expires_at <= v_now;
            FOR v_row IN
                SELECT v.id AS video_id, g.team_id, v.created_at AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = g.team_id
                WHERE v.status = 'uploading'
                  AND v.created_at + interval '7 days' <= v_now
            LOOP
                UPDATE app.video SET status = 'deletion_pending'
                WHERE id = v_row.video_id AND status = 'uploading';
                PERFORM private.ensure_retention_manifest(
                    'video_all', 'incomplete-upload:' || v_row.video_id::text,
                    v_row.team_id, NULL, v_row.video_id, NULL,
                    v_row.deadline + interval '7 days', v_row.backup_days
                );
                v_count := v_count + 1;
            END LOOP;

            FOR v_row IN
                SELECT v.id AS video_id, g.team_id,
                       CASE
                         WHEN v.rejected_at IS NOT NULL
                           THEN v.rejected_at + interval '24 hours'
                         WHEN v.upload_completed_at IS NOT NULL
                           THEN least(
                             v.first_terminal_failure_at + interval '7 days',
                             v.upload_completed_at + interval '14 days',
                             v.source_expires_at
                           )
                         ELSE v.created_at + interval '7 days'
                       END AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = g.team_id
                WHERE v.status = 'failed' AND (
                    (v.rejected_at IS NOT NULL
                     AND v.rejected_at + interval '24 hours' <= v_now)
                    OR (v.upload_completed_at IS NOT NULL
                        AND v.first_terminal_failure_at IS NOT NULL
                        AND least(
                            v.first_terminal_failure_at + interval '7 days',
                            v.upload_completed_at + interval '14 days',
                            v.source_expires_at
                        ) <= v_now)
                    OR (v.upload_completed_at IS NULL AND v.rejected_at IS NULL
                        AND v.created_at + interval '7 days' <= v_now)
                )
            LOOP
                UPDATE app.video SET status = 'deletion_pending'
                WHERE id = v_row.video_id AND status = 'failed';
                PERFORM private.ensure_retention_manifest(
                    'video_all', 'failed-video:' || v_row.video_id::text,
                    v_row.team_id, NULL, v_row.video_id, NULL,
                    v_row.deadline, v_row.backup_days
                );
                v_count := v_count + 1;
            END LOOP;

            -- A crashed processing attempt may never get a terminal-failure
            -- clock. A retried failed attempt keeps its first failure clock.
            FOR v_row IN
                SELECT v.id AS video_id, g.team_id,
                       least(
                           v.upload_completed_at + interval '14 days',
                           coalesce(
                               v.first_terminal_failure_at + interval '7 days',
                               v.upload_completed_at + interval '14 days'
                           ),
                           v.source_expires_at
                       ) AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = g.team_id
                WHERE v.status IN ('uploaded', 'processing')
                  AND v.upload_completed_at IS NOT NULL
                  AND least(
                      v.upload_completed_at + interval '14 days',
                      coalesce(
                          v.first_terminal_failure_at + interval '7 days',
                          v.upload_completed_at + interval '14 days'
                      ),
                      v.source_expires_at
                  ) <= v_now
            LOOP
                UPDATE app.video SET status = 'deletion_pending'
                WHERE id = v_row.video_id AND status IN ('uploaded', 'processing');
                PERFORM private.ensure_retention_manifest(
                    'video_all', 'unprocessed-video:' || v_row.video_id::text,
                    v_row.team_id, NULL, v_row.video_id, NULL,
                    v_row.deadline, v_row.backup_days
                );
                v_count := v_count + 1;
            END LOOP;

            FOR v_row IN
                SELECT v.id AS video_id, g.team_id, v.source_expires_at AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.video v JOIN app.game g ON g.id = v.game_id
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = g.team_id
                WHERE v.upload_completed_at IS NOT NULL
                  AND v.source_deleted_at IS NULL
                  AND v.source_expires_at <= v_now
                  AND v.status = 'ready'
            LOOP
                PERFORM private.ensure_retention_manifest(
                    'video_source', 'video-source:' || v_row.video_id::text,
                    v_row.team_id, NULL, v_row.video_id, NULL,
                    v_row.deadline, v_row.backup_days
                );
                v_count := v_count + 1;
            END LOOP;

            FOR v_row IN
                SELECT t.id AS team_id, t.season_end_at + interval '365 days' AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.team t
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = t.id
                WHERE t.season_end_at + interval '365 days' <= v_now
                  AND EXISTS (
                      SELECT 1 FROM app.game g WHERE g.team_id = t.id
                      UNION ALL
                      SELECT 1 FROM app.player p WHERE p.team_id = t.id
                      UNION ALL
                      SELECT 1 FROM app.development_goal goal
                      JOIN app.player p ON p.id = goal.player_id
                      WHERE p.team_id = t.id
                  )
            LOOP
                UPDATE app.team SET media_deletion_pending_at = coalesce(
                    media_deletion_pending_at, v_now
                ) WHERE id = v_row.team_id;
                UPDATE app.video SET status = 'deletion_pending'
                WHERE game_id IN (
                    SELECT id FROM app.game WHERE team_id = v_row.team_id
                ) AND status <> 'deleted';
                UPDATE app.player SET deletion_pending_at = coalesce(
                    deletion_pending_at, v_now
                ) WHERE team_id = v_row.team_id;
                PERFORM private.ensure_retention_manifest(
                    'season_expiry', 'season-expiry:' || v_row.team_id::text,
                    v_row.team_id, NULL, NULL, NULL,
                    v_row.deadline, v_row.backup_days
                );
                v_count := v_count + 1;
            END LOOP;

            FOR v_row IN
                SELECT clip.id AS clip_id, game.team_id, clip.delete_after AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.evidence_clip clip
                JOIN app.judgment judgment ON judgment.id = clip.judgment_id
                JOIN app.observation observation ON observation.id = judgment.observation_id
                JOIN app.video video ON video.id = observation.video_id
                JOIN app.game game ON game.id = video.game_id
                LEFT JOIN app.retention_policy_confirmation c ON c.team_id = game.team_id
                WHERE clip.delete_after <= v_now AND clip.status <> 'deleted'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.judgment current
                      WHERE current.current_clip_id = clip.id
                  )
            LOOP
                UPDATE app.evidence_clip SET status = 'deleted', deleted_at = v_now
                WHERE id = v_row.clip_id AND NOT EXISTS (
                    SELECT 1 FROM app.judgment current
                    WHERE current.current_clip_id = v_row.clip_id
                );
                IF FOUND THEN
                    PERFORM private.ensure_retention_manifest(
                        'export_cleanup', 'export-cleanup:' || v_row.clip_id::text,
                        v_row.team_id, NULL, NULL, v_row.clip_id,
                        v_row.deadline, v_row.backup_days
                    );
                    v_count := v_count + 1;
                END IF;
            END LOOP;

            -- Failed/cancelled private exports use the publication's first
            -- terminal clock even when an old exporter never set delete_after.
            FOR v_row IN
                SELECT DISTINCT clip.id AS clip_id, game.team_id,
                       publication.private_exports_expires_at AS deadline,
                       coalesce(c.provider_backup_max_days, 30) AS backup_days
                FROM app.review_publication publication
                JOIN app.review_publication_item item
                  ON item.publication_id = publication.id
                JOIN app.evidence_clip clip
                  ON clip.judgment_id = item.judgment_id
                 AND clip.version = item.requested_clip_version
                JOIN app.judgment judgment ON judgment.id = clip.judgment_id
                JOIN app.observation observation
                  ON observation.id = judgment.observation_id
                JOIN app.video video ON video.id = observation.video_id
                JOIN app.game game ON game.id = video.game_id
                LEFT JOIN app.retention_policy_confirmation c
                  ON c.team_id = game.team_id
                WHERE publication.status IN ('failed', 'cancelled')
                  AND publication.private_exports_expires_at <= v_now
                  AND clip.status <> 'deleted'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.judgment current
                      WHERE current.current_clip_id = clip.id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM app.review_publication_item active_item
                      JOIN app.review_publication active_publication
                        ON active_publication.id = active_item.publication_id
                      WHERE active_publication.status = 'exporting'
                        AND active_item.judgment_id = clip.judgment_id
                        AND active_item.requested_clip_version = clip.version
                  )
            LOOP
                UPDATE app.evidence_clip target
                SET status = 'deleted', deleted_at = v_now
                WHERE target.id = v_row.clip_id
                  AND NOT EXISTS (
                      SELECT 1 FROM app.judgment current
                      WHERE current.current_clip_id = v_row.clip_id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM app.review_publication_item active_item
                      JOIN app.review_publication active_publication
                        ON active_publication.id = active_item.publication_id
                      WHERE active_publication.status = 'exporting'
                        AND active_item.judgment_id = target.judgment_id
                        AND active_item.requested_clip_version = target.version
                  );
                IF FOUND THEN
                    PERFORM private.ensure_retention_manifest(
                        'export_cleanup', 'export-cleanup:' || v_row.clip_id::text,
                        v_row.team_id, NULL, NULL, v_row.clip_id,
                        v_row.deadline, v_row.backup_days
                    );
                    v_count := v_count + 1;
                END IF;
            END LOOP;
            RETURN v_count;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.player_erasure_impact(p_player_id uuid)
        RETURNS TABLE (
            player_id uuid, team_id uuid, video_count integer,
            other_player_clip_count integer, remaining_player_count integer,
            remaining_goal_count integer, remaining_linked_account_count integer,
            can_request boolean
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT p.id, p.team_id,
                   (SELECT count(*)::integer FROM app.video v
                    JOIN app.game g ON g.id = v.game_id
                    WHERE g.team_id = p.team_id) AS video_count,
                   (SELECT count(*)::integer FROM app.evidence_clip clip
                    JOIN app.judgment j ON j.id = clip.judgment_id
                    JOIN app.observation o ON o.id = j.observation_id
                    JOIN app.video v ON v.id = o.video_id
                    JOIN app.game g ON g.id = v.game_id
                    WHERE g.team_id = p.team_id AND o.player_id <> p.id
                      AND clip.status <> 'deleted') AS other_player_clip_count,
                   (SELECT count(*)::integer FROM app.player other
                    WHERE other.team_id = p.team_id AND other.id <> p.id)
                       AS remaining_player_count,
                   (SELECT count(*)::integer FROM app.development_goal goal
                    JOIN app.player other ON other.id = goal.player_id
                    WHERE other.team_id = p.team_id AND other.id <> p.id)
                       AS remaining_goal_count,
                   (SELECT count(DISTINCT other.user_id)::integer
                    FROM app.player other
                    WHERE other.team_id = p.team_id AND other.id <> p.id
                      AND other.user_id IS NOT NULL)
                       AS remaining_linked_account_count,
                   private.is_player_coach(p.id)
                   AND confirmation.operator_user_id = private.current_user_id()
                   AND p.deletion_pending_at IS NULL AS can_request
            FROM app.player p
            JOIN app.retention_policy_confirmation confirmation
              ON confirmation.team_id = p.team_id
            WHERE p.id = p_player_id AND private.is_player_coach(p.id)
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.request_player_erasure(
            p_player_id uuid, p_idempotency_key text,
            p_expected_video_count integer,
            p_expected_other_player_clip_count integer,
            p_collateral_confirmed boolean, p_notice_confirmed boolean,
            p_unrelated_reviewed boolean
        ) RETURNS app.deletion_manifest
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_player app.player%ROWTYPE;
            v_confirmation app.retention_policy_confirmation%ROWTYPE;
            v_manifest app.deletion_manifest%ROWTYPE;
            v_videos integer; v_clips integer;
        BEGIN
            IF p_idempotency_key IS NULL
               OR p_idempotency_key !~
                  '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
               OR NOT coalesce(p_collateral_confirmed, false)
               OR NOT coalesce(p_notice_confirmed, false)
               OR NOT coalesce(p_unrelated_reviewed, false) THEN
                RAISE EXCEPTION 'complete deletion confirmation is required'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_player FROM app.player
            WHERE id = p_player_id FOR UPDATE;
            IF NOT FOUND OR NOT private.is_player_coach(p_player_id) THEN
                RAISE EXCEPTION 'player unavailable' USING ERRCODE = '42501';
            END IF;
            SELECT * INTO v_manifest FROM app.deletion_manifest
            WHERE scope_key = 'player-erasure:' || p_player_id::text || ':'
                              || p_idempotency_key;
            IF FOUND THEN RETURN v_manifest; END IF;
            IF v_player.deletion_pending_at IS NOT NULL THEN
                RAISE EXCEPTION 'player deletion is already pending'
                    USING ERRCODE = 'P2205';
            END IF;
            SELECT * INTO v_confirmation FROM app.retention_policy_confirmation
            WHERE team_id = v_player.team_id
              AND operator_user_id = private.current_user_id();
            IF NOT FOUND THEN
                RAISE EXCEPTION 'responsible operator confirmation is required'
                    USING ERRCODE = 'P2202';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'player-erasure:' || v_player.team_id::text, 0
            ));
            SELECT count(*)::integer INTO v_videos FROM app.video v
            JOIN app.game g ON g.id = v.game_id
            WHERE g.team_id = v_player.team_id;
            SELECT count(*)::integer INTO v_clips FROM app.evidence_clip clip
            JOIN app.judgment j ON j.id = clip.judgment_id
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            JOIN app.game g ON g.id = v.game_id
            WHERE g.team_id = v_player.team_id AND o.player_id <> p_player_id
              AND clip.status <> 'deleted';
            IF v_videos <> p_expected_video_count
               OR v_clips <> p_expected_other_player_clip_count THEN
                RAISE EXCEPTION 'deletion impact changed' USING ERRCODE = 'P2203';
            END IF;

            INSERT INTO app.deletion_manifest (
                kind, scope_key, team_id, player_id, requested_by,
                operator_user_id, deadline_at, backup_expires_at,
                unrelated_reviewed_at, video_count, other_player_clip_count
            ) VALUES (
                'player_erasure',
                'player-erasure:' || p_player_id::text || ':' || p_idempotency_key,
                v_player.team_id, p_player_id, private.current_user_id(),
                private.current_user_id(), now(),
                now() + make_interval(days => v_confirmation.provider_backup_max_days),
                now(), v_videos, v_clips
            ) ON CONFLICT (scope_key) DO UPDATE
                SET scope_key = EXCLUDED.scope_key
            RETURNING * INTO v_manifest;

            UPDATE app.player SET active = false,
                deleted_at = coalesce(deleted_at, now()),
                deletion_pending_at = coalesce(deletion_pending_at, now())
            WHERE id = p_player_id;
            DELETE FROM app.team_membership
            WHERE team_id = v_player.team_id AND user_id = v_player.user_id
              AND role = 'player';
            UPDATE app.team SET media_deletion_pending_at = coalesce(
                media_deletion_pending_at, now()
            ) WHERE id = v_player.team_id;
            UPDATE app.video SET status = 'deletion_pending'
            WHERE game_id IN (
                SELECT id FROM app.game WHERE team_id = v_player.team_id
            ) AND status <> 'deleted';
            UPDATE app.review_publication SET
                status = CASE WHEN status IN ('exporting', 'failed')
                              THEN 'cancelled' ELSE status END,
                cancelled_at = CASE WHEN status IN ('exporting', 'failed')
                                    THEN coalesce(cancelled_at, now())
                                    ELSE cancelled_at END,
                private_exports_expires_at = CASE
                    WHEN status IN ('exporting', 'failed')
                    THEN least(coalesce(private_exports_expires_at, now()), now())
                    ELSE private_exports_expires_at END,
                updated_at = now()
            WHERE game_id IN (
                SELECT id FROM app.game WHERE team_id = v_player.team_id
            );
            UPDATE app.email_delivery delivery SET
                status = 'suppressed', suppressed_at = now()
            WHERE delivery.status = 'queued' AND (
                delivery.player_id IN (
                    SELECT id FROM app.player WHERE team_id = v_player.team_id
                ) OR delivery.video_id IN (
                    SELECT v.id FROM app.video v JOIN app.game g ON g.id = v.game_id
                    WHERE g.team_id = v_player.team_id
                ) OR delivery.publication_id IN (
                    SELECT p.id FROM app.review_publication p
                    JOIN app.game g ON g.id = p.game_id
                    WHERE g.team_id = v_player.team_id
                )
            );
            PERFORM private.seed_deletion_manifest_objects(v_manifest.id);
            PERFORM private.cancel_manifest_work(v_manifest.id);
            PERFORM private.enqueue_manifest_job(v_manifest.id);
            RETURN v_manifest;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.deletion_manifest_status(p_manifest_id uuid)
        RETURNS TABLE (
            id uuid, kind text, status text, requested_at timestamptz,
            active_cleanup_verified_at timestamptz,
            backup_expires_at timestamptz, backup_verified_at timestamptz,
            completed_at timestamptz, failure_code text,
            video_count integer, other_player_clip_count integer
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT m.id, m.kind, m.status, m.requested_at,
                   m.active_cleanup_verified_at, m.backup_expires_at,
                   m.backup_verified_at, m.completed_at, m.failure_code,
                   m.video_count, m.other_player_clip_count
            FROM app.deletion_manifest m
            WHERE m.id = p_manifest_id
              AND m.operator_user_id = private.current_user_id()
              AND private.is_team_coach(m.team_id)
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.team_deletion_statuses(p_team_id uuid)
        RETURNS TABLE (
            id uuid, kind text, status text, requested_at timestamptz,
            active_cleanup_verified_at timestamptz,
            backup_expires_at timestamptz, backup_verified_at timestamptz,
            completed_at timestamptz, failure_code text,
            video_count integer, other_player_clip_count integer
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT m.id, m.kind, m.status, m.requested_at,
                   m.active_cleanup_verified_at, m.backup_expires_at,
                   m.backup_verified_at, m.completed_at, m.failure_code,
                   m.video_count, m.other_player_clip_count
            FROM app.deletion_manifest m
            WHERE m.team_id = p_team_id
              AND m.operator_user_id = private.current_user_id()
              AND private.is_team_coach(m.team_id)
            ORDER BY m.requested_at DESC, m.id
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.deletion_manifest_input(
            p_job_id uuid, p_worker_id text
        ) RETURNS TABLE (
            object_id uuid, object_key text, multipart_upload_id text
        ) LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            SELECT job.deletion_manifest_id INTO v_manifest
            FROM app.processing_job job
            WHERE job.id = p_job_id
              AND job.kind IN ('video_retention_delete', 'player_data_delete')
              AND job.status = 'running' AND job.locked_by = p_worker_id;
            IF v_manifest IS NULL THEN RETURN; END IF;
            UPDATE app.deletion_manifest SET
                status = 'running', started_at = coalesce(started_at, now()),
                failure_code = NULL
            WHERE id = v_manifest AND status IN ('pending', 'unresolved', 'running');
            -- Re-discover deterministic and persisted keys on every pass. A
            -- writer that lost its lease just before recording a newly-created
            -- object cannot make that object invisible to the verification
            -- sweep.
            PERFORM private.seed_deletion_manifest_objects(v_manifest);
            RETURN QUERY
                SELECT o.id, o.object_key, o.multipart_upload_id
                FROM app.deletion_manifest_object o
                WHERE o.manifest_id = v_manifest
                ORDER BY o.object_kind, o.id;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.fail_deletion_object(
            p_job_id uuid, p_worker_id text, p_object_id uuid, p_error_code text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            IF p_error_code NOT IN ('storage_delete_failed', 'storage_verify_failed') THEN
                RAISE EXCEPTION 'unsupported deletion error code'
                    USING ERRCODE = '22023';
            END IF;
            SELECT deletion_manifest_id INTO v_manifest
            FROM app.processing_job
            WHERE id = p_job_id
              AND kind IN ('video_retention_delete', 'player_data_delete')
              AND status = 'running' AND locked_by = p_worker_id;
            IF v_manifest IS NULL THEN RETURN false; END IF;
            UPDATE app.deletion_manifest_object SET
                status = 'failed', attempts = attempts + 1,
                last_attempt_at = now(), error_code = p_error_code
            WHERE id = p_object_id AND manifest_id = v_manifest;
            IF NOT FOUND THEN RETURN false; END IF;
            UPDATE app.deletion_manifest SET
                status = 'unresolved', failure_code = p_error_code
            WHERE id = v_manifest;
            RETURN true;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.complete_deletion_object(
            p_job_id uuid, p_worker_id text, p_object_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            SELECT deletion_manifest_id INTO v_manifest
            FROM app.processing_job
            WHERE id = p_job_id
              AND kind IN ('video_retention_delete', 'player_data_delete')
              AND status = 'running' AND locked_by = p_worker_id;
            IF v_manifest IS NULL THEN RETURN false; END IF;
            UPDATE app.deletion_manifest_object SET
                status = 'deleted', attempts = attempts + 1,
                last_attempt_at = now(), deleted_at = now(), error_code = NULL
            WHERE id = p_object_id AND manifest_id = v_manifest;
            RETURN FOUND;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.deletion_auth_account(
            p_job_id uuid, p_worker_id text
        ) RETURNS uuid
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_player_id uuid; v_user_id uuid;
        BEGIN
            SELECT manifest.player_id INTO v_player_id
            FROM app.processing_job job
            JOIN app.deletion_manifest manifest
              ON manifest.id = job.deletion_manifest_id
            WHERE job.id = p_job_id AND job.kind = 'player_data_delete'
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND manifest.kind = 'player_erasure'
              AND manifest.first_sweep_at IS NULL;
            IF v_player_id IS NULL THEN RETURN NULL; END IF;
            SELECT user_id INTO v_user_id FROM app.player
            WHERE id = v_player_id;
            IF v_user_id IS NULL
               OR EXISTS (
                   SELECT 1 FROM app.team_membership
                   WHERE user_id = v_user_id
               )
               OR EXISTS (
                   SELECT 1 FROM app.player
                   WHERE user_id = v_user_id AND id <> v_player_id
               )
               OR EXISTS (
                   SELECT 1 FROM app.team WHERE created_by = v_user_id
               ) THEN
                RETURN NULL;
            END IF;
            RETURN v_user_id;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.fail_deletion_auth(
            p_job_id uuid, p_worker_id text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            SELECT deletion_manifest_id INTO v_manifest
            FROM app.processing_job
            WHERE id = p_job_id AND kind = 'player_data_delete'
              AND status = 'running' AND locked_by = p_worker_id;
            IF v_manifest IS NULL THEN RETURN false; END IF;
            UPDATE app.deletion_manifest SET
                status = 'unresolved', failure_code = 'auth_account_delete_failed'
            WHERE id = v_manifest;
            RETURN FOUND;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.deletion_suppression_record(
            p_job_id uuid, p_worker_id text
        ) RETURNS TABLE (
            manifest_id uuid, kind text, team_id uuid, target_id uuid,
            requested_at timestamptz, backup_expires_at timestamptz
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT manifest.id, manifest.kind, manifest.team_id,
                   CASE
                       WHEN manifest.kind = 'player_erasure' THEN manifest.player_id
                       WHEN manifest.kind = 'reflection_erasure'
                           THEN manifest.reflection_id
                       WHEN manifest.kind = 'export_cleanup'
                           THEN manifest.evidence_clip_id
                       ELSE manifest.video_id
                   END,
                   manifest.requested_at, manifest.backup_expires_at
            FROM app.processing_job job
            JOIN app.deletion_manifest manifest
              ON manifest.id = job.deletion_manifest_id
            WHERE job.id = p_job_id
              AND job.kind IN ('video_retention_delete', 'player_data_delete')
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND manifest.kind IN (
                  'player_erasure', 'season_expiry', 'video_source', 'video_all',
                  'export_cleanup', 'reflection_erasure'
              )
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.fail_deletion_suppression(
            p_job_id uuid, p_worker_id text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            SELECT deletion_manifest_id INTO v_manifest
            FROM app.processing_job
            WHERE id = p_job_id
              AND kind IN ('video_retention_delete', 'player_data_delete')
              AND status = 'running' AND locked_by = p_worker_id;
            IF v_manifest IS NULL THEN RETURN false; END IF;
            UPDATE app.deletion_manifest SET status = 'unresolved',
                failure_code = 'suppression_record_failed'
            WHERE id = v_manifest;
            RETURN FOUND;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.expired_deletion_ledgers(
            p_job_id uuid, p_worker_id text, p_now timestamptz DEFAULT now()
        ) RETURNS TABLE (manifest_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT manifest.id
            FROM app.deletion_manifest manifest
            WHERE EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
                  AND job.status = 'running' AND job.locked_by = p_worker_id
            )
              AND manifest.expires_at <= p_now
              AND (
                  manifest.status = 'completed'
                  OR (manifest.status = 'unresolved'
                      AND manifest.failure_code = 'suppression_record_failed')
              )
            ORDER BY manifest.expires_at, manifest.id
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.fail_deletion_ledger_cleanup(
            p_job_id uuid, p_worker_id text, p_manifest_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
                  AND job.status = 'running' AND job.locked_by = p_worker_id
            ) THEN RETURN false; END IF;
            UPDATE app.deletion_manifest SET status = 'unresolved',
                failure_code = 'suppression_record_failed'
            WHERE id = p_manifest_id AND expires_at <= now();
            RETURN FOUND;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.complete_deletion_ledger_cleanup(
            p_job_id uuid, p_worker_id text, p_manifest_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id = p_job_id AND job.kind = 'retention_sweep'
                  AND job.status = 'running' AND job.locked_by = p_worker_id
            ) THEN RETURN false; END IF;
            DELETE FROM app.deletion_manifest
            WHERE id = p_manifest_id AND expires_at <= now()
              AND (
                  status = 'completed'
                  OR (status = 'unresolved'
                      AND failure_code = 'suppression_record_failed')
              );
            RETURN FOUND;
        END;
        $$
    """)

    # A deletion job that exhausts retries must leave a truthful durable state.
    # Ordinary retry transitions return to queued and do not fire this branch.
    op.execute("""
        CREATE FUNCTION private.mark_terminal_deletion_job_failure()
        RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.kind IN ('video_retention_delete', 'player_data_delete')
               AND NEW.status IN ('failed', 'cancelled')
               AND NEW.status IS DISTINCT FROM OLD.status
               AND NEW.deletion_manifest_id IS NOT NULL THEN
                UPDATE app.deletion_manifest SET
                    status = 'unresolved',
                    failure_code = CASE WHEN NEW.status = 'failed'
                        THEN 'worker_attempts_exhausted'
                        ELSE 'worker_drain_pending' END
                WHERE id = NEW.deletion_manifest_id
                  AND status <> 'completed';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER processing_job_terminal_deletion_failure
        AFTER UPDATE OF status ON app.processing_job
        FOR EACH ROW
        EXECUTE FUNCTION private.mark_terminal_deletion_job_failure()
    """)

    _create_cleanup_function()
    _create_finalize_and_replay_functions()


def _create_cleanup_function() -> None:
    op.execute("""
        CREATE FUNCTION private.delete_video_product_graph(p_video_ids uuid[])
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_judgments uuid[]; v_publications uuid[];
        BEGIN
            SELECT coalesce(array_agg(j.id), ARRAY[]::uuid[]) INTO v_judgments
            FROM app.judgment j JOIN app.observation o ON o.id = j.observation_id
            WHERE o.video_id = ANY(p_video_ids);
            SELECT coalesce(array_agg(DISTINCT i.publication_id), ARRAY[]::uuid[])
            INTO v_publications
            FROM app.review_publication_item i
            WHERE i.judgment_id = ANY(v_judgments);

            UPDATE app.processing_job SET
                cancel_requested_at = coalesce(cancel_requested_at, now()),
                status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END
            WHERE status IN ('queued', 'running') AND (
                video_id = ANY(p_video_ids)
                OR judgment_id = ANY(v_judgments)
                OR review_publication_id = ANY(v_publications)
            );
            UPDATE app.judgment SET
                publication_status = 'withdrawn', current_publication_id = NULL,
                current_revision_id = NULL, current_clip_id = NULL,
                published_at = NULL, updated_at = now()
            WHERE id = ANY(v_judgments);
            DELETE FROM app.review_publication WHERE id = ANY(v_publications);
            DELETE FROM app.evidence_clip WHERE judgment_id = ANY(v_judgments);
            DELETE FROM app.judgment WHERE id = ANY(v_judgments);
            DELETE FROM app.observation WHERE video_id = ANY(p_video_ids);
            DELETE FROM app.video WHERE id = ANY(p_video_ids);
        END;
        $$
    """)


def _create_finalize_and_replay_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.finalize_deletion_manifest(
            p_job_id uuid, p_worker_id text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_manifest app.deletion_manifest%ROWTYPE;
            v_video_ids uuid[]; v_account uuid;
        BEGIN
            SELECT manifest.* INTO v_manifest
            FROM app.processing_job job
            JOIN app.deletion_manifest manifest
              ON manifest.id = job.deletion_manifest_id
            WHERE job.id = p_job_id
              AND job.kind IN ('video_retention_delete', 'player_data_delete')
              AND job.status = 'running' AND job.locked_by = p_worker_id
            FOR UPDATE OF manifest;
            IF NOT FOUND THEN RETURN false; END IF;
            IF EXISTS (
                SELECT 1 FROM app.deletion_manifest_object object
                WHERE object.manifest_id = v_manifest.id
                  AND object.status <> 'deleted'
            ) THEN
                UPDATE app.deletion_manifest SET status = 'unresolved',
                    failure_code = coalesce(failure_code, 'storage_verify_failed')
                WHERE id = v_manifest.id;
                RETURN false;
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id <> p_job_id AND job.status IN ('queued', 'running')
                  AND job.deletion_manifest_id IS DISTINCT FROM v_manifest.id
                  AND (
                    (v_manifest.kind IN ('season_expiry', 'player_erasure') AND (
                        job.video_id IN (
                            SELECT video.id FROM app.video video
                            JOIN app.game game ON game.id = video.game_id
                            WHERE game.team_id = v_manifest.team_id
                        ) OR job.review_publication_id IN (
                            SELECT publication.id FROM app.review_publication publication
                            JOIN app.game game ON game.id = publication.game_id
                            WHERE game.team_id = v_manifest.team_id
                        )
                    )) OR job.video_id = v_manifest.video_id
                    OR (v_manifest.kind = 'export_cleanup' AND EXISTS (
                        SELECT 1
                        FROM app.review_publication_item item
                        JOIN app.evidence_clip clip
                          ON clip.judgment_id = item.judgment_id
                         AND clip.version = item.requested_clip_version
                        WHERE clip.id = v_manifest.evidence_clip_id
                          AND job.kind = 'clip_export'
                          AND job.review_publication_id = item.publication_id
                          AND job.judgment_id = item.judgment_id
                    ))
                  )
            ) THEN
                UPDATE app.deletion_manifest SET status = 'unresolved',
                    failure_code = 'worker_drain_pending'
                WHERE id = v_manifest.id;
                RETURN false;
            END IF;

            -- One lease-length delay separates object removal from the final
            -- sweep. A worker cancelled during upload can finish writing only
            -- before this queued verification pass runs.
            IF v_manifest.first_sweep_at IS NULL THEN
                UPDATE app.deletion_manifest SET first_sweep_at = now()
                WHERE id = v_manifest.id;
                INSERT INTO app.processing_job (
                    player_id, deletion_manifest_id, kind, idempotency_key,
                    payload, max_attempts, available_at
                ) VALUES (
                    CASE WHEN v_manifest.kind = 'player_erasure'
                         THEN v_manifest.player_id ELSE NULL END,
                    v_manifest.id,
                    CASE WHEN v_manifest.kind = 'player_erasure'
                         THEN 'player_data_delete'
                         ELSE 'video_retention_delete' END,
                    'delete-manifest-final:' || v_manifest.id::text,
                    '{}'::jsonb, 20, now() + interval '2 minutes'
                ) ON CONFLICT (idempotency_key) DO NOTHING;
                RETURN true;
            END IF;

            IF v_manifest.kind = 'video_source' THEN
                UPDATE app.video SET source_deleted_at = now()
                WHERE id = v_manifest.video_id;
            ELSIF v_manifest.kind = 'export_cleanup' THEN
                UPDATE app.review_publication_item SET evidence_clip_id = NULL
                WHERE evidence_clip_id = v_manifest.evidence_clip_id;
                DELETE FROM app.evidence_clip
                WHERE id = v_manifest.evidence_clip_id
                  AND NOT EXISTS (
                    SELECT 1 FROM app.judgment
                    WHERE current_clip_id = v_manifest.evidence_clip_id
                  );
            ELSIF v_manifest.kind = 'reflection_erasure' THEN
                PERFORM set_config('app.retention_delete', '1', true);
                DELETE FROM app.player_reflection
                WHERE id = v_manifest.reflection_id;
            ELSE
                PERFORM set_config('app.retention_delete', '1', true);
                IF v_manifest.kind = 'video_all' THEN
                    v_video_ids := ARRAY[v_manifest.video_id];
                ELSE
                    SELECT coalesce(array_agg(video.id), ARRAY[]::uuid[])
                    INTO v_video_ids
                    FROM app.video video JOIN app.game game ON game.id = video.game_id
                    WHERE game.team_id = v_manifest.team_id;
                END IF;
                PERFORM private.delete_video_product_graph(v_video_ids);
                IF v_manifest.kind IN ('season_expiry', 'player_erasure') THEN
                    DELETE FROM app.game WHERE team_id = v_manifest.team_id;
                END IF;
                IF v_manifest.kind = 'season_expiry' THEN
                    DELETE FROM app.development_goal goal
                    USING app.player player
                    WHERE goal.player_id = player.id
                      AND player.team_id = v_manifest.team_id;
                    DELETE FROM app.product_event WHERE team_id = v_manifest.team_id;
                    DELETE FROM app.team_membership membership
                    USING app.player player
                    WHERE membership.team_id = v_manifest.team_id
                      AND membership.user_id = player.user_id
                      AND membership.role = 'player';
                    UPDATE app.player SET active = false,
                        deleted_at = coalesce(deleted_at, now())
                    WHERE team_id = v_manifest.team_id;
                ELSIF v_manifest.kind = 'player_erasure' THEN
                    IF v_manifest.unrelated_reviewed_at IS NULL THEN
                        UPDATE app.deletion_manifest SET status = 'unresolved',
                            failure_code = 'unrelated_data_review_pending'
                        WHERE id = v_manifest.id;
                        RETURN false;
                    END IF;
                    SELECT player.user_id INTO v_account FROM app.player player
                    WHERE player.id = v_manifest.player_id;
                    DELETE FROM app.development_goal
                    WHERE player_id = v_manifest.player_id;
                    DELETE FROM app.player WHERE id = v_manifest.player_id;
                    DELETE FROM app.product_event WHERE team_id = v_manifest.team_id;
                    IF v_account IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM app.team_membership
                           WHERE user_id = v_account
                       )
                       AND NOT EXISTS (
                           SELECT 1 FROM app.player WHERE user_id = v_account
                       )
                       AND NOT EXISTS (
                           SELECT 1 FROM app.team WHERE created_by = v_account
                       ) THEN
                        DELETE FROM app.user_account WHERE id = v_account;
                    END IF;
                    UPDATE app.team SET media_deletion_pending_at = NULL
                    WHERE id = v_manifest.team_id;
                END IF;
            END IF;

            UPDATE app.deletion_manifest SET
                status = CASE WHEN backup_verified_at IS NULL
                              THEN 'awaiting_backup' ELSE 'completed' END,
                active_cleanup_verified_at = coalesce(
                    active_cleanup_verified_at, now()
                ),
                completed_at = CASE WHEN backup_verified_at IS NOT NULL
                                    THEN now() ELSE NULL END,
                backup_expires_at = CASE
                    WHEN active_cleanup_verified_at IS NULL THEN greatest(
                        backup_expires_at,
                        now() + pg_catalog.make_interval(days => coalesce((
                            SELECT confirmation.provider_backup_max_days
                            FROM app.retention_policy_confirmation confirmation
                            WHERE confirmation.team_id = v_manifest.team_id
                        ), 30))
                    )
                    ELSE backup_expires_at
                END,
                expires_at = CASE WHEN backup_verified_at IS NOT NULL
                                  THEN now() + interval '30 days' ELSE NULL END,
                failure_code = CASE WHEN backup_verified_at IS NULL
                                    THEN 'backup_expiry_pending' ELSE NULL END
            WHERE id = v_manifest.id;
            RETURN true;
        EXCEPTION WHEN OTHERS THEN
            UPDATE app.deletion_manifest SET status = 'unresolved',
                failure_code = 'database_cleanup_failed'
            WHERE id = v_manifest.id;
            RETURN false;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.confirm_manifest_backup_expired(p_manifest_id uuid)
        RETURNS app.deletion_manifest
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest app.deletion_manifest%ROWTYPE;
        BEGIN
            SELECT * INTO v_manifest FROM app.deletion_manifest
            WHERE id = p_manifest_id FOR UPDATE;
            IF NOT FOUND OR v_manifest.operator_user_id IS DISTINCT FROM private.current_user_id()
               OR NOT private.is_team_coach(v_manifest.team_id) THEN
                RAISE EXCEPTION 'deletion manifest unavailable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_manifest.active_cleanup_verified_at IS NULL
               OR v_manifest.backup_expires_at > now() THEN
                RAISE EXCEPTION 'backup expiry cannot be confirmed yet'
                    USING ERRCODE = 'P2204';
            END IF;
            UPDATE app.deletion_manifest SET
                backup_verified_at = coalesce(backup_verified_at, now()),
                status = 'completed', completed_at = coalesce(completed_at, now()),
                expires_at = coalesce(expires_at, now() + interval '30 days'),
                failure_code = NULL
            WHERE id = p_manifest_id RETURNING * INTO v_manifest;
            RETURN v_manifest;
        END;
        $$
    """)

    # Operator imports content-free records retained outside a restored DB.
    # Replay marks access blocked and reuses the same idempotent deletion path.
    op.execute("""
        CREATE FUNCTION private.replay_deletion_suppression(
            p_manifest_id uuid, p_kind text, p_team_id uuid, p_target_id uuid,
            p_requested_at timestamptz, p_backup_expires_at timestamptz
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_manifest uuid;
        BEGIN
            IF p_kind NOT IN ('player_erasure', 'season_expiry',
                              'video_source', 'video_all', 'export_cleanup',
                              'reflection_erasure') THEN
                RAISE EXCEPTION 'unsupported replay kind' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.deletion_manifest (
                id, kind, scope_key, team_id, player_id, video_id,
                evidence_clip_id, reflection_id,
                requested_by, operator_user_id, status, deadline_at,
                requested_at, backup_expires_at, restore_replayed_at,
                unrelated_reviewed_at
            ) VALUES (
                p_manifest_id, p_kind, 'restore-replay:' || p_manifest_id::text,
                p_team_id,
                CASE WHEN p_kind = 'player_erasure' THEN p_target_id END,
                CASE WHEN p_kind IN ('video_source', 'video_all') THEN p_target_id END,
                CASE WHEN p_kind = 'export_cleanup' THEN p_target_id END,
                CASE WHEN p_kind = 'reflection_erasure' THEN p_target_id END,
                (SELECT confirmation.confirmed_by
                 FROM app.retention_policy_confirmation confirmation
                 WHERE confirmation.team_id = p_team_id),
                (SELECT confirmation.operator_user_id
                 FROM app.retention_policy_confirmation confirmation
                 WHERE confirmation.team_id = p_team_id),
                'pending', p_requested_at, p_requested_at,
                greatest(
                    p_backup_expires_at,
                    now() + pg_catalog.make_interval(days => coalesce((
                        SELECT confirmation.provider_backup_max_days
                        FROM app.retention_policy_confirmation confirmation
                        WHERE confirmation.team_id = p_team_id
                    ), 30))
                ), now(),
                CASE WHEN p_kind = 'player_erasure' THEN now() END
            ) ON CONFLICT (id) DO UPDATE
                SET status = 'pending', started_at = NULL,
                    first_sweep_at = NULL,
                    active_cleanup_verified_at = NULL,
                    backup_expires_at = CASE
                        WHEN app.deletion_manifest.restore_replayed_at IS NULL
                        THEN EXCLUDED.backup_expires_at
                        ELSE app.deletion_manifest.backup_expires_at
                    END,
                    backup_verified_at = NULL, completed_at = NULL,
                    expires_at = NULL, failure_code = NULL,
                    restore_replayed_at = now()
            RETURNING id INTO v_manifest;
            DELETE FROM app.processing_job
            WHERE deletion_manifest_id = v_manifest;
            UPDATE app.deletion_manifest_object SET status = 'pending',
                attempts = 0, last_attempt_at = NULL, deleted_at = NULL,
                error_code = NULL
            WHERE manifest_id = v_manifest;
            IF p_kind = 'player_erasure' THEN
                DELETE FROM app.team_membership membership
                USING app.player player
                WHERE player.id = p_target_id
                  AND membership.team_id = p_team_id
                  AND membership.user_id = player.user_id
                  AND membership.role = 'player';
                UPDATE app.player SET active = false,
                    deleted_at = coalesce(deleted_at, now()),
                    deletion_pending_at = coalesce(deletion_pending_at, now())
                WHERE id = p_target_id;
                UPDATE app.team SET media_deletion_pending_at = coalesce(
                    media_deletion_pending_at, now()
                ) WHERE id = p_team_id;
            ELSIF p_kind = 'season_expiry' THEN
                UPDATE app.team SET media_deletion_pending_at = coalesce(
                    media_deletion_pending_at, now()
                ) WHERE id = p_team_id;
                UPDATE app.player SET deletion_pending_at = coalesce(
                    deletion_pending_at, now()
                ) WHERE team_id = p_team_id;
            ELSIF p_kind = 'export_cleanup' THEN
                UPDATE app.judgment SET publication_status = 'withdrawn',
                    current_publication_id = NULL, current_revision_id = NULL,
                    current_clip_id = NULL, published_at = NULL,
                    updated_at = now()
                WHERE current_clip_id = p_target_id;
                UPDATE app.evidence_clip SET status = 'deleted',
                    deleted_at = coalesce(deleted_at, now()),
                    delete_after = least(coalesce(delete_after, now()), now())
                WHERE id = p_target_id;
            ELSIF p_kind = 'reflection_erasure' THEN
                PERFORM set_config('app.retention_delete', '1', true);
                DELETE FROM app.player_reflection WHERE id = p_target_id;
            END IF;
            UPDATE app.video SET status = 'deletion_pending'
            WHERE (p_kind IN ('player_erasure', 'season_expiry') AND game_id IN (
                SELECT id FROM app.game WHERE team_id = p_team_id
            )) OR (p_kind = 'video_all' AND id = p_target_id);
            PERFORM private.seed_deletion_manifest_objects(v_manifest);
            PERFORM private.cancel_manifest_work(v_manifest);
            PERFORM private.enqueue_manifest_job(v_manifest);
            RETURN v_manifest;
        END;
        $$
    """)


def _extend_queue() -> None:
    op.execute("""
        ALTER TABLE app.processing_job
            ADD COLUMN player_id uuid REFERENCES app.player (id) ON DELETE SET NULL,
            ADD COLUMN deletion_manifest_id uuid
                REFERENCES app.deletion_manifest (id) ON DELETE CASCADE
    """)
    op.execute(
        "CREATE INDEX processing_job_player_idx ON app.processing_job (player_id)"
    )
    op.execute(
        "CREATE INDEX processing_job_deletion_manifest_idx"
        " ON app.processing_job (deletion_manifest_id)"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_kind_allowed"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_target_required"
    )
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_kind_allowed
            CHECK (kind IN (
                'transcode', 'thumbnail', 'clip_export', 'email_delivery',
                'retention_sweep', 'video_retention_delete', 'player_data_delete'
            ))
    """)
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_target_required
            CHECK (
                (kind IN ('transcode', 'thumbnail')
                 AND video_id IS NOT NULL
                 AND judgment_id IS NULL AND review_publication_id IS NULL
                 AND email_delivery_id IS NULL AND player_id IS NULL
                 AND deletion_manifest_id IS NULL)
                OR
                (kind = 'clip_export'
                 AND video_id IS NULL
                 AND judgment_id IS NOT NULL AND review_publication_id IS NOT NULL
                 AND email_delivery_id IS NULL AND player_id IS NULL
                 AND deletion_manifest_id IS NULL)
                OR
                (kind = 'email_delivery'
                 AND video_id IS NULL AND judgment_id IS NULL
                 AND review_publication_id IS NULL
                 AND email_delivery_id IS NOT NULL AND player_id IS NULL
                 AND deletion_manifest_id IS NULL)
                OR
                (kind = 'retention_sweep'
                 AND video_id IS NULL AND judgment_id IS NULL
                 AND review_publication_id IS NULL AND email_delivery_id IS NULL
                 AND player_id IS NULL AND deletion_manifest_id IS NULL)
                OR
                (kind = 'video_retention_delete'
                 AND judgment_id IS NULL AND review_publication_id IS NULL
                 AND email_delivery_id IS NULL AND player_id IS NULL
                 AND deletion_manifest_id IS NOT NULL)
                OR
                (kind = 'player_data_delete'
                 AND video_id IS NULL AND judgment_id IS NULL
                 AND review_publication_id IS NULL AND email_delivery_id IS NULL
                 AND deletion_manifest_id IS NOT NULL)
            )
    """)


def _strengthen_worker_fencing() -> None:
    # Direct player table reads use this helper through the publication RLS
    # policy. Requiring one complete current item applies the video/deadline
    # fence to that path too, not only to DTO and signing helpers.
    op.execute("""
        CREATE OR REPLACE FUNCTION private.is_current_publication_for_player(
            p_publication_id uuid
        ) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.review_publication publication
                JOIN app.judgment judgment
                  ON judgment.current_publication_id = publication.id
                 AND judgment.publication_status = 'published'
                WHERE publication.id = p_publication_id
                  AND publication.status = 'published'
                  AND private.is_player_self(publication.player_id)
                  AND private.is_current_publication_item_for_player(
                      publication.id, judgment.id
                  )
            )
        $$
    """)
    op.execute("DROP POLICY judgment_player_select ON app.judgment")
    op.execute(f"""
        CREATE POLICY judgment_player_select ON app.judgment
            FOR SELECT TO {API_ROLE}
            USING (
                current_publication_id IS NOT NULL
                AND private.is_current_publication_item_for_player(
                    current_publication_id, id
                )
            )
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION private.evidence_clip_object_disposable(
            p_job_id uuid, p_worker_id text, p_storage_key text
        ) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = '' AS $$
            SELECT CASE WHEN EXISTS (
                SELECT 1
                FROM app.evidence_clip clip
                JOIN app.judgment judgment ON judgment.id = clip.judgment_id
                JOIN app.observation observation
                  ON observation.id = judgment.observation_id
                JOIN app.video video ON video.id = observation.video_id
                WHERE clip.storage_key = p_storage_key
                  AND video.status IN ('deletion_pending', 'deleted')
            ) THEN true ELSE (
                EXISTS (
                    SELECT 1 FROM app.processing_job job
                    WHERE job.id = p_job_id
                      AND job.kind = 'clip_export'
                      AND job.status = 'running'
                      AND job.locked_by = p_worker_id
                ) AND NOT EXISTS (
                    SELECT 1 FROM app.evidence_clip clip
                    WHERE clip.storage_key = p_storage_key
                      AND (
                          clip.status = 'ready'
                          OR EXISTS (
                              SELECT 1 FROM app.judgment judgment
                              WHERE judgment.current_clip_id = clip.id
                          )
                      )
                )
            ) END
        $$
    """)


def _create_policies_and_grants() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    op.execute(f"""
        CREATE POLICY retention_confirmation_coach_select
            ON app.retention_policy_confirmation FOR SELECT TO {API_ROLE}
            USING (private.is_team_coach(team_id))
    """)
    for table in ("deletion_manifest", "deletion_manifest_object", "product_event"):
        op.execute(f"""
            CREATE POLICY {table}_operator_select ON app.{table}
                FOR SELECT TO {OPERATOR_ROLE} USING (true)
        """)
    # Deletion jobs are deliberately absent from the ordinary queue projection.
    op.execute("DROP POLICY processing_job_coach_select ON app.processing_job")
    op.execute(f"""
        CREATE POLICY processing_job_coach_select ON app.processing_job
            FOR SELECT TO {API_ROLE}
            USING (
                kind IN ('transcode', 'thumbnail', 'clip_export', 'email_delivery')
                AND (
                    (video_id IS NOT NULL AND private.is_video_coach(video_id))
                    OR (review_publication_id IS NOT NULL
                        AND private.is_review_publication_coach(review_publication_id))
                )
            )
    """)

    functions = (
        "private.enforce_season_cutoff()",
        "private.confirm_retention_policy(uuid,smallint,boolean,boolean,boolean,boolean,boolean)",
        "private.insert_product_event(text,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz)",
        "private.capture_observation_event()",
        "private.capture_judgment_revision_event()",
        "private.capture_publication_event()",
        "private.capture_clip_ready_event()",
        "private.capture_reflection_event()",
        "private.record_review_started(uuid,uuid)",
        "private.record_player_opened(uuid)",
        "private.seed_deletion_manifest_objects(uuid)",
        "private.cancel_manifest_work(uuid)",
        "private.enqueue_manifest_job(uuid)",
        "private.ensure_retention_manifest(text,text,uuid,uuid,uuid,uuid,timestamptz,integer)",
        "private.enqueue_retention_sweep(timestamptz)",
        "private.prepare_retention_sweep(uuid,text,timestamptz)",
        "private.player_erasure_impact(uuid)",
        "private.request_player_erasure(uuid,text,integer,integer,boolean,boolean,boolean)",
        "private.deletion_manifest_status(uuid)",
        "private.team_deletion_statuses(uuid)",
        "private.deletion_manifest_input(uuid,text)",
        "private.fail_deletion_object(uuid,text,uuid,text)",
        "private.complete_deletion_object(uuid,text,uuid)",
        "private.deletion_auth_account(uuid,text)",
        "private.fail_deletion_auth(uuid,text)",
        "private.deletion_suppression_record(uuid,text)",
        "private.fail_deletion_suppression(uuid,text)",
        "private.expired_deletion_ledgers(uuid,text,timestamptz)",
        "private.fail_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.complete_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.mark_terminal_deletion_job_failure()",
        "private.delete_video_product_graph(uuid[])",
        "private.finalize_deletion_manifest(uuid,text)",
        "private.confirm_manifest_backup_expired(uuid)",
        "private.replay_deletion_suppression(uuid,text,uuid,uuid,timestamptz,timestamptz)",
    )
    for function in functions:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
        )

    for function in (
        "private.confirm_retention_policy(uuid,smallint,boolean,boolean,boolean,boolean,boolean)",
        "private.record_review_started(uuid,uuid)",
        "private.record_player_opened(uuid)",
        "private.player_erasure_impact(uuid)",
        "private.request_player_erasure(uuid,text,integer,integer,boolean,boolean,boolean)",
        "private.deletion_manifest_status(uuid)",
        "private.team_deletion_statuses(uuid)",
        "private.confirm_manifest_backup_expired(uuid)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {API_ROLE}")
    for function in (
        "private.enqueue_retention_sweep(timestamptz)",
        "private.prepare_retention_sweep(uuid,text,timestamptz)",
        "private.deletion_manifest_input(uuid,text)",
        "private.fail_deletion_object(uuid,text,uuid,text)",
        "private.complete_deletion_object(uuid,text,uuid)",
        "private.deletion_auth_account(uuid,text)",
        "private.fail_deletion_auth(uuid,text)",
        "private.deletion_suppression_record(uuid,text)",
        "private.fail_deletion_suppression(uuid,text)",
        "private.expired_deletion_ledgers(uuid,text,timestamptz)",
        "private.fail_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.complete_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.finalize_deletion_manifest(uuid,text)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")
    op.execute(
        "GRANT EXECUTE ON FUNCTION"
        " private.replay_deletion_suppression(uuid,text,uuid,uuid,timestamptz,timestamptz)"
        f" TO {OPERATOR_ROLE}"
    )
    op.execute(f"GRANT USAGE ON SCHEMA app TO {OPERATOR_ROLE}")
    op.execute(
        "GRANT SELECT ON app.deletion_manifest, app.deletion_manifest_object,"
        f" app.product_event TO {OPERATOR_ROLE}"
    )

    op.execute(f"GRANT SELECT ON app.retention_policy_confirmation TO {API_ROLE}")
    op.execute(f"GRANT UPDATE (abandoned_at, rejected_at) ON app.video TO {API_ROLE}")
    for role in ("PUBLIC", "anon", "authenticated"):
        for table in TABLES:
            op.execute(f"REVOKE ALL ON TABLE app.{table} FROM {role}")

    # Fix player signing to include the same video/deadline fence as evidence reads.
    op.execute("""
        CREATE OR REPLACE FUNCTION private.player_clip_for_signing(
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
            JOIN app.observation o ON o.id = j.observation_id
            JOIN app.video v ON v.id = o.video_id
            WHERE j.id = p_judgment_id
              AND r.id = p_expected_revision_id
              AND private.is_current_publication_item_for_player(
                  i.publication_id, i.judgment_id
              )
              AND v.status = 'ready'
              AND v.derivatives_expires_at > now()
              AND c.status = 'ready'
              AND (c.delete_after IS NULL OR c.delete_after > now())
            FOR SHARE OF j
        $$
    """)
    op.execute(
        "ALTER FUNCTION private.player_clip_for_signing(uuid,uuid)"
        f" OWNER TO {MIGRATION_ROLE}"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION private.player_clip_for_signing(uuid,uuid)"
        " FROM PUBLIC, anon, authenticated"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION private.player_clip_for_signing(uuid,uuid)"
        f" TO {API_ROLE}"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION private.player_evidence(p_goal_id uuid)
        RETURNS TABLE (
            publication_id uuid, game_label text, published_at timestamptz,
            ordinal smallint, judgment_id uuid, published_revision_id uuid,
            verdict text, comment_text text, duration_ms integer,
            coach_display_name text
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT publication.id,
                   CASE WHEN game.opponent IS NULL THEN initcap(game.kind)
                        ELSE 'vs ' || game.opponent END,
                   publication.published_at, item.ordinal, judgment.id,
                   revision.id, revision.verdict, revision.comment_text,
                   clip.duration_ms, author.display_name
            FROM app.review_publication publication
            JOIN app.game game ON game.id = publication.game_id
            JOIN app.team team ON team.id = game.team_id
            JOIN app.player player ON player.id = publication.player_id
            JOIN app.review_publication_item item
              ON item.publication_id = publication.id
            JOIN app.judgment judgment ON judgment.id = item.judgment_id
            JOIN app.judgment_revision revision
              ON revision.id = item.judgment_revision_id
            JOIN app.evidence_clip clip ON clip.id = item.evidence_clip_id
            JOIN app.observation observation
              ON observation.id = judgment.observation_id
            JOIN app.video video ON video.id = observation.video_id
            JOIN app.user_account author ON author.id = revision.author_user_id
            WHERE publication.goal_id = p_goal_id
              AND private.is_current_publication_item_for_player(
                  publication.id, judgment.id
              )
              AND team.media_deletion_pending_at IS NULL
              AND player.deletion_pending_at IS NULL
              AND video.status = 'ready'
              AND video.derivatives_expires_at > now()
              AND clip.status = 'ready'
              AND (clip.delete_after IS NULL OR clip.delete_after > now())
            ORDER BY game.played_at DESC, publication.id, item.ordinal
        $$
    """)


def downgrade() -> None:
    # Rows of kinds unknown to 0012 cannot survive its narrower check. These
    # jobs only drive 0013 tables/functions, which the downgrade removes too.
    op.execute("""
        CREATE OR REPLACE FUNCTION private.is_current_publication_for_player(
            p_publication_id uuid
        ) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.review_publication publication
                WHERE publication.id = p_publication_id
                  AND publication.status = 'published'
                  AND private.is_player_self(publication.player_id)
                  AND EXISTS (
                      SELECT 1 FROM app.judgment judgment
                      WHERE judgment.current_publication_id = publication.id
                        AND judgment.publication_status = 'published'
                  )
            )
        $$
    """)
    op.execute("DROP POLICY judgment_player_select ON app.judgment")
    op.execute(f"""
        CREATE POLICY judgment_player_select ON app.judgment
            FOR SELECT TO {API_ROLE}
            USING (
                publication_status = 'published'
                AND private.is_goal_player_self(goal_id)
            )
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION private.evidence_clip_object_disposable(
            p_job_id uuid, p_worker_id text, p_storage_key text
        ) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.processing_job job
                WHERE job.id = p_job_id
                  AND job.kind = 'clip_export'
                  AND job.status = 'running'
                  AND job.locked_by = p_worker_id
            ) AND NOT EXISTS (
                SELECT 1 FROM app.evidence_clip clip
                WHERE clip.storage_key = p_storage_key
                  AND (
                      clip.status = 'ready'
                      OR EXISTS (
                          SELECT 1 FROM app.judgment judgment
                          WHERE judgment.current_clip_id = clip.id
                      )
                  )
            )
        $$
    """)
    op.execute("""
        DELETE FROM app.processing_job
        WHERE kind IN (
            'retention_sweep', 'video_retention_delete', 'player_data_delete'
        )
    """)
    op.execute(
        "DROP TRIGGER IF EXISTS processing_job_terminal_deletion_failure"
        " ON app.processing_job"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA app FROM {OPERATOR_ROLE}")
    op.execute("""
        CREATE OR REPLACE FUNCTION private.player_clip_for_signing(
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
    op.execute(
        "ALTER FUNCTION private.player_clip_for_signing(uuid,uuid)"
        f" OWNER TO {MIGRATION_ROLE}"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION private.player_clip_for_signing(uuid,uuid)"
        " FROM PUBLIC, anon, authenticated"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION private.player_clip_for_signing(uuid,uuid)"
        f" TO {API_ROLE}"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION private.player_evidence(p_goal_id uuid)
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

    op.execute(
        "DROP POLICY IF EXISTS processing_job_coach_select ON app.processing_job"
    )
    op.execute("""
        CREATE POLICY processing_job_coach_select ON app.processing_job
            FOR SELECT TO shoulder_api
            USING (
                (video_id IS NOT NULL AND private.is_video_coach(video_id))
                OR (review_publication_id IS NOT NULL
                    AND private.is_review_publication_coach(review_publication_id))
            )
    """)
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_target_required"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_kind_allowed"
    )
    op.execute("ALTER TABLE app.processing_job DROP COLUMN deletion_manifest_id")
    op.execute("ALTER TABLE app.processing_job DROP COLUMN player_id")
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_kind_allowed
            CHECK (kind IN ('transcode', 'thumbnail', 'clip_export', 'email_delivery'))
    """)
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_target_required
            CHECK (
                (kind IN ('transcode', 'thumbnail')
                 AND video_id IS NOT NULL
                 AND judgment_id IS NULL AND review_publication_id IS NULL
                 AND email_delivery_id IS NULL)
                OR
                (kind = 'clip_export'
                 AND video_id IS NULL
                 AND judgment_id IS NOT NULL AND review_publication_id IS NOT NULL
                 AND email_delivery_id IS NULL)
                OR
                (kind = 'email_delivery'
                 AND video_id IS NULL AND judgment_id IS NULL
                 AND review_publication_id IS NULL
                 AND email_delivery_id IS NOT NULL)
            )
    """)

    op.execute(
        "DROP TRIGGER IF EXISTS player_reflection_removed_product_event ON app.player_reflection"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS player_reflection_saved_product_event ON app.player_reflection"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_clip_product_event ON app.evidence_clip"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS review_publication_product_event ON app.review_publication"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS judgment_revision_product_event ON app.judgment_revision"
    )
    op.execute("DROP TRIGGER IF EXISTS observation_product_event ON app.observation")
    op.execute("DROP TRIGGER IF EXISTS team_season_cutoff_immutable ON app.team")

    functions = (
        "private.replay_deletion_suppression(uuid,text,uuid,uuid,timestamptz,timestamptz)",
        "private.confirm_manifest_backup_expired(uuid)",
        "private.finalize_deletion_manifest(uuid,text)",
        "private.delete_video_product_graph(uuid[])",
        "private.complete_deletion_object(uuid,text,uuid)",
        "private.fail_deletion_auth(uuid,text)",
        "private.deletion_auth_account(uuid,text)",
        "private.complete_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.mark_terminal_deletion_job_failure()",
        "private.fail_deletion_ledger_cleanup(uuid,text,uuid)",
        "private.expired_deletion_ledgers(uuid,text,timestamptz)",
        "private.fail_deletion_suppression(uuid,text)",
        "private.deletion_suppression_record(uuid,text)",
        "private.fail_deletion_object(uuid,text,uuid,text)",
        "private.deletion_manifest_input(uuid,text)",
        "private.deletion_manifest_status(uuid)",
        "private.team_deletion_statuses(uuid)",
        "private.request_player_erasure(uuid,text,integer,integer,boolean,boolean,boolean)",
        "private.player_erasure_impact(uuid)",
        # Remove the pre-final two-argument development signature if a local
        # database applied it before the explicit clock parameter was added.
        "private.prepare_retention_sweep(uuid,text)",
        "private.prepare_retention_sweep(uuid,text,timestamptz)",
        "private.enqueue_retention_sweep(timestamptz)",
        "private.ensure_retention_manifest(text,text,uuid,uuid,uuid,uuid,timestamptz,integer)",
        "private.enqueue_manifest_job(uuid)",
        "private.cancel_manifest_work(uuid)",
        "private.seed_deletion_manifest_objects(uuid)",
        "private.record_player_opened(uuid)",
        "private.record_review_started(uuid,uuid)",
        "private.capture_reflection_event()",
        "private.capture_clip_ready_event()",
        "private.capture_publication_event()",
        "private.capture_judgment_revision_event()",
        "private.capture_observation_event()",
        "private.insert_product_event(text,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz)",
        "private.confirm_retention_policy(uuid,smallint,boolean,boolean,boolean,boolean,boolean)",
        "private.enforce_season_cutoff()",
    )
    for function in functions:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS app.{table}")
    op.execute("ALTER TABLE app.video DROP COLUMN source_deleted_at")
    op.execute("ALTER TABLE app.video DROP COLUMN rejected_at")
    op.execute("ALTER TABLE app.video DROP COLUMN abandoned_at")
    op.execute("ALTER TABLE app.team DROP COLUMN media_deletion_pending_at")
