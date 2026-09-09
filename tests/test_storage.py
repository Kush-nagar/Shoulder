"""Task 8 storage integration against real S3-compatible object storage.

These run against the Compose MinIO that `scripts/check-storage.ps1` starts,
which is the same S3 API surface R2 exposes. Presigned URLs are exercised with
a real HTTP client, because the only interesting question about a signed URL is
what an actual request to it can and cannot do.

`docs/11-testing-quality.md` names the boundary cases directly: a presigned PUT
cannot read, a presigned GET cannot write or address another object, and an
expired URL fails.
"""

import hashlib
import os
import time
import unittest
import uuid

import httpx

from services.api import storage

CONFIGURED = all(
    os.environ.get(name)
    for name in (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
)
REQUIRED = os.environ.get("REQUIRE_STORAGE_TESTS", "").lower() in ("1", "true")
TIMEOUT = httpx.Timeout(30.0)


class ConfigurationTests(unittest.TestCase):
    def test_storage_tests_are_configured_where_required(self) -> None:
        """A storage job must never pass by skipping the storage suite."""
        if REQUIRED:
            self.assertTrue(CONFIGURED, "R2_* storage environment is required")
            self.assertFalse(
                getattr(StorageTests, "__unittest_skip__", False),
                "the storage suite must run where storage is required",
            )


class PartPlanTests(unittest.TestCase):
    """Pure arithmetic; no storage needed, so these always run."""

    def test_part_count_rounds_up_to_cover_the_last_bytes(self) -> None:
        size = storage.PART_SIZE_BYTES
        self.assertEqual(storage.part_count(1), 1)
        self.assertEqual(storage.part_count(size), 1)
        self.assertEqual(storage.part_count(size + 1), 2)
        self.assertEqual(storage.part_count(size * 3), 3)

    def test_only_the_last_part_may_be_short(self) -> None:
        size = storage.PART_SIZE_BYTES * 2 + 17
        self.assertEqual(storage.expected_part_size(size, 1), storage.PART_SIZE_BYTES)
        self.assertEqual(storage.expected_part_size(size, 2), storage.PART_SIZE_BYTES)
        self.assertEqual(storage.expected_part_size(size, 3), 17)

    def test_a_part_outside_the_plan_is_refused(self) -> None:
        for number in (0, 2):
            with self.subTest(number=number):
                with self.assertRaises(storage.StorageError):
                    storage.expected_part_size(1024, number)

    def test_the_part_size_stays_above_the_S3_minimum(self) -> None:
        """Any part but the last is rejected below 5 MiB, so the plan must clear it."""
        self.assertGreaterEqual(storage.PART_SIZE_BYTES, storage.MIN_PART_SIZE_BYTES)

    def test_the_maximum_upload_and_part_ceiling_agree(self) -> None:
        self.assertEqual(
            storage.MAX_PARTS, storage.MAX_UPLOAD_BYTES // storage.PART_SIZE_BYTES
        )
        self.assertEqual(
            storage.part_count(storage.MAX_UPLOAD_BYTES), storage.MAX_PARTS
        )

    def test_a_key_is_built_from_the_video_id_and_an_allowlisted_extension(
        self,
    ) -> None:
        video_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
        self.assertEqual(
            storage.original_key(video_id, "mov"),
            f"originals/{video_id}/source.mov",
        )

    def test_a_key_cannot_be_built_from_an_unknown_extension(self) -> None:
        for extension in ("exe", "", "mp4/../../etc", "MP4"):
            with self.subTest(extension=extension):
                with self.assertRaises(storage.StorageError):
                    storage.original_key(uuid.uuid4(), extension)


@unittest.skipUnless(CONFIGURED, "object storage is not configured")
class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        storage.get_client.cache_clear()
        self.addCleanup(storage.get_client.cache_clear)
        self.video_id = uuid.uuid4()
        self.key = storage.original_key(self.video_id, "mp4")
        self.uploads: list[tuple[str, str]] = []
        self.addCleanup(self.discard_uploads)

    def discard_uploads(self) -> None:
        for key, upload_id in self.uploads:
            try:
                storage.abort_multipart(key, upload_id)
            except storage.StorageError:
                pass

    def start(self, key: str | None = None) -> tuple[str, str]:
        target = key or self.key
        upload_id = storage.create_multipart(target, "video/mp4")
        self.uploads.append((target, upload_id))
        return target, upload_id

    def put(self, url: str, body: bytes) -> httpx.Response:
        return httpx.put(url, content=body, timeout=TIMEOUT)

    # --- the happy path ---------------------------------------------------

    def test_a_multipart_upload_completes_and_the_object_matches(self) -> None:
        """Two real parts, signed individually, land as one object."""
        key, upload_id = self.start()
        first = b"a" * storage.PART_SIZE_BYTES
        second = b"b" * 1024
        for number, body in ((1, first), (2, second)):
            response = self.put(storage.sign_part(key, upload_id, number), body)
            self.assertEqual(response.status_code, 200, "a signed part PUT failed")

        parts = storage.list_parts(key, upload_id)
        self.assertEqual([part.part_number for part in parts], [1, 2])
        self.assertEqual([part.size_bytes for part in parts], [len(first), len(second)])
        storage.complete_multipart(key, upload_id, parts)
        self.uploads.clear()
        self.addCleanup(self.delete_object, key)

        self.assertEqual(storage.head_object(key), len(first) + len(second))
        fetched = httpx.get(storage.sign_get(key), timeout=TIMEOUT)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(
            hashlib.sha256(fetched.content).hexdigest(),
            hashlib.sha256(first + second).hexdigest(),
        )

    def delete_object(self, key: str) -> None:
        storage.get_client().delete_object(Bucket=storage.bucket(), Key=key)

    def test_an_interrupted_upload_keeps_the_parts_it_already_has(self) -> None:
        """The resume contract: a missing part is the only thing left to send."""
        key, upload_id = self.start()
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        # Part 2 is never sent, as if the connection dropped here.
        parts = storage.list_parts(key, upload_id)
        self.assertEqual([part.part_number for part in parts], [1])

    def test_an_aborted_upload_leaves_no_object_and_no_parts(self) -> None:
        key, upload_id = self.start()
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        storage.abort_multipart(key, upload_id)
        self.uploads.clear()
        self.assertIsNone(storage.head_object(key))
        with self.assertRaises(storage.StorageError):
            storage.list_parts(key, upload_id)

    def test_aborting_twice_is_safe(self) -> None:
        """A coach's abort and the abandoned-upload sweeper can race."""
        key, upload_id = self.start()
        storage.abort_multipart(key, upload_id)
        storage.abort_multipart(key, upload_id)
        self.uploads.clear()

    def test_completing_an_aborted_upload_fails(self) -> None:
        key, upload_id = self.start()
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        parts = storage.list_parts(key, upload_id)
        storage.abort_multipart(key, upload_id)
        self.uploads.clear()
        with self.assertRaises(storage.StorageError):
            storage.complete_multipart(key, upload_id, parts)

    def test_completing_with_a_missing_part_fails(self) -> None:
        """A gap in the part list can never become a whole object."""
        key, upload_id = self.start()
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        self.put(storage.sign_part(key, upload_id, 3), b"c" * 512)
        parts = storage.list_parts(key, upload_id)
        invented = [
            *parts,
            storage.StoredPart(part_number=2, etag="0" * 32, size_bytes=512),
        ]
        with self.assertRaises(storage.StorageError):
            storage.complete_multipart(
                key, upload_id, sorted(invented, key=lambda part: part.part_number)
            )

    def test_a_second_completion_of_the_same_upload_fails(self) -> None:
        """The API's idempotency comes from its own row, not from a second call."""
        key, upload_id = self.start()
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        parts = storage.list_parts(key, upload_id)
        storage.complete_multipart(key, upload_id, parts)
        self.uploads.clear()
        self.addCleanup(self.delete_object, key)
        with self.assertRaises(storage.StorageError):
            storage.complete_multipart(key, upload_id, parts)

    # --- what a signed URL cannot do --------------------------------------

    def test_a_signed_part_url_cannot_write_a_different_part(self) -> None:
        key, upload_id = self.start()
        url = storage.sign_part(key, upload_id, 1)
        response = self.put(
            url.replace("partNumber=1", "partNumber=2"),
            b"a" * storage.PART_SIZE_BYTES,
        )
        self.assertEqual(response.status_code, 403)

    def test_a_signed_part_url_cannot_address_another_object(self) -> None:
        key, upload_id = self.start()
        other = storage.original_key(uuid.uuid4(), "mp4")
        url = storage.sign_part(key, upload_id, 1)
        response = self.put(url.replace(key, other), b"a" * storage.PART_SIZE_BYTES)
        self.assertEqual(response.status_code, 403)

    def test_a_signed_part_url_cannot_read(self) -> None:
        """A PUT signature does not authorize a GET of the same object."""
        key, upload_id = self.start()
        url = storage.sign_part(key, upload_id, 1)
        self.put(url, b"a" * storage.PART_SIZE_BYTES)
        response = httpx.get(url, timeout=TIMEOUT)
        self.assertEqual(response.status_code, 403)

    def test_a_signed_get_cannot_write(self) -> None:
        key = self.completed_object()
        url = storage.sign_get(key)
        self.assertEqual(self.put(url, b"overwritten").status_code, 403)
        self.assertEqual(storage.head_object(key), storage.PART_SIZE_BYTES)

    def test_a_signed_get_cannot_address_another_object(self) -> None:
        key = self.completed_object()
        other = self.completed_object()
        response = httpx.get(storage.sign_get(key).replace(key, other), timeout=TIMEOUT)
        self.assertEqual(response.status_code, 403)

    def test_a_signed_get_expires(self) -> None:
        key = self.completed_object()
        url = storage.sign_get(key, seconds=1)
        time.sleep(2)
        self.assertEqual(httpx.get(url, timeout=TIMEOUT).status_code, 403)

    def test_a_signing_lifetime_beyond_the_coach_ceiling_is_refused(self) -> None:
        """`docs/10-security-privacy.md` caps coach playback at fifteen minutes."""
        for seconds in (0, storage.GET_URL_SECONDS + 1, 86400):
            with self.subTest(seconds=seconds):
                with self.assertRaises(storage.StorageError):
                    storage.sign_get("originals/x/source.mp4", seconds=seconds)

    def test_an_unauthenticated_request_cannot_read_the_bucket(self) -> None:
        """The bucket is private; only a signature opens one object."""
        key = self.completed_object()
        endpoint = os.environ["R2_ENDPOINT_URL"].rstrip("/")
        direct = httpx.get(f"{endpoint}/{storage.bucket()}/{key}", timeout=TIMEOUT)
        self.assertIn(direct.status_code, (401, 403))

    def test_cors_answers_the_configured_origin_and_no_other(self) -> None:
        """The browser PUTs directly, so the bucket's CORS list is load-bearing.

        `docs/02-architecture.md`: CORS lists only the production and local app
        origins. Locally that list is `MINIO_API_CORS_ALLOW_ORIGIN` in
        `infra/compose.yaml`; on R2 it is `infra/r2-cors.json`.
        """
        key, upload_id = self.start()
        url = storage.sign_part(key, upload_id, 1)
        allowed = httpx.request(
            "OPTIONS",
            url,
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "PUT",
            },
            timeout=TIMEOUT,
        )
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:3000",
        )
        refused = httpx.request(
            "OPTIONS",
            url,
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "PUT",
            },
            timeout=TIMEOUT,
        )
        self.assertNotIn(
            refused.headers.get("access-control-allow-origin"),
            ("https://evil.example", "*"),
        )

    def test_head_object_reports_absence_rather_than_raising(self) -> None:
        self.assertIsNone(storage.head_object(f"originals/{uuid.uuid4()}/source.mp4"))

    def completed_object(self) -> str:
        """One finished single-part object, cleaned up after the test."""
        key, upload_id = self.start(storage.original_key(uuid.uuid4(), "mp4"))
        self.put(storage.sign_part(key, upload_id, 1), b"a" * storage.PART_SIZE_BYTES)
        storage.complete_multipart(key, upload_id, storage.list_parts(key, upload_id))
        self.uploads = [entry for entry in self.uploads if entry[1] != upload_id]
        self.addCleanup(self.delete_object, key)
        return key


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
