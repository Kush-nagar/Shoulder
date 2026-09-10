"""The worker loop's outcome decisions, against the real queue.

`services/worker/jobs.py` is covered by `tests/test_database_queue.py`; this
suite covers the process around it — which of release, cancel, fail, and succeed
`Worker.execute` picks, and why. Those choices are the difference between a
rolling deploy that pauses work and one that strands a coach's video.

Requires migration `0005` and the URLs `scripts/check-db.ps1` provides.
"""

import os
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

sys.path.append(str(Path(__file__).resolve().parent))

from test_database_video import VideoWorld  # noqa: E402

from services.worker import jobs  # noqa: E402
from services.worker import main as worker_main  # noqa: E402
from services.worker.main import Cancelled, Worker  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")


@unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
class WorkerLoopTests(VideoWorld):
    def setUp(self) -> None:
        super().setUp()
        jobs.get_engine.cache_clear()
        self.addCleanup(jobs.get_engine.cache_clear)
        self.clear_queue()
        self.loop = Worker("loop-worker")
        # A handler registry the test owns; production registers none in this
        # block, and the claim query filters on exactly this set.
        self.handlers = worker_main.HANDLERS
        self.addCleanup(self.handlers.clear)

    def clear_queue(self) -> None:
        from sqlalchemy import text

        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.processing_job WHERE video_id IN (:a, :b)"),
                {"a": self.video_a, "b": self.video_b},
            )

    def enqueue(self, kind: str = "transcode", suffix: str = "loop") -> UUID:
        return self.admin_insert_job(
            self.video_a, kind, idempotency_key=f"{kind}:{self.video_a}:{suffix}"
        )

    def job_row(self, job_id: UUID) -> Any:
        from sqlalchemy import text

        with self.admin.connect() as connection:
            return connection.execute(
                text("SELECT * FROM app.processing_job WHERE id = :id"),
                {"id": job_id},
            ).one()

    def test_a_finished_handler_succeeds(self) -> None:
        job_id = self.enqueue()
        ran: list[UUID] = []

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            ran.append(job.id)

        self.handlers["transcode"] = handler
        self.assertTrue(self.loop.run_once())
        self.assertEqual(ran, [job_id])
        self.assertEqual(self.job_row(job_id).status, "succeeded")

    def test_a_shutdown_mid_job_requeues_instead_of_cancelling(self) -> None:
        """A rolling deploy must not strand a video nobody asked to cancel."""
        job_id = self.enqueue()

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            self.loop.stop()
            self.assertFalse(keep_going(None))
            raise Cancelled

        self.handlers["transcode"] = handler
        self.loop.run_once()
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertIsNone(row.error_code)
        self.assertIsNone(row.locked_by)
        # The attempt is handed back: the work never reached a conclusion, and
        # keeping it would strand the job on its last claim.
        self.assertEqual(row.attempts, 0)

    def test_a_handler_that_returns_after_shutdown_is_not_a_success(self) -> None:
        """Half-processed work must never be recorded as finished."""
        job_id = self.enqueue()

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            self.loop.stop()

        self.handlers["transcode"] = handler
        self.loop.run_once()
        self.assertEqual(self.job_row(job_id).status, "queued")

    def test_an_explicit_cancellation_is_terminal(self) -> None:
        job_id = self.enqueue()

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            with self.admin.connect() as connection, connection.begin():
                jobs.request_cancel(connection, job.id)
            self.assertFalse(keep_going(None))
            raise Cancelled

        self.handlers["transcode"] = handler
        self.loop.run_once()
        self.assertEqual(self.job_row(job_id).status, "cancelled")

    def test_a_raising_handler_fails_with_coach_safe_text_only(self) -> None:
        job_id = self.enqueue()

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            raise RuntimeError("s3://shoulder-local/originals/secret/source.mp4")

        self.handlers["transcode"] = handler
        # Patched rather than captured: it keeps the traceback out of the test
        # output and asserts the operator still gets one.
        with patch.object(worker_main.logger, "exception") as logged:
            self.loop.run_once()
        logged.assert_called_once()
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued", "a first failure is retryable")
        self.assertEqual(row.error_code, "handler_error")
        # The stored text is fixed; nothing from the exception reaches the row.
        self.assertNotIn("originals/", row.error_message)
        self.assertNotIn("s3://", row.error_message)

    def test_a_worker_with_no_handler_claims_nothing_at_all(self) -> None:
        """The claim query filters on registered kinds, so nothing is touched."""
        job_id = self.enqueue()
        self.assertFalse(self.loop.run_once())
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertEqual(row.attempts, 0)


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
