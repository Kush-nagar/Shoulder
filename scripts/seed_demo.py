"""Create the synthetic public-demo team (ADR 0021). Idempotent.

Usage, with the same owner URL Alembic uses:

    MIGRATION_DATABASE_URL=postgresql+psycopg://... uv run python -m scripts.seed_demo

It creates (once) a synthetic coach account `demo-coach@shoulder.invalid`
that never signs in, and the team "Demo FC" with the reserved
`age_group = 'DEMO'` marker that `private.demo_join` requires. It prints the
team id; set it on the API with `DEMO_TEAM_ID=<id>` and `DEMO_MODE=on`.
Visitors then join as their own player row; no real data is involved.
"""

import os
import sys

from sqlalchemy import create_engine, text

COACH_EMAIL = "demo-coach@shoulder.invalid"


def seed(url: str) -> str:
    engine = create_engine(url)
    try:
        with engine.connect() as connection, connection.begin():
            team_id = connection.execute(
                text(
                    "SELECT id FROM app.team WHERE name = 'Demo FC'"
                    " AND age_group = 'DEMO' ORDER BY created_at LIMIT 1"
                )
            ).scalar_one_or_none()
            if team_id is not None:
                return str(team_id)
            coach_id = connection.execute(
                text("SELECT id FROM auth.users WHERE email = :email"),
                {"email": COACH_EMAIL},
            ).scalar_one_or_none()
            if coach_id is None:
                # Mirrors the test fixture; the sync trigger makes user_account.
                coach_id = connection.execute(
                    text("""
                        INSERT INTO auth.users
                            (id, instance_id, aud, role, email, raw_user_meta_data)
                        VALUES (
                            gen_random_uuid(),
                            '00000000-0000-0000-0000-000000000000',
                            'authenticated', 'authenticated', :email,
                            '{"display_name": "Demo Coach"}'::jsonb
                        )
                        RETURNING id
                    """),
                    {"email": COACH_EMAIL},
                ).scalar_one()
            team_id = connection.execute(
                text("""
                    INSERT INTO app.team
                        (name, age_group, season_label, season_end_at, created_by)
                    VALUES ('Demo FC', 'DEMO', 'Demo season',
                            now() + interval '365 days', :coach)
                    RETURNING id
                """),
                {"coach": coach_id},
            ).scalar_one()
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :coach, 'coach')
                """),
                {"team": team_id, "coach": coach_id},
            )
            return str(team_id)
    finally:
        engine.dispose()


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is required")
    print(f"DEMO_TEAM_ID={seed(url)}")


if __name__ == "__main__":
    main()
