"""The CPU worker process.

A separate process from FastAPI with no HTTP surface and no user identity. It
claims one job at a time from `app.processing_job`, runs the handler registered
for that kind, heartbeats while it works, and records a terminal or retryable
outcome. `docs/02-architecture.md` puts it on its own machine with ffmpeg; the
claim mechanics live in `services/worker/jobs.py`.

Block 02 registers no production handler. Task 11 registers `transcode` and
Task 12 registers `thumbnail`. Until then `HANDLERS` is empty, the claim query
matches no kind, and the rows enqueued at upload completion wait in the queue
instead of failing: an unimplemented kind must not burn a job's attempts.
"""

import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from services.worker import jobs

logger = logging.getLogger("shoulder.worker")

# kind -> handler. A handler receives the claimed job and a callable it must
# poll: it returns False when the worker should stop, either because the lease
# was lost or because cancellation was requested.
Handler = Callable[[jobs.Job, Callable[[float | None], bool]], None]
HANDLERS: dict[str, Handler] = {}

IDLE_SLEEP_SECONDS = 2.0
SWEEP_INTERVAL_SECONDS = 30.0


class Cancelled(Exception):
    """A handler saw `keep_going()` return False and stopped.

    It carries no reason on purpose. A handler cannot tell a cancellation from
    a shutdown or a lost lease, so `Worker.stopped_early` reads the row and
    decides which of those actually happened.
    """


def worker_id() -> str:
    """Stable enough to read in a lease, unique enough not to collide."""
    return f"{socket.gethostname()[:60]}:{os.getpid()}:{uuid4().hex[:8]}"


class Worker:
    def __init__(self, identity: str | None = None) -> None:
        self.identity = identity or worker_id()
        self.stopping = threading.Event()
        self._last_sweep = 0.0

    def stop(self, *_: object) -> None:
        self.stopping.set()

    def run_once(self) -> bool:
        """Claim and run at most one job. True when one was handled."""
        self.maybe_sweep()
        kinds = tuple(sorted(HANDLERS))
        job = jobs.claim(self.identity, kinds)
        if job is None:
            return False
        self.execute(job)
        return True

    def maybe_sweep(self) -> None:
        now = time.monotonic()
        if now - self._last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = now
        recovered = jobs.sweep_expired_leases()
        if recovered:
            logger.info("recovered %s expired lease(s)", recovered)

    def execute(self, job: jobs.Job) -> None:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            # Only reachable if HANDLERS changed between the claim query and
            # here. `release` hands the attempt back, so a kind with no handler
            # waits rather than burning its way to terminal failure.
            jobs.release(job.id, self.identity)
            return

        last_beat = 0.0

        def keep_going(progress: float | None = None) -> bool:
            """Heartbeat, and answer whether the work should continue."""
            nonlocal last_beat
            if self.stopping.is_set() or jobs.cancel_requested(job.id):
                return False
            now = time.monotonic()
            if progress is None and now - last_beat < jobs.HEARTBEAT_SECONDS:
                return True
            last_beat = now
            return jobs.heartbeat(job.id, self.identity, progress)

        try:
            handler(job, keep_going)
        except Cancelled:
            self.stopped_early(job)
            return
        except Exception:
            # A `StorageError` no longer chains its botocore cause, so this
            # traceback cannot carry an object key. The stored strings are
            # fixed and coach-safe either way.
            logger.exception("job %s failed", job.id)
            jobs.fail(
                job.id,
                self.identity,
                "handler_error",
                "Shoulder could not prepare this video. It will try again.",
            )
            return
        if self.stopping.is_set():
            # A handler that returned instead of raising after `keep_going()`
            # went false has not finished. Calling that a success would leave a
            # half-processed video marked ready.
            self.stopped_early(job)
            return
        if not jobs.succeed(job.id, self.identity):
            logger.warning("job %s finished without a live lease", job.id)

    def stopped_early(self, job: jobs.Job) -> None:
        """Record what actually stopped the work, and only that.

        Only an explicit cancellation is terminal. A shutdown or a lost lease
        returns the job to the queue, so a rolling deploy cannot leave a video
        `cancelled` that nobody asked to cancel.
        """
        if jobs.cancel_requested(job.id):
            if not jobs.cancelled(job.id, self.identity):
                logger.info("job %s lease was already gone at cancellation", job.id)
            return
        if not jobs.release(job.id, self.identity):
            # The lease had already expired; the sweeper owns the row now.
            logger.info("job %s lease was already gone when stopping", job.id)

    def run(self) -> None:
        logger.info("worker %s started; kinds=%s", self.identity, sorted(HANDLERS))
        while not self.stopping.is_set():
            try:
                if not self.run_once():
                    self.stopping.wait(IDLE_SLEEP_SECONDS)
            except jobs.QueueError:
                logger.exception("queue unavailable")
                self.stopping.wait(IDLE_SLEEP_SECONDS)
        logger.info("worker %s stopped", self.identity)


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=os.environ.get("WORKER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = Worker()
    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, worker.stop)
    worker.run()


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
