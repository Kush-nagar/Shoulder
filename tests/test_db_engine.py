"""Engine choice for the serverless API (ADR 0028)."""

import os
import unittest
from unittest import mock

from sqlalchemy.pool import NullPool, QueuePool

from services.api import db


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        db.get_engine.cache_clear()
        self.addCleanup(db.get_engine.cache_clear)

    def engine_for(self, url: str):  # type: ignore[no-untyped-def]
        with mock.patch.dict(os.environ, {"DATABASE_URL": url}):
            return db.get_engine()

    def test_transaction_pooler_holds_no_connections(self) -> None:
        engine = self.engine_for(
            "postgresql+psycopg://u.ref:p@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )
        self.assertIsInstance(engine.pool, NullPool)

    def test_direct_connections_keep_the_pool(self) -> None:
        engine = self.engine_for("postgresql+psycopg://u:p@127.0.0.1:54322/postgres")
        self.assertIsInstance(engine.pool, QueuePool)


if __name__ == "__main__":
    unittest.main()
