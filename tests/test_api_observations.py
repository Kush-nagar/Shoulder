"""Task 14 observation routes against the production-equivalent runtime role."""

import sys
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase  # noqa: E402


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class ObservationApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("mark.coach@example.test", "Coach A")
        self.other_coach = self.create_auth_user("mark.coach.b@example.test", "Coach B")
        self.player_account = self.create_auth_user(
            "mark.player@example.test", "Player A"
        )
        self.team = self.admin_insert_team(self.coach, "Marking FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.player = self.admin_insert_player(
            self.team,
            user_id=self.player_account,
            display_name="Player A",
            jersey_number=7,
        )
        self.other_player = self.admin_insert_player(
            self.other_team, display_name="Other player", jersey_number=8
        )
        self.add_membership(self.team, self.player_account)
        self.game = self.admin_insert_game(self.team, self.coach)
        self.video = self.admin_insert_video(self.game, self.coach, ready=True)
        self.pending_video = self.admin_insert_video(self.game, self.coach, ready=False)

    def add_membership(self, team_id: UUID, user_id: UUID) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": team_id, "user": user_id},
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

    def admin_insert_video(self, game_id: UUID, coach_id: UUID, *, ready: bool) -> UUID:
        video_id = uuid4()
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.video (
                        id, game_id, original_key, original_filename,
                        content_type, size_bytes, uploaded_by, status,
                        playback_key, duration_ms, width, height, fps, ready_at
                    ) VALUES (
                        :id, :game, :original_key, 'match.mp4', 'video/mp4', 1,
                        :coach, :status, :playback_key, :duration,
                        :width, :height, :fps, :ready_at
                    )
                """),
                {
                    "id": video_id,
                    "game": game_id,
                    "coach": coach_id,
                    "status": "ready" if ready else "uploaded",
                    "original_key": f"originals/{video_id}/source.mp4",
                    "playback_key": (
                        f"playback/{video_id}/coach-720p.mp4" if ready else None
                    ),
                    "duration": 60000 if ready else None,
                    "width": 1280 if ready else None,
                    "height": 720 if ready else None,
                    "fps": 30 if ready else None,
                    "ready_at": "2026-09-13T12:00:00Z" if ready else None,
                },
            )
        return video_id

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def payload(self, **overrides: object) -> dict[str, object]:
        return {
            "player_id": str(self.player),
            "t_start_ms": 1000,
            "t_end_ms": 4000,
            **overrides,
        }

    def test_coach_creates_and_lists_a_manual_observation(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/videos/{self.video}/observations", json=self.payload()
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["video_id"], str(self.video))
        self.assertEqual(body["player_id"], str(self.player))
        self.assertEqual(body["source"], "coach_manual")
        self.assertEqual(body["created_by"], str(self.coach))
        listed = client.get(
            f"/v1/videos/{self.video}/observations",
            params={"player_id": str(self.player)},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([row["id"] for row in listed.json()], [body["id"]])

    def test_client_id_makes_an_interrupted_create_safe_to_retry(self) -> None:
        client = self.client_for(self.coach)
        client_id = uuid4()
        payload = self.payload(client_id=str(client_id))

        first = client.post(f"/v1/videos/{self.video}/observations", json=payload)
        second = client.post(f"/v1/videos/{self.video}/observations", json=payload)

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["id"], str(client_id))
        listed = client.get(
            f"/v1/videos/{self.video}/observations",
            params={"player_id": str(self.player)},
        )
        self.assertEqual(len(listed.json()), 1)

    def test_wrong_team_player_is_rejected(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/videos/{self.video}/observations",
            json=self.payload(player_id=str(self.other_player)),
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1],
            "observation-context-invalid",
        )

    def test_bounds_must_fit_the_source_video(self) -> None:
        client = self.client_for(self.coach)
        for start, end in ((-1, 1000), (1000, 1000), (1000, 60001)):
            with self.subTest(start=start, end=end):
                response = client.post(
                    f"/v1/videos/{self.video}/observations",
                    json=self.payload(t_start_ms=start, t_end_ms=end),
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_video_must_be_ready_before_marking(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/videos/{self.pending_video}/observations", json=self.payload()
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["type"].rsplit("/", 1)[-1], "video-not-ready")

    def test_player_and_other_team_cannot_use_observation_routes(self) -> None:
        for identity in (self.player_account, self.other_coach):
            with self.subTest(identity=identity):
                client = self.client_for(identity)
                self.assertEqual(
                    client.post(
                        f"/v1/videos/{self.video}/observations",
                        json=self.payload(),
                    ).status_code,
                    404,
                )
                self.assertEqual(
                    client.get(
                        f"/v1/videos/{self.video}/observations",
                        params={"player_id": str(self.player)},
                    ).status_code,
                    404,
                )
