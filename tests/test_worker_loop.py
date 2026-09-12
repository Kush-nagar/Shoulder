"""The worker loop's outcome decisions, against the real queue.

`services/worker/jobs.py` is covered by `tests/test_database_queue.py`; this
suite covers the process around it — which of release, cancel, fail, and succeed
`Worker.execute` picks, and why. Those choices are the difference between a
rolling deploy that pauses work and one that strands a coach's video.

Requires migration `0005` and the URLs `scripts/check-db.ps1` provides.
"""

import os
import sys
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

sys.path.append(str(Path(__file__).resolve().parent))

from test_database_video import VideoWorld  # noqa: E402

from services.worker import jobs, media  # noqa: E402
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
        # A handler registry the test owns, emptied for the test and restored
        # afterwards. The claim query filters on exactly this set, and the
        # production registry (`transcode`, `thumbnail`) must survive the suite.
        registry = patch.dict(worker_main.HANDLERS, {}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.handlers = worker_main.HANDLERS

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

    def test_a_long_blocking_operation_heartbeats_and_keeps_its_lease(self) -> None:
        """A media call exceeding the 120s lease must not let it expire.

        `docs/02-architecture.md`: "The worker heartbeats during ffmpeg work."
        This drives `media._run_with_heartbeat` through the real `keep_going`
        closure `Worker.execute` builds, against the real queue, and proves
        two things a lease-timeout increase would not: the heartbeat actually
        advances more than once while a blocking subprocess runs, and a second
        worker's `claim` sees nothing available for the whole duration.
        `HEARTBEAT_SECONDS`/`POLL_SECONDS` are patched small so this stays a
        fast unit-speed test rather than waiting out a real lease.
        """
        job_id = self.enqueue()

        def handler(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
            # A child that blocks without writing anything, the exact shape
            # `_run_with_heartbeat` exists to survive: a plain blocking read
            # of its stdout would never notice the deadline or a lost lease.
            argv = [sys.executable, "-c", "import time; time.sleep(0.6)"]
            media._run_with_heartbeat(argv, 30, keep_going)

        self.handlers["transcode"] = handler

        with (
            patch.object(jobs, "HEARTBEAT_SECONDS", 0.05),
            patch.object(media, "POLL_SECONDS", 0.05),
        ):
            job = jobs.claim(self.loop.identity, ("transcode",))
            assert job is not None
            self.assertEqual(job.id, job_id)

            heartbeats: list[Any] = []
            stolen: list[Any] = []
            done = threading.Event()

            def watch() -> None:
                while not done.is_set():
                    heartbeats.append(self.job_row(job_id).heartbeat_at)
                    stolen.append(jobs.claim("thief-worker", ("transcode",)))
                    done.wait(0.05)

            watcher = threading.Thread(target=watch)
            watcher.start()
            self.loop.execute(job)
            done.set()
            watcher.join(timeout=5)

        self.assertEqual(self.job_row(job_id).status, "succeeded")
        self.assertTrue(
            all(claimed is None for claimed in stolen),
            "a concurrent worker claimed a job whose lease was still heartbeating",
        )
        distinct = {beat for beat in heartbeats if beat is not None}
        self.assertGreaterEqual(
            len(distinct), 2, "the lease's heartbeat never advanced during the work"
        )

    def test_a_worker_with_no_handler_claims_nothing_at_all(self) -> None:
        """The claim query filters on registered kinds, so nothing is touched."""
        job_id = self.enqueue()
        self.assertFalse(self.loop.run_once())
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertEqual(row.attempts, 0)


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
