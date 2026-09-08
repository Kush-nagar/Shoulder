"""Restrict bootstrap authority and require membership for player reads."""

from alembic import op

revision = "0002_task4_privileges"
down_revision = "0001_core_identity"
branch_labels = None
depends_on = None

BOOTSTRAP = "private.bootstrap_initial_team(uuid, text, text, timestamptz, text)"


def upgrade() -> None:
    op.execute("""
        CREATE ROLE shoulder_operator LOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOBYPASSRLS NOINHERIT
    """)
    op.execute("ALTER ROLE shoulder_operator SET search_path = ''")
    op.execute("GRANT USAGE ON SCHEMA private TO shoulder_operator")
    op.execute(f"REVOKE EXECUTE ON FUNCTION {BOOTSTRAP} FROM shoulder_api")
    op.execute(f"GRANT EXECUTE ON FUNCTION {BOOTSTRAP} TO shoulder_operator")
    op.execute("""
        ALTER POLICY player_visible_select ON app.player USING (
            private.is_team_coach(team_id)
            OR (
                user_id = private.current_user_id()
                AND private.is_team_member(team_id)
                AND deleted_at IS NULL
                AND deletion_pending_at IS NULL
            )
        )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER POLICY player_visible_select ON app.player USING (
            private.is_team_coach(team_id)
            OR (
                user_id = private.current_user_id()
                AND deleted_at IS NULL
                AND deletion_pending_at IS NULL
            )
        )
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION {BOOTSTRAP} TO shoulder_api")
    op.execute(f"REVOKE EXECUTE ON FUNCTION {BOOTSTRAP} FROM shoulder_operator")
    op.execute("REVOKE USAGE ON SCHEMA private FROM shoulder_operator")
    op.execute("DROP ROLE shoulder_operator")
