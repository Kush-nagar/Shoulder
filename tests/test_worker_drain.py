"""`--drain` mode (ADR 0028): run until the queue stays empty, then exit."""

import unittest
from unittest import mock

from services.worker import jobs, main


class DrainTests(unittest.TestCase):
    def test_runs_queued_jobs_then_exits_once_idle(self) -> None:
        worker = main.Worker("test")
        results = iter([True, True, False, False])
        with (
            mock.patch.object(worker, "run_once", side_effect=lambda: next(results)),
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
            mock.patch.object(main, "IDLE_SLEEP_SECONDS", 0.0),
        ):
            self.assertEqual(worker.drain(idle_seconds=0.0), 0)

    def test_stop_ends_the_drain(self) -> None:
        worker = main.Worker("test")
        worker.stop()
        self.assertEqual(worker.drain(idle_seconds=60.0), 0)


if __name__ == "__main__":
    unittest.main()
