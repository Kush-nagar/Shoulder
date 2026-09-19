"""Permit client-generated observation IDs for retry-safe drafts

Revision ID: 0009_draft_recovery
Revises: 0008_coach_judgments

Task 16 retries an interrupted observation create with the same UUID. Existing
RLS still validates team, player, bounds, source, and session-derived author.
"""

from alembic import op

revision = "0009_draft_recovery"
down_revision = "0008_coach_judgments"
branch_labels = None
depends_on = None

API_ROLE = "shoulder_api"


def upgrade() -> None:
    op.execute(f"GRANT INSERT (id) ON app.observation TO {API_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT (id) ON app.observation FROM {API_ROLE}")
