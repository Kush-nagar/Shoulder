"""Task 17 publication, snapshot, and player-media API acceptance."""

import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase  # noqa: E402


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class PublicationApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(self.delete_publication_rows)
        self.coach = self.create_auth_user("publish.coach@example.test", "Coach A")
        self.player_account = self.create_auth_user(
            "publish.player.a@example.test", "Player A"
        )
        self.other_player_account = self.create_auth_user(
            "publish.player.b@example.test", "Player B"
        )
        self.team = self.admin_insert_team(self.coach, "Publishing FC")
        self.player = self.admin_insert_player(
            self.team, user_id=self.player_account, display_name="Player A"
        )
        self.other_player = self.admin_insert_player(
            self.team, user_id=self.other_player_account, display_name="Player B"
        )
        self.add_membership(self.player_account)
        self.add_membership(self.other_player_account)
        self.game = self.admin_insert_game()
        self.video = self.admin_insert_video()
        self.goal = self.admin_insert_goal(self.player)
        self.observations = [self.admin_insert_observation(index) for index in range(6)]
        self.judgments = [self.create_judgment(index) for index in range(6)]

    def add_membership(self, user_id: UUID) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": self.team, "user": user_id},
            )

    def delete_publication_rows(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    UPDATE app.judgment SET
                        publication_status = 'draft', current_publication_id = NULL,
                        current_revision_id = NULL, current_clip_id = NULL,
                        published_at = NULL
                """)
            )
            connection.execute(text("DELETE FROM app.review_publication"))
            connection.execute(text("DELETE FROM app.evidence_clip"))
            connection.execute(text("DELETE FROM app.judgment"))

    def admin_insert_game(self) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.game (team_id, played_at, created_by)
                            VALUES (:team, now(), :coach) RETURNING id
                        """),
                        {"team": self.team, "coach": self.coach},
                    ).scalar_one()
                )
            )

    def admin_insert_video(self) -> UUID:
        video_id = uuid4()
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.video (
                        id, game_id, original_key, original_filename,
                        content_type, size_bytes, uploaded_by, status,
                        playback_key, duration_ms, width, height, fps, ready_at,
                        derivatives_expires_at
                    ) VALUES (
                        :id, :game, :original_key, 'match.mp4', 'video/mp4', 1,
                        :coach, 'ready', :playback_key, 60000, 1280, 720, 30,
                        now(), now() + interval '30 days'
                    )
                """),
                {
                    "id": video_id,
                    "game": self.game,
                    "coach": self.coach,
                    "original_key": f"originals/{video_id}/source.mp4",
                    "playback_key": storage.playback_key(video_id),
                },
            )
        return video_id

    def admin_insert_goal(self, player_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.development_goal
                                (player_id, title, created_by)
                            VALUES (:player, 'First touch', :coach) RETURNING id
                        """),
                        {"player": player_id, "coach": self.coach},
                    ).scalar_one()
                )
            )

    def admin_insert_observation(self, index: int) -> UUID:
        start = 1000 + index * 3000
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.observation (
                                video_id, player_id, t_start_ms, t_end_ms,
                                source, created_by
                            ) VALUES (
                                :video, :player, :start, :finish,
                                'coach_manual', :coach
                            ) RETURNING id
                        """),
                        {
                            "video": self.video,
                            "player": self.player,
                            "start": start,
                            "finish": start + 2000,
                            "coach": self.coach,
                        },
                    ).scalar_one()
                )
            )

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def create_judgment(self, index: int) -> dict[str, Any]:
        start = 1000 + index * 3000
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observations[index]}/judgments",
            json={
                "goal_id": str(self.goal),
                "verdict": "applied" if index % 2 == 0 else "opportunity",
                "comment_text": f"Coach comment {index}.",
                "clip_start_ms": start,
                "clip_end_ms": start + 1000,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return cast("dict[str, Any]", response.json())

    def publish(
        self,
        indices: list[int],
        *,
        replaces: str | None = None,
        key: str | None = None,
    ) -> Response:
        return cast(
            Response,
            self.client_for(self.coach).post(
                f"/v1/reviews/{self.game}/{self.player}/publish",
                headers={"Idempotency-Key": key or f"publish-{uuid4()}"},
                json={
                    "goal_id": str(self.goal),
                    "replaces_publication_id": replaces,
                    "items": [
                        {
                            "judgment_id": self.judgments[index]["id"],
                            "version": self.judgments[index]["version"],
                        }
                        for index in indices
                    ],
                },
            ),
        )

    def finish(self, publication_id: str) -> None:
        """Act as a verified worker output without involving object storage."""
        with self.admin.connect() as connection, connection.begin():
            rows = connection.execute(
                text("""
                    SELECT i.judgment_id, i.requested_clip_version, c.id,
                           r.clip_end_ms - r.clip_start_ms AS duration_ms
                    FROM app.review_publication_item i
                    JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
                    JOIN app.evidence_clip c
                      ON c.judgment_id = i.judgment_id
                     AND c.version = i.requested_clip_version
                    WHERE i.publication_id = :publication
                      AND i.evidence_clip_id IS NULL
                """),
                {"publication": publication_id},
            ).all()
            for row in rows:
                connection.execute(
                    text("""
                        UPDATE app.evidence_clip SET
                            duration_ms = :duration, size_bytes = 1000,
                            sha256 = repeat('a', 64), status = 'ready', ready_at = now()
                        WHERE id = :clip
                    """),
                    {"duration": row.duration_ms, "clip": row.id},
                )
                connection.execute(
                    text("""
                        UPDATE app.review_publication_item
                        SET evidence_clip_id = :clip, updated_at = now()
                        WHERE publication_id = :publication
                          AND judgment_id = :judgment
                    """),
                    {
                        "clip": row.id,
                        "publication": publication_id,
                        "judgment": row.judgment_id,
                    },
                )
            finalized = connection.execute(
                text("SELECT private.finalize_review_publication(:publication)"),
                {"publication": publication_id},
            ).scalar_one()
        self.assertTrue(finalized)

    def evidence(self, actor: UUID | None = None) -> list[dict[str, Any]]:
        response = self.client_for(actor or self.player_account).get(
            f"/v1/me/goals/{self.goal}/evidence"
        )
        self.assertEqual(response.status_code, 200, response.text)
        return cast("list[dict[str, Any]]", response.json())

    def test_three_to_six_items_and_one_current_set_are_enforced(self) -> None:
        for indices in ([0, 1], [0, 1, 2, 3, 4, 5, 0]):
            response = self.publish(indices)
            self.assertEqual(response.status_code, 422, response.text)
        first = self.publish([0, 1, 2])
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(first.json()["status"], "exporting")
        concurrent = self.publish([3, 4, 5])
        self.assertEqual(concurrent.status_code, 409, concurrent.text)

    def test_idempotency_and_stale_version_or_predecessor_conflict(self) -> None:
        first = self.publish([0, 1, 2], key="same-key")
        replay = self.publish([0, 1, 2], key="same-key")
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()["id"], first.json()["id"])
        mismatch = self.publish([0, 1, 3], key="same-key")
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        self.client_for(self.coach).post(
            f"/v1/review-publications/{first.json()['id']}/cancel"
        )
        stale = self.publish([0, 1, 2])
        self.assertEqual(stale.status_code, 202, stale.text)
        self.client_for(self.coach).post(
            f"/v1/review-publications/{stale.json()['id']}/cancel"
        )
        self.judgments[0]["version"] = 99
        stale_version = self.publish([0, 1, 2])
        self.assertEqual(stale_version.status_code, 409, stale_version.text)

    def test_first_visibility_waits_for_every_clip_and_player_b_is_denied(self) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.assertEqual(self.evidence(), [])
        self.finish(publication["id"])
        own = self.evidence()
        self.assertEqual(len(own), 1)
        self.assertEqual(len(own[0]["items"]), 3)
        # The game label and coach name come only from the authorized definer
        # projection; `app.game` and `app.user_account` stay closed to a player.
        self.assertEqual(own[0]["game_label"], "Match")
        self.assertTrue(
            all(item["coach_display_name"] == "Coach A" for item in own[0]["items"])
        )
        self.assertEqual(self.evidence(self.other_player_account), [])
        serialized = str(own)
        self.assertNotIn(str(self.video), serialized)
        self.assertNotIn("playback/", serialized)
        self.assertNotIn("storage_key", serialized)

    def test_player_evidence_projection_is_authorized_in_the_database(self) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.player_account)
            rows = connection.execute(
                text("SELECT * FROM private.player_evidence(:goal)"),
                {"goal": self.goal},
            ).all()
        self.assertEqual(len(rows), 3)
        self.assertTrue(
            all(row.coach_display_name == "Coach A" for row in rows),
            rows,
        )
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.other_player_account)
            denied = connection.execute(
                text("SELECT * FROM private.player_evidence(:goal)"),
                {"goal": self.goal},
            ).all()
        self.assertEqual(denied, [])

    def test_draft_text_stays_hidden_and_comment_edit_gets_a_new_clip(self) -> None:
        first = self.publish([0, 1, 2]).json()
        self.finish(first["id"])
        old = self.evidence()[0]["items"][0]
        edited = self.client_for(self.coach).patch(
            f"/v1/judgments/{self.judgments[0]['id']}",
            headers={"If-Match": '"1"'},
            json={
                "verdict": "applied",
                "comment_text": "New unpublished sentence.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.judgments[0] = edited.json()
        replacement = self.publish([0, 1, 2], replaces=first["id"]).json()
        self.assertEqual(self.evidence()[0]["items"][0], old)
        changed = replacement["items"][0]
        self.assertIsNone(changed["evidence_clip_id"])
        self.assertGreater(changed["requested_clip_version"], 1)
        self.assertIsNotNone(replacement["items"][1]["evidence_clip_id"])
        self.finish(replacement["id"])
        new = self.evidence()[0]["items"][0]
        self.assertEqual(new["comment"], "New unpublished sentence.")
        self.assertNotEqual(new["published_revision_id"], old["published_revision_id"])

    def test_edit_during_export_fails_and_failure_keeps_old_snapshot(self) -> None:
        first = self.publish([0, 1, 2]).json()
        self.finish(first["id"])
        replacement = self.publish([0, 1, 2], replaces=first["id"]).json()
        edit = self.client_for(self.coach).patch(
            f"/v1/judgments/{self.judgments[0]['id']}",
            headers={"If-Match": '"1"'},
            json={
                "verdict": "applied",
                "comment_text": "Blocked while exporting.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        # Every item was reused, so an unchanged replacement finalizes inline.
        self.assertEqual(replacement["status"], "published")
        self.assertEqual(edit.status_code, 200, edit.text)

        # A changed revision creates real export work; its terminal failure
        # leaves the just-published predecessor untouched.
        current = self.evidence()
        self.judgments[0] = edit.json()
        pending = self.publish([0, 1, 2], replaces=replacement["id"]).json()
        blocked = self.client_for(self.coach).patch(
            f"/v1/judgments/{self.judgments[0]['id']}",
            headers={"If-Match": '"2"'},
            json={
                "verdict": "applied",
                "comment_text": "Still blocked.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    UPDATE app.processing_job SET
                        status = 'failed', attempts = max_attempts, finished_at = now()
                    WHERE review_publication_id = :publication
                      AND status = 'queued'
                """),
                {"publication": pending["id"]},
            )
        failed = self.client_for(self.coach).get(
            f"/v1/review-publications/{pending['id']}"
        )
        self.assertEqual(failed.json()["status"], "failed")
        self.assertEqual(self.evidence(), current)

    def test_cancel_retry_and_withdrawal_fence_old_work(self) -> None:
        first = self.publish([0, 1, 2]).json()
        self.finish(first["id"])
        edited = (
            self.client_for(self.coach)
            .patch(
                f"/v1/judgments/{self.judgments[0]['id']}",
                headers={"If-Match": '"1"'},
                json={
                    "verdict": "applied",
                    "comment_text": "Replacement.",
                    "clip_start_ms": 1000,
                    "clip_end_ms": 2000,
                },
            )
            .json()
        )
        self.judgments[0] = edited
        pending = self.publish([0, 1, 2], replaces=first["id"]).json()
        cancelled = self.client_for(self.coach).post(
            f"/v1/review-publications/{pending['id']}/cancel"
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        retry = self.client_for(self.coach).post(
            f"/v1/review-publications/{pending['id']}/retry"
        )
        self.assertEqual(retry.status_code, 409, retry.text)

        pending2 = self.publish([0, 1, 2], replaces=first["id"]).json()
        withdrawn = self.client_for(self.coach).post(
            f"/v1/judgments/{self.judgments[0]['id']}/withdraw"
        )
        self.assertEqual(withdrawn.status_code, 204, withdrawn.text)
        state = (
            self.client_for(self.coach)
            .get(f"/v1/review-publications/{pending2['id']}")
            .json()
        )
        self.assertEqual(state["status"], "cancelled")
        self.assertFalse(self.admin_finalize(pending2["id"]))
        visible = self.evidence()[0]["items"]
        self.assertEqual(len(visible), 2)

    def admin_finalize(self, publication_id: str) -> bool:
        with self.admin.connect() as connection, connection.begin():
            return bool(
                connection.execute(
                    text("SELECT private.finalize_review_publication(:publication)"),
                    {"publication": publication_id},
                ).scalar_one()
            )

    def test_player_clip_signing_is_current_object_only_and_expires_closed(
        self,
    ) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        item = self.evidence()[0]["items"][0]
        with mock.patch.object(
            storage, "sign_player_get", return_value="https://object.test/signed"
        ) as signer:
            response = self.client_for(self.player_account).post(
                f"/v1/me/judgments/{item['judgment_id']}/clip-url",
                json={"expected_published_revision_id": item["published_revision_id"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["expires_in"], 300)
        key = signer.call_args.args[0]
        self.assertTrue(key.startswith("clips/"))
        self.assertNotIn("playback/", key)

        denied = self.client_for(self.other_player_account).post(
            f"/v1/me/judgments/{item['judgment_id']}/clip-url",
            json={"expected_published_revision_id": item["published_revision_id"]},
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    UPDATE app.video SET derivatives_expires_at = now()
                    WHERE id = :video
                """),
                {"video": self.video},
            )
        expired = self.client_for(self.player_account).post(
            f"/v1/me/judgments/{item['judgment_id']}/clip-url",
            json={"expected_published_revision_id": item["published_revision_id"]},
        )
        self.assertEqual(expired.status_code, 409, expired.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
