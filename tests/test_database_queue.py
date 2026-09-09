"""Task 10 — the durable Postgres work queue, against a real database.

Nothing here is mocked. The concurrency proof runs two worker identities in two
threads against real `FOR UPDATE SKIP LOCKED` transactions, because the whole
point of the design is Postgres's locking behavior; a fake queue would prove
only that the test's own bookkeeping works.

Requires migration `0005` and the URLs `scripts/check-db.ps1` provides,
including `WORKER_DATABASE_URL` for the `shoulder_worker` login (ADR 0018).
"""

import os
import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import REQUIRED  # noqa: E402
from test_database_video import VideoWorld  # noqa: E402

from services.worker import jobs  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
CONCURRENT_JOBS = 100


class ConfigurationTests(unittest.TestCase):
    def test_the_concurrency_suite_runs_where_a_database_is_required(self) -> None:
        if REQUIRED:
            self.assertTrue(WORKER_URL, "WORKER_DATABASE_URL is required")
            self.assertFalse(
                getattr(QueueTests, "__unittest_skip__", False),
                "the queue concurrency suite must never be skipped",
            )


class BackoffTests(unittest.TestCase):
    """Pure curve checks; the SQL equivalence is asserted against the database."""

    def test_backoff_grows_and_then_holds_at_the_ceiling(self) -> None:
        self.assertEqual(
            [jobs.backoff_seconds(n) for n in range(1, 8)],
            [30, 60, 120, 240, 300, 300, 300],
        )

    def test_a_first_attempt_still_gets_the_base_delay(self) -> None:
        self.assertEqual(jobs.backoff_seconds(0), jobs.BACKOFF_BASE_SECONDS)

    def test_the_lease_outlives_several_heartbeat_intervals(self) -> None:
        """A busy worker must not have its live job swept out from under it."""
        self.assertGreaterEqual(jobs.LEASE_SECONDS, jobs.HEARTBEAT_SECONDS * 3)


@unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
class QueueTests(VideoWorld):
    def setUp(self) -> None:
        super().setUp()
        # `jobs` reads the URL from the environment; the harness already has it.
        jobs.get_engine.cache_clear()
        self.addCleanup(jobs.get_engine.cache_clear)
        self.kinds = ("transcode",)

    def enqueue(self, count: int, kind: str = "transcode") -> list[UUID]:
        return [
            self.admin_insert_job(
                self.video_a, kind, idempotency_key=f"{kind}:{self.video_a}:{index}"
            )
            for index in range(count)
        ]

    def job_row(self, job_id: UUID) -> Any:
        with self.admin.connect() as connection:
            return connection.execute(
                text("SELECT * FROM app.processing_job WHERE id = :id"),
                {"id": job_id},
            ).one()

    def clear_queue(self) -> None:
        """Only this test's rows exist; the harness deletes them with the team."""
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.processing_job WHERE video_id IN (:a, :b)"),
                {"a": self.video_a, "b": self.video_b},
            )

    # --- claiming ---------------------------------------------------------

    def test_a_claim_takes_the_lease_and_counts_the_attempt(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        claimed = jobs.claim("worker-1", self.kinds)
        assert claimed is not None
        self.assertEqual(claimed.id, job_id)
        self.assertEqual(claimed.attempts, 1)
        row = self.job_row(job_id)
        self.assertEqual(row.status, "running")
        self.assertEqual(row.locked_by, "worker-1")
        self.assertIsNotNone(row.locked_at)
        self.assertIsNotNone(row.heartbeat_at)
        self.assertIsNotNone(row.started_at)

    def test_a_running_job_is_not_claimed_again(self) -> None:
        self.clear_queue()
        self.enqueue(1)
        self.assertIsNotNone(jobs.claim("worker-1", self.kinds))
        self.assertIsNone(jobs.claim("worker-2", self.kinds))

    def test_a_worker_never_claims_a_kind_it_cannot_run(self) -> None:
        """An unimplemented kind waits rather than burning its attempts."""
        self.clear_queue()
        (job_id,) = self.enqueue(1, kind="thumbnail")
        self.assertIsNone(jobs.claim("worker-1", ("transcode",)))
        self.assertEqual(self.job_row(job_id).status, "queued")
        self.assertEqual(self.job_row(job_id).attempts, 0)

    def test_a_worker_with_no_handlers_claims_nothing(self) -> None:
        self.clear_queue()
        self.enqueue(1)
        self.assertIsNone(jobs.claim("worker-1", ()))

    def test_a_job_scheduled_for_later_is_not_yet_eligible(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.processing_job"
                    " SET available_at = now() + interval '1 hour' WHERE id = :id"
                ),
                {"id": job_id},
            )
        self.assertIsNone(jobs.claim("worker-1", self.kinds))

    def test_jobs_are_claimed_in_availability_then_creation_order(self) -> None:
        self.clear_queue()
        first, second, third = self.enqueue(3)
        with self.admin.connect() as connection, connection.begin():
            # Make the third eligible earliest; it must be claimed first.
            connection.execute(
                text(
                    "UPDATE app.processing_job"
                    " SET available_at = now() - interval '1 hour' WHERE id = :id"
                ),
                {"id": third},
            )
        order = []
        for index in range(3):
            claimed = jobs.claim(f"worker-{index}", self.kinds)
            assert claimed is not None
            order.append(claimed.id)
        self.assertEqual(order, [third, first, second])

    # --- the load-bearing concurrency proof --------------------------------

    def test_two_workers_claim_one_hundred_jobs_with_no_double_execution(self) -> None:
        """Two real workers, one hundred real rows, zero jobs claimed twice."""
        self.clear_queue()
        expected = set(self.enqueue(CONCURRENT_JOBS))
        claimed: list[UUID] = []
        guard = threading.Lock()
        errors: list[BaseException] = []
        start = threading.Barrier(2)

        def drain(name: str) -> None:
            try:
                start.wait(timeout=30)
                while True:
                    job = jobs.claim(name, self.kinds)
                    if job is None:
                        # An empty claim can also mean "every remaining row is
                        # locked right now", so confirm the queue is really
                        # drained before this worker gives up.
                        if not self.queued_remaining():
                            return
                        continue
                    with guard:
                        claimed.append(job.id)
                    jobs.succeed(job.id, name)
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        threads = [
            threading.Thread(target=drain, args=(f"worker-{index}",), daemon=True)
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
            self.assertFalse(thread.is_alive(), "a worker thread did not finish")
        self.assertEqual(errors, [])

        self.assertEqual(len(claimed), CONCURRENT_JOBS, "a job was claimed twice")
        self.assertEqual(set(claimed), expected)
        with self.admin.connect() as connection:
            statuses = connection.execute(
                text("""
                    SELECT status, count(*), max(attempts) FROM app.processing_job
                    WHERE video_id = :video GROUP BY status
                """),
                {"video": self.video_a},
            ).all()
        self.assertEqual(
            [(row[0], row[1], row[2]) for row in statuses],
            [("succeeded", CONCURRENT_JOBS, 1)],
        )

    def queued_remaining(self) -> int:
        with self.admin.connect() as connection:
            return int(
                connection.execute(
                    text("""
                        SELECT count(*) FROM app.processing_job
                        WHERE status = 'queued' AND video_id = :video
                    """),
                    {"video": self.video_a},
                ).scalar_one()
            )

    def test_concurrent_claims_never_return_the_same_row(self) -> None:
        """`SKIP LOCKED` in isolation: two simultaneous claims, two rows."""
        self.clear_queue()
        self.enqueue(2)
        results: list[UUID | None] = [None, None]
        ready = threading.Barrier(2)

        def grab(slot: int) -> None:
            ready.wait(timeout=30)
            job = jobs.claim(f"racer-{slot}", self.kinds)
            results[slot] = job.id if job else None

        threads = [threading.Thread(target=grab, args=(slot,)) for slot in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertNotIn(None, results)
        self.assertNotEqual(results[0], results[1])

    # --- leases, heartbeats, and recovery ---------------------------------

    def test_a_heartbeat_keeps_a_lease_and_records_progress(self) -> None:
        self.clear_queue()
        self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertTrue(jobs.heartbeat(job.id, "worker-1", 0.5))
        self.assertEqual(float(self.job_row(job.id).progress), 0.5)

    def test_a_second_worker_cannot_heartbeat_someone_elses_lease(self) -> None:
        self.clear_queue()
        self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertFalse(jobs.heartbeat(job.id, "worker-2"))

    def test_an_expired_lease_is_recovered_once_and_stays_retryable(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        job = jobs.claim("crashing-worker", self.kinds)
        assert job is not None
        self.expire_lease(job_id)

        self.assertEqual(jobs.sweep_expired_leases(), 1)
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertEqual(row.attempts, 1)
        self.assertIsNone(row.locked_by)
        # A job that is merely waiting to retry carries no error; only one that
        # has given up does. See `test_a_swept_job_that_gives_up_says_so`.
        self.assertIsNone(row.error_code)
        # A second sweep must not touch an already recovered row.
        self.assertEqual(jobs.sweep_expired_leases(), 0)

    def test_a_live_heartbeat_is_never_swept(self) -> None:
        self.clear_queue()
        self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertEqual(jobs.sweep_expired_leases(), 0)
        self.assertEqual(self.job_row(job.id).status, "running")

    def test_a_crashed_worker_cannot_finish_a_job_it_no_longer_holds(self) -> None:
        """The recovered job belongs to whoever claims it next."""
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        job = jobs.claim("crashing-worker", self.kinds)
        assert job is not None
        self.expire_lease(job_id)
        jobs.sweep_expired_leases()
        # Recovery applies backoff, so the row is not instantly re-claimable.
        self.assertIsNone(jobs.claim("worker-2", self.kinds))
        self.make_available(job_id)

        second = jobs.claim("worker-2", self.kinds)
        assert second is not None
        self.assertEqual(second.id, job_id)
        self.assertEqual(second.attempts, 2)
        # The crashed worker's stale completion must not land on someone
        # else's lease, which is what makes recovery safe rather than racy.
        self.assertFalse(jobs.succeed(job_id, "crashing-worker"))
        self.assertEqual(self.job_row(job_id).status, "running")
        self.assertTrue(jobs.succeed(job_id, "worker-2"))

    def make_available(self, job_id: UUID) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.processing_job SET available_at = now() WHERE id = :id"
                ),
                {"id": job_id},
            )

    def test_a_lease_that_exhausts_its_attempts_fails_instead_of_looping(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.processing_job SET max_attempts = 1 WHERE id = :id"),
                {"id": job_id},
            )
        jobs.claim("crashing-worker", self.kinds)
        self.expire_lease(job_id)
        self.assertEqual(jobs.sweep_expired_leases(), 1)
        row = self.job_row(job_id)
        self.assertEqual(row.status, "failed")
        self.assertIsNotNone(row.finished_at)

    def expire_lease(self, job_id: UUID) -> None:
        """Simulate a worker that stopped without releasing its lease."""
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(f"""
                    UPDATE app.processing_job
                    SET heartbeat_at = now()
                        - interval '{jobs.LEASE_SECONDS * 2} seconds'
                    WHERE id = :id
                """),
                {"id": job_id},
            )

    # --- failure, backoff, and cancellation --------------------------------

    def test_a_retryable_failure_requeues_with_the_documented_backoff(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertTrue(jobs.fail(job_id, "worker-1", "probe_failed", "Try again."))
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertIsNone(row.finished_at)
        self.assertIsNone(row.locked_by)
        with self.admin.connect() as connection:
            delay = connection.execute(
                text(
                    "SELECT extract(epoch FROM (available_at - now()))"
                    " FROM app.processing_job WHERE id = :id"
                ),
                {"id": job_id},
            ).scalar_one()
        # The SQL curve and `backoff_seconds` must agree; allow for clock drift
        # between the UPDATE and this read.
        self.assertAlmostEqual(
            float(delay), float(jobs.backoff_seconds(row.attempts)), delta=5
        )

    def test_backoff_reaches_the_ceiling_in_the_database_too(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.processing_job SET attempts = 7, max_attempts = 20"
                    " WHERE id = :id"
                ),
                {"id": job_id},
            )
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        jobs.fail(job_id, "worker-1", "probe_failed", "Try again.")
        with self.admin.connect() as connection:
            delay = connection.execute(
                text(
                    "SELECT extract(epoch FROM (available_at - now()))"
                    " FROM app.processing_job WHERE id = :id"
                ),
                {"id": job_id},
            ).scalar_one()
        self.assertAlmostEqual(float(delay), float(jobs.BACKOFF_MAX_SECONDS), delta=5)

    def test_the_last_attempt_becomes_a_terminal_failure(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.processing_job SET max_attempts = 1 WHERE id = :id"),
                {"id": job_id},
            )
        jobs.claim("worker-1", self.kinds)
        jobs.fail(job_id, "worker-1", "bad_media", "This file cannot be processed.")
        row = self.job_row(job_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_code, "bad_media")
        self.assertIsNotNone(row.finished_at)

    def test_a_non_retryable_failure_is_terminal_on_the_first_attempt(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("worker-1", self.kinds)
        jobs.fail(job_id, "worker-1", "bad_media", "Unreadable file.", retryable=False)
        self.assertEqual(self.job_row(job_id).status, "failed")

    def test_error_text_is_bounded_so_it_cannot_carry_a_provider_message(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("worker-1", self.kinds)
        jobs.fail(job_id, "worker-1", "x" * 200, "y" * 900)
        row = self.job_row(job_id)
        self.assertEqual(len(row.error_code), 60)
        self.assertEqual(len(row.error_message), 300)

    def test_cancellation_is_visible_to_the_worker_that_holds_the_job(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertFalse(jobs.cancel_requested(job_id))
        with self.admin.connect() as connection, connection.begin():
            self.assertEqual(jobs.request_cancel(connection, job_id), 1)
        self.assertTrue(jobs.cancel_requested(job_id))
        self.assertTrue(jobs.cancelled(job_id, "worker-1"))
        row = self.job_row(job_id)
        self.assertEqual(row.status, "cancelled")
        self.assertIsNone(row.locked_by)

    def test_a_finished_job_cannot_be_cancelled(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("worker-1", self.kinds)
        jobs.succeed(job_id, "worker-1")
        with self.admin.connect() as connection, connection.begin():
            self.assertEqual(jobs.request_cancel(connection, job_id), 0)

    def test_releasing_a_job_records_no_failure_and_returns_its_attempt(self) -> None:
        """A worker that stops is not a job that failed, or one that tried."""
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        job = jobs.claim("worker-1", self.kinds)
        assert job is not None
        self.assertEqual(self.job_row(job_id).attempts, 1)
        self.assertTrue(jobs.release(job_id, "worker-1"))
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertEqual(row.attempts, 0, "a release hands the attempt back")
        self.assertIsNone(row.error_code)
        self.assertIsNone(row.error_message)
        self.assertIsNone(row.locked_by)
        self.assertIsNone(row.finished_at)

    def test_releasing_the_last_attempt_leaves_the_job_claimable(self) -> None:
        """Otherwise the next claim would violate the attempts bound and die.

        A released row that kept its attempt would sit at `max_attempts` in
        `queued`, where the claim's `attempts + 1` breaks
        `processing_job_attempts_bounded` and strands the job forever.
        """
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.processing_job SET max_attempts = 1 WHERE id = :id"),
                {"id": job_id},
            )
        jobs.claim("worker-1", self.kinds)
        self.assertTrue(jobs.release(job_id, "worker-1"))
        self.make_available(job_id)
        again = jobs.claim("worker-2", self.kinds)
        assert again is not None
        self.assertEqual(again.id, job_id)
        self.assertEqual(again.attempts, 1)

    def test_an_exhausted_queued_row_is_never_claimed(self) -> None:
        """Belt and braces: claiming it would break the attempts bound."""
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.processing_job SET attempts = 3, max_attempts = 3"
                    " WHERE id = :id"
                ),
                {"id": job_id},
            )
        self.assertIsNone(jobs.claim("worker-1", self.kinds))
        self.assertEqual(self.job_row(job_id).status, "queued")

    def test_a_second_worker_cannot_release_someone_elses_lease(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("worker-1", self.kinds)
        self.assertFalse(jobs.release(job_id, "worker-2"))
        self.assertEqual(self.job_row(job_id).status, "running")

    def test_a_recovered_job_carries_no_error_while_it_waits(self) -> None:
        """`docs/05-ui.md`: waiting to retry must not read as failed."""
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("crashing-worker", self.kinds)
        self.expire_lease(job_id)
        jobs.sweep_expired_leases()
        row = self.job_row(job_id)
        self.assertEqual(row.status, "queued")
        self.assertIsNone(row.error_code)
        self.assertIsNone(row.error_message)

    def test_a_swept_job_that_gives_up_says_so(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.processing_job SET max_attempts = 1 WHERE id = :id"),
                {"id": job_id},
            )
        jobs.claim("crashing-worker", self.kinds)
        self.expire_lease(job_id)
        jobs.sweep_expired_leases()
        row = self.job_row(job_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_code, "lease_expired")
        self.assertNotIn("originals/", row.error_message)

    def test_the_sweeper_backs_off_on_the_same_curve_as_a_failure(self) -> None:
        """A crash must not be retried faster than a reported error."""
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.processing_job SET attempts = 3, max_attempts = 20"
                    " WHERE id = :id"
                ),
                {"id": job_id},
            )
        jobs.claim("crashing-worker", self.kinds)
        self.expire_lease(job_id)
        jobs.sweep_expired_leases()
        with self.admin.connect() as connection:
            delay = connection.execute(
                text(
                    "SELECT extract(epoch FROM (available_at - now()))"
                    " FROM app.processing_job WHERE id = :id"
                ),
                {"id": job_id},
            ).scalar_one()
        self.assertAlmostEqual(float(delay), float(jobs.backoff_seconds(4)), delta=5)

    def test_a_succeeded_job_is_released_and_complete(self) -> None:
        self.clear_queue()
        (job_id,) = self.enqueue(1)
        jobs.claim("worker-1", self.kinds)
        self.assertTrue(jobs.succeed(job_id, "worker-1"))
        row = self.job_row(job_id)
        self.assertEqual(row.status, "succeeded")
        self.assertEqual(float(row.progress), 1.0)
        self.assertIsNone(row.locked_by)
        self.assertIsNotNone(row.finished_at)

    def test_enqueueing_the_same_key_twice_creates_one_job(self) -> None:
        self.clear_queue()
        key = f"transcode:{self.video_a}:v1"
        with self.admin.connect() as connection, connection.begin():
            for _ in range(2):
                connection.execute(
                    text("""
                        INSERT INTO app.processing_job
                            (video_id, kind, idempotency_key)
                        VALUES (:video, 'transcode', :key)
                        ON CONFLICT (idempotency_key) DO NOTHING
                    """),
                    {"video": self.video_a, "key": key},
                )
        with self.admin.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM app.processing_job"
                    " WHERE idempotency_key = :key"
                ),
                {"key": key},
            ).scalar_one()
        self.assertEqual(count, 1)


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
