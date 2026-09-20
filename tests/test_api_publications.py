"""Tasks 17 and 19 publication, player-media, and reflection acceptance."""

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest import mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402


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
            connection.execute(text("DELETE FROM app.player_reflection_request"))
            connection.execute(text("DELETE FROM app.player_reflection"))
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

    def save_reflection(
        self,
        judgment_id: str,
        reflection_text: str,
        *,
        actor: UUID | None = None,
        key: str | None = None,
        current: dict[str, Any] | None = None,
    ) -> Response:
        return cast(
            Response,
            self.client_for(actor or self.player_account).put(
                f"/v1/me/judgments/{judgment_id}/reflection",
                headers={"Idempotency-Key": key or f"reflection-{uuid4()}"},
                json={
                    "intent": "edit" if current else "create",
                    "text": reflection_text,
                    "expected_reflection_id": current["id"] if current else None,
                    "expected_etag": current["etag"] if current else None,
                    "request_created_at": datetime.now(UTC).isoformat(),
                },
            ),
        )

    def delete_reflection(
        self,
        judgment_id: str,
        current: dict[str, Any],
        *,
        actor: UUID | None = None,
        key: str | None = None,
    ) -> Response:
        return cast(
            Response,
            self.client_for(actor or self.player_account).request(
                "DELETE",
                f"/v1/me/judgments/{judgment_id}/reflection",
                headers={"Idempotency-Key": key or f"delete-{uuid4()}"},
                json={
                    "expected_reflection_id": current["id"],
                    "expected_etag": current["etag"],
                    "request_created_at": datetime.now(UTC).isoformat(),
                },
            ),
        )

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

    def test_reflection_author_crud_coach_read_only_and_other_player_denied(
        self,
    ) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        judgment_id = self.judgments[0]["id"]

        created_response = self.save_reflection(
            judgment_id, "I saw the pass before receiving."
        )
        self.assertEqual(created_response.status_code, 200, created_response.text)
        created = created_response.json()
        own = self.client_for(self.player_account).get("/v1/me/reflections")
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json(), [created])
        coach = self.client_for(self.coach).get(
            f"/v1/players/{self.player}/reflections"
        )
        self.assertEqual(coach.status_code, 200, coach.text)
        self.assertEqual(coach.json(), [created])
        other = self.client_for(self.other_player_account).get("/v1/me/reflections")
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json(), [])

        coach_edit = self.save_reflection(
            judgment_id,
            "Coach must not write this.",
            actor=self.coach,
            current=created,
        )
        self.assertEqual(coach_edit.status_code, 404, coach_edit.text)
        other_edit = self.save_reflection(
            judgment_id,
            "Another player must not write this.",
            actor=self.other_player_account,
            current=created,
        )
        self.assertEqual(other_edit.status_code, 404, other_edit.text)

        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.player_account)
            self.assertEqual(
                connection.execute(
                    text("SELECT id FROM app.player_reflection")
                ).scalar_one(),
                UUID(created["id"]),
            )
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.coach)
            self.assertEqual(
                connection.execute(
                    text("SELECT id FROM app.player_reflection")
                ).scalar_one(),
                UUID(created["id"]),
            )
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.other_player_account)
            self.assertEqual(
                connection.execute(text("SELECT id FROM app.player_reflection")).all(),
                [],
            )
        for actor in (self.player_account, self.coach):
            with self.subTest(actor=str(actor)), self.assertRaises(DBAPIError):
                with self.runtime.connect() as connection, connection.begin():
                    self.as_user(connection, actor)
                    connection.execute(
                        text("UPDATE app.player_reflection SET text = 'bypass'")
                    )
            with self.subTest(marker_actor=str(actor)), self.assertRaises(DBAPIError):
                with self.runtime.connect() as connection, connection.begin():
                    self.as_user(connection, actor)
                    connection.execute(
                        text("SELECT * FROM app.player_reflection_request")
                    ).all()

        edited_response = self.save_reflection(
            judgment_id,
            "I checked both sides first.",
            current=created,
            key="accepted-edit",
        )
        self.assertEqual(edited_response.status_code, 200, edited_response.text)
        edited = edited_response.json()
        self.assertNotEqual(edited["etag"], created["etag"])
        newer_response = self.save_reflection(
            judgment_id, "I checked earlier on the next clip.", current=edited
        )
        self.assertEqual(newer_response.status_code, 200, newer_response.text)
        stale_retry = self.save_reflection(
            judgment_id,
            "I checked both sides first.",
            current=created,
            key="accepted-edit",
        )
        self.assertEqual(stale_retry.status_code, 409, stale_retry.text)
        deleted = self.delete_reflection(judgment_id, newer_response.json())
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(
            self.client_for(self.player_account).get("/v1/me/reflections").json(), []
        )

    def test_reflection_length_duplicate_expiry_and_optional_skip(self) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        judgment_id = self.judgments[0]["id"]
        before = self.evidence()
        for value in ("   ", "x" * 1001):
            with self.subTest(length=len(value)):
                invalid = self.save_reflection(judgment_id, value)
                self.assertEqual(invalid.status_code, 422, invalid.text)
        # The runtime function is a public security boundary too. It must not
        # accept an overlong value whose trimmed length happens to fit.
        with self.assertRaises(DBAPIError) as caught:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, self.player_account)
                connection.execute(
                    text("""
                        SELECT private.save_player_reflection(
                            :judgment, 'create', :reflection_text,
                            NULL, NULL, :created_at, :request_key
                        )
                    """),
                    {
                        "judgment": judgment_id,
                        "reflection_text": "x" + " " * 1000,
                        "created_at": datetime.now(UTC),
                        "request_key": "direct-overlong-reflection",
                    },
                )
        self.assertEqual(sqlstate(caught.exception), "P1902")
        expired = self.client_for(self.player_account).put(
            f"/v1/me/judgments/{judgment_id}/reflection",
            headers={"Idempotency-Key": "expired-reflection"},
            json={
                "intent": "create",
                "text": "This request is too old.",
                "expected_reflection_id": None,
                "expected_etag": None,
                "request_created_at": (
                    datetime.now(UTC) - timedelta(days=8)
                ).isoformat(),
            },
        )
        self.assertEqual(expired.status_code, 422, expired.text)

        first = self.save_reflection(judgment_id, "x" * 1000, key="same-save")
        duplicate = self.save_reflection(judgment_id, "x" * 1000, key="same-save")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(first.json()["id"], duplicate.json()["id"])
        self.assertEqual(first.json()["etag"], duplicate.json()["etag"])
        with self.admin.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM app.player_reflection "
                    "WHERE judgment_id = :judgment"
                ),
                {"judgment": judgment_id},
            ).scalar_one()
        self.assertEqual(count, 1)
        # Playback and navigation evidence remain available without any save;
        # "Skip" is a client-only action and never calls a gating API.
        self.assertEqual(self.evidence(), before)

    def test_reflection_save_delete_race_and_old_retries_do_not_resurrect(
        self,
    ) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        judgment_id = self.judgments[0]["id"]
        create_key = "race-create"
        created = self.save_reflection(
            judgment_id, "Original reflection.", key=create_key
        ).json()

        def edit() -> int:
            return self.save_reflection(
                judgment_id,
                "Concurrent edit.",
                key="race-edit",
                current=created,
            ).status_code

        def delete() -> int:
            return self.delete_reflection(
                judgment_id, created, key="race-delete"
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            edit_future = pool.submit(edit)
            delete_future = pool.submit(delete)
            edit_status = edit_future.result()
            delete_status = delete_future.result()
        self.assertIn((edit_status, delete_status), ((200, 409), (409, 204)))

        current_rows = (
            self.client_for(self.player_account).get("/v1/me/reflections").json()
        )
        if current_rows:
            removed = self.delete_reflection(
                judgment_id, current_rows[0], key="race-cleanup-delete"
            )
            self.assertEqual(removed.status_code, 204, removed.text)

        old_create_retry = self.save_reflection(
            judgment_id, "Original reflection.", key=create_key
        )
        self.assertEqual(old_create_retry.status_code, 409, old_create_retry.text)
        recreated_response = self.save_reflection(
            judgment_id, "Deliberate new reflection.", key="deliberate-new-create"
        )
        self.assertEqual(recreated_response.status_code, 200, recreated_response.text)
        recreated = recreated_response.json()

        old_delete_retry = self.delete_reflection(
            judgment_id, created, key="race-delete"
        )
        # A completed delete replays as 204 without touching the new row. A
        # delete that lost the race was never accepted and must conflict with
        # the deliberate replacement instead.
        expected_retry = 204 if delete_status == 204 else 409
        self.assertEqual(
            old_delete_retry.status_code, expected_retry, old_delete_retry.text
        )
        remaining = (
            self.client_for(self.player_account).get("/v1/me/reflections").json()
        )
        self.assertEqual([row["id"] for row in remaining], [recreated["id"]])

    def test_withdrawn_reflection_remains_manageable_but_cannot_be_recreated(
        self,
    ) -> None:
        publication = self.publish([0, 1, 2]).json()
        self.finish(publication["id"])
        judgment_id = self.judgments[0]["id"]
        created = self.save_reflection(
            judgment_id, "Available before withdrawal."
        ).json()
        withdrawn = self.client_for(self.coach).post(
            f"/v1/judgments/{judgment_id}/withdraw"
        )
        self.assertEqual(withdrawn.status_code, 204, withdrawn.text)

        own = self.client_for(self.player_account).get("/v1/me/reflections").json()
        self.assertEqual(len(own), 1)
        self.assertFalse(own[0]["evidence_available"])
        edited = self.save_reflection(
            judgment_id, "Still mine after withdrawal.", current=created
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(
            edited.json()["judgment_version_at_save"],
            created["judgment_version_at_save"],
        )
        removed = self.delete_reflection(judgment_id, edited.json())
        self.assertEqual(removed.status_code, 204, removed.text)
        forbidden_create = self.save_reflection(
            judgment_id, "Cannot start after withdrawal."
        )
        self.assertEqual(forbidden_create.status_code, 409, forbidden_create.text)

    def test_republish_context_updates_without_reflection_text_history(self) -> None:
        first_publication = self.publish([0, 1, 2]).json()
        self.finish(first_publication["id"])
        judgment_id = self.judgments[0]["id"]
        old_text = "Version one private reflection."
        created = self.save_reflection(judgment_id, old_text).json()
        self.assertEqual(created["judgment_version_at_save"], 1)

        edited_judgment = self.client_for(self.coach).patch(
            f"/v1/judgments/{judgment_id}",
            headers={"If-Match": '"1"'},
            json={
                "verdict": "applied",
                "comment_text": "Republished coach sentence.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(edited_judgment.status_code, 200, edited_judgment.text)
        self.judgments[0] = edited_judgment.json()
        replacement = self.publish([0, 1, 2], replaces=first_publication["id"]).json()
        self.finish(replacement["id"])

        earlier = (
            self.client_for(self.player_account).get("/v1/me/reflections").json()[0]
        )
        self.assertEqual(earlier["current_published_version"], 2)
        self.assertTrue(earlier["is_for_earlier_version"])
        new_text = "Version two private reflection."
        updated = self.save_reflection(judgment_id, new_text, current=earlier).json()
        self.assertEqual(updated["judgment_version_at_save"], 2)
        self.assertFalse(updated["is_for_earlier_version"])

        with self.admin.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT text FROM app.player_reflection "
                        "WHERE judgment_id = :judgment"
                    ),
                    {"judgment": judgment_id},
                )
                .scalars()
                .all()
            )
            marker_columns = (
                connection.execute(
                    text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'app'
                      AND table_name = 'player_reflection_request'
                """)
                )
                .scalars()
                .all()
            )
            longest_marker = connection.execute(
                text("""
                    SELECT max(expires_at - processed_at)
                    FROM app.player_reflection_request
                """)
            ).scalar_one()
        self.assertEqual(rows, [new_text])
        self.assertNotIn(old_text, rows)
        self.assertNotIn("text", marker_columns)
        self.assertNotIn("payload", marker_columns)
        self.assertLessEqual(longest_marker, timedelta(days=7))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
