"""Grant marketplace platform-admin to one existing account (Block 10M).

Usage, with the same owner URL Alembic uses:

    MIGRATION_DATABASE_URL=postgresql+psycopg://... \\
        uv run python -m scripts.grant_admin --email ops@example.com

There is no self-service path to admin; this operator script is the only one.
Idempotent. The grant is written to the append-only marketplace audit.
"""

import argparse
import os
import sys

from sqlalchemy import create_engine, text


def grant(url: str, email: str) -> str:
    engine = create_engine(url)
    try:
        with engine.connect() as connection, connection.begin():
            user_id = connection.execute(
                text(
                    "SELECT id FROM app.user_account WHERE lower(email) = lower(:email)"
                ),
                {"email": email.strip()},
            ).scalar_one_or_none()
            if user_id is None:
                raise LookupError("no account has that address; sign in once first")
            inserted = connection.execute(
                text("""
                    INSERT INTO app.platform_admin (user_id) VALUES (:id)
                    ON CONFLICT (user_id) DO NOTHING
                """),
                {"id": user_id},
            ).rowcount
            if inserted:
                connection.execute(
                    text("""
                        INSERT INTO app.marketplace_audit
                            (action, subject_type, subject_id)
                        VALUES ('platform_admin.granted', 'user_account', :id)
                    """),
                    {"id": user_id},
                )
            return str(user_id)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant marketplace platform admin.")
    parser.add_argument("--email", required=True)
    arguments = parser.parse_args()
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is required")
    try:
        print(f"platform admin: {grant(url, arguments.email)}")
    except LookupError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
