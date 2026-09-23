"""Block 08P player practice videos and AI coach feedback (ADR 0021).

Isolation runs through `shoulder_api` (RLS) at both the database and API
layers; the AI model is always mocked. The storage round trip needs the
`R2_*` environment `scripts/check-db.ps1` provides.
"""

import dataclasses
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api import ai_coach, storage
from services.api.auth import authenticated_identity
from services.api.main import app
from services.api.schemas import AiCoachResult, Drill, PracticeFeatures
from services.worker import jobs, retention

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
STORAGE_CONFIGURED = all(
    os.environ.get(name)
    for name in (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
)
BASE = "/v1/player/practice-videos"
FEATURES: dict[str, Any] = {
    "frames_analyzed": 900,
    "fps": 30,
    "duration_ms": 30000,
    "knee_flexion_deg": {"p10": 12, "p50": 34, "p90": 61},
    "hip_flexion_deg": {"p10": 10, "p50": 20, "p90": 40},
    "trunk_lean_deg": {"p10": -5, "p50": 3, "p90": 12},
    "head_turns": 7,
    "head_turns_per_min": 14.0,
    "stance_width_ratio": {"p50": 1.2},
    "visibility_mean": 0.82,
}
RESULT = AiCoachResult(
    body="Keep scanning before the ball arrives.",
    drills=[Drill(title="Shoulder checks", why="See space early.", how="Look twice.")],
    model="test/model",
)


class FeatureValidationTests(unittest.TestCase):
    def test_contract_example_is_accepted(self) -> None:
        PracticeFeatures.model_validate(FEATURES)

    def test_unknown_keys_and_landmark_arrays_are_rejected(self) -> None:
        for extra in (
            {"landmarks": [[0.1, 0.2, 0.3]] * 33},
            {"knee_flexion_deg": {"p10": 1, "p50": 2, "p90": 3, "raw": [1, 2]}},
            {"head_turns": [1, 2, 3]},
            {"visibility_mean": float("nan")},
            {"fps": 0},
        ):
            with self.subTest(extra=list(extra)):
                with self.assertRaises(ValidationError):
                    PracticeFeatures.model_validate({**FEATURES, **extra})

    def test_oversized_body_is_refused_before_parsing(self) -> None:
        app.dependency_overrides[authenticated_identity] = lambda: str(uuid4())
        self.addCleanup(app.dependency_overrides.clear)
        body = json.dumps({**FEATURES, "pad": "x" * 5000})
        response = TestClient(app).post(
            f"{BASE}/{uuid4()}/ai-feedback",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)

    def test_ai_result_bounds_drills_and_body(self) -> None:
        drill = {"title": "t", "why": "w", "how": "h"}
        with self.assertRaises(ValidationError):
            AiCoachResult(body="x", drills=[Drill(**drill)] * 4, model="m")
        with self.assertRaises(ValidationError):
            AiCoachResult(body="x" * 1201, drills=[], model="m")


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class PracticeTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("practice.coach@example.test", "Coach")
        self.user_a = self.create_auth_user("practice.a@example.test", "Player A")
        self.user_b = self.create_auth_user("practice.b@example.test", "Player B")
        self.team = self.admin_insert_team(self.coach, "Practice FC")
        self.player_a = self.linked_player(self.user_a, 7)
        self.player_b = self.linked_player(self.user_b, 8)
        with self.admin.connect() as connection, connection.begin():
            self.goal_a = connection.execute(
                text("""
                    INSERT INTO app.development_goal (player_id, title, created_by)
                    VALUES (:player, 'Scan before receiving', :coach) RETURNING id
                """),
                {"player": self.player_a, "coach": self.coach},
            ).scalar_one()
        self.video_a = self.admin_video(self.player_a, self.user_a)
        self.video_b = self.admin_video(self.player_b, self.user_b)

    def linked_player(self, user_id: UUID, jersey: int) -> UUID:
        player = self.admin_insert_player(
            self.team, user_id=user_id, display_name=f"P{jersey}", jersey_number=jersey
        )
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": self.team, "user": user_id},
            )
        return player

    def admin_video(
        self, player: UUID, user: UUID, *, expires: str = "now() + interval '90 days'"
    ) -> UUID:
        video_id = uuid4()
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(f"""
                    INSERT INTO app.practice_video (
                        id, player_id, created_by_user_id, object_key,
                        content_type, size_bytes, status, upload_completed_at,
                        expires_at
                    ) VALUES (
                        :id, :player, :user, :key, 'video/mp4', 10, 'ready',
                        {expires} - interval '90 days', {expires}
                    )
                """),
                {
                    "id": video_id,
                    "player": player,
                    "user": user,
                    "key": storage.practice_key(video_id, "video/mp4"),
                },
            )
        return video_id

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def visible(self, user_id: UUID, sql: str) -> list[Any]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            return list(connection.execute(text(sql)).all())

    def count(self, sql: str, **params: Any) -> int:
        with self.admin.connect() as connection:
            return int(connection.execute(text(sql), params).scalar_one())

    # -- database layer -------------------------------------------------------

    def test_database_rows_are_visible_only_to_their_player(self) -> None:
        sql = "SELECT id FROM app.practice_video"
        self.assertEqual([r.id for r in self.visible(self.user_a, sql)], [self.video_a])
        self.assertEqual([r.id for r in self.visible(self.user_b, sql)], [self.video_b])
        self.assertEqual(self.visible(self.coach, sql), [])
        self.assertEqual(
            self.visible(self.coach, "SELECT id FROM app.ai_coach_feedback"), []
        )

    def test_database_writes_on_another_player_are_refused(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.user_a)
            deleted = connection.execute(
                text("DELETE FROM app.practice_video WHERE id = :id"),
                {"id": self.video_b},
            ).rowcount
            updated = connection.execute(
                text(
                    "UPDATE app.practice_video SET status = 'uploading' WHERE id = :id"
                ),
                {"id": self.video_b},
            ).rowcount
        self.assertEqual((deleted, updated), (0, 0))
        for user, player, table_sql in (
            (
                self.user_a,
                self.player_b,
                "INSERT INTO app.practice_video (player_id, created_by_user_id,"
                " object_key, content_type, size_bytes) VALUES (:player, :user,"
                " :key, 'video/mp4', 1)",
            ),
            (
                self.user_a,
                self.player_b,
                "INSERT INTO app.ai_coach_feedback (practice_video_id, player_id,"
                " features, model, body, drills) VALUES (:video, :player, '{}',"
                " 'm', 'b', '[]')",
            ),
            (
                self.user_a,
                self.player_a,
                "INSERT INTO app.ai_coach_feedback (practice_video_id, player_id,"
                " features, model, body, drills) VALUES (:video, :player, '{}',"
                " 'm', 'b', '[]')",
            ),
            (
                self.coach,
                self.player_a,
                "INSERT INTO app.practice_video (player_id, created_by_user_id,"
                " object_key, content_type, size_bytes) VALUES (:player, :user,"
                " :key, 'video/mp4', 1)",
            ),
        ):
            with self.subTest(sql=table_sql[:40], player=player):
                with self.assertRaises(DBAPIError) as caught:
                    with self.runtime.connect() as connection, connection.begin():
                        self.as_user(connection, user)
                        connection.execute(
                            text(table_sql),
                            {
                                "player": player,
                                "user": user,
                                "key": f"practice/{uuid4()}/source.mp4",
                                # Player A's own feedback on B's video is refused.
                                "video": self.video_b,
                            },
                        )
                self.assertEqual(sqlstate(caught.exception), "42501")

    # -- API layer ------------------------------------------------------------

    def test_api_isolates_every_endpoint(self) -> None:
        client = self.client_for(self.user_a)
        with (
            patch.object(storage, "sign_get", return_value="https://signed"),
            patch.object(storage, "delete_object") as deleted,
            patch.object(storage, "head_media") as head,
            patch.object(ai_coach, "generate_feedback") as model,
        ):
            target = f"{BASE}/{self.video_b}"
            for method, path, body in (
                ("GET", target, None),
                ("POST", f"{target}/complete", {}),
                ("DELETE", target, None),
                ("POST", f"{target}/ai-feedback", FEATURES),
                ("GET", f"{target}/ai-feedback", None),
            ):
                with self.subTest(method=method, path=path):
                    response = client.request(method, path, json=body)
                    self.assertEqual(response.status_code, 404, response.text)
            listed = client.get(BASE).json()
            self.assertEqual([item["id"] for item in listed], [str(self.video_a)])
            deleted.assert_not_called()
            head.assert_not_called()
            model.assert_not_called()

            coach = self.client_for(self.coach)
            self.assertEqual(coach.get(BASE).status_code, 403)
            self.assertEqual(coach.get(f"{BASE}/{self.video_a}").status_code, 404)
            self.assertEqual(
                coach.post(
                    BASE, json={"content_type": "video/mp4", "size_bytes": 1}
                ).status_code,
                403,
            )
        self.assertEqual(
            self.count(
                "SELECT count(*) FROM app.practice_video WHERE id = :id",
                id=self.video_b,
            ),
            1,
        )

    def test_ai_feedback_is_stored_with_the_active_goal(self) -> None:
        client = self.client_for(self.user_a)
        with patch.object(ai_coach, "generate_feedback", return_value=RESULT) as model:
            response = client.post(f"{BASE}/{self.video_a}/ai-feedback", json=FEATURES)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(model.call_args.args[1], "Scan before receiving")
        self.assertEqual(response.json()["development_goal_id"], str(self.goal_a))
        listed = client.get(f"{BASE}/{self.video_a}/ai-feedback").json()
        self.assertEqual([item["id"] for item in listed], [response.json()["id"]])
        self.assertEqual(
            self.client_for(self.user_b)
            .get(f"{BASE}/{self.video_a}/ai-feedback")
            .status_code,
            404,
        )

    def test_upstream_failure_is_502_and_stores_nothing(self) -> None:
        client = self.client_for(self.user_a)
        for failure in (RuntimeError("down"), NotImplementedError()):
            with patch.object(ai_coach, "generate_feedback", side_effect=failure):
                response = client.post(
                    f"{BASE}/{self.video_a}/ai-feedback", json=FEATURES
                )
            self.assertEqual(response.status_code, 502)
        self.assertEqual(
            self.count(
                "SELECT count(*) FROM app.ai_coach_feedback WHERE player_id = :p",
                p=self.player_a,
            ),
            0,
        )

    def test_rate_limit_is_ten_per_day_per_player(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            for _ in range(10):
                connection.execute(
                    text("""
                        INSERT INTO app.ai_coach_feedback (
                            practice_video_id, player_id, features, model, body,
                            drills
                        ) VALUES (:video, :player, '{}', 'm', 'b', '[]')
                    """),
                    {"video": self.video_a, "player": self.player_a},
                )
        with patch.object(ai_coach, "generate_feedback", return_value=RESULT) as model:
            limited = self.client_for(self.user_a).post(
                f"{BASE}/{self.video_a}/ai-feedback", json=FEATURES
            )
            other = self.client_for(self.user_b).post(
                f"{BASE}/{self.video_b}/ai-feedback", json=FEATURES
            )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(other.status_code, 201, other.text)
        self.assertEqual(model.call_count, 1)

    def test_invalid_features_are_422_before_any_model_call(self) -> None:
        with patch.object(ai_coach, "generate_feedback") as model:
            response = self.client_for(self.user_a).post(
                f"{BASE}/{self.video_a}/ai-feedback",
                json={**FEATURES, "landmarks": [[0.1, 0.2]]},
            )
        self.assertEqual(response.status_code, 422)
        model.assert_not_called()

    def test_complete_rejects_a_mismatched_object_and_deletes_it(self) -> None:
        client = self.client_for(self.user_a)
        with patch.object(storage, "sign_put", return_value="https://put"):
            created = client.post(
                BASE, json={"content_type": "video/mp4", "size_bytes": 100}
            )
        self.assertEqual(created.status_code, 201, created.text)
        video_id = created.json()["id"]
        with patch.object(storage, "head_media", return_value=None):
            self.assertEqual(
                client.post(f"{BASE}/{video_id}/complete", json={}).status_code, 409
            )
        with (
            patch.object(storage, "head_media", return_value=(999, "video/mp4")),
            patch.object(storage, "delete_object") as deleted,
        ):
            response = client.post(f"{BASE}/{video_id}/complete", json={})
        self.assertEqual(response.status_code, 422)
        deleted.assert_called_once_with(f"practice/{video_id}/source.mp4")
        self.assertEqual(
            self.count(
                "SELECT count(*) FROM app.practice_video WHERE id = :id", id=video_id
            ),
            0,
        )

    @unittest.skipUnless(STORAGE_CONFIGURED, "object storage is not configured")
    def test_real_upload_round_trip_and_delete(self) -> None:
        storage.get_client.cache_clear()
        self.addCleanup(storage.get_client.cache_clear)
        client = self.client_for(self.user_a)
        payload = b"\x00\x00\x00\x18ftypmp42" + b"0" * 500
        created = client.post(
            BASE,
            json={
                "content_type": "video/mp4",
                "size_bytes": len(payload),
                "title": "Juggling",
            },
        ).json()
        put = httpx.put(
            created["upload_url"],
            content=payload,
            headers={"Content-Type": "video/mp4"},
        )
        self.assertEqual(put.status_code, 200)
        done = client.post(f"{BASE}/{created['id']}/complete", json={"duration_ms": 5})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["status"], "ready")
        detail = client.get(f"{BASE}/{created['id']}").json()
        self.assertEqual(httpx.get(detail["playback_url"]).content, payload)
        self.assertEqual(client.delete(f"{BASE}/{created['id']}").status_code, 204)
        self.assertIsNone(storage.head_object(f"practice/{created['id']}/source.mp4"))

    # -- retention ------------------------------------------------------------

    @unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
    def test_retention_purges_only_expired_practice_videos(self) -> None:
        expired = self.admin_video(
            self.player_a, self.user_a, expires="now() - interval '1 second'"
        )
        worker = f"practice-{uuid4()}"
        with self.admin.connect() as connection, connection.begin():
            job_id = connection.execute(
                text("""
                    INSERT INTO app.processing_job (
                        kind, idempotency_key, status, attempts, max_attempts,
                        locked_at, locked_by, heartbeat_at
                    ) VALUES (
                        'retention_sweep', :key, 'running', 1, 5,
                        now(), :worker, now()
                    ) RETURNING id
                """),
                {"key": f"practice:{uuid4()}", "worker": worker},
            ).scalar_one()
        job = jobs.Job(
            id=UUID(str(job_id)),
            kind="retention_sweep",
            video_id=None,
            email_delivery_id=None,
            player_id=None,
            deletion_manifest_id=None,
            attempts=1,
            max_attempts=5,
            payload={},
            locked_by=worker,
        )
        stale = dataclasses.replace(job, locked_by="not-the-holder")
        with patch.object(retention.storage, "delete_object") as deleted:
            self.assertEqual(retention.purge_practice_videos(stale, lambda _p: True), 0)
            with patch.object(retention.storage, "head_object", return_value=None):
                purged = retention.purge_practice_videos(job, lambda _p: True)
        deleted.assert_called_once_with(storage.practice_key(expired, "video/mp4"))
        self.assertEqual(purged, 1)
        remaining = self.count(
            "SELECT count(*) FROM app.practice_video WHERE id = ANY(:ids)",
            ids=[expired, self.video_a],
        )
        self.assertEqual(remaining, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
