"""Retention scheduling, object deletion, and deletion verification.

All stored/logged failures use fixed codes. Object keys remain confined to the
restricted manifest and storage calls; they never enter exception messages.
"""

import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from services.api import storage as storage
from services.worker import accounts as accounts
from services.worker import jobs
from services.worker.jobs import Cancelled

INCOMPLETE_UPLOAD_RETENTION = timedelta(days=7)
REJECTED_MEDIA_RETENTION = timedelta(hours=24)
FAILED_PROCESSING_RETENTION = timedelta(days=7)
UNPROCESSED_UPLOAD_RETENTION = timedelta(days=14)
SOURCE_RETENTION = timedelta(days=90)
SEASON_RETENTION = timedelta(days=365)
PRIVATE_EXPORT_RETENTION = timedelta(days=7)
SCRATCH_RETENTION = timedelta(hours=24)


class RetentionError(Exception):
    """A deletion step failed without exposing its target or provider detail."""


def due(deadline: datetime, now: datetime) -> bool:
    """Deadlines are inclusive: access ends exactly at the persisted instant."""
    return now >= deadline


def incomplete_upload_deadline(created_at: datetime) -> datetime:
    return created_at + INCOMPLETE_UPLOAD_RETENTION


def rejected_media_deadline(rejected_at: datetime) -> datetime:
    return rejected_at + REJECTED_MEDIA_RETENTION


def failed_processing_deadline(
    upload_completed_at: datetime, first_terminal_failure_at: datetime
) -> datetime:
    return min(
        first_terminal_failure_at + FAILED_PROCESSING_RETENTION,
        upload_completed_at + UNPROCESSED_UPLOAD_RETENTION,
        source_deadline(upload_completed_at),
    )


def source_deadline(upload_completed_at: datetime) -> datetime:
    return upload_completed_at + SOURCE_RETENTION


def season_deadline(season_end_at: datetime) -> datetime:
    return season_end_at + SEASON_RETENTION


def private_export_deadline(first_terminal_at: datetime) -> datetime:
    return first_terminal_at + PRIVATE_EXPORT_RETENTION


def sweep_scratch(root: Path | None = None, *, now: datetime) -> int:
    """Remove only expired task directories under the resolved temp root."""
    temp_root = (root or Path(tempfile.gettempdir())).resolve()
    removed = 0
    cutoff = now.timestamp() - SCRATCH_RETENTION.total_seconds()
    for candidate in temp_root.glob("shoulder-media-*"):
        resolved = candidate.resolve()
        if resolved.parent != temp_root or not resolved.is_dir():
            continue
        try:
            expired = resolved.stat().st_mtime <= cutoff
        except FileNotFoundError:
            continue
        if expired:
            shutil.rmtree(resolved)
            removed += 1
    return removed


def record_object_failure(
    job_id: UUID, worker_id: str, object_id: UUID, error_code: str
) -> None:
    """Persist one allowlisted failure code; never accept provider text."""
    if error_code not in {"storage_delete_failed", "storage_verify_failed"}:
        raise ValueError("unsupported deletion failure code")
    with jobs.transaction() as connection:
        connection.execute(
            text(
                "SELECT private.fail_deletion_object("
                ":job_id, :worker_id, :object_id, :error_code)"
            ),
            {
                "job_id": str(job_id),
                "worker_id": worker_id,
                "object_id": str(object_id),
                "error_code": error_code,
            },
        )


def delete_manifest_object(
    *,
    job_id: UUID,
    worker_id: str,
    object_id: UUID,
    object_key: str,
    multipart_upload_id: str | None,
) -> None:
    """Idempotently abort/delete/verify one exact manifest object."""
    try:
        if multipart_upload_id is not None:
            storage.abort_multipart(object_key, multipart_upload_id)
        storage.delete_object(object_key)
        if storage.head_object(object_key) is not None:
            record_object_failure(job_id, worker_id, object_id, "storage_verify_failed")
            raise RetentionError("stored object absence could not be verified")
    except RetentionError:
        raise
    except Exception:
        record_object_failure(job_id, worker_id, object_id, "storage_delete_failed")
        raise RetentionError("stored object deletion failed") from None


def enqueue_due_sweep(now: datetime | None = None) -> UUID | None:
    """Create one durable sweep job per UTC hour."""
    with jobs.transaction() as connection:
        if now is None:
            value = connection.execute(
                text("SELECT private.enqueue_retention_sweep()")
            ).scalar_one_or_none()
        else:
            value = connection.execute(
                text("SELECT private.enqueue_retention_sweep(:now)"), {"now": now}
            ).scalar_one_or_none()
    return UUID(str(value)) if value is not None else None


def retention_sweep_job(
    job: jobs.Job, keep_going: Callable[[float | None], bool]
) -> None:
    if not keep_going(0.0):
        raise Cancelled
    with jobs.transaction() as connection:
        expired = connection.execute(
            text(
                "SELECT manifest_id FROM private.expired_deletion_ledgers("
                ":job_id, :worker_id)"
            ),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).all()
    for row in expired:
        if not keep_going(None):
            raise Cancelled
        try:
            key = storage.deletion_ledger_key(UUID(str(row.manifest_id)))
            storage.delete_object(key)
            if storage.head_object(key) is not None:
                raise RetentionError("suppression record absence was not verified")
        except Exception:
            with jobs.transaction() as connection:
                connection.execute(
                    text(
                        "SELECT private.fail_deletion_ledger_cleanup("
                        ":job_id, :worker_id, :manifest_id)"
                    ),
                    {
                        "job_id": str(job.id),
                        "worker_id": job.locked_by,
                        "manifest_id": str(row.manifest_id),
                    },
                )
            raise RetentionError("suppression record deletion failed") from None
        with jobs.transaction() as connection:
            connection.execute(
                text(
                    "SELECT private.complete_deletion_ledger_cleanup("
                    ":job_id, :worker_id, :manifest_id)"
                ),
                {
                    "job_id": str(job.id),
                    "worker_id": job.locked_by,
                    "manifest_id": str(row.manifest_id),
                },
            )
    with jobs.transaction() as connection:
        connection.execute(
            text("SELECT private.prepare_retention_sweep(:job_id, :worker_id)"),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        )
    # After the coach sweep, so a practice storage failure cannot delay it.
    purge_practice_videos(job, keep_going)
    if not keep_going(1.0):
        raise Cancelled


def purge_practice_videos(
    job: jobs.Job, keep_going: Callable[[float | None], bool]
) -> int:
    """Delete expired player practice objects, verify absence, then rows."""
    with jobs.transaction() as connection:
        expired = connection.execute(
            text(
                "SELECT id, object_key FROM private.expired_practice_videos("
                ":job_id, :worker_id)"
            ),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).all()
    for row in expired:
        if not keep_going(None):
            raise Cancelled
        try:
            storage.delete_object(row.object_key)
            if storage.head_object(row.object_key) is not None:
                raise RetentionError("practice object absence was not verified")
        except Exception:
            # The row stays, so the next hourly sweep retries this object.
            raise RetentionError("practice object deletion failed") from None
        with jobs.transaction() as connection:
            connection.execute(
                text("SELECT private.purge_practice_video(:job_id, :worker_id, :id)"),
                {"job_id": str(job.id), "worker_id": job.locked_by, "id": str(row.id)},
            )
    return len(expired)


def _manifest_objects(job: jobs.Job) -> tuple[UUID, list[Any]]:
    if job.deletion_manifest_id is None:
        raise RetentionError("deletion job has no manifest")
    with jobs.transaction() as connection:
        rows = connection.execute(
            text(
                "SELECT object_id, object_key, multipart_upload_id "
                "FROM private.deletion_manifest_input(:job_id, :worker_id)"
            ),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).all()
    return job.deletion_manifest_id, list(rows)


def deletion_job(job: jobs.Job, keep_going: Callable[[float | None], bool]) -> None:
    manifest_id, objects = _manifest_objects(job)
    with jobs.transaction() as connection:
        suppression = connection.execute(
            text(
                "SELECT * FROM private.deletion_suppression_record(:job_id, :worker_id)"
            ),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).one_or_none()
    if suppression is not None:
        try:
            storage.write_deletion_suppression(
                manifest_id=UUID(str(suppression.manifest_id)),
                kind=str(suppression.kind),
                team_id=UUID(str(suppression.team_id)),
                target_id=(
                    UUID(str(suppression.target_id))
                    if suppression.target_id is not None
                    else None
                ),
                requested_at=suppression.requested_at.isoformat(),
                backup_expires_at=suppression.backup_expires_at.isoformat(),
            )
        except storage.StorageError:
            with jobs.transaction() as connection:
                connection.execute(
                    text(
                        "SELECT private.fail_deletion_suppression(:job_id, :worker_id)"
                    ),
                    {"job_id": str(job.id), "worker_id": job.locked_by},
                )
            raise RetentionError("suppression record could not be persisted") from None
    total = max(len(objects), 1)
    for index, item in enumerate(objects):
        if not keep_going(index / total):
            raise Cancelled
        delete_manifest_object(
            job_id=job.id,
            worker_id=job.locked_by,
            object_id=item.object_id,
            object_key=item.object_key,
            multipart_upload_id=item.multipart_upload_id,
        )
        with jobs.transaction() as connection:
            connection.execute(
                text(
                    "SELECT private.complete_deletion_object("
                    ":job_id, :worker_id, :object_id)"
                ),
                {
                    "job_id": str(job.id),
                    "worker_id": job.locked_by,
                    "object_id": str(item.object_id),
                },
            )
    if not keep_going(0.99):
        raise Cancelled
    if job.kind == "player_data_delete":
        with jobs.transaction() as connection:
            auth_account = connection.execute(
                text("SELECT private.deletion_auth_account(:job_id, :worker_id)"),
                {"job_id": str(job.id), "worker_id": job.locked_by},
            ).scalar_one_or_none()
        if auth_account is not None:
            try:
                accounts.delete_auth_user(UUID(str(auth_account)))
            except accounts.AccountDeletionError:
                with jobs.transaction() as connection:
                    connection.execute(
                        text("SELECT private.fail_deletion_auth(:job_id, :worker_id)"),
                        {"job_id": str(job.id), "worker_id": job.locked_by},
                    )
                raise RetentionError("auth account deletion failed") from None
    with jobs.transaction() as connection:
        finalized = connection.execute(
            text("SELECT private.finalize_deletion_manifest(:job_id, :worker_id)"),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).scalar_one()
    if not finalized:
        raise RetentionError("deletion manifest could not be finalized")


HANDLERS: dict[str, Any] = {
    "retention_sweep": retention_sweep_job,
    "video_retention_delete": deletion_job,
    "player_data_delete": deletion_job,
}
