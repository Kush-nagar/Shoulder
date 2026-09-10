"""The durable Postgres work queue.

`docs/02-architecture.md`: one table and `FOR UPDATE SKIP LOCKED`. No Redis, no
broker, no in-process queue, and no state that only exists inside a worker.

Every function here is one short transaction. A claim never holds a row lock
across the work itself: the lock exists only long enough to move the row to
`running` and stamp the lease, after which the lease and its heartbeat are what
keep a second worker away. That is the difference between a queue that survives
a crash and one that stalls behind a long transaction.

This module connects as `shoulder_worker` (ADR 0018). It has no user identity,
so nothing here reads or sets `app.user_id`.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

# A lease is stale once its heartbeat is older than this. It must comfortably
# exceed the heartbeat interval, or a busy worker's live job gets requeued.
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 20
# Exponential with a ceiling: 30s, 60s, 120s, 240s, 300s, 300s...
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 300


class QueueError(Exception):
    """The queue could not be reached or answered."""


@dataclass(frozen=True)
class Job:
    """One claimed job. `attempts` already counts this attempt."""

    id: UUID
    kind: str
    video_id: UUID | None
    attempts: int
    max_attempts: int
    payload: dict[str, Any]


def backoff_seconds(attempts: int) -> int:
    """Delay before the next attempt. Moves `available_at`, never `created_at`.

    `fail` and `sweep_expired_leases` compute this in SQL so the value is read
    from the row being updated. This is the same curve in Python, and
    `tests/test_database_queue.py` asserts the two agree.
    """
    if attempts < 1:
        return BACKOFF_BASE_SECONDS
    growth = int(2 ** (attempts - 1))
    return min(BACKOFF_BASE_SECONDS * growth, BACKOFF_MAX_SECONDS)


@lru_cache
def get_engine() -> Engine:
    url = os.environ.get("WORKER_DATABASE_URL")
    if not url:
        raise QueueError("the worker database URL is not configured")
    # A small pool: a worker holds one connection per short transaction.
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


@contextmanager
def transaction() -> Iterator[Connection]:
    with get_engine().connect() as connection, connection.begin():
        yield connection


def claim(worker_id: str, kinds: tuple[str, ...]) -> Job | None:
    """Claim one eligible job, or return None.

    `FOR UPDATE SKIP LOCKED` is what makes two workers safe: the second
    transaction skips the row the first has locked instead of waiting on it,
    so neither blocks and neither sees the same row.

    `kinds` is the caller's registered handler set. A worker never claims work
    it cannot run, so an unimplemented kind waits in the queue rather than
    burning an attempt and reaching terminal failure.

    The `attempts < max_attempts` guard is belt and braces: nothing should put
    an exhausted row back in `queued`, and if anything ever did, claiming it
    would violate `processing_job_attempts_bounded` and kill the worker rather
    than fail the job.
    """
    if not kinds:
        return None
    with transaction() as connection:
        candidate = connection.execute(
            text("""
                SELECT id FROM app.processing_job
                WHERE status = 'queued'
                  AND available_at <= now()
                  AND attempts < max_attempts
                  AND kind = ANY(:kinds)
                ORDER BY available_at, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            """),
            {"kinds": list(kinds)},
        ).scalar_one_or_none()
        if candidate is None:
            return None
        row = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = 'running',
                    attempts = attempts + 1,
                    locked_at = now(),
                    locked_by = :worker_id,
                    heartbeat_at = now(),
                    started_at = coalesce(started_at, now()),
                    error_code = NULL,
                    error_message = NULL
                WHERE id = :id AND status = 'queued'
                RETURNING id, kind, video_id, attempts, max_attempts, payload
            """),
            {"id": candidate, "worker_id": worker_id},
        ).one()
    return Job(
        id=row.id,
        kind=row.kind,
        video_id=row.video_id,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        payload=dict(row.payload),
    )


def heartbeat(job_id: UUID, worker_id: str, progress: float | None = None) -> bool:
    """Refresh a lease this worker still holds.

    Returns False when the lease is gone, which is the signal to stop working:
    a sweeper has already requeued the job and another worker may hold it. The
    `locked_by` predicate is what stops a worker from stealing its own job back
    after losing it.
    """
    with transaction() as connection:
        updated = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    heartbeat_at = now(),
                    progress = coalesce(cast(:progress AS numeric), progress)
                WHERE id = :id AND status = 'running' AND locked_by = :worker_id
            """),
            {"id": str(job_id), "worker_id": worker_id, "progress": progress},
        ).rowcount
    return updated == 1


def cancel_requested(job_id: UUID) -> bool:
    """Cooperative cancellation: the worker asks between stages."""
    with transaction() as connection:
        requested = connection.execute(
            text(
                "SELECT cancel_requested_at IS NOT NULL FROM app.processing_job"
                " WHERE id = :id"
            ),
            {"id": str(job_id)},
        ).scalar_one_or_none()
    return bool(requested)


def request_cancel(connection: Connection, job_id: UUID) -> int:
    """Ask a job to stop. Only a nonterminal job can be asked."""
    return connection.execute(
        text("""
            UPDATE app.processing_job SET cancel_requested_at = now()
            WHERE id = :id AND status IN ('queued', 'running')
        """),
        {"id": str(job_id)},
    ).rowcount


def succeed(job_id: UUID, worker_id: str) -> bool:
    with transaction() as connection:
        updated = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = 'succeeded', progress = 1, finished_at = now(),
                    locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
                WHERE id = :id AND status = 'running' AND locked_by = :worker_id
            """),
            {"id": str(job_id), "worker_id": worker_id},
        ).rowcount
    return updated == 1


def cancelled(job_id: UUID, worker_id: str) -> bool:
    with transaction() as connection:
        updated = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = 'cancelled', finished_at = now(),
                    locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
                WHERE id = :id AND status = 'running' AND locked_by = :worker_id
            """),
            {"id": str(job_id), "worker_id": worker_id},
        ).rowcount
    return updated == 1


def release(job_id: UUID, worker_id: str) -> bool:
    """Return a claimed job to the queue and hand its attempt back.

    Used when the worker stops rather than the work failing: a shutdown in the
    middle of a job is not a terminal outcome, and marking it `cancelled` would
    strand a video nobody asked to cancel.

    `attempts` counts attempts that reached a conclusion, so a release gives
    one back. Keeping it would strand the job on its last claim: the row would
    return to `queued` with `attempts = max_attempts`, and the next claim's
    increment would violate `processing_job_attempts_bounded`, leaving it
    queued and permanently unclaimable. A worker that dies instead of releasing
    is still bounded, because `sweep_expired_leases` keeps that attempt.
    """
    with transaction() as connection:
        updated = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = 'queued',
                    attempts = greatest(attempts - 1, 0),
                    available_at = now() + make_interval(secs => :base),
                    locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
                WHERE id = :id AND status = 'running' AND locked_by = :worker_id
            """),
            {
                "id": str(job_id),
                "worker_id": worker_id,
                "base": float(BACKOFF_BASE_SECONDS),
            },
        ).rowcount
    return updated == 1


def fail(
    job_id: UUID,
    worker_id: str,
    error_code: str,
    error_message: str,
    retryable: bool = True,
) -> bool:
    """Requeue with backoff while attempts remain; otherwise fail terminally.

    `error_code` and `error_message` are coach-safe strings chosen by the
    caller. `docs/10-security-privacy.md` forbids a provider message, a key, or
    a signed URL here, so nothing derived from an exception is stored.
    """
    with transaction() as connection:
        updated = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = CASE
                        WHEN :retryable AND attempts < max_attempts
                        THEN 'queued' ELSE 'failed'
                    END,
                    available_at = CASE
                        WHEN :retryable AND attempts < max_attempts
                        THEN now() + make_interval(
                            secs => least(:base * 2 ^ (attempts - 1), :ceiling)
                        )
                        ELSE available_at
                    END,
                    finished_at = CASE
                        WHEN :retryable AND attempts < max_attempts
                        THEN NULL ELSE now()
                    END,
                    error_code = :error_code,
                    error_message = :error_message,
                    locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
                WHERE id = :id AND status = 'running' AND locked_by = :worker_id
            """),
            {
                "id": str(job_id),
                "worker_id": worker_id,
                "retryable": retryable,
                "base": float(BACKOFF_BASE_SECONDS),
                "ceiling": float(BACKOFF_MAX_SECONDS),
                "error_code": error_code[:60],
                "error_message": error_message[:300],
            },
        ).rowcount
    return updated == 1


def sweep_expired_leases(lease_seconds: int = LEASE_SECONDS) -> int:
    """Recover jobs whose worker stopped heartbeating.

    A job with attempts left returns to `queued` on the same curve `fail` uses,
    so a worker that crashes is not retried faster than one that reported an
    error. One that has exhausted its attempts becomes `failed`, so a crash
    loop ends in a state a coach can be told about instead of cycling forever.
    """
    with transaction() as connection:
        recovered = connection.execute(
            text("""
                UPDATE app.processing_job SET
                    status = CASE
                        WHEN attempts < max_attempts THEN 'queued' ELSE 'failed'
                    END,
                    available_at = CASE
                        WHEN attempts < max_attempts
                        THEN now() + make_interval(
                            secs => least(:base * 2 ^ (attempts - 1), :ceiling)
                        )
                        ELSE available_at
                    END,
                    finished_at = CASE
                        WHEN attempts < max_attempts THEN NULL ELSE now()
                    END,
                    -- A requeued job carries no error. The Block 03 coach
                    -- surface reads these columns, and "waiting to retry" must
                    -- not read there as "this failed".
                    error_code = CASE
                        WHEN attempts < max_attempts THEN NULL ELSE 'lease_expired'
                    END,
                    error_message = CASE
                        WHEN attempts < max_attempts THEN NULL
                        ELSE 'Shoulder stopped preparing this video and could'
                             || ' not finish it.'
                    END,
                    locked_at = NULL, locked_by = NULL, heartbeat_at = NULL
                WHERE status = 'running'
                  AND heartbeat_at < now() - make_interval(secs => :lease)
            """),
            {
                "lease": float(lease_seconds),
                "base": float(BACKOFF_BASE_SECONDS),
                "ceiling": float(BACKOFF_MAX_SECONDS),
            },
        ).rowcount
    return int(recovered)


def lease_interval() -> timedelta:
    return timedelta(seconds=LEASE_SECONDS)
