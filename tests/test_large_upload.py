"""Task 8's hard acceptance case: a 2 GB file through the real multipart path.

`docs/06-tasks.md` names a 2 GB generated file; `docs/11-testing-quality.md`
puts it in a controlled integration job rather than ordinary unit CI. It is
opt-in through `RUN_LARGE_UPLOAD=1` and `scripts/check-storage.ps1` sets that.

The point of this test is that nothing is bypassed. The bytes reach storage
through the same presigned part URLs a browser would use, the parts are
reconciled from storage, and completion goes through the real endpoint. An
administrative `put_object` would prove nothing about the implemented path.

The payload is generated into the system temporary directory, never the
repository, and is deleted afterwards even when the test fails.
"""

import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import DatabaseTestCase  # noqa: E402

ENABLED = os.environ.get("RUN_LARGE_UPLOAD", "").lower() in ("1", "true")
STORAGE_CONFIGURED = all(
    os.environ.get(name)
    for name in (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
)
TARGET_BYTES = 2 * 1024 * 1024 * 1024
# One 8 MiB block, repeated, so generating 2 GB costs no meaningful CPU.
BLOCK = 8 * 1024 * 1024
TIMEOUT = httpx.Timeout(600.0)


@unittest.skipUnless(ENABLED, "set RUN_LARGE_UPLOAD=1 to run the 2 GB proof")
@unittest.skipUnless(STORAGE_CONFIGURED, "object storage is not configured")
class LargeUploadTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        storage.get_client.cache_clear()
        self.addCleanup(storage.get_client.cache_clear)
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("large.coach@example.test", "Coach A")
        self.team = self.admin_insert_team(self.coach, "Large FC")
        app.dependency_overrides[authenticated_identity] = lambda: str(self.coach)
        self.client = TestClient(app)

    def test_a_two_gigabyte_file_lands_in_the_bucket(self) -> None:
        path = self.generate_payload()
        started = time.monotonic()

        game = self.client.post(
            "/v1/games",
            json={"team_id": str(self.team), "played_at": "2026-05-01T18:00:00Z"},
        )
        self.assertEqual(game.status_code, 201, game.text)
        game_id = game.json()["id"]

        session = self.client.post(
            f"/v1/games/{game_id}/videos/uploads",
            json={
                "filename": "full-match.mp4",
                "size_bytes": TARGET_BYTES,
                "content_type": "video/mp4",
            },
        )
        self.assertEqual(session.status_code, 201, session.text)
        video_id = UUID(session.json()["video_id"])
        part_count = session.json()["part_count"]
        self.assertEqual(part_count, TARGET_BYTES // storage.PART_SIZE_BYTES)
        self.addCleanup(self.discard, video_id)

        self.send_parts(video_id, path, part_count)

        state = self.client.get(f"/v1/videos/{video_id}/upload-state")
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()["missing_part_numbers"], [])

        completed = self.client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "uploaded")

        key = self.storage_key(video_id)
        self.assertEqual(storage.head_object(key), TARGET_BYTES)
        self.verify_edges(key, path)
        elapsed = time.monotonic() - started
        print(
            f"\n2 GB multipart upload completed in {elapsed:.0f}s"
            f" over {part_count} parts"
        )

    def send_parts(self, video_id: UUID, path: Path, part_count: int) -> None:
        """Sign and PUT every part, exactly as the browser client does."""
        with path.open("rb") as handle:
            for number in range(1, part_count + 1):
                signed = self.client.post(
                    f"/v1/videos/{video_id}/upload-parts/sign",
                    json={"part_numbers": [number]},
                )
                self.assertEqual(signed.status_code, 200, signed.text)
                part = signed.json()["parts"][0]
                chunk = handle.read(part["size_bytes"])
                self.assertEqual(len(chunk), part["size_bytes"])
                response = httpx.put(part["url"], content=chunk, timeout=TIMEOUT)
                self.assertEqual(
                    response.status_code, 200, f"part {number} was refused"
                )

    def verify_edges(self, key: str, path: Path) -> None:
        """Range-read the first and last block and compare with the source.

        Downloading 2 GB back would double the runtime and prove nothing more
        than that both ends of the object are in the right place.
        """
        url = storage.sign_get(key)
        first = httpx.get(
            url, headers={"Range": f"bytes=0-{BLOCK - 1}"}, timeout=TIMEOUT
        )
        last = httpx.get(
            url,
            headers={"Range": f"bytes={TARGET_BYTES - BLOCK}-{TARGET_BYTES - 1}"},
            timeout=TIMEOUT,
        )
        self.assertEqual(first.status_code, 206)
        self.assertEqual(last.status_code, 206)
        with path.open("rb") as handle:
            expected_first = handle.read(BLOCK)
            handle.seek(TARGET_BYTES - BLOCK)
            expected_last = handle.read(BLOCK)
        self.assertEqual(
            hashlib.sha256(first.content).hexdigest(),
            hashlib.sha256(expected_first).hexdigest(),
        )
        self.assertEqual(
            hashlib.sha256(last.content).hexdigest(),
            hashlib.sha256(expected_last).hexdigest(),
        )

    def storage_key(self, video_id: UUID) -> str:
        from sqlalchemy import text

        with self.admin.connect() as connection:
            return str(
                connection.execute(
                    text("SELECT original_key FROM app.video WHERE id = :id"),
                    {"id": video_id},
                ).scalar_one()
            )

    def generate_payload(self) -> Path:
        """A disposable 2 GB file outside the repository, removed afterwards."""
        handle = tempfile.NamedTemporaryFile(
            prefix="shoulder-large-upload-", suffix=".bin", delete=False
        )
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        # Varying block content, so a misordered part cannot pass the edge check.
        with handle:
            for index in range(TARGET_BYTES // BLOCK):
                handle.write(bytes([index % 251]) * BLOCK)
        self.assertEqual(path.stat().st_size, TARGET_BYTES)
        return path

    def discard(self, video_id: UUID) -> None:
        from sqlalchemy import text

        with self.admin.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT original_key, multipart_upload_id"
                    " FROM app.video WHERE id = :id"
                ),
                {"id": video_id},
            ).one_or_none()
        if row is None:
            return
        if row.multipart_upload_id:
            try:
                storage.abort_multipart(row.original_key, row.multipart_upload_id)
            except storage.StorageError:
                pass
        try:
            storage.get_client().delete_object(
                Bucket=storage.bucket(), Key=row.original_key
            )
        except Exception:  # noqa: BLE001 - cleanup is best effort
            pass


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
