"""Task 22 retention clocks and content-free worker behavior."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from uuid import uuid4

from services.api import storage
from services.worker import accounts, media, retention

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class RetentionClockTests(unittest.TestCase):
    def test_incomplete_upload_is_due_at_seven_days_not_one_tick_before(self) -> None:
        deadline = retention.incomplete_upload_deadline(NOW)
        self.assertEqual(deadline, NOW + timedelta(days=7))
        self.assertFalse(retention.due(deadline, deadline - timedelta(microseconds=1)))
        self.assertTrue(retention.due(deadline, deadline))

    def test_rejected_media_is_due_at_twenty_four_hours(self) -> None:
        deadline = retention.rejected_media_deadline(NOW)
        self.assertEqual(deadline, NOW + timedelta(hours=24))
        self.assertFalse(retention.due(deadline, deadline - timedelta(microseconds=1)))
        self.assertTrue(retention.due(deadline, deadline))

    def test_failed_processing_uses_earliest_persisted_clock(self) -> None:
        completed = NOW
        failed = NOW + timedelta(days=10)
        self.assertEqual(
            retention.failed_processing_deadline(completed, failed),
            completed + timedelta(days=14),
        )
        # A retry three days later cannot move either persisted timestamp.
        self.assertEqual(
            retention.failed_processing_deadline(completed, failed),
            completed + timedelta(days=14),
        )
        self.assertEqual(
            retention.failed_processing_deadline(completed, NOW + timedelta(days=1)),
            NOW + timedelta(days=8),
        )

    def test_source_and_season_clocks_are_absolute(self) -> None:
        self.assertEqual(retention.source_deadline(NOW), NOW + timedelta(days=90))
        self.assertEqual(retention.season_deadline(NOW), NOW + timedelta(days=365))

    def test_private_export_deadline_never_uses_a_retry_time(self) -> None:
        self.assertEqual(
            retention.private_export_deadline(NOW), NOW + timedelta(days=7)
        )


class ScratchSweepTests(unittest.TestCase):
    def test_only_known_old_scratch_directories_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            old = Path(root, "shoulder-media-old")
            fresh = Path(root, "shoulder-media-fresh")
            unrelated = Path(root, "other-old")
            for directory in (old, fresh, unrelated):
                directory.mkdir()
                (directory / "bytes").write_bytes(b"private")
            old_time = (NOW - timedelta(hours=24)).timestamp()
            fresh_time = (NOW - timedelta(hours=23)).timestamp()
            unrelated_time = (NOW - timedelta(days=2)).timestamp()
            import os

            os.utime(old, (old_time, old_time))
            os.utime(fresh, (fresh_time, fresh_time))
            os.utime(unrelated, (unrelated_time, unrelated_time))

            removed = retention.sweep_scratch(Path(root), now=NOW)

            self.assertEqual(removed, 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(unrelated.exists())


class ManifestObjectTests(unittest.TestCase):
    def test_object_failure_records_only_a_safe_code(self) -> None:
        manifest_id = uuid4()
        object_id = uuid4()
        secret_key = f"clips/{uuid4()}/1.mp4"
        with (
            patch.object(
                retention.storage, "delete_object", side_effect=Exception(secret_key)
            ),
            patch.object(retention, "record_object_failure") as failed,
        ):
            with self.assertRaises(retention.RetentionError):
                retention.delete_manifest_object(
                    job_id=manifest_id,
                    worker_id="retention-test",
                    object_id=object_id,
                    object_key=secret_key,
                    multipart_upload_id=None,
                )
        failed.assert_called_once_with(
            manifest_id, "retention-test", object_id, "storage_delete_failed"
        )
        self.assertNotIn(secret_key, str(failed.call_args))

    def test_suppression_record_is_content_free_and_deterministic(self) -> None:
        manifest_id = uuid4()
        team_id = uuid4()
        player_id = uuid4()
        with (
            patch.dict("os.environ", {"R2_BUCKET": "private"}, clear=False),
            patch.object(storage, "_call", return_value={}) as operation,
        ):
            storage.write_deletion_suppression(
                manifest_id=manifest_id,
                kind="player_erasure",
                team_id=team_id,
                target_id=player_id,
                requested_at=NOW.isoformat(),
                backup_expires_at=(NOW + timedelta(days=30)).isoformat(),
            )
        arguments = operation.call_args.kwargs
        self.assertEqual(arguments["Key"], storage.deletion_ledger_key(manifest_id))
        serialized = arguments["Body"].decode("utf-8")
        self.assertEqual(
            set(json.loads(serialized)),
            {
                "manifest_id",
                "kind",
                "team_id",
                "target_id",
                "requested_at",
                "backup_expires_at",
            },
        )
        for forbidden in ("name", "comment", "reflection", "filename", "email"):
            self.assertNotIn(forbidden, serialized.lower())


class AccountDeletionTests(unittest.TestCase):
    def test_auth_delete_is_exact_server_only_and_absence_is_success(self) -> None:
        user_id = uuid4()
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        with (
            patch.dict(
                "os.environ",
                {
                    "SUPABASE_URL": "http://127.0.0.1:54321/",
                    "SUPABASE_SECRET_KEY": "server-secret",
                },
                clear=False,
            ),
            patch.object(accounts, "urlopen", return_value=response) as opened,
        ):
            accounts.delete_auth_user(user_id)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(
            request.full_url,
            f"http://127.0.0.1:54321/auth/v1/admin/users/{user_id}",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer server-secret")

        absent = HTTPError(
            request.full_url, 404, "private response", Message(), BytesIO()
        )
        with (
            patch.dict(
                "os.environ",
                {
                    "SUPABASE_URL": "http://127.0.0.1:54321",
                    "SUPABASE_SECRET_KEY": "server-secret",
                },
                clear=False,
            ),
            patch.object(accounts, "urlopen", side_effect=absent),
        ):
            accounts.delete_auth_user(user_id)

    def test_auth_delete_failure_exposes_no_provider_content(self) -> None:
        user_id = uuid4()
        error = HTTPError("private-url", 500, "private response", Message(), BytesIO())
        with (
            patch.dict(
                "os.environ",
                {"SUPABASE_URL": "https://example.test", "SUPABASE_SECRET_KEY": "x"},
                clear=False,
            ),
            patch.object(accounts, "urlopen", side_effect=error),
        ):
            with self.assertRaisesRegex(
                accounts.AccountDeletionError, "auth account deletion failed"
            ) as caught:
                accounts.delete_auth_user(user_id)
        self.assertNotIn(str(user_id), str(caught.exception))


class LateDerivativeCleanupTests(unittest.TestCase):
    def test_cancelled_worker_removes_every_fixed_derivative_after_fence(self) -> None:
        video_id = uuid4()
        connection = MagicMock()
        connection.execute.return_value.scalar_one_or_none.return_value = (
            "deletion_pending"
        )
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        with (
            patch.object(media.jobs, "transaction", return_value=transaction),
            patch.object(media.storage, "delete_object") as delete_object,
        ):
            media._discard_video_derivatives_if_deleting(video_id)

        self.assertEqual(delete_object.call_count, 6)
        deleted = {call.args[0] for call in delete_object.call_args_list}
        self.assertEqual(
            deleted,
            {
                storage.playback_key(video_id),
                storage.thumbnail_index_key(video_id),
                *(storage.sprite_key(video_id, sheet) for sheet in range(4)),
            },
        )

    def test_live_video_derivatives_are_never_discarded(self) -> None:
        connection = MagicMock()
        connection.execute.return_value.scalar_one_or_none.return_value = "processing"
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        with (
            patch.object(media.jobs, "transaction", return_value=transaction),
            patch.object(media.storage, "delete_object") as delete_object,
        ):
            media._discard_video_derivatives_if_deleting(uuid4())
        delete_object.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
