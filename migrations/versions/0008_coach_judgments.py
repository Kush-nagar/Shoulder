"""Coach judgments and their immutable revision history

Revision ID: 0008_coach_judgments
Revises: 0007_manual_observations

Task 15 adds `app.judgment` and `app.judgment_revision` only. Publication and
clip pointers (`current_publication_id`, `current_clip_id`) are introduced in
Task 17, when `review_publication` and `evidence_clip` exist; no published
state is reachable from this migration. `current_revision_id` exists now
because `judgment_revision` exists now, but nothing in this task's grants lets
the runtime role set it, so it stays null until Task 17's publish path writes
it through its own definer function.

Every content write goes through `private.write_judgment_revision`, a single
SECURITY DEFINER function that creates revision 1 or appends an edit in one
transaction. The runtime role has no direct INSERT/UPDATE/DELETE grant on
either table: that is the "narrow transactional write path" `docs/03-schema.md`
requires instead of an ordinary RLS WITH CHECK, because the invariants here
(exactly-one-more version, original-author-only, no-op detection, a full
snapshot on every accepted edit) cross rows in a way a row-level policy cannot
express by itself.
"""

from alembic import op

revision = "0008_coach_judgments"
down_revision = "0007_manual_observations"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"

HELPER_FUNCTIONS = (
    "private.is_goal_coach(uuid)",
    "private.is_goal_player_self(uuid)",
    "private.is_judgment_coach(uuid)",
    "private.is_published_revision_for_player(uuid,uuid)",
)
WRITE_FUNCTION = (
    "private.write_judgment_revision"
    "(uuid,uuid,uuid,bigint,text,text,integer,integer)"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.judgment (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            observation_id uuid NOT NULL
                REFERENCES app.observation (id) ON DELETE RESTRICT,
            goal_id uuid NOT NULL
                REFERENCES app.development_goal (id),
            author_user_id uuid NOT NULL REFERENCES app.user_account (id),
            version bigint NOT NULL DEFAULT 1
                CONSTRAINT judgment_version_positive CHECK (version > 0),
            publication_status text NOT NULL DEFAULT 'draft'
                CONSTRAINT judgment_publication_status_allowed
                    CHECK (publication_status IN ('draft', 'published', 'withdrawn')),
            published_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judgment_observation_goal_unique
                UNIQUE (observation_id, goal_id)
        )
    """)
    op.execute(
        "CREATE INDEX judgment_goal_published_idx"
        " ON app.judgment (goal_id, published_at DESC)"
    )
    op.execute("CREATE INDEX judgment_author_idx ON app.judgment (author_user_id)")

    op.execute("""
        CREATE TABLE app.judgment_revision (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            judgment_id uuid NOT NULL
                REFERENCES app.judgment (id) ON DELETE CASCADE,
            version bigint NOT NULL
                CONSTRAINT judgment_revision_version_positive CHECK (version > 0),
            author_user_id uuid NOT NULL REFERENCES app.user_account (id),
            verdict text NOT NULL
                CONSTRAINT judgment_revision_verdict_allowed
                    CHECK (verdict IN ('applied', 'opportunity', 'not_relevant')),
            comment_text text
                CONSTRAINT judgment_revision_comment_length
                    CHECK (
                        comment_text IS NULL
                        OR char_length(comment_text) BETWEEN 1 AND 400
                    ),
            clip_start_ms integer NOT NULL
                CONSTRAINT judgment_revision_clip_start_non_negative
                    CHECK (clip_start_ms >= 0),
            clip_end_ms integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judgment_revision_clip_order CHECK (clip_end_ms > clip_start_ms),
            CONSTRAINT judgment_revision_unique_version UNIQUE (judgment_id, version)
        )
    """)
    op.execute(
        "CREATE INDEX judgment_revision_judgment_idx"
        " ON app.judgment_revision (judgment_id)"
    )
    op.execute(
        "CREATE INDEX judgment_revision_author_idx"
        " ON app.judgment_revision (author_user_id)"
    )

    # Added after `judgment_revision` exists, to break the circular reference.
    # Nothing in this task's grants lets the runtime role write it.
    op.execute("""
        ALTER TABLE app.judgment ADD COLUMN current_revision_id uuid
            REFERENCES app.judgment_revision (id)
    """)
    op.execute(
        "CREATE INDEX judgment_current_revision_idx"
        " ON app.judgment (current_revision_id)"
    )

    # --- Coach/player visibility helpers, SECURITY DEFINER so a judgment or
    # revision policy does not need to read development_goal/player through the
    # caller's own policies. Mirror `private.is_player_coach` / `is_player_self`.
    op.execute("""
        CREATE FUNCTION private.is_goal_coach(p_goal_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.development_goal g
                WHERE g.id = p_goal_id AND private.is_player_coach(g.player_id)
            )
        $$;
    """)
    op.execute("""
        CREATE FUNCTION private.is_goal_player_self(p_goal_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.development_goal g
                WHERE g.id = p_goal_id AND private.is_player_self(g.player_id)
            )
        $$;
    """)
    op.execute("""
        CREATE FUNCTION private.is_judgment_coach(p_judgment_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.judgment j
                WHERE j.id = p_judgment_id AND private.is_goal_coach(j.goal_id)
            )
        $$;
    """)
    # No published judgment can exist before Task 17 writes `current_revision_id`
    # and flips `publication_status`, so this policy predicate cannot yet match
    # any row; it is defined now so Task 17 adds no new judgment_revision policy.
    op.execute("""
        CREATE FUNCTION private.is_published_revision_for_player(
            p_judgment_id uuid,
            p_revision_id uuid
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.judgment j
                WHERE j.id = p_judgment_id
                  AND j.current_revision_id = p_revision_id
                  AND j.publication_status = 'published'
                  AND private.is_goal_player_self(j.goal_id)
            )
        $$;
    """)

    # --- The one write path. Everything content-changing goes through here:
    # NULL judgment id creates judgment + revision 1 atomically; a real id edits
    # under `If-Match`-style optimistic concurrency. A no-op/replayed save
    # returns the unchanged row without touching `version` or inserting a row.
    # All validation happens before the version increment and revision insert,
    # so a later failure aborts the whole transaction rather than leaving a
    # judgment on a version with no matching revision row.
    op.execute("""
        CREATE FUNCTION private.write_judgment_revision(
            p_judgment_id uuid,
            p_observation_id uuid,
            p_goal_id uuid,
            p_expected_version bigint,
            p_verdict text,
            p_comment_text text,
            p_clip_start_ms integer,
            p_clip_end_ms integer
        ) RETURNS app.judgment
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            v_judgment app.judgment%ROWTYPE;
            v_latest app.judgment_revision%ROWTYPE;
            v_goal_player uuid;
            v_observation_player uuid;
            v_duration_ms integer;
        BEGIN
            IF p_verdict NOT IN ('applied', 'opportunity', 'not_relevant') THEN
                RAISE EXCEPTION 'invalid verdict'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_clip_start_ms IS NULL OR p_clip_end_ms IS NULL
               OR p_clip_start_ms < 0 OR p_clip_end_ms <= p_clip_start_ms THEN
                RAISE EXCEPTION 'invalid clip bounds'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_comment_text IS NOT NULL
               AND char_length(p_comment_text) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'invalid comment length'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            IF p_judgment_id IS NULL THEN
                -- Create path: judgment + revision 1.
                IF p_observation_id IS NULL OR p_goal_id IS NULL THEN
                    RAISE EXCEPTION 'observation and goal are required'
                        USING ERRCODE = 'invalid_parameter_value';
                END IF;
                IF NOT private.is_goal_coach(p_goal_id) THEN
                    RAISE EXCEPTION 'goal not visible to caller'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;

                SELECT g.player_id INTO v_goal_player
                FROM app.development_goal g WHERE g.id = p_goal_id;
                SELECT o.player_id, v.duration_ms
                    INTO v_observation_player, v_duration_ms
                FROM app.observation o
                JOIN app.video v ON v.id = o.video_id
                WHERE o.id = p_observation_id;
                IF v_observation_player IS NULL
                   OR v_observation_player IS DISTINCT FROM v_goal_player THEN
                    RAISE EXCEPTION 'observation does not match this goal'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF v_duration_ms IS NULL OR p_clip_end_ms > v_duration_ms THEN
                    RAISE EXCEPTION 'clip bounds exceed the source video'
                        USING ERRCODE = 'invalid_parameter_value';
                END IF;

                INSERT INTO app.judgment (
                    observation_id, goal_id, author_user_id, version,
                    publication_status
                ) VALUES (
                    p_observation_id, p_goal_id, private.current_user_id(), 1,
                    'draft'
                ) RETURNING * INTO v_judgment;

                INSERT INTO app.judgment_revision (
                    judgment_id, version, author_user_id, verdict, comment_text,
                    clip_start_ms, clip_end_ms
                ) VALUES (
                    v_judgment.id, 1, v_judgment.author_user_id, p_verdict,
                    p_comment_text, p_clip_start_ms, p_clip_end_ms
                );
                RETURN v_judgment;
            END IF;

            -- Edit path: optimistic concurrency plus original-author-only.
            IF p_expected_version IS NULL THEN
                RAISE EXCEPTION 'expected version is required'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            SELECT * INTO v_judgment
            FROM app.judgment WHERE id = p_judgment_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'judgment not found'
                    USING ERRCODE = 'no_data_found';
            END IF;
            IF NOT private.is_goal_coach(v_judgment.goal_id) THEN
                RAISE EXCEPTION 'goal not visible to caller'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF v_judgment.author_user_id IS DISTINCT FROM private.current_user_id()
            THEN
                RAISE EXCEPTION 'only the original author may edit'
                    USING ERRCODE = 'PJ001';
            END IF;

            SELECT v.duration_ms INTO v_duration_ms
            FROM app.observation o
            JOIN app.video v ON v.id = o.video_id
            WHERE o.id = v_judgment.observation_id;
            IF v_duration_ms IS NULL OR p_clip_end_ms > v_duration_ms THEN
                RAISE EXCEPTION 'clip bounds exceed the source video'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            -- Content first, version second. `docs/04-api.md` requires that
            -- "no-op or idempotent replay does not increment", and those are
            -- two different requests: a save of unchanged content against the
            -- current version, and a retry of an edit that already succeeded
            -- whose response the client never received. The second arrives
            -- with the version it was written against, which is now one
            -- behind, and comparing versions first answered it with a
            -- conflict -- so an at-least-once client could never make that
            -- write idempotent.
            --
            -- Checking version first is also unnecessary here. Optimistic
            -- concurrency exists to stop a lost update, and if the submitted
            -- content is already exactly the current revision there is no
            -- update to lose: the state the caller asked for is the state
            -- that exists. A stale write whose content *differs* still
            -- conflicts, which is the case the precondition is for.
            SELECT * INTO v_latest
            FROM app.judgment_revision
            WHERE judgment_id = v_judgment.id AND version = v_judgment.version;

            IF v_latest.verdict = p_verdict
               AND v_latest.comment_text IS NOT DISTINCT FROM p_comment_text
               AND v_latest.clip_start_ms = p_clip_start_ms
               AND v_latest.clip_end_ms = p_clip_end_ms THEN
                -- No new revision and no version change, whether this is a
                -- no-op against the current version or a replay of the edit
                -- that produced it.
                RETURN v_judgment;
            END IF;

            IF v_judgment.version IS DISTINCT FROM p_expected_version THEN
                RAISE EXCEPTION 'stale version' USING ERRCODE = '40001';
            END IF;

            UPDATE app.judgment
            SET version = version + 1, updated_at = now()
            WHERE id = v_judgment.id
            RETURNING * INTO v_judgment;

            INSERT INTO app.judgment_revision (
                judgment_id, version, author_user_id, verdict, comment_text,
                clip_start_ms, clip_end_ms
            ) VALUES (
                v_judgment.id, v_judgment.version, v_judgment.author_user_id,
                p_verdict, p_comment_text, p_clip_start_ms, p_clip_end_ms
            );

            RETURN v_judgment;
        END;
        $$;
    """)

    op.execute(f"ALTER TABLE app.judgment OWNER TO {MIGRATION_ROLE}")
    op.execute(f"ALTER TABLE app.judgment_revision OWNER TO {MIGRATION_ROLE}")
    for function in (*HELPER_FUNCTIONS, WRITE_FUNCTION):
        op.execute(f"ALTER FUNCTION {function} OWNER TO {MIGRATION_ROLE}")

    op.execute("ALTER TABLE app.judgment ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.judgment FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.judgment_revision ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.judgment_revision FORCE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE POLICY judgment_owner_maintenance ON app.judgment
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)
    op.execute(f"""
        CREATE POLICY judgment_revision_owner_maintenance ON app.judgment_revision
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)

    op.execute(f"""
        CREATE POLICY judgment_coach_select ON app.judgment
            FOR SELECT TO {API_ROLE}
            USING (private.is_goal_coach(goal_id))
    """)
    op.execute(f"""
        CREATE POLICY judgment_player_select ON app.judgment
            FOR SELECT TO {API_ROLE}
            USING (
                publication_status = 'published'
                AND private.is_goal_player_self(goal_id)
            )
    """)
    op.execute(f"""
        CREATE POLICY judgment_revision_coach_select ON app.judgment_revision
            FOR SELECT TO {API_ROLE}
            USING (private.is_judgment_coach(judgment_id))
    """)
    op.execute(f"""
        CREATE POLICY judgment_revision_player_select ON app.judgment_revision
            FOR SELECT TO {API_ROLE}
            USING (private.is_published_revision_for_player(judgment_id, id))
    """)

    # SELECT only. INSERT/UPDATE/DELETE are reachable exclusively through
    # `private.write_judgment_revision`; no grant exists for the raw verbs.
    op.execute(f"GRANT SELECT ON app.judgment TO {API_ROLE}")
    op.execute(f"GRANT SELECT ON app.judgment_revision TO {API_ROLE}")
    op.execute(f"""
        GRANT EXECUTE ON FUNCTION {WRITE_FUNCTION} TO {API_ROLE}
    """)
    for function in HELPER_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {API_ROLE}")

    for role in ("PUBLIC", "anon", "authenticated"):
        for table in ("app.judgment", "app.judgment_revision"):
            op.execute(f"REVOKE ALL ON TABLE {table} FROM {role}")
        for function in (*HELPER_FUNCTIONS, WRITE_FUNCTION):
            op.execute(f"REVOKE ALL ON FUNCTION {function} FROM {role}")


def downgrade() -> None:
    # The order is forced from both ends, and neither end is obvious.
    #
    # `write_judgment_revision` is declared `RETURNS app.judgment`, so it
    # depends on that table's row type and the table cannot be dropped while
    # it exists. The four helpers are the other way round: the row-level
    # security policies are defined in terms of them, so they cannot be
    # dropped until the tables -- and with them their policies -- are gone.
    #
    # Write function, then tables, then helpers. Anything else fails with
    # DependentObjectsStillExist part-way through, which is a downgrade that
    # stops in the middle. Neither DROP ... CASCADE is used: cascading here
    # would drop whatever else came to depend on these, unseen.
    op.execute(f"DROP FUNCTION IF EXISTS {WRITE_FUNCTION}")
    # `judgment.current_revision_id` and `judgment_revision.judgment_id` form a
    # circular FK; drop the forward-declared column first.
    op.execute("ALTER TABLE app.judgment DROP COLUMN IF EXISTS current_revision_id")
    op.execute("DROP TABLE IF EXISTS app.judgment_revision")
    op.execute("DROP TABLE IF EXISTS app.judgment")
    for function in reversed(HELPER_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
