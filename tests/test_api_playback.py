"""Task 11 and 12 coach playback routes, against the real runtime role.

These run through `shoulder_api`, the same `NOBYPASSRLS` login production uses,
so a 403, a 404, or a 409 here is the database's answer rather than the
service's opinion.

The load-bearing property is rule 4 in `AGENTS.md`: the coach playback object is
coach-only. No player route signs it, and no request value chooses which object
gets signed.

Requires migration `0006` plus the URLs and `R2_*` environment that
`scripts/check-storage.ps1` provides.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from services import timeline
from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import (  # noqa: E402
    ADMIN_URL,
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
DURATION_MS = 90 * 60 * 1000


class ConfigurationTests(unittest.TestCase):
    def test_the_playback_suite_runs_where_storage_is_required(self) -> None:
        if STORAGE_REQUIRED:
            self.assertTrue(ADMIN_URL and RUNTIME_URL, "database URLs are required")
            self.assertTrue(STORAGE_CONFIGURED, "R2_* storage environment is required")
            self.assertFalse(
                getattr(PlaybackApiTests, "__unittest_skip__", False),
                "the playback API suite must run where storage is required",
            )


@unittest.skipUnless(STORAGE_CONFIGURED, "object storage is not configured")
class PlaybackApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        storage.get_client.cache_clear()
        self.addCleanup(storage.get_client.cache_clear)
        self.addCleanup(app.dependency_overrides.clear)

        self.coach = self.create_auth_user("play.coach@example.test", "Coach A")
        self.other_coach = self.create_auth_user("play.coach.b@example.test", "B")
        self.player = self.create_auth_user("play.player@example.test", "Player A1")
        self.team = self.admin_insert_team(self.coach, "Playback FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.admin_insert_player(
            self.team, user_id=self.player, display_name="Player A1", jersey_number=7
        )
        self.add_membership(self.team, self.player, "player")

        self.game = self.admin_insert_game(self.team, self.coach)
        self.ready = self.admin_insert_video(self.game, self.coach, ready=True)
        self.pending = self.admin_insert_video(self.game, self.coach, ready=False)
        # The timeline is gated on the published index, because the thumbnail
        # job runs separately from the transcode that marks a video ready.
        self.publish_index(self.ready)

    def publish_index(self, video_id: UUID) -> None:
        key = storage.thumbnail_index_key(video_id)
        storage.get_client().put_object(
            Bucket=storage.bucket(),
            Key=key,
            Body=b'{"interval_ms": 13500}',
            ContentType="application/json",
        )
        self.addCleanup(self.discard_object, key)

    def discard_object(self, key: str) -> None:
        try:
            storage.get_client().delete_object(Bucket=storage.bucket(), Key=key)
        except Exception:  # noqa: BLE001 - cleanup is best effort
            pass

    def add_membership(self, team_id: UUID, user_id: UUID, role: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, :role)
                """),
                {"team": team_id, "user": user_id, "role": role},
            )

    def admin_insert_game(self, team_id: UUID, coach_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.game (team_id, played_at, created_by)
                            VALUES (:team, now(), :coach) RETURNING id
                        """),
                        {"team": team_id, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def admin_insert_video(self, game_id: UUID, coach_id: UUID, ready: bool) -> UUID:
        video_id = uuid4()
        fields: dict[str, Any] = {
            "id": video_id,
            "game_id": game_id,
            "original_key": storage.original_key(video_id, "mp4"),
            "original_filename": "match.mp4",
            "content_type": "video/mp4",
            "size_bytes": 64 * 1024 * 1024,
            "uploaded_by": coach_id,
            "status": "ready" if ready else "uploaded",
        }
        if ready:
            fields.update(
                {
                    "playback_key": storage.playback_key(video_id),
                    "duration_ms": DURATION_MS,
                    "width": 1280,
                    "height": 720,
                    "fps": 30,
                    "ready_at": "now()",
                    "derivatives_expires_at": "now()",
                }
            )
        sql_values = {"ready_at", "derivatives_expires_at"}
        names = ", ".join(key for key in fields if key not in sql_values)
        values = ", ".join(f":{key}" for key in fields if key not in sql_values)
        if ready:
            names += ", ready_at, derivatives_expires_at"
            values += ", now(), now() + interval '30 days'"
            fields.pop("ready_at")
            fields.pop("derivatives_expires_at")
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(f"INSERT INTO app.video ({names}) VALUES ({values})"), fields
            )
        return video_id

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    # --- playback URL -----------------------------------------------------

    def test_a_coach_signs_the_playback_object_for_their_own_video(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/videos/{self.ready}/playback-url"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["video_id"], str(self.ready))
        self.assertEqual(body["duration_ms"], DURATION_MS)
        self.assertEqual(body["expires_in"], storage.GET_URL_SECONDS)

    def test_the_signed_url_names_the_coach_object_and_nothing_else(self) -> None:
        """One object, one verb. It must not be the original upload."""
        body = (
            self.client_for(self.coach)
            .post(f"/v1/videos/{self.ready}/playback-url")
            .json()
        )
        path = urlparse(body["url"]).path
        self.assertIn(f"playback/{self.ready}/coach-720p.mp4", path)
        self.assertNotIn("originals/", path)

    def test_the_signing_lifetime_stays_within_the_coach_ceiling(self) -> None:
        """`docs/10-security-privacy.md` caps a coach URL at fifteen minutes."""
        body = (
            self.client_for(self.coach)
            .post(f"/v1/videos/{self.ready}/playback-url")
            .json()
        )
        self.assertLessEqual(body["expires_in"], 900)

    def test_a_video_still_being_prepared_is_a_conflict_not_a_not_found(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/videos/{self.pending}/playback-url"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["type"].rsplit("/", 1)[-1], "video-not-ready")

    def test_a_coach_outside_the_team_cannot_sign_playback(self) -> None:
        response = self.client_for(self.other_coach).post(
            f"/v1/videos/{self.ready}/playback-url"
        )
        self.assertEqual(response.status_code, 404)

    def test_a_player_can_never_sign_the_coach_playback_object(self) -> None:
        """Rule 4: players never receive full-match access."""
        response = self.client_for(self.player).post(
            f"/v1/videos/{self.ready}/playback-url"
        )
        self.assertEqual(response.status_code, 404)

    def test_an_unknown_video_reads_the_same_as_a_hidden_one(self) -> None:
        outsider = self.client_for(self.other_coach)
        self.assertEqual(
            outsider.post(f"/v1/videos/{uuid4()}/playback-url").status_code, 404
        )

    # --- timeline ---------------------------------------------------------

    def test_the_timeline_geometry_matches_the_shared_function(self) -> None:
        body = (
            self.client_for(self.coach).get(f"/v1/videos/{self.ready}/timeline").json()
        )
        layout = timeline.sprite_layout(DURATION_MS)
        self.assertEqual(body["interval_ms"], layout.interval_ms)
        self.assertEqual(body["tile_count"], layout.tile_count)
        self.assertEqual(body["columns"], layout.columns)
        self.assertEqual(body["rows"], layout.rows)
        self.assertEqual(len(body["sheets"]), layout.sheet_count)

    def test_a_full_match_timeline_stays_a_handful_of_objects(self) -> None:
        """Task 12 exists so the timeline is not hundreds of images."""
        body = (
            self.client_for(self.coach).get(f"/v1/videos/{self.ready}/timeline").json()
        )
        self.assertLessEqual(len(body["sheets"]), timeline.MAX_SHEETS)

    def test_every_sheet_url_names_its_own_sprite_object(self) -> None:
        body = (
            self.client_for(self.coach).get(f"/v1/videos/{self.ready}/timeline").json()
        )
        for sheet in body["sheets"]:
            path = urlparse(sheet["url"]).path
            self.assertIn(f"thumbs/{self.ready}/sprite-{sheet['sheet']}.jpg", path)
            self.assertNotIn("originals/", path)

    def test_a_timeline_whose_sheets_are_not_published_yet_is_a_conflict(self) -> None:
        """Transcode marks a video ready before the thumbnail job has run.

        Signing sheets that do not exist would hand the scrubber URLs that 404
        with no way to tell why.
        """
        later = self.admin_insert_video(self.game, self.coach, ready=True)
        response = self.client_for(self.coach).get(f"/v1/videos/{later}/timeline")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "timeline-not-ready"
        )
        # Playback itself does not depend on thumbnails, so it still works.
        self.assertEqual(
            self.client_for(self.coach)
            .post(f"/v1/videos/{later}/playback-url")
            .status_code,
            200,
        )

    def test_a_timeline_for_an_unprepared_video_is_a_conflict(self) -> None:
        response = self.client_for(self.coach).get(
            f"/v1/videos/{self.pending}/timeline"
        )
        self.assertEqual(response.status_code, 409)

    def test_a_player_cannot_read_the_timeline(self) -> None:
        response = self.client_for(self.player).get(f"/v1/videos/{self.ready}/timeline")
        self.assertEqual(response.status_code, 404)

    def test_a_coach_outside_the_team_cannot_read_the_timeline(self) -> None:
        response = self.client_for(self.other_coach).get(
            f"/v1/videos/{self.ready}/timeline"
        )
        self.assertEqual(response.status_code, 404)

    # --- disclosure -------------------------------------------------------

    def test_no_playback_response_exposes_a_storage_key(self) -> None:
        """`docs/04-api.md`: metadata and processing state, no storage keys."""
        client = self.client_for(self.coach)
        for response in (
            client.post(f"/v1/videos/{self.ready}/playback-url"),
            client.get(f"/v1/videos/{self.ready}/timeline"),
            client.get(f"/v1/videos/{self.ready}"),
        ):
            with self.subTest(url=str(response.url)):
                body = response.json()
                self.assertNotIn("playback_key", body)
                self.assertNotIn("original_key", body)

    def test_every_refusal_is_a_problem_document(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/videos/{self.pending}/playback-url"
        )
        self.assertEqual(
            response.headers["content-type"].split(";")[0], "application/problem+json"
        )
        self.assertEqual(
            set(response.json()), {"type", "title", "status", "detail", "instance"}
        )


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
