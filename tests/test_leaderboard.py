"""Block 09B W2 opt-in team leaderboard (ADR 0023).

The board is team-scoped, opt-in, nickname-only, and read through one definer
function that checks membership itself. Isolation runs through `shoulder_api`
(RLS) at both the database and API layers.
"""

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.leaderboard_service import period_start
from services.api.main import app
from services.api.schemas import (
    COORDINATE_PATTERN,
    LeaderboardMembershipUpdate,
    screen_nickname,
)

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

MEMBERSHIP = "/v1/player/leaderboard-membership"


class NicknameTests(unittest.TestCase):
    def test_plain_nicknames_are_accepted_and_spaces_collapse(self) -> None:
        for raw, expected in (
            ("Speedy", "Speedy"),
            ("  Left   Back 7 ", "Left Back 7"),
            ("Cassie", "Cassie"),
            ("Hancock", "Hancock"),
            ("Jo", "Jo"),
            ("Number 10", "Number 10"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    LeaderboardMembershipUpdate(nickname=raw).nickname, expected
                )

    def test_shape_profanity_and_contact_details_are_refused(self) -> None:
        for raw in (
            "a",
            "x" * 21,
            "Kid_99",
            "me@mail.com",
            "site.example",
            "FUCKER",
            "sh1t head",
            "Big Ass",
            "a55",
            "07700 900123",
            "call 555 1234",
            "jo gmail com",
            "www foo com",
            "insta jojo",
            "",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    LeaderboardMembershipUpdate(nickname=raw)
        with self.assertRaises(ValidationError):
            LeaderboardMembershipUpdate.model_validate(
                {"nickname": "Speedy", "display_name": "x"}
            )

    def test_session_notes_refuse_coordinates(self) -> None:
        for note in ("51.50735, -0.12776", "51°30'N 0°7'W", "51.50735N 0.12776W"):
            self.assertIsNotNone(COORDINATE_PATTERN.search(note), note)
        for note in ("Ran 5.2 km", "12.3456 seconds", "Left wing, 2nd half"):
            self.assertIsNone(COORDINATE_PATTERN.search(note), note)

    def test_contact_handles_are_refused(self) -> None:
        for nickname in ("ig jdoe", "Discord x", "insta sam", "kik me"):
            with self.assertRaises(ValueError, msg=nickname):
                screen_nickname(nickname)

    def test_week_starts_monday_utc_and_season_is_a_year(self) -> None:
        now = datetime(2026, 9, 24, 15, 30, tzinfo=UTC)  # a Thursday
        self.assertEqual(period_start("week", now), datetime(2026, 9, 21, tzinfo=UTC))
        self.assertEqual(
            period_start("season", now), datetime(2025, 9, 24, 15, 30, tzinfo=UTC)
        )

    def test_unknown_metric_and_period_are_refused(self) -> None:
        app.dependency_overrides[authenticated_identity] = lambda: str(UUID(int=1))
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)
        path = f"/v1/teams/{UUID(int=2)}/leaderboard"
        self.assertEqual(client.get(path, params={"metric": "rank"}).status_code, 422)
        self.assertEqual(client.get(path, params={"period": "ever"}).status_code, 422)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class LeaderboardTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("board.coach@example.test", "Coach")
        self.other_coach = self.create_auth_user("board.other@example.test", "Oc")
        self.user_a = self.create_auth_user("board.a@example.test", "Alice Real")
        self.user_b = self.create_auth_user("board.b@example.test", "Bob Real")
        self.user_c = self.create_auth_user("board.c@example.test", "Cara Real")
        self.user_x = self.create_auth_user("board.x@example.test", "Xena Real")
        self.team = self.admin_insert_team(self.coach, "Board FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.player_a = self.linked_player(self.team, self.user_a, "Alice Real", 7)
        self.player_b = self.linked_player(self.team, self.user_b, "Bob Real", 8)
        # C never opts in; X opts in on another team.
        self.player_c = self.linked_player(self.team, self.user_c, "Cara Real", 9)
        self.player_x = self.linked_player(self.other_team, self.user_x, "Xena Real", 7)
        self.admin_session(self.player_a, distance=4000, sprints=3, speed=700)
        self.admin_session(self.player_a, distance=3000, sprints=2, speed=650)
        self.admin_session(self.player_b, distance=9000, sprints=1, speed=820)
        self.admin_session(self.player_c, distance=12000, sprints=9, speed=900)
        self.admin_session(self.player_x, distance=15000, sprints=9, speed=900)
        self.opt_in(self.player_a, "Rocket")
        self.opt_in(self.player_b, "Wall")
        self.opt_in(self.player_x, "Far Away")

    def linked_player(self, team: UUID, user_id: UUID, name: str, jersey: int) -> UUID:
        player = self.admin_insert_player(
            team, user_id=user_id, display_name=name, jersey_number=jersey
        )
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": team, "user": user_id},
            )
        return player

    def admin_session(
        self, player: UUID, *, distance: int, sprints: int, speed: int
    ) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.training_session (
                        player_id, kind, started_at, ended_at, duration_s,
                        distance_m, top_speed_cms, sprint_count, heatmap,
                        gps_quality
                    ) VALUES (
                        :player, 'training', now() - interval '61 minutes',
                        now() - interval '1 minute', 3600, :distance, :speed,
                        :sprints, array_fill(0::smallint, ARRAY[96]), 'good'
                    )
                """),
                {
                    "player": player,
                    "distance": distance,
                    "sprints": sprints,
                    "speed": speed,
                },
            )

    def opt_in(self, player: UUID, nickname: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.leaderboard_member (player_id, nickname)
                    VALUES (:player, :nickname)
                """),
                {"player": player, "nickname": nickname},
            )

    def board_as(
        self, user_id: UUID, team: UUID, metric: str = "distance"
    ) -> list[tuple[str, int, bool]]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            rows = connection.execute(
                text("""
                    SELECT nickname, value, is_me FROM private.team_leaderboard(
                        :team, :metric, now() - interval '365 days'
                    )
                """),
                {"team": team, "metric": metric},
            ).all()
        return [(row.nickname, row.value, row.is_me) for row in rows]

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    # -- database layer -------------------------------------------------------

    def test_board_is_opt_in_team_scoped_and_best_first(self) -> None:
        self.assertEqual(
            self.board_as(self.user_a, self.team),
            [("Wall", 9000, False), ("Rocket", 7000, True)],
        )
        self.assertEqual(
            self.board_as(self.user_a, self.team, "sprints"),
            [("Rocket", 5, True), ("Wall", 1, False)],
        )
        self.assertEqual(
            self.board_as(self.user_b, self.team, "top_speed")[0], ("Wall", 820, True)
        )
        self.assertEqual(
            self.board_as(self.user_b, self.team, "sessions"),
            [("Rocket", 2, False), ("Wall", 1, True)],
        )
        # An opted-out teammate sees the board without appearing on it.
        self.assertEqual(
            [row[0] for row in self.board_as(self.user_c, self.team)],
            ["Wall", "Rocket"],
        )
        self.assertEqual(self.board_as(self.user_a, self.team, "rank"), [])

    def test_coach_reads_own_team_and_non_members_read_nothing(self) -> None:
        self.assertEqual(
            [row[:2] for row in self.board_as(self.coach, self.team)],
            [("Wall", 9000), ("Rocket", 7000)],
        )
        self.assertEqual(self.board_as(self.other_coach, self.team), [])
        self.assertEqual(self.board_as(self.user_x, self.team), [])
        self.assertEqual(self.board_as(self.user_a, self.other_team), [])
        self.assertEqual(
            self.board_as(self.user_x, self.other_team), [("Far Away", 15000, True)]
        )

    def test_leaving_or_losing_membership_hides_the_player(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.team_membership WHERE user_id = :user"),
                {"user": self.user_b},
            )
        self.assertEqual(
            self.board_as(self.user_a, self.team), [("Rocket", 7000, True)]
        )
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.user_a)
            connection.execute(text("DELETE FROM app.leaderboard_member"))
        self.assertEqual(self.board_as(self.coach, self.team), [])

    def test_membership_table_is_player_self_only(self) -> None:
        for user, expected in (
            (self.user_a, {"Rocket"}),
            (self.user_c, set()),
            (self.coach, set()),
            (self.other_coach, set()),
        ):
            with self.subTest(user=user):
                with self.runtime.connect() as connection, connection.begin():
                    self.as_user(connection, user)
                    rows = connection.execute(
                        text("SELECT nickname FROM app.leaderboard_member")
                    )
                    self.assertEqual({row.nickname for row in rows}, expected)
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.user_a)
            changed = connection.execute(
                text("UPDATE app.leaderboard_member SET nickname = 'Hacked'")
            ).rowcount
            removed = connection.execute(
                text("DELETE FROM app.leaderboard_member WHERE player_id = :id"),
                {"id": self.player_b},
            ).rowcount
        self.assertEqual((changed, removed), (1, 0))
        for user, player in ((self.user_a, self.player_c), (self.coach, self.player_c)):
            with self.subTest(insert_as=user):
                with self.assertRaises(DBAPIError) as caught:
                    with self.runtime.connect() as connection, connection.begin():
                        self.as_user(connection, user)
                        connection.execute(
                            text("""
                                INSERT INTO app.leaderboard_member (player_id, nickname)
                                VALUES (:id, 'Sneaky')
                            """),
                            {"id": player},
                        )
                self.assertEqual(sqlstate(caught.exception), "42501")

    def test_nickname_check_holds_without_the_api(self) -> None:
        for nickname in ("a", "x" * 21, "me@mail.com", "semi;colon"):
            with self.subTest(nickname=nickname):
                with self.assertRaises(DBAPIError) as caught:
                    self.opt_in(self.player_c, nickname)
                self.assertEqual(sqlstate(caught.exception), "23514")

    def test_player_erasure_cascades(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.player WHERE id = :id"), {"id": self.player_a}
            )
        self.assertEqual(
            [row[0] for row in self.board_as(self.coach, self.team)], ["Wall"]
        )

    # -- API layer ------------------------------------------------------------

    def test_api_join_rename_leave_round_trip(self) -> None:
        client = self.client_for(self.user_c)
        state = client.get(MEMBERSHIP).json()
        self.assertEqual((state["team_id"], state["nickname"]), (str(self.team), None))
        joined = client.put(MEMBERSHIP, json={"nickname": " Quick   Feet "})
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertEqual(joined.json()["nickname"], "Quick Feet")
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "Speedy"}).json()["nickname"],
            "Speedy",
        )
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "shit"}).status_code, 422
        )
        board = client.get(
            f"/v1/teams/{self.team}/leaderboard",
            params={"metric": "distance", "period": "season"},
        )
        self.assertEqual(board.status_code, 200, board.text)
        self.assertEqual(
            board.json()["entries"][0],
            {"nickname": "Speedy", "value": 12000, "is_me": True},
        )
        self.assertEqual(client.delete(MEMBERSHIP).status_code, 204)
        self.assertEqual(client.delete(MEMBERSHIP).status_code, 204)
        self.assertIsNone(client.get(MEMBERSHIP).json()["nickname"])

    def test_api_refuses_real_names_and_teammates_nicknames(self) -> None:
        client = self.client_for(self.user_c)
        # ADR 0023 guardrail 3: the account name and email never become labels.
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "Cara Nine"}).status_code, 422
        )
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "Board C"}).status_code, 422
        )
        # A teammate's nickname, in any case, is taken; another team's is not.
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "rocket"}).status_code, 409
        )
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "Far Away"}).status_code, 200
        )
        # Renaming yourself to your own nickname is not a collision.
        self.assertEqual(
            client.put(MEMBERSHIP, json={"nickname": "Far Away"}).status_code, 200
        )

    def test_api_board_is_nickname_only_and_team_scoped(self) -> None:
        board = self.client_for(self.user_a).get(
            f"/v1/teams/{self.team}/leaderboard", params={"period": "season"}
        )
        self.assertEqual(board.status_code, 200, board.text)
        payload = json.dumps(board.json())
        for leaked in (
            "Alice Real", "Bob Real", "Cara Real", "Far Away",
            str(self.player_a), str(self.player_b), str(self.user_b),
        ):  # fmt: skip
            self.assertNotIn(leaked, payload)
        self.assertEqual(
            self.client_for(self.user_x)
            .get(f"/v1/teams/{self.team}/leaderboard")
            .status_code,
            404,
        )
        self.assertEqual(
            self.client_for(self.other_coach)
            .get(f"/v1/teams/{self.team}/leaderboard")
            .status_code,
            404,
        )
        coach = self.client_for(self.coach).get(f"/v1/teams/{self.team}/leaderboard")
        self.assertEqual(
            [entry["nickname"] for entry in coach.json()["entries"]], ["Wall", "Rocket"]
        )

    def test_coach_has_no_membership_to_manage(self) -> None:
        coach = self.client_for(self.coach)
        self.assertEqual(coach.get(MEMBERSHIP).status_code, 403)
        self.assertEqual(
            coach.put(MEMBERSHIP, json={"nickname": "Boss"}).status_code, 403
        )
        self.assertEqual(coach.delete(MEMBERSHIP).status_code, 403)
