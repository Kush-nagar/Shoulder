"""Project 02 game and upload routes against the real runtime role and storage.

These run through `shoulder_api`, the same `NOBYPASSRLS` login production uses,
and against the real S3 API, so a 403, a 404, or a resumed part is the
database's and storage's answer rather than the service's opinion. Token
verification itself is covered by `tests/test_auth.py`; the verified subject is
injected so the database-derived answer is what is under test.

Requires migration `0005` plus the URLs and `R2_*` environment that
`scripts/check-storage.ps1` provides.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import (  # noqa: E402
    ADMIN_URL,
    REQUIRED,
    RUNTIME_URL,
    DatabaseTestCase,
)

STORAGE_CONFIGURED = all(
    os.environ.get(name)
    for name in (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
)
STORAGE_REQUIRED = os.environ.get("REQUIRE_STORAGE_TESTS", "").lower() in ("1", "true")
TIMEOUT = httpx.Timeout(30.0)
# One part, comfortably under the 32 MiB part size, so most cases stay quick.
SMALL = 1024 * 1024


class ConfigurationTests(unittest.TestCase):
    def test_the_upload_suite_runs_where_storage_is_required(self) -> None:
        if STORAGE_REQUIRED:
            self.assertTrue(ADMIN_URL and RUNTIME_URL, "database URLs are required")
            self.assertTrue(STORAGE_CONFIGURED, "R2_* storage environment is required")
            self.assertFalse(
                getattr(UploadApiTests, "__unittest_skip__", False),
                "the upload API suite must run where storage is required",
            )
        if REQUIRED and not STORAGE_CONFIGURED:
            # The database job runs without MinIO; say so rather than silently
            # reporting a green run that never touched an upload.
            self.skipTest("storage is not configured for this job")


@unittest.skipUnless(STORAGE_CONFIGURED, "object storage is not configured")
class UploadApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        storage.get_client.cache_clear()
        self.addCleanup(storage.get_client.cache_clear)
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(self.discard_objects)
        self.objects: list[str] = []

        self.coach = self.create_auth_user("upload.coach@example.test", "Coach A")
        self.other_coach = self.create_auth_user("upload.coach.b@example.test", "B")
        self.player = self.create_auth_user("upload.player@example.test", "Player A1")
        self.team = self.admin_insert_team(self.coach, "Upload FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.player_row = self.admin_insert_player(
            self.team, user_id=self.player, display_name="Player A1", jersey_number=7
        )
        self.add_membership(self.team, self.player, "player")

    def add_membership(self, team_id: UUID, user_id: UUID, role: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, :role)
                """),
                {"team": team_id, "user": user_id, "role": role},
            )

    def discard_objects(self) -> None:
        """Remove whatever this test actually stored, completed or not."""
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT v.original_key, v.multipart_upload_id FROM app.video v
                    JOIN app.game g ON g.id = v.game_id
                    WHERE g.team_id = ANY(:teams)
                """),
                {"teams": [self.team, self.other_team]},
            ).all()
        client = storage.get_client()
        for row in rows:
            if row.multipart_upload_id:
                try:
                    storage.abort_multipart(row.original_key, row.multipart_upload_id)
                except storage.StorageError:
                    pass
            try:
                client.delete_object(Bucket=storage.bucket(), Key=row.original_key)
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def create_game(self, client: TestClient, team_id: UUID | None = None) -> UUID:
        response = client.post(
            "/v1/games",
            json={
                "team_id": str(team_id or self.team),
                "played_at": "2026-05-01T18:00:00Z",
                "opponent": "Visitors",
                "kind": "match",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return UUID(response.json()["id"])

    def start_upload(
        self, client: TestClient, game_id: UUID, size: int = SMALL, **overrides: Any
    ) -> dict[str, Any]:
        body = {
            "filename": "match.mp4",
            "size_bytes": size,
            "content_type": "video/mp4",
            **overrides,
        }
        response = client.post(f"/v1/games/{game_id}/videos/uploads", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return dict(response.json())

    def upload_part(
        self, client: TestClient, video_id: UUID, number: int, body: bytes
    ) -> None:
        signed = client.post(
            f"/v1/videos/{video_id}/upload-parts/sign",
            json={"part_numbers": [number]},
        )
        self.assertEqual(signed.status_code, 200, signed.text)
        part = signed.json()["parts"][0]
        self.assertEqual(part["size_bytes"], len(body))
        put = httpx.put(part["url"], content=body, timeout=TIMEOUT)
        self.assertEqual(put.status_code, 200, "the browser PUT was refused")

    def video_row(self, video_id: UUID) -> Any:
        with self.admin.connect() as connection:
            return connection.execute(
                text("SELECT * FROM app.video WHERE id = :id"), {"id": video_id}
            ).one()

    def jobs_for(self, video_id: UUID) -> list[Any]:
        with self.admin.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT kind, idempotency_key, status"
                        " FROM app.processing_job WHERE video_id = :id ORDER BY kind"
                    ),
                    {"id": video_id},
                ).all()
            )

    # --- games ------------------------------------------------------------

    def test_a_coach_creates_a_game_on_their_own_team(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        listed = client.get(f"/v1/teams/{self.team}/games")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [game["id"] for game in listed.json()["games"]], [str(game_id)]
        )

    def test_a_coach_cannot_create_a_game_on_another_team(self) -> None:
        """An invisible team is 404, not 403: existence is not disclosed."""
        response = self.client_for(self.other_coach).post(
            "/v1/games",
            json={"team_id": str(self.team), "played_at": "2026-05-01T18:00:00Z"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.client_for(self.other_coach)
            .post(
                "/v1/games",
                json={"team_id": str(uuid4()), "played_at": "2026-05-01T18:00:00Z"},
            )
            .status_code,
            404,
        )

    def test_a_player_cannot_reach_any_game_route(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        player = self.client_for(self.player)
        self.assertEqual(player.get(f"/v1/games/{game_id}").status_code, 404)
        self.assertEqual(player.get(f"/v1/teams/{self.team}/games").status_code, 403)
        self.assertEqual(
            player.post(
                "/v1/games",
                json={"team_id": str(self.team), "played_at": "2026-05-01T18:00:00Z"},
            ).status_code,
            403,
        )

    def test_an_unknown_game_reads_the_same_as_a_hidden_one(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        outsider = self.client_for(self.other_coach)
        self.assertEqual(outsider.get(f"/v1/games/{game_id}").status_code, 404)
        self.assertEqual(outsider.get(f"/v1/games/{uuid4()}").status_code, 404)

    def test_a_malformed_page_cursor_is_rejected(self) -> None:
        client = self.client_for(self.coach)
        response = client.get(f"/v1/teams/{self.team}/games?cursor=not-a-cursor")
        self.assertEqual(response.status_code, 422)

    # --- upload validation -------------------------------------------------

    def test_an_unsupported_extension_is_refused_before_anything_is_signed(
        self,
    ) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        response = client.post(
            f"/v1/games/{game_id}/videos/uploads",
            json={
                "filename": "match.exe",
                "size_bytes": SMALL,
                "content_type": "video/mp4",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "unsupported-media-type"
        )

    def test_a_declared_type_that_contradicts_the_extension_is_refused(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        response = client.post(
            f"/v1/games/{game_id}/videos/uploads",
            json={
                "filename": "match.mp4",
                "size_bytes": SMALL,
                "content_type": "video/quicktime",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_a_mov_whose_browser_reports_no_type_is_accepted(self) -> None:
        """Several browsers recognise no type for `.mov`.

        `docs/04-api.md` treats the declared type as a hint, so silence is not a
        contradiction. The stored type comes from the validated extension.
        """
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        for declared in ("", "application/octet-stream"):
            with self.subTest(declared=declared):
                session = self.start_upload(
                    client, game_id, filename="match.mov", content_type=declared
                )
                row = self.video_row(UUID(session["video_id"]))
                self.assertEqual(row.content_type, "video/quicktime")
                self.assertTrue(row.original_key.endswith("source.mov"))

    def test_a_file_beyond_the_configured_ceiling_is_refused(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        response = client.post(
            f"/v1/games/{game_id}/videos/uploads",
            json={
                "filename": "match.mp4",
                "size_bytes": storage.MAX_UPLOAD_BYTES + 1,
                "content_type": "video/mp4",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["type"].rsplit("/", 1)[-1], "upload-too-large")

    def test_a_coach_outside_the_team_cannot_start_an_upload(self) -> None:
        game_id = self.create_game(self.client_for(self.coach))
        response = self.client_for(self.other_coach).post(
            f"/v1/games/{game_id}/videos/uploads",
            json={
                "filename": "match.mp4",
                "size_bytes": SMALL,
                "content_type": "video/mp4",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_the_object_key_never_contains_the_submitted_filename(self) -> None:
        """`docs/10-security-privacy.md`: never interpolate a client filename."""
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        for filename, displayed, declared in (
            ("../../etc/match; rm -rf x.mp4", "match; rm -rf x.mp4", "video/mp4"),
            (r"C:\Users\coach\Videos\match.MP4", "match.MP4", "video/mp4"),
            ("/var/lib/secrets/../match.mov", "match.mov", "video/quicktime"),
        ):
            with self.subTest(filename=filename):
                session = self.start_upload(
                    client, game_id, filename=filename, content_type=declared
                )
                row = self.video_row(UUID(session["video_id"]))
                extension = displayed.rsplit(".", 1)[-1].lower()
                self.assertEqual(
                    row.original_key,
                    f"originals/{session['video_id']}/source.{extension}",
                )
                # The display name keeps no path data either.
                self.assertEqual(row.original_filename, displayed)

    def test_no_upload_response_carries_a_storage_key_or_upload_id(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        row = self.video_row(video_id)
        for response in (
            client.get(f"/v1/videos/{video_id}"),
            client.get(f"/v1/videos/{video_id}/upload-state"),
            client.get(f"/v1/games/{game_id}"),
        ):
            with self.subTest(url=str(response.url)):
                self.assertNotIn(row.original_key, response.text)
                self.assertNotIn(row.multipart_upload_id, response.text)
                self.assertNotIn("originals/", response.text)

    # --- signing -----------------------------------------------------------

    def test_a_part_number_outside_the_plan_is_refused(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        for number in (0, 2, 99):
            with self.subTest(number=number):
                response = client.post(
                    f"/v1/videos/{session['video_id']}/upload-parts/sign",
                    json={"part_numbers": [number]},
                )
                self.assertEqual(response.status_code, 422)

    def test_a_coach_outside_the_team_cannot_sign_a_part(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        response = self.client_for(self.other_coach).post(
            f"/v1/videos/{session['video_id']}/upload-parts/sign",
            json={"part_numbers": [1]},
        )
        self.assertEqual(response.status_code, 404)

    # --- resume and completion ---------------------------------------------

    def test_upload_state_reports_only_the_parts_storage_actually_holds(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        size = storage.PART_SIZE_BYTES + 2048
        session = self.start_upload(client, game_id, size=size)
        video_id = UUID(session["video_id"])
        self.assertEqual(session["part_count"], 2)

        before = client.get(f"/v1/videos/{video_id}/upload-state").json()
        self.assertEqual(before["parts"], [])
        self.assertEqual(before["missing_part_numbers"], [1, 2])

        self.upload_part(client, video_id, 1, b"a" * storage.PART_SIZE_BYTES)
        after = client.get(f"/v1/videos/{video_id}/upload-state").json()
        self.assertEqual([part["part_number"] for part in after["parts"]], [1])
        self.assertEqual(after["missing_part_numbers"], [2])

    def test_a_resumed_upload_never_repeats_a_completed_part(self) -> None:
        """Task 8's definition of done, proved through the real endpoints."""
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        size = storage.PART_SIZE_BYTES + 2048
        session = self.start_upload(client, game_id, size=size)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * storage.PART_SIZE_BYTES)

        # The interruption: the client forgets everything and asks the server.
        state = client.get(f"/v1/videos/{video_id}/upload-state").json()
        first_etag = state["parts"][0]["etag"]
        self.assertEqual(state["missing_part_numbers"], [2])
        for number in state["missing_part_numbers"]:
            self.upload_part(client, video_id, number, b"b" * 2048)

        completed = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(completed.status_code, 200, completed.text)
        # Part 1's bytes were never sent twice: its ETag is unchanged.
        with self.admin.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT etag FROM app.video_upload_part"
                    " WHERE video_id = :id AND part_number = 1"
                ),
                {"id": video_id},
            ).scalar_one()
        self.assertEqual(stored, first_etag)
        self.assertEqual(
            storage.head_object(self.video_row(video_id).original_key), size
        )

    def test_completion_starts_the_retention_clock_and_enqueues_the_work(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)

        response = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "uploaded")

        row = self.video_row(video_id)
        self.assertEqual(row.status, "uploaded")
        self.assertIsNone(row.multipart_upload_id, "the upload id must not linger")
        self.assertIsNotNone(row.upload_completed_at)
        self.assertEqual((row.source_expires_at - row.upload_completed_at).days, 90)
        self.assertIsNotNone(row.derivatives_expires_at)

        self.assertEqual(
            [(job.kind, job.idempotency_key) for job in self.jobs_for(video_id)],
            [
                ("thumbnail", f"thumbnail:{video_id}:v1"),
                ("transcode", f"transcode:{video_id}:v1"),
            ],
        )

    def test_an_upload_assembled_by_a_failed_attempt_can_still_finish(self) -> None:
        """The window between assembling the object and committing the row.

        A fault there would otherwise leave the row `uploading` with an upload
        id storage has discarded, so every later completion failed on
        `ListParts` and the coach could never finish or abandon the attempt.
        """
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)

        # Assemble the object exactly as a completion would, then leave the row
        # untouched, which is the state a crash in the second phase produces.
        row = self.video_row(video_id)
        storage.complete_multipart(
            row.original_key,
            row.multipart_upload_id,
            storage.list_parts(row.original_key, row.multipart_upload_id),
        )
        self.assertEqual(self.video_row(video_id).status, "uploading")

        # The resume screen has to keep working in that window too, not 503.
        state = client.get(f"/v1/videos/{video_id}/upload-state")
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()["missing_part_numbers"], [])

        response = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.video_row(video_id).status, "uploaded")
        self.assertEqual(len(self.jobs_for(video_id)), 2)

    def test_an_upload_assembled_by_a_failed_attempt_can_still_be_abandoned(
        self,
    ) -> None:
        """The other half of the same window: abandoning must stay possible."""
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)
        row = self.video_row(video_id)
        storage.complete_multipart(
            row.original_key,
            row.multipart_upload_id,
            storage.list_parts(row.original_key, row.multipart_upload_id),
        )

        response = client.post(f"/v1/videos/{video_id}/upload-abort")
        self.assertEqual(response.status_code, 200, response.text)
        failed = self.video_row(video_id)
        self.assertEqual(failed.status, "failed")
        self.assertIsNotNone(failed.first_terminal_failure_at)

    def test_a_repeated_completion_is_idempotent(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)

        first = client.post(f"/v1/videos/{video_id}/upload-complete")
        second = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(self.jobs_for(video_id)), 2, "work was enqueued twice")

    def test_completing_before_every_part_arrived_is_refused(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(
            client, game_id, size=storage.PART_SIZE_BYTES + 2048
        )
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * storage.PART_SIZE_BYTES)

        response = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "upload-incomplete"
        )
        self.assertEqual(self.video_row(video_id).status, "uploading")
        self.assertEqual(self.jobs_for(video_id), [])

    def test_a_short_part_is_never_recorded_and_stays_resumable(self) -> None:
        """A signed URL authorizes a part; it does not force its length.

        The part plan is the guard: `reconcile_parts` persists only a part whose
        stored length matches the plan, so a truncated PUT leaves the part
        missing rather than silently completing a corrupt object. It stays
        resumable, because re-sending one part is the right recovery.
        """
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id, size=SMALL)
        video_id = UUID(session["video_id"])
        signed = client.post(
            f"/v1/videos/{video_id}/upload-parts/sign", json={"part_numbers": [1]}
        ).json()["parts"][0]
        httpx.put(signed["url"], content=b"a" * (SMALL // 2), timeout=TIMEOUT)

        state = client.get(f"/v1/videos/{video_id}/upload-state").json()
        self.assertEqual(state["parts"], [])
        self.assertEqual(state["missing_part_numbers"], [1])

        response = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "upload-incomplete"
        )
        self.assertEqual(self.jobs_for(video_id), [])
        self.assertEqual(self.video_row(video_id).status, "uploading")

        # Re-sending the full part completes it; nothing had to start over.
        self.upload_part(client, video_id, 1, b"a" * SMALL)
        self.assertEqual(
            client.post(f"/v1/videos/{video_id}/upload-complete").status_code, 200
        )

    def test_a_stored_object_that_disagrees_with_the_plan_is_rejected(self) -> None:
        """Defence in depth behind the part plan, and its state must persist.

        `complete_multipart` assembles the object; this asserts the check that
        the assembled length is what the coach declared. The stored length is
        forced to disagree because the part plan makes it unreachable
        otherwise, which is the point: the guard exists for the case where
        storage and `ListParts` disagree.

        Marking has to survive the request. Raising inside the transaction
        would roll the terminal state back and leave the row `uploading`
        forever with a completed object behind it and no deadline for the Task
        22 sweeper to measure from.
        """
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id, size=SMALL)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)

        # Patched on the storage module the route resolves through, so the real
        # `complete_multipart` still assembles the object against real storage.
        with patch.object(storage, "head_object", return_value=SMALL - 1):
            response = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "upload-size-mismatch"
        )
        self.assertEqual(self.jobs_for(video_id), [])

        row = self.video_row(video_id)
        self.assertEqual(row.status, "failed")
        self.assertIsNotNone(row.first_terminal_failure_at)
        self.assertIsNone(row.multipart_upload_id)
        self.assertIsNone(row.upload_completed_at)
        self.assertIsNone(row.source_expires_at)
        # A retry cannot revive a rejected attempt or move its deadline.
        first_failure = row.first_terminal_failure_at
        retry = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["type"].rsplit("/", 1)[-1], "upload-not-open")
        self.assertEqual(
            self.video_row(video_id).first_terminal_failure_at, first_failure
        )

    def test_a_coach_outside_the_team_cannot_complete_an_upload(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)
        response = self.client_for(self.other_coach).post(
            f"/v1/videos/{video_id}/upload-complete"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.video_row(video_id).status, "uploading")

    # --- abort -------------------------------------------------------------

    def test_aborting_removes_the_upload_and_marks_the_attempt_terminal(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)

        response = client.post(f"/v1/videos/{video_id}/upload-abort")
        self.assertEqual(response.status_code, 200, response.text)
        row = self.video_row(video_id)
        self.assertEqual(row.status, "failed")
        self.assertIsNotNone(row.first_terminal_failure_at)
        self.assertIsNone(row.multipart_upload_id)
        self.assertIsNone(storage.head_object(row.original_key))
        with self.admin.connect() as connection:
            parts = connection.execute(
                text("SELECT count(*) FROM app.video_upload_part WHERE video_id = :id"),
                {"id": video_id},
            ).scalar_one()
        self.assertEqual(parts, 0)

    def test_a_repeated_abort_does_not_move_the_failure_deadline(self) -> None:
        """A retry must never reset a retention clock."""
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        client.post(f"/v1/videos/{video_id}/upload-abort")
        first = self.video_row(video_id).first_terminal_failure_at
        second_response = client.post(f"/v1/videos/{video_id}/upload-abort")
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(self.video_row(video_id).first_terminal_failure_at, first)

    def test_a_completed_upload_cannot_be_aborted(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        self.upload_part(client, video_id, 1, b"a" * SMALL)
        client.post(f"/v1/videos/{video_id}/upload-complete")

        response = client.post(f"/v1/videos/{video_id}/upload-abort")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.video_row(video_id).status, "uploaded")

    def test_an_aborted_upload_cannot_be_signed_or_completed(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        client.post(f"/v1/videos/{video_id}/upload-abort")

        signed = client.post(
            f"/v1/videos/{video_id}/upload-parts/sign", json={"part_numbers": [1]}
        )
        self.assertEqual(signed.status_code, 409)
        completed = client.post(f"/v1/videos/{video_id}/upload-complete")
        self.assertEqual(completed.status_code, 409)

    def test_a_coach_outside_the_team_cannot_abort_an_upload(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        response = self.client_for(self.other_coach).post(
            f"/v1/videos/{video_id}/upload-abort"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.video_row(video_id).status, "uploading")

    # --- reading video state ----------------------------------------------

    def test_a_player_cannot_read_a_video_or_its_upload_state(self) -> None:
        client = self.client_for(self.coach)
        game_id = self.create_game(client)
        session = self.start_upload(client, game_id)
        video_id = UUID(session["video_id"])
        player = self.client_for(self.player)
        for path in (
            f"/v1/videos/{video_id}",
            f"/v1/videos/{video_id}/upload-state",
        ):
            with self.subTest(path=path):
                self.assertEqual(player.get(path).status_code, 404)

    def test_every_error_body_is_a_problem_document(self) -> None:
        client = self.client_for(self.other_coach)
        response = client.get(f"/v1/videos/{uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.headers["content-type"].split(";")[0], "application/problem+json"
        )
        body = response.json()
        self.assertEqual(set(body), {"type", "title", "status", "detail", "instance"})


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
