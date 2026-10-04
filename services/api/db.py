"""Runtime database access.

The API connects as the dedicated `NOBYPASSRLS` role, never as a table owner or
service credential, and publishes the verified subject transaction-locally as
`app.user_id`. Policies read it through `private.current_user_id()`, so a
connection returned to the pool carries no identity.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.pool import NullPool

NO_STORE = {"Cache-Control": "private, no-store"}
# Supabase's transaction-mode pooler. `app.user_id` is transaction-local, so a
# pooled backend never carries one request's identity into another.
TRANSACTION_POOLER_PORT = 6543


@lru_cache
def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "Service unavailable", headers=NO_STORE)
    if make_url(url).port == TRANSACTION_POOLER_PORT:
        # Serverless (ADR 0028): Supabase's transaction pooler owns pooling,
        # so hold no connections between requests and never prepare
        # statements a different backend would not know about.
        return create_engine(
            url, poolclass=NullPool, connect_args={"prepare_threshold": None}
        )
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@contextmanager
def user_transaction(user_id: str) -> Iterator[Connection]:
    """Open one transaction whose rows are authorized as `user_id`."""
    with get_engine().connect() as connection, connection.begin():
        connection.execute(
            # The third argument makes the setting transaction-local.
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": user_id},
        )
        yield connection


@contextmanager
def operator_transaction() -> Iterator[Connection]:
    """Open one transaction with no user identity, for operator-only calls."""
    url = os.environ.get("OPERATOR_DATABASE_URL")
    if not url:
        raise HTTPException(503, "Service unavailable", headers=NO_STORE)
    engine = create_engine(url)
    try:
        with engine.connect() as connection, connection.begin():
            if connection.execute(text("SELECT current_user")).scalar_one() != (
                "shoulder_operator"
            ):
                raise HTTPException(503, "Service unavailable", headers=NO_STORE)
            yield connection
    finally:
        engine.dispose()
