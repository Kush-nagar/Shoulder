"""Safe coach roster display for linked accounts

Revision ID: 0003_roster_display
Revises: 0002_task4_privileges
Create Date: 2026-09-08

`docs/03-schema.md` allows a coach a limited linked roster display of
`user_account` "through safe query", while direct table access stays self-only.
This adds that one narrowly scoped helper: it authorizes on the caller's own
coach membership, returns display names only, and never exposes an address.
"""

from alembic import op

revision = "0003_roster_display"
down_revision = "0002_task4_privileges"
branch_labels = None
depends_on = None

ROSTER = "private.team_roster(uuid)"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION private.team_roster(p_team_id uuid)
        RETURNS TABLE (player_id uuid, player_name text, account_name text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT p.id, p.display_name, a.display_name
            FROM app.player p
            LEFT JOIN app.user_account a ON a.id = p.user_id
            WHERE p.team_id = p_team_id
              AND p.deleted_at IS NULL
              AND p.deletion_pending_at IS NULL
              -- Authorization is the caller's own membership, never an argument.
              AND private.is_team_coach(p_team_id)
        $$;
    """)
    op.execute(f"ALTER FUNCTION {ROSTER} OWNER TO shoulder_migration")
    for role in ("PUBLIC", "anon", "authenticated"):
        op.execute(f"REVOKE ALL ON FUNCTION {ROSTER} FROM {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ROSTER} TO shoulder_api")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {ROSTER}")
