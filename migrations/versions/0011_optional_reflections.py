"""Author-controlled optional player reflections

Revision ID: 0011_optional_reflections
Revises: 0010_player_publications
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0011_optional_reflections"
down_revision = "0010_player_publications"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"

RUNTIME_FUNCTIONS = (
    "private.is_player_reflection_author(uuid,uuid)",
    "private.save_player_reflection(uuid,text,text,uuid,uuid,timestamptz,text)",
    "private.delete_player_reflection(uuid,uuid,uuid,timestamptz,text)",
)
INTERNAL_FUNCTIONS = (
    "private.purge_expired_player_reflection_requests()",
    "private.keep_player_reflection_identity()",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.player_reflection (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            judgment_id uuid NOT NULL UNIQUE
                REFERENCES app.judgment (id) ON DELETE CASCADE,
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            text text NOT NULL
                CONSTRAINT player_reflection_text_length
                    CHECK (
                        char_length(text) BETWEEN 1 AND 1000
                        AND char_length(btrim(text)) >= 1
                    ),
            judgment_version_at_save bigint NOT NULL
                CONSTRAINT player_reflection_version_positive
                    CHECK (judgment_version_at_save > 0),
            etag uuid NOT NULL DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX player_reflection_judgment_idx"
        " ON app.player_reflection (judgment_id)"
    )
    op.execute(
        "CREATE INDEX player_reflection_player_idx ON app.player_reflection (player_id)"
    )

    # Content-free replay and deletion tombstones. There is deliberately no
    # payload, reflection text, text hash, JSON, or prior-value column here.
    op.execute("""
        CREATE TABLE app.player_reflection_request (
            player_id uuid NOT NULL REFERENCES app.player (id) ON DELETE CASCADE,
            idempotency_key text NOT NULL
                CONSTRAINT player_reflection_request_key_length
                    CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
            judgment_id uuid NOT NULL
                REFERENCES app.judgment (id) ON DELETE CASCADE,
            action text NOT NULL
                CONSTRAINT player_reflection_request_action
                    CHECK (action IN ('create', 'edit', 'delete')),
            expected_reflection_id uuid,
            expected_etag uuid,
            result_reflection_id uuid NOT NULL,
            result_etag uuid NOT NULL,
            request_created_at timestamptz NOT NULL,
            processed_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            PRIMARY KEY (player_id, idempotency_key),
            CONSTRAINT player_reflection_request_bounded
                CHECK (expires_at <= processed_at + interval '7 days'),
            CONSTRAINT player_reflection_request_intent_shape CHECK (
                (action = 'create'
                 AND expected_reflection_id IS NULL AND expected_etag IS NULL)
                OR
                (action IN ('edit', 'delete')
                 AND expected_reflection_id IS NOT NULL
                 AND expected_etag IS NOT NULL)
            )
        )
    """)
    op.execute(
        "CREATE INDEX player_reflection_request_judgment_idx"
        " ON app.player_reflection_request (judgment_id)"
    )
    op.execute(
        "CREATE INDEX player_reflection_request_expires_idx"
        " ON app.player_reflection_request (expires_at)"
    )

    for table in ("player_reflection", "player_reflection_request"):
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)

    op.execute("""
        CREATE FUNCTION private.is_player_reflection_author(
            p_player_id uuid, p_judgment_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.player p
                JOIN app.development_goal g ON g.player_id = p.id
                JOIN app.judgment j ON j.goal_id = g.id
                WHERE p.id = p_player_id
                  AND j.id = p_judgment_id
                  AND private.is_player_self(p.id)
            )
        $$
    """)

    op.execute(f"""
        CREATE POLICY player_reflection_player_select ON app.player_reflection
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_reflection_author(player_id, judgment_id))
    """)
    op.execute(f"""
        CREATE POLICY player_reflection_coach_select ON app.player_reflection
            FOR SELECT TO {API_ROLE}
            USING (private.is_player_coach(player_id))
    """)
    # The API writes through the serialized functions below. These policies
    # still define the row boundary if table mutation is ever granted; no
    # ordinary runtime role receives that grant in this migration.
    op.execute(f"""
        CREATE POLICY player_reflection_player_insert ON app.player_reflection
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_player_reflection_author(player_id, judgment_id)
                AND private.is_published_revision_for_player(
                    judgment_id,
                    (SELECT j.current_revision_id FROM app.judgment j
                     WHERE j.id = judgment_id)
                )
            )
    """)
    op.execute(f"""
        CREATE POLICY player_reflection_player_update ON app.player_reflection
            FOR UPDATE TO {API_ROLE}
            USING (private.is_player_reflection_author(player_id, judgment_id))
            WITH CHECK (private.is_player_reflection_author(player_id, judgment_id))
    """)
    op.execute(f"""
        CREATE POLICY player_reflection_player_delete ON app.player_reflection
            FOR DELETE TO {API_ROLE}
            USING (private.is_player_reflection_author(player_id, judgment_id))
    """)

    op.execute("""
        CREATE FUNCTION private.keep_player_reflection_identity() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.judgment_id IS DISTINCT FROM OLD.judgment_id
               OR NEW.player_id IS DISTINCT FROM OLD.player_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'reflection identity is immutable'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER player_reflection_identity_immutable
        BEFORE UPDATE ON app.player_reflection
        FOR EACH ROW EXECUTE FUNCTION private.keep_player_reflection_identity()
    """)

    op.execute("""
        CREATE FUNCTION private.purge_expired_player_reflection_requests()
        RETURNS void
        LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
            DELETE FROM app.player_reflection_request
            WHERE expires_at <= pg_catalog.now()
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.save_player_reflection(
            p_judgment_id uuid,
            p_intent text,
            p_text text,
            p_expected_reflection_id uuid,
            p_expected_etag uuid,
            p_request_created_at timestamptz,
            p_idempotency_key text
        ) RETURNS app.player_reflection
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_player_id uuid;
            v_current_version bigint;
            v_reflection app.player_reflection%ROWTYPE;
            v_request app.player_reflection_request%ROWTYPE;
        BEGIN
            IF p_request_created_at IS NULL
               OR p_request_created_at < pg_catalog.now() - interval '7 days'
               OR p_request_created_at > pg_catalog.now() + interval '5 minutes'
               OR pg_catalog.char_length(p_idempotency_key) NOT BETWEEN 1 AND 200
               OR pg_catalog.char_length(p_text) NOT BETWEEN 1 AND 1000
               OR pg_catalog.char_length(pg_catalog.btrim(p_text)) < 1
               OR p_intent NOT IN ('create', 'edit')
               OR (p_intent = 'create' AND (
                    p_expected_reflection_id IS NOT NULL OR p_expected_etag IS NOT NULL
               ))
               OR (p_intent = 'edit' AND (
                    p_expected_reflection_id IS NULL OR p_expected_etag IS NULL
               )) THEN
                RAISE EXCEPTION 'invalid reflection request'
                    USING ERRCODE = 'P1902';
            END IF;

            SELECT p.id INTO v_player_id
            FROM app.player p
            JOIN app.development_goal g ON g.player_id = p.id
            JOIN app.judgment j ON j.goal_id = g.id
            WHERE j.id = p_judgment_id
              AND private.is_player_self(p.id);
            IF v_player_id IS NULL THEN
                RAISE EXCEPTION 'reflection not available'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(p_judgment_id::text, 1901)
            );
            PERFORM private.purge_expired_player_reflection_requests();

            SELECT * INTO v_request
            FROM app.player_reflection_request
            WHERE player_id = v_player_id
              AND idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_request.judgment_id IS DISTINCT FROM p_judgment_id
                   OR v_request.action IS DISTINCT FROM p_intent
                   OR v_request.expected_reflection_id
                        IS DISTINCT FROM p_expected_reflection_id
                   OR v_request.expected_etag IS DISTINCT FROM p_expected_etag THEN
                    RAISE EXCEPTION 'idempotency key payload mismatch'
                        USING ERRCODE = 'P1901';
                END IF;
                SELECT * INTO v_reflection
                FROM app.player_reflection
                WHERE id = v_request.result_reflection_id
                  AND etag = v_request.result_etag;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'reflection request is stale'
                        USING ERRCODE = 'P1901';
                END IF;
                RETURN v_reflection;
            END IF;

            SELECT * INTO v_reflection
            FROM app.player_reflection
            WHERE judgment_id = p_judgment_id
            FOR UPDATE;

            IF p_intent = 'create' THEN
                IF FOUND THEN
                    RAISE EXCEPTION 'reflection already exists'
                        USING ERRCODE = 'P1901';
                END IF;
                SELECT r.version INTO v_current_version
                FROM app.judgment j
                JOIN app.judgment_revision r ON r.id = j.current_revision_id
                WHERE j.id = p_judgment_id
                  AND j.publication_status = 'published'
                  AND private.is_published_revision_for_player(j.id, r.id)
                FOR SHARE OF j;
                IF v_current_version IS NULL THEN
                    RAISE EXCEPTION 'published evidence is required'
                        USING ERRCODE = 'P1901';
                END IF;
                INSERT INTO app.player_reflection (
                    judgment_id, player_id, text, judgment_version_at_save
                ) VALUES (
                    p_judgment_id, v_player_id, p_text, v_current_version
                ) RETURNING * INTO v_reflection;
            ELSE
                IF NOT FOUND
                   OR v_reflection.id IS DISTINCT FROM p_expected_reflection_id
                   OR v_reflection.etag IS DISTINCT FROM p_expected_etag THEN
                    RAISE EXCEPTION 'reflection edit is stale'
                        USING ERRCODE = 'P1901';
                END IF;
                SELECT r.version INTO v_current_version
                FROM app.judgment j
                JOIN app.judgment_revision r ON r.id = j.current_revision_id
                WHERE j.id = p_judgment_id
                  AND j.publication_status = 'published'
                  AND private.is_published_revision_for_player(j.id, r.id)
                FOR SHARE OF j;
                UPDATE app.player_reflection SET
                    text = p_text,
                    judgment_version_at_save = coalesce(
                        v_current_version, judgment_version_at_save
                    ),
                    etag = gen_random_uuid(),
                    updated_at = pg_catalog.now()
                WHERE id = v_reflection.id
                RETURNING * INTO v_reflection;
            END IF;

            INSERT INTO app.player_reflection_request (
                player_id, idempotency_key, judgment_id, action,
                expected_reflection_id, expected_etag,
                result_reflection_id, result_etag, request_created_at,
                expires_at
            ) VALUES (
                v_player_id, p_idempotency_key, p_judgment_id, p_intent,
                p_expected_reflection_id, p_expected_etag,
                v_reflection.id, v_reflection.etag, p_request_created_at,
                pg_catalog.now() + interval '7 days'
            );
            RETURN v_reflection;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION private.delete_player_reflection(
            p_judgment_id uuid,
            p_expected_reflection_id uuid,
            p_expected_etag uuid,
            p_request_created_at timestamptz,
            p_idempotency_key text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_player_id uuid;
            v_reflection app.player_reflection%ROWTYPE;
            v_request app.player_reflection_request%ROWTYPE;
        BEGIN
            IF p_expected_reflection_id IS NULL OR p_expected_etag IS NULL
               OR p_request_created_at IS NULL
               OR p_request_created_at < pg_catalog.now() - interval '7 days'
               OR p_request_created_at > pg_catalog.now() + interval '5 minutes'
               OR pg_catalog.char_length(p_idempotency_key) NOT BETWEEN 1 AND 200 THEN
                RAISE EXCEPTION 'invalid reflection delete request'
                    USING ERRCODE = 'P1902';
            END IF;

            SELECT p.id INTO v_player_id
            FROM app.player p
            JOIN app.development_goal g ON g.player_id = p.id
            JOIN app.judgment j ON j.goal_id = g.id
            WHERE j.id = p_judgment_id
              AND private.is_player_self(p.id);
            IF v_player_id IS NULL THEN
                RAISE EXCEPTION 'reflection not available'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(p_judgment_id::text, 1901)
            );
            PERFORM private.purge_expired_player_reflection_requests();

            SELECT * INTO v_request
            FROM app.player_reflection_request
            WHERE player_id = v_player_id
              AND idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_request.judgment_id IS DISTINCT FROM p_judgment_id
                   OR v_request.action <> 'delete'
                   OR v_request.expected_reflection_id
                        IS DISTINCT FROM p_expected_reflection_id
                   OR v_request.expected_etag IS DISTINCT FROM p_expected_etag THEN
                    RAISE EXCEPTION 'idempotency key payload mismatch'
                        USING ERRCODE = 'P1901';
                END IF;
                RETURN true;
            END IF;

            SELECT * INTO v_reflection
            FROM app.player_reflection
            WHERE judgment_id = p_judgment_id
            FOR UPDATE;
            IF FOUND AND (
                v_reflection.id IS DISTINCT FROM p_expected_reflection_id
                OR v_reflection.etag IS DISTINCT FROM p_expected_etag
            ) THEN
                RAISE EXCEPTION 'reflection delete is stale'
                    USING ERRCODE = 'P1901';
            END IF;

            IF FOUND THEN
                DELETE FROM app.player_reflection WHERE id = v_reflection.id;
            END IF;
            INSERT INTO app.player_reflection_request (
                player_id, idempotency_key, judgment_id, action,
                expected_reflection_id, expected_etag,
                result_reflection_id, result_etag, request_created_at,
                expires_at
            ) VALUES (
                v_player_id, p_idempotency_key, p_judgment_id, 'delete',
                p_expected_reflection_id, p_expected_etag,
                p_expected_reflection_id, p_expected_etag,
                p_request_created_at, pg_catalog.now() + interval '7 days'
            );
            IF EXISTS (
                SELECT 1 FROM app.player_reflection
                WHERE id = p_expected_reflection_id
            ) THEN
                RAISE EXCEPTION 'active reflection deletion failed';
            END IF;
            RETURN true;
        END;
        $$
    """)

    op.execute(f"GRANT SELECT ON app.player_reflection TO {API_ROLE}")
    for function in RUNTIME_FUNCTIONS + INTERNAL_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}"
        )
    for function in RUNTIME_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {API_ROLE}")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS player_reflection_identity_immutable"
        " ON app.player_reflection"
    )
    # Drop composite-returning and trigger functions before their tables. The
    # author helper stays until the table drop removes policies that depend on
    # it.
    for function in (
        "private.keep_player_reflection_identity()",
        "private.purge_expired_player_reflection_requests()",
        "private.delete_player_reflection(uuid,uuid,uuid,timestamptz,text)",
        "private.save_player_reflection(uuid,text,text,uuid,uuid,timestamptz,text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS app.player_reflection_request")
    op.execute("DROP TABLE IF EXISTS app.player_reflection")
    op.execute("DROP FUNCTION IF EXISTS private.is_player_reflection_author(uuid,uuid)")
