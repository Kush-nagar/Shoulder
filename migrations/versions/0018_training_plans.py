"""Coach-authored weekly training plans (Block 09B W3)

Revision ID: 0018_training_plans
Revises: 0016_training_sessions

A plan targets one player or, with a null `player_id`, the whole team. Items
reference static drill slugs from `apps/web/content/drills.ts`; the database
bounds their shape and count, the API validates each item.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0018_training_plans"
down_revision = "0016_training_sessions"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
# A plan for one player must name a player of the same team.
SAME_TEAM = """
    (player_id IS NULL OR EXISTS (
        SELECT 1 FROM app.player p
        WHERE p.id = training_plan.player_id AND p.team_id = training_plan.team_id
    ))
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.training_plan (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id uuid NOT NULL REFERENCES app.team (id) ON DELETE CASCADE,
            player_id uuid REFERENCES app.player (id) ON DELETE CASCADE,
            created_by uuid NOT NULL REFERENCES app.user_account (id),
            title text NOT NULL
                CONSTRAINT training_plan_title_length
                    CHECK (char_length(title) BETWEEN 1 AND 80),
            week_of date NOT NULL
                CONSTRAINT training_plan_week_starts_monday
                    CHECK (extract(isodow FROM week_of) = 1),
            items jsonb NOT NULL
                CONSTRAINT training_plan_items_shape
                    CHECK (jsonb_typeof(items) = 'array'
                           AND jsonb_array_length(items) BETWEEN 1 AND 8
                           AND octet_length(items::text) <= 4096),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    for column in ("team_id", "player_id", "created_by"):
        op.execute(
            f"CREATE INDEX training_plan_{column}_idx ON app.training_plan ({column})"
        )
    op.execute(
        "CREATE INDEX training_plan_team_week_idx"
        " ON app.training_plan (team_id, week_of DESC)"
    )

    op.execute(f"ALTER TABLE app.training_plan OWNER TO {MIGRATION_ROLE}")
    op.execute("ALTER TABLE app.training_plan ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.training_plan FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY training_plan_owner_maintenance ON app.training_plan
            FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
    """)
    op.execute(f"""
        CREATE POLICY training_plan_coach_select ON app.training_plan
            FOR SELECT TO {API_ROLE}
            USING (private.is_team_coach(team_id))
    """)
    op.execute(f"""
        CREATE POLICY training_plan_coach_insert ON app.training_plan
            FOR INSERT TO {API_ROLE}
            WITH CHECK (
                private.is_team_coach(team_id)
                AND created_by = private.current_user_id()
                AND {SAME_TEAM}
            )
    """)
    op.execute(f"""
        CREATE POLICY training_plan_coach_update ON app.training_plan
            FOR UPDATE TO {API_ROLE}
            USING (private.is_team_coach(team_id))
            WITH CHECK (private.is_team_coach(team_id))
    """)
    op.execute(f"""
        CREATE POLICY training_plan_coach_delete ON app.training_plan
            FOR DELETE TO {API_ROLE}
            USING (private.is_team_coach(team_id))
    """)
    # A player reads their own plans and whole-team plans of their own team;
    # never another player's individual plan.
    op.execute(f"""
        CREATE POLICY training_plan_player_select ON app.training_plan
            FOR SELECT TO {API_ROLE}
            USING (
                CASE WHEN player_id IS NULL
                    THEN private.is_team_member(team_id)
                    ELSE private.is_player_self(player_id)
                END
            )
    """)
    op.execute(f"GRANT SELECT, INSERT, DELETE ON app.training_plan TO {API_ROLE}")
    # Target team and player are fixed after creation.
    op.execute(
        f"GRANT UPDATE (title, week_of, items, updated_at) ON app.training_plan TO {API_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.training_plan")
