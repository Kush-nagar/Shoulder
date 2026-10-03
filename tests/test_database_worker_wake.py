"""Worker wake-up trigger (ADR 0028, migration 0021)."""

import unittest
from uuid import uuid4

from sqlalchemy import text
from test_database import DatabaseTestCase


class WorkerWakeTests(DatabaseTestCase):
    def test_trigger_is_statement_level_after_insert(self) -> None:
        with self.admin.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT t.tgtype, p.prosecdef,
                           coalesce(array_to_string(p.proconfig, ','), '') AS config
                    FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                    WHERE t.tgrelid = 'app.processing_job'::regclass
                      AND t.tgname = 'processing_job_wake_worker'
                """)
            ).one()
        # tgtype bit 0 = row-level; bit 2 = INSERT. Statement level, on insert.
        self.assertEqual(row.tgtype & 1, 0)
        self.assertTrue(row.tgtype & 4)
        self.assertTrue(row.prosecdef)
        self.assertIn('search_path=""', row.config)

    def test_no_runtime_role_can_call_or_reach_it(self) -> None:
        with self.admin.connect() as connection:
            for role in ("shoulder_api", "shoulder_worker", "shoulder_operator"):
                with self.subTest(role=role):
                    allowed = connection.execute(
                        text("""
                            SELECT has_function_privilege(
                                       :role, 'worker_wake.dispatch()', 'EXECUTE'),
                                   has_schema_privilege(:role, 'worker_wake', 'USAGE')
                        """),
                        {"role": role},
                    ).one()
                    self.assertEqual(tuple(allowed), (False, False))

    def test_enqueue_without_a_token_succeeds_and_sends_nothing(self) -> None:
        key = f"wake-test-{uuid4()}"
        with self.admin.connect() as connection, connection.begin():
            has_token = connection.execute(
                text("""
                    SELECT to_regclass('vault.decrypted_secrets') IS NOT NULL
                       AND EXISTS (SELECT 1 FROM vault.decrypted_secrets
                                   WHERE name = 'worker_dispatch_token')
                """)
            ).scalar_one()
            if has_token:
                self.skipTest("a dispatch token is configured on this database")
            before = connection.execute(
                text("""
                    SELECT CASE
                        WHEN to_regclass('net.http_request_queue') IS NULL THEN 0
                        ELSE (SELECT count(*) FROM net.http_request_queue)
                    END
                """)
            ).scalar_one()
            connection.execute(
                text("""
                    INSERT INTO app.processing_job (kind, idempotency_key, max_attempts)
                    VALUES ('retention_sweep', :key, 1)
                """),
                {"key": key},
            )
            after = connection.execute(
                text("""
                    SELECT CASE
                        WHEN to_regclass('net.http_request_queue') IS NULL THEN 0
                        ELSE (SELECT count(*) FROM net.http_request_queue)
                    END
                """)
            ).scalar_one()
            connection.execute(
                text("DELETE FROM app.processing_job WHERE idempotency_key = :key"),
                {"key": key},
            )
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
