"""`--drain` mode (ADR 0028): run until the queue stays empty, then exit."""

import unittest
from unittest import mock

from services.worker import jobs, main, retention


class DrainTests(unittest.TestCase):
    def test_runs_queued_jobs_then_exits_once_idle(self) -> None:
        worker = main.Worker("test")
        results = iter([True, True, False, False])
        with (
            mock.patch.object(worker, "run_once", side_effect=lambda: next(results)),
            mock.patch.object(worker, "maybe_sweep"),
            mock.patch.object(main, "IDLE_SLEEP_SECONDS", 0.0),
        ):
            self.assertEqual(worker.drain(idle_seconds=0.0), 2)

    def test_a_queue_outage_does_not_crash_the_drain(self) -> None:
        worker = main.Worker("test")
        calls = iter([True, False])

        def run_once() -> bool:
            if next(calls):
                raise jobs.QueueError("down")
            return False

        with (
            mock.patch.object(worker, "run_once", side_effect=run_once),
            mock.patch.object(worker, "maybe_sweep"),
            mock.patch.object(main, "IDLE_SLEEP_SECONDS", 0.0),
        ):
            self.assertEqual(worker.drain(idle_seconds=0.0), 0)

    def test_sweeps_once_per_wake_up(self) -> None:
        worker = main.Worker("test")
        with (
            mock.patch.object(jobs, "sweep_expired_leases", return_value=0) as leases,
            mock.patch.object(retention, "enqueue_due_sweep") as enqueue,
            mock.patch.object(retention, "sweep_scratch", return_value=0),
            mock.patch.object(jobs, "claim", side_effect=lambda *_: None),
            mock.patch.object(main, "IDLE_SLEEP_SECONDS", 0.0),
        ):
            # Real run_once: it calls maybe_sweep, which must now be a no-op.
            worker.drain(idle_seconds=0.0)
        self.assertEqual(leases.call_count, 1)
        self.assertEqual(enqueue.call_count, 1)

    def test_stop_ends_the_drain(self) -> None:
        worker = main.Worker("test")
        worker.stop()
        worker.maybe_sweep = mock.Mock()  # type: ignore[method-assign]
        self.assertEqual(worker.drain(idle_seconds=60.0), 0)


if __name__ == "__main__":
    unittest.main()
