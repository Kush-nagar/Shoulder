"""Task 15 judgment routes against the production-equivalent runtime role."""

import sys
import unittest
from pathlib import Path
from unittest import mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from services.api import judgment_routes
from services.api.auth import authenticated_identity
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase  # noqa: E402


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class JudgmentApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        # See the note in test_database_judgment: `observation_id` is
        # ON DELETE RESTRICT by specification, so a judgment left behind
        # blocks the shared cleanup's team cascade.
        self.addCleanup(self.delete_judgments)
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

    def add_membership(
        self, team_id: UUID, user_id: UUID, role: str = "player"
    ) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, :role)
                """),
                {"team": team_id, "user": user_id, "role": role},
            )

    def delete_judgments(self) -> None:
        """Remove every judgment this test created, revisions cascading."""
        with self.admin.connect() as connection, connection.begin():
            connection.execute(text("DELETE FROM app.judgment"))

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

    def retire_goal(self, goal_id: UUID) -> None:
        """Close a goal, so the player may be given a new active one."""
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    UPDATE app.development_goal
                    SET status = 'retired', closed_at = now()
                    WHERE id = :goal
                """),
                {"goal": goal_id},
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
        self.assertEqual(response.headers["ETag"], '"1"')

    def test_coach_loads_current_judgment_for_an_observation(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        loaded = client.get(
            f"/v1/observations/{self.observation}/judgment?goal_id={self.goal}"
        )
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual(loaded.json(), created.json())
        self.assertEqual(loaded.headers["ETag"], '"1"')

    def test_a_judgment_is_loaded_for_the_goal_that_was_asked_about(self) -> None:
        """One observation can carry a judgment per goal, and did.

        `app.judgment` is unique on (observation_id, goal_id), so a player who
        changes goals keeps the earlier judgment alongside the new one. A
        lookup keyed on the observation alone matched both, raised
        MultipleResultsFound, and the route turned that into a 503 -- the
        coach's draft simply never came back.
        """
        client = self.client_for(self.coach)
        first = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        self.assertEqual(first.status_code, 201, first.text)

        # A player has one active goal at a time, so a second one only exists
        # once the first is closed. That is the path this defect was on: the
        # judgment against the retired goal stays, and the new goal gets its
        # own.
        self.retire_goal(self.goal)
        second_goal = self.admin_insert_goal(self.player, self.coach)
        second = client.post(
            f"/v1/observations/{self.observation}/judgments",
            json=self.payload(goal_id=str(second_goal), comment_text="Second goal."),
        )
        self.assertEqual(second.status_code, 201, second.text)

        for goal, created in ((self.goal, first), (second_goal, second)):
            loaded = client.get(
                f"/v1/observations/{self.observation}/judgment?goal_id={goal}"
            )
            self.assertEqual(loaded.status_code, 200, loaded.text)
            self.assertEqual(loaded.json(), created.json())

    def test_a_judgment_lookup_without_a_goal_is_refused(self) -> None:
        """The goal is part of the question, not an optional narrowing."""
        response = self.client_for(self.coach).get(
            f"/v1/observations/{self.observation}/judgment"
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_missing_observation_judgment_is_an_empty_success(self) -> None:
        response = self.client_for(self.coach).get(
            f"/v1/observations/{self.observation}/judgment?goal_id={self.goal}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json())

    def test_player_cannot_load_a_draft_judgment_by_observation(self) -> None:
        self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        response = self.client_for(self.player_account).get(
            f"/v1/observations/{self.observation}/judgment?goal_id={self.goal}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json())

    def test_a_spoofed_author_is_rejected_not_ignored(self) -> None:
        """Task 15 requires a spoofed author to be rejected.

        Pydantic ignores unknown fields by default, so this used to be
        accepted with 201 and silently dropped. The author was still the
        session's, but a client that believed it had set one was never told
        otherwise, and the same silence hides a typo in a real field.
        """
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json={**self.payload(), "author_user_id": str(self.other_coach)},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_server_managed_fields_cannot_be_set_on_an_edit(self) -> None:
        """Version, pointers and identity are server-managed on a patch too."""
        created = (
            self.client_for(self.coach)
            .post(f"/v1/observations/{self.observation}/judgments", json=self.payload())
            .json()
        )
        for field, value in (
            ("version", 99),
            ("author_user_id", str(self.other_coach)),
            ("publication_status", "published"),
            ("current_revision_id", str(uuid4())),
        ):
            with self.subTest(field=field):
                response = self.client_for(self.coach).patch(
                    f"/v1/judgments/{created['id']}",
                    headers={"If-Match": '"1"'},
                    json={
                        "verdict": "applied",
                        "comment_text": "Trying to set a server field.",
                        "clip_start_ms": 1000,
                        "clip_end_ms": 2000,
                        field: value,
                    },
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_author_is_still_the_session_identity(self) -> None:
        """The session decides the author, on a request that is accepted."""
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
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
        created = (
            self.client_for(self.coach)
            .post(f"/v1/observations/{self.observation}/judgments", json=self.payload())
            .json()
        )
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
        self.assertEqual(response.headers["ETag"], '"2"')

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

    def test_a_conflict_returns_the_latest_coach_authored_snapshot(self) -> None:
        """`docs/04-api.md`: the 409 carries the snapshot it lost to.

        Without it the coach's rejected draft has nothing to be reconciled
        against, and Task 16 has to recover a draft it cannot compare.
        """
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        winner = client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "opportunity",
                "comment_text": "The edit that won.",
                "clip_start_ms": 1200,
                "clip_end_ms": 2400,
            },
        )
        self.assertEqual(winner.status_code, 200, winner.text)

        response = client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "not_relevant",
                "comment_text": "The edit that lost.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        current = response.json()["current"]
        self.assertEqual(current["version"], 2)
        self.assertEqual(current["verdict"], "opportunity")
        self.assertEqual(current["comment_text"], "The edit that won.")
        self.assertEqual(current["clip_start_ms"], 1200)
        self.assertEqual(current["clip_end_ms"], 2400)
        self.assertEqual(current["id"], created["id"])

    def test_the_etag_is_a_quoted_entity_tag_and_round_trips(self) -> None:
        """An HTTP entity-tag is quoted, and a correct client echoes it back.

        Sent bare, a client that echoed `If-Match: "1"` exactly as HTTP
        requires was rejected with 400 — the precondition failing on the
        clients that implement it properly.
        """
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        )
        self.assertEqual(created.headers["ETag"], '"1"')

        edited = client.patch(
            f"/v1/judgments/{created.json()['id']}",
            headers={"If-Match": created.headers["ETag"]},
            json={
                "verdict": "opportunity",
                "comment_text": "Echoed the tag back.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.headers["ETag"], '"2"')

    def test_a_wildcard_or_weak_precondition_is_refused(self) -> None:
        """Each of these is the caller's error, answered before any write.

        The last is past the write function's `bigint`: unbounded it parsed
        here and failed while binding, which the route reported as a 503.
        """
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        for header in ("*", 'W/"1"', "9223372036854775808"):
            with self.subTest(if_match=header):
                response = client.patch(
                    f"/v1/judgments/{created['id']}",
                    headers={"If-Match": header},
                    json={
                        "verdict": "applied",
                        "comment_text": "Should not apply.",
                        "clip_start_ms": 1000,
                        "clip_end_ms": 2000,
                    },
                )
                self.assertEqual(response.status_code, 400, response.text)

    def test_revision_history_is_coach_only(self) -> None:
        """`docs/03-schema.md` makes the history coach-only.

        The player policy on `judgment_revision` grants the one revision a
        judgment publishes, so an endpoint trusting row-level security alone
        would begin answering this route for players the moment Task 17 can
        publish. The service states the coach predicate itself instead.
        """
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": '"1"'},
            json={
                "verdict": "opportunity",
                "comment_text": "A second draft.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )

        coach_history = client.get(f"/v1/judgments/{created['id']}/revisions")
        self.assertEqual(coach_history.status_code, 200, coach_history.text)
        self.assertEqual([r["version"] for r in coach_history.json()], [1, 2])

        for label, actor in (
            ("the player", self.player_account),
            ("another team's coach", self.other_coach),
        ):
            with self.subTest(actor=label):
                response = self.client_for(actor).get(
                    f"/v1/judgments/{created['id']}/revisions"
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), [])

    def test_a_failed_snapshot_read_is_an_outage_not_a_conflict(self) -> None:
        """A database failure must not be flattened into a 409 without one.

        Doing so reports a recoverable conflict at the moment the client most
        needs the snapshot, and hides an outage behind it.
        """
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/observations/{self.observation}/judgments", json=self.payload()
        ).json()
        client.patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": '"1"'},
            json={
                "verdict": "opportunity",
                "comment_text": "The edit that won.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )

        def unavailable_load(*args: object, **kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection lost"))

        with mock.patch.object(
            judgment_routes, "load_judgment_service", unavailable_load
        ):
            response = client.patch(
                f"/v1/judgments/{created['id']}",
                headers={"If-Match": '"1"'},
                json={
                    "verdict": "not_relevant",
                    "comment_text": "The edit that lost.",
                    "clip_start_ms": 1000,
                    "clip_end_ms": 2000,
                },
            )
        self.assertEqual(response.status_code, 503, response.text)

    def test_a_conflict_snapshot_is_not_served_to_another_team(self) -> None:
        """The recovery payload is still a read, decided by row-level security."""
        created = (
            self.client_for(self.coach)
            .post(f"/v1/observations/{self.observation}/judgments", json=self.payload())
            .json()
        )
        response = self.client_for(self.other_coach).patch(
            f"/v1/judgments/{created['id']}",
            headers={"If-Match": "1"},
            json={
                "verdict": "applied",
                "comment_text": "Not mine to touch.",
                "clip_start_ms": 1000,
                "clip_end_ms": 2000,
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("current", response.json())

    def test_only_the_original_author_may_edit(self) -> None:
        created = (
            self.client_for(self.coach)
            .post(f"/v1/observations/{self.observation}/judgments", json=self.payload())
            .json()
        )
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

    def test_an_out_of_range_offset_is_the_caller_s_error_not_an_outage(self) -> None:
        """A PostgreSQL `integer` ceiling, enforced where the caller can see it.

        Unbounded, 2147483648 passed validation and failed while binding the
        write function, which the route reported as 503 -- an outage, for an
        out-of-range field.
        """
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json=self.payload(clip_start_ms=0, clip_end_ms=2147483648),
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_not_relevant_verdict_can_be_created_and_read_back(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/observations/{self.observation}/judgments",
            json=self.payload(verdict="not_relevant"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["verdict"], "not_relevant")
        self.assertEqual(response.json()["publication_status"], "draft")
