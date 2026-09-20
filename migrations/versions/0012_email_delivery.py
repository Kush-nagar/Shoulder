"""Content-free email delivery outbox

Revision ID: 0012_email_delivery
Revises: 0011_optional_reflections
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0012_email_delivery"
down_revision = "0011_optional_reflections"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
WORKER_ROLE = "shoulder_worker"
TABLES = ("email_delivery", "email_reflection_event")
WORKER_FUNCTIONS = (
    "private.email_delivery_input(uuid,text)",
    "private.complete_email_delivery(uuid,text,text)",
    "private.suppress_email_delivery(uuid,text)",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.email_delivery (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            recipient_user_id uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT email_delivery_kind_allowed CHECK (kind IN (
                    'evidence_ready', 'video_ready', 'video_failed',
                    'reflection_digest'
                )),
            event_key text NOT NULL UNIQUE
                CONSTRAINT email_delivery_event_key_length
                    CHECK (char_length(event_key) BETWEEN 1 AND 180),
            publication_id uuid
                REFERENCES app.review_publication (id) ON DELETE CASCADE,
            video_id uuid REFERENCES app.video (id) ON DELETE CASCADE,
            player_id uuid REFERENCES app.player (id) ON DELETE CASCADE,
            digest_on date,
            status text NOT NULL DEFAULT 'queued'
                CONSTRAINT email_delivery_status_allowed CHECK (status IN (
                    'queued', 'sent', 'suppressed', 'failed'
                )),
            provider_message_id text
                CONSTRAINT email_delivery_provider_id_length CHECK (
                    provider_message_id IS NULL
                    OR char_length(provider_message_id) BETWEEN 1 AND 100
                ),
            created_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            suppressed_at timestamptz,
            CONSTRAINT email_delivery_target_shape CHECK (
                (kind = 'evidence_ready'
                 AND publication_id IS NOT NULL
                 AND video_id IS NULL AND player_id IS NULL AND digest_on IS NULL)
                OR
                (kind IN ('video_ready', 'video_failed')
                 AND publication_id IS NULL
                 AND video_id IS NOT NULL AND player_id IS NULL AND digest_on IS NULL)
                OR
                (kind = 'reflection_digest'
                 AND publication_id IS NULL AND video_id IS NULL
                 AND player_id IS NOT NULL AND digest_on IS NOT NULL)
            ),
            CONSTRAINT email_delivery_outcome_shape CHECK (
                (status = 'queued'
                 AND provider_message_id IS NULL
                 AND sent_at IS NULL AND suppressed_at IS NULL)
                OR
                (status = 'sent'
                 AND provider_message_id IS NOT NULL
                 AND sent_at IS NOT NULL AND suppressed_at IS NULL)
                OR
                (status = 'suppressed'
                 AND provider_message_id IS NULL
                 AND sent_at IS NULL AND suppressed_at IS NOT NULL)
                OR
                (status = 'failed'
                 AND provider_message_id IS NULL
                 AND sent_at IS NULL AND suppressed_at IS NULL)
            )
        )
    """)
    op.execute(
        "CREATE INDEX email_delivery_recipient_idx"
        " ON app.email_delivery (recipient_user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX email_delivery_publication_idx"
        " ON app.email_delivery (publication_id)"
    )
    op.execute("CREATE INDEX email_delivery_video_idx ON app.email_delivery (video_id)")
    op.execute(
        "CREATE INDEX email_delivery_player_idx ON app.email_delivery (player_id)"
    )

    # One row per submitted reflection and coach digest. No reflection text,
    # text hash, verdict, note, player name, or event payload exists here.
    op.execute("""
        CREATE TABLE app.email_reflection_event (
            delivery_id uuid NOT NULL
                REFERENCES app.email_delivery (id) ON DELETE CASCADE,
            reflection_id uuid NOT NULL
                REFERENCES app.player_reflection (id) ON DELETE CASCADE,
            event_key text NOT NULL UNIQUE
                CONSTRAINT email_reflection_event_key_length
                    CHECK (char_length(event_key) BETWEEN 1 AND 180),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (delivery_id, reflection_id)
        )
    """)
    op.execute(
        "CREATE INDEX email_reflection_event_reflection_idx"
        " ON app.email_reflection_event (reflection_id)"
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    op.execute("""
        ALTER TABLE app.processing_job
            ADD COLUMN email_delivery_id uuid
                REFERENCES app.email_delivery (id) ON DELETE CASCADE
    """)
    op.execute(
        "CREATE INDEX processing_job_email_delivery_idx"
        " ON app.processing_job (email_delivery_id)"
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
                'transcode', 'thumbnail', 'clip_export', 'email_delivery'
            ))
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
                 AND video_id IS NULL
                 AND judgment_id IS NULL AND review_publication_id IS NULL
                 AND email_delivery_id IS NOT NULL)
            )
    """)

    _create_enqueue_functions()
    _create_worker_functions()
    _create_failure_trigger()

    for function in WORKER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")

    for function in (
        "private.enqueue_email_delivery_job()",
        "private.queue_publication_email()",
        "private.queue_video_email()",
        "private.queue_reflection_digest()",
        "private.mark_failed_email_delivery()",
    ):
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" shoulder_api, {WORKER_ROLE}"
        )

    for role in ("PUBLIC", "anon", "authenticated", "shoulder_api", WORKER_ROLE):
        for table in TABLES:
            op.execute(f"REVOKE ALL ON TABLE app.{table} FROM {role}")


def _create_enqueue_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.enqueue_email_delivery_job() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            INSERT INTO app.processing_job (
                email_delivery_id, kind, idempotency_key, available_at,
                payload, max_attempts
            ) VALUES (
                NEW.id, 'email_delivery', 'email:' || NEW.event_key,
                CASE WHEN NEW.kind = 'reflection_digest'
                     THEN (NEW.digest_on + 1)::timestamp AT TIME ZONE 'UTC'
                     ELSE pg_catalog.now() END,
                '{}'::jsonb, 5
            ) ON CONFLICT (idempotency_key) DO NOTHING;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER email_delivery_enqueue_job
        AFTER INSERT ON app.email_delivery
        FOR EACH ROW EXECUTE FUNCTION private.enqueue_email_delivery_job()
    """)

    op.execute("""
        CREATE FUNCTION private.queue_publication_email() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.status = 'published'
               AND OLD.status IS DISTINCT FROM 'published' THEN
                INSERT INTO app.email_delivery (
                    recipient_user_id, kind, event_key, publication_id
                )
                SELECT p.user_id, 'evidence_ready',
                       'evidence-ready:' || NEW.id::text, NEW.id
                FROM app.player p
                WHERE p.id = NEW.player_id
                  AND p.user_id IS NOT NULL
                  AND p.active AND p.deleted_at IS NULL
                  AND p.deletion_pending_at IS NULL
                ON CONFLICT (event_key) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER review_publication_email_ready
        AFTER UPDATE OF status ON app.review_publication
        FOR EACH ROW EXECUTE FUNCTION private.queue_publication_email()
    """)

    op.execute("""
        CREATE FUNCTION private.queue_video_email() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE v_kind text;
        BEGIN
            IF NEW.status NOT IN ('ready', 'failed')
               OR OLD.status IS NOT DISTINCT FROM NEW.status THEN
                RETURN NEW;
            END IF;
            v_kind := CASE NEW.status
                WHEN 'ready' THEN 'video_ready' ELSE 'video_failed' END;
            INSERT INTO app.email_delivery (
                recipient_user_id, kind, event_key, video_id
            ) VALUES (
                NEW.uploaded_by, v_kind,
                replace(v_kind, '_', '-') || ':' || NEW.id::text, NEW.id
            ) ON CONFLICT (event_key) DO NOTHING;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER video_email_outcome
        AFTER UPDATE OF status ON app.video
        FOR EACH ROW EXECUTE FUNCTION private.queue_video_email()
    """)

    op.execute("""
        CREATE FUNCTION private.queue_reflection_digest() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_team_id uuid;
            v_coach_id uuid;
            v_delivery_id uuid;
            v_digest_on date := (pg_catalog.now() AT TIME ZONE 'UTC')::date;
            v_delivery_key text;
        BEGIN
            SELECT p.team_id INTO v_team_id
            FROM app.player p WHERE p.id = NEW.player_id;
            FOR v_coach_id IN
                SELECT m.user_id FROM app.team_membership m
                WHERE m.team_id = v_team_id AND m.role = 'coach'
                ORDER BY m.user_id
            LOOP
                v_delivery_key := 'reflection-digest:' || v_coach_id::text || ':'
                    || NEW.player_id::text || ':' || v_digest_on::text;
                INSERT INTO app.email_delivery (
                    recipient_user_id, kind, event_key, player_id, digest_on
                ) VALUES (
                    v_coach_id, 'reflection_digest', v_delivery_key,
                    NEW.player_id, v_digest_on
                )
                ON CONFLICT (event_key) DO UPDATE
                    SET event_key = EXCLUDED.event_key
                RETURNING id INTO v_delivery_id;

                INSERT INTO app.email_reflection_event (
                    delivery_id, reflection_id, event_key
                ) VALUES (
                    v_delivery_id, NEW.id,
                    'reflection-submitted:' || NEW.id::text || ':'
                        || v_coach_id::text
                ) ON CONFLICT (event_key) DO NOTHING;
            END LOOP;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER player_reflection_email_digest
        AFTER INSERT ON app.player_reflection
        FOR EACH ROW EXECUTE FUNCTION private.queue_reflection_digest()
    """)


def _create_worker_functions() -> None:
    op.execute("""
        CREATE FUNCTION private.email_delivery_input(
            p_job_id uuid, p_worker_id text
        ) RETURNS TABLE (
            delivery_id uuid, kind text, recipient_email text, event_key text,
            publication_id uuid, goal_id uuid, game_id uuid, player_id uuid,
            sendable boolean
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT d.id, d.kind, account.email, d.event_key,
                   d.publication_id, publication.goal_id, video.game_id,
                   d.player_id,
                   CASE WHEN d.kind = 'reflection_digest' THEN EXISTS (
                       SELECT 1 FROM app.email_reflection_event event
                       WHERE event.delivery_id = d.id
                   ) ELSE true END
            FROM app.processing_job job
            JOIN app.email_delivery d ON d.id = job.email_delivery_id
            JOIN app.user_account account ON account.id = d.recipient_user_id
            LEFT JOIN app.review_publication publication
              ON publication.id = d.publication_id
            LEFT JOIN app.video video ON video.id = d.video_id
            WHERE job.id = p_job_id
              AND job.kind = 'email_delivery'
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND d.status = 'queued'
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.complete_email_delivery(
            p_job_id uuid, p_worker_id text, p_provider_message_id text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF p_provider_message_id IS NULL
               OR pg_catalog.char_length(p_provider_message_id) NOT BETWEEN 1 AND 100
               OR p_provider_message_id ~ '[\r\n]' THEN
                RETURN false;
            END IF;
            UPDATE app.email_delivery delivery SET
                status = 'sent', provider_message_id = p_provider_message_id,
                sent_at = pg_catalog.now()
            FROM app.processing_job job
            WHERE job.id = p_job_id
              AND job.kind = 'email_delivery'
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND delivery.id = job.email_delivery_id
              AND delivery.status = 'queued';
            RETURN FOUND;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.suppress_email_delivery(
            p_job_id uuid, p_worker_id text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            UPDATE app.email_delivery delivery SET
                status = 'suppressed', suppressed_at = pg_catalog.now()
            FROM app.processing_job job
            WHERE job.id = p_job_id
              AND job.kind = 'email_delivery'
              AND job.status = 'running' AND job.locked_by = p_worker_id
              AND delivery.id = job.email_delivery_id
              AND delivery.kind = 'reflection_digest'
              AND delivery.status = 'queued'
              AND NOT EXISTS (
                  SELECT 1 FROM app.email_reflection_event event
                  WHERE event.delivery_id = delivery.id
              );
            RETURN FOUND;
        END;
        $$
    """)


def _create_failure_trigger() -> None:
    op.execute("""
        CREATE FUNCTION private.mark_failed_email_delivery() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.kind = 'email_delivery' AND NEW.status = 'failed'
               AND OLD.status IS DISTINCT FROM 'failed' THEN
                UPDATE app.email_delivery SET status = 'failed'
                WHERE id = NEW.email_delivery_id AND status = 'queued';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER processing_job_email_failure
        AFTER UPDATE OF status ON app.processing_job
        FOR EACH ROW EXECUTE FUNCTION private.mark_failed_email_delivery()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS processing_job_email_failure ON app.processing_job"
    )
    op.execute("DROP FUNCTION IF EXISTS private.mark_failed_email_delivery()")
    op.execute(
        "DROP TRIGGER IF EXISTS player_reflection_email_digest ON app.player_reflection"
    )
    op.execute("DROP FUNCTION IF EXISTS private.queue_reflection_digest()")
    op.execute("DROP TRIGGER IF EXISTS video_email_outcome ON app.video")
    op.execute("DROP FUNCTION IF EXISTS private.queue_video_email()")
    op.execute(
        "DROP TRIGGER IF EXISTS review_publication_email_ready"
        " ON app.review_publication"
    )
    op.execute("DROP FUNCTION IF EXISTS private.queue_publication_email()")
    op.execute(
        "DROP TRIGGER IF EXISTS email_delivery_enqueue_job ON app.email_delivery"
    )
    op.execute("DROP FUNCTION IF EXISTS private.enqueue_email_delivery_job()")
    for function in reversed(WORKER_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")

    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_target_required"
    )
    op.execute(
        "ALTER TABLE app.processing_job DROP CONSTRAINT processing_job_kind_allowed"
    )
    op.execute("ALTER TABLE app.processing_job DROP COLUMN email_delivery_id")
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_kind_allowed
            CHECK (kind IN ('transcode', 'thumbnail', 'clip_export'))
    """)
    op.execute("""
        ALTER TABLE app.processing_job ADD CONSTRAINT processing_job_target_required
            CHECK (
                (kind IN ('transcode', 'thumbnail')
                 AND video_id IS NOT NULL
                 AND judgment_id IS NULL AND review_publication_id IS NULL)
                OR
                (kind = 'clip_export'
                 AND video_id IS NULL
                 AND judgment_id IS NOT NULL AND review_publication_id IS NOT NULL)
            )
    """)
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS app.{table}")
