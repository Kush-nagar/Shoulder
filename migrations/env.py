"""Alembic environment.

Migrations connect with `MIGRATION_DATABASE_URL`. That role administers schema
objects; the API runtime role in `DATABASE_URL` never runs migrations and never
owns protected tables.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

VERSION_TABLE_SCHEMA = "app"


def migration_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL is required to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=None,
        literal_binds=True,
        version_table_schema=VERSION_TABLE_SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(migration_url(), future=True)
    with engine.connect() as connection:
        # The version table lives in the non-exposed `app` schema, so that
        # schema must exist before Alembic touches it. Downgrades leave only
        # this schema and the empty version table for Alembic bookkeeping.
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS private"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
