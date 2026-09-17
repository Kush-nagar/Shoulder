"""Task 15 judgment routes against the production-equivalent runtime role."""

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
class JudgmentApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("judge.coach@example.test", "Coach A")
        self.other_coach = self.create_auth_user(
            "judge.coach.b@example.test", "Coach B"
        )
        self.co_coach = self.create_auth_user("judge.co.coach@example.test", "Co-coach")
        self.player_account = self.create_auth_user(
            "judge.player@example.test", "Player A"
        )
        self.team = self.admin_insert_team(self.coach, "Judging FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.player = self.admin_insert_player(
            self.team, user_id=self.player_account, display_name="Player A"
        )
        self.other_player = self.admin_insert_player(
            self.other_team, display_name="Other player"
        )
        self.add_membership(self.team, self.player_account)
        self.add_membership(self.team, self.co_coach, role="coach")
        self.game = self.admin_insert_game(self.team, self.coach)
        self.video = self.admin_insert_video(self.game, self.coach, duration_ms=60000)
        self.observation = self.admin_insert_observation(self.video, self.player)
        self.goal = self.admin_insert_goal(self.player, self.coach)
        self.other_goal = self.admin_insert_goal(self.other_player, self.other_coach)

    def add_membership(self, team_id: UUID, user_id: UUID, role: str = "player") -> None:
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

    def admin_insert_video(
        self, game_id: UUID, coach_id: UUID, *, duration_ms: int
    ) -> UUID:
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
                        :coach, 'ready', :playback_key, :duration, 1280, 720, 30,
                        now()
                    )
                """),
                {
                    "id": video_id,
                    "game": game_id,
                    "coach": coach_id,
                    "original_key": f"originals/{video_id}/source.mp4",
                    "playback_key": f"playback/{video_id}/coach-720p.mp4",
                    "duration": duration_ms,
                },
            )
        return video_id

    def admin_insert_observation(self, video_id: UUID, player_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.observation (
                                video_id, player_id, t_start_ms, t_end_ms,
                                source, created_by
                            ) VALUES (
                                :video, :player, 1000, 4000, 'coach_manual', :coach
                            ) RETURNING id
                        """),
                        {"video": video_id, "player": player_id, "coach": self.coach},
                    ).scalar_one()
                )
            )

    def admin_insert_goal(self, player_id: UUID, coach_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.development_goal
                                (player_id, title, created_by)
                            VALUES (:player, 'First touch', :coach)
                            RETURNING id
                        """),
                        {"player": player_id, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def payload(self, **overrides: object) -> dict[str, object]:
        return {
            "goal_id": str(self.goal),
            "verdict": "applied",
            "comment_text": "Great pressing.",
            "clip_start_ms": 1000,
            "clip_end_ms": 2000,
            **overrides,
        }

    def test_coach_creates_a_judgment_with_revision_one(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["author_user_id"], str(self.coach))
        self.assertEqual(body["publication_status"], "draft")
        self.assertEqual(body["verdict"], "applied")
        self.assertEqual(response.headers["ETag"], "1")

    def test_request_body_has_no_author_field_to_spoof(self) -> None:
        """Author is always the session identity; there is nothing to inject."""
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json={**self.payload(), "author_user_id": str(self.other_coach)},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["author_user_id"], str(self.coach))

    def test_cross_team_goal_is_rejected(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json=self.payload(goal_id=str(self.other_goal)),
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_other_team_coach_cannot_create_against_this_observation(self) -> None:
        response = self.client_for(self.other_coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_edit_requires_if_match(self) -> None:
        created = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        response = self.client_for(self.coach).patch(
            f"/v1/judgments/{created['id']}",
            json={
                "verdict": "applied",
                "comment_text": "Updated.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 428, response.text)

    def test_edit_creates_a_new_revision_with_a_matching_etag(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        response = client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "opportunity",
                "comment_text": "Second look.",
                "clip_start_ms": 1000,
                "clip_end_ms": 3000,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["verdict"], "opportunity")
        self.assertEqual(response.headers["ETag"], "2")

    def test_no_op_replay_does_not_advance_the_version(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        response = client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "applied",
                "comment_text": "Great pressing.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["version"], 1)

    def test_stale_version_is_a_conflict(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "opportunity",
                "comment_text": "First edit.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        response = client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "not_relevant",
                "comment_text": "Stale edit.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "judgment-version-conflict"
        )

    def test_only_the_original_author_may_edit(self) -> None:
        created = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        response = self.client_for(self.co_coach).patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "applied",
                "comment_text": "Hijacked edit.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()["type"].rsplit("/", 1)[-1], "judgment-not-original-author"
        )

    def test_player_cannot_create_or_edit(self) -> None:
        client = self.client_for(self.player_account)
        response = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_revision_history_is_coach_only(self) -> None:
        created = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        coach_history = self.client_for(self.coach).get(
            f"/v1/judgments/{created['id']}/revisions"
        )
        self.assertEqual(coach_history.status_code, 200, coach_history.text)
        self.assertEqual(len(coach_history.json()), 1)
        self.assertEqual(coach_history.json()[0]["version"], 1)

        player_history = self.client_for(self.player_account).get(
            f"/v1/judgments/{created['id']}/revisions"
        )
        self.assertEqual(player_history.status_code, 200, player_history.text)
        self.assertEqual(player_history.json(), [])

    def test_not_relevant_verdict_can_be_created_and_read_back(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json=self.payload(verdict="not_relevant"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["verdict"], "not_relevant")
        self.assertEqual(response.json()["publication_status"], "draft")
