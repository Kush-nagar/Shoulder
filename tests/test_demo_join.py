"""Public-demo self-join (ADR 0021): `private.demo_join` and `POST /v1/demo/join`.

Runs through the `shoulder_api` login like every isolation suite.
"""

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.demo_routes import demo_team_id
from services.api.main import app

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

GOAL_TITLE = "Check your shoulder before you receive"


class DemoConfigTests(unittest.TestCase):
    def test_demo_is_off_unless_explicitly_on_with_a_team(self) -> None:
        team = str(uuid4())
        for env, expected in (
            ({}, None),
            ({"DEMO_TEAM_ID": team}, None),
            ({"DEMO_MODE": "off", "DEMO_TEAM_ID": team}, None),
            ({"DEMO_MODE": "on"}, None),
            ({"DEMO_MODE": "on", "DEMO_TEAM_ID": "not-a-uuid"}, None),
            ({"DEMO_MODE": "on", "DEMO_TEAM_ID": team}, UUID(team)),
        ):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=False):
                for key in ("DEMO_MODE", "DEMO_TEAM_ID"):
                    if key not in env:
                        os.environ.pop(key, None)
                self.assertEqual(demo_team_id(), expected)

    def test_join_is_404_when_disabled(self) -> None:
        app.dependency_overrides[authenticated_identity] = lambda: str(uuid4())
        self.addCleanup(app.dependency_overrides.clear)
        with patch.dict(os.environ, {"DEMO_MODE": ""}):
            response = TestClient(app).post("/v1/demo/join")
        self.assertEqual(response.status_code, 404)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class DemoJoinDatabaseTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.coach = self.create_auth_user("demo.coach@example.test")
        self.team = self.admin_insert_team(self.coach, "Demo FC test")
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.team SET age_group = 'DEMO' WHERE id = :id"),
                {"id": self.team},
            )

    def join(self, user_id: UUID, team_id: UUID | None = None) -> UUID | None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            value = connection.execute(
                text("SELECT private.demo_join(:team)"),
                {"team": str(team_id or self.team)},
            ).scalar_one()
        return None if value is None else UUID(str(value))

    def counts(self, user_id: UUID) -> tuple[int, int, int]:
        with self.admin.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT
                      (SELECT count(*) FROM app.team_membership
                        WHERE user_id = :u AND team_id = :t AND role = 'player'),
                      (SELECT count(*) FROM app.player
                        WHERE user_id = :u AND team_id = :t),
                      (SELECT count(*) FROM app.development_goal g
                        JOIN app.player p ON p.id = g.player_id
                        WHERE p.user_id = :u AND g.status = 'active'
                          AND g.title = :title AND g.created_by = :coach)
                """),
                {
                    "u": user_id,
                    "t": self.team,
                    "title": GOAL_TITLE,
                    "coach": self.coach,
                },
            ).one()
        return (row[0], row[1], row[2])

    def test_join_creates_one_membership_player_and_goal(self) -> None:
        visitor = self.create_auth_user("demo.visitor@example.test", "Visitor Name")
        player_id = self.join(visitor)
        self.assertIsNotNone(player_id)
        self.assertEqual(self.counts(visitor), (1, 1, 1))
        with self.admin.connect() as connection:
            name = connection.execute(
                text("SELECT display_name FROM app.player WHERE id = :id"),
                {"id": player_id},
            ).scalar_one()
        # Fixed, non-identifying: neither the real name nor the email.
        self.assertEqual(name, "Demo player")

    def test_join_is_idempotent(self) -> None:
        visitor = self.create_auth_user("demo.again@example.test")
        first = self.join(visitor)
        self.assertEqual(self.join(visitor), first)
        self.assertEqual(self.counts(visitor), (1, 1, 1))

    def test_concurrent_joins_create_one_player(self) -> None:
        visitor = self.create_auth_user("demo.race@example.test")
        barrier = Barrier(4)

        def race() -> UUID | None:
            barrier.wait()
            return self.join(visitor)

        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: race(), range(4)))
        self.assertEqual(len(set(results)), 1)
        self.assertIsNotNone(results[0])
        self.assertEqual(self.counts(visitor), (1, 1, 1))

    def test_non_demo_team_is_refused(self) -> None:
        other_coach = self.create_auth_user("demo.realcoach@example.test")
        real_team = self.admin_insert_team(other_coach, "Real FC")
        visitor = self.create_auth_user("demo.intruder@example.test")
        for team in (real_team, uuid4()):
            with self.subTest(team=team):
                with self.assertRaises(DBAPIError) as caught:
                    self.join(visitor, team)
                self.assertEqual(sqlstate(caught.exception), "42501")
        with self.admin.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT (SELECT count(*) FROM app.team_membership"
                        " WHERE user_id = :u)"
                        " + (SELECT count(*) FROM app.player WHERE user_id = :u)"
                    ),
                    {"u": visitor},
                ).scalar_one(),
                0,
            )

    def test_existing_coach_gets_nothing(self) -> None:
        other_coach = self.create_auth_user("demo.busycoach@example.test")
        self.admin_insert_team(other_coach, "Busy FC")
        self.assertIsNone(self.join(other_coach))
        self.assertEqual(self.counts(other_coach), (0, 0, 0))
        # The demo team's own coach cannot become a player on it either.
        self.assertIsNone(self.join(self.coach))
        self.assertEqual(self.counts(self.coach), (0, 0, 0))

    def test_missing_identity_joins_nothing(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, None)
            self.assertIsNone(
                connection.execute(
                    text("SELECT private.demo_join(:team)"), {"team": str(self.team)}
                ).scalar_one()
            )

    def test_demo_players_cannot_read_each_other(self) -> None:
        a = self.create_auth_user("demo.a@example.test")
        b = self.create_auth_user("demo.b@example.test")
        player_a, player_b = self.join(a), self.join(b)
        with self.admin.connect() as connection, connection.begin():
            for user, player in ((a, player_a), (b, player_b)):
                connection.execute(
                    text("""
                        INSERT INTO app.practice_video (
                            player_id, created_by_user_id, object_key,
                            content_type, size_bytes
                        ) VALUES (:player, :user, :key, 'video/mp4', 1)
                    """),
                    {"player": player, "user": user, "key": f"demo/{uuid4()}"},
                )
        for user, own, other in ((a, player_a, player_b), (b, player_b, player_a)):
            with self.subTest(user=user):
                with self.runtime.connect() as connection, connection.begin():
                    self.as_user(connection, user)
                    for table, column in (
                        ("app.player", "id"),
                        ("app.development_goal", "player_id"),
                        ("app.practice_video", "player_id"),
                    ):
                        seen = {
                            UUID(str(value))
                            for value in connection.execute(
                                text(f"SELECT {column} FROM {table}")
                            ).scalars()
                        }
                        self.assertIn(own, seen, table)
                        self.assertNotIn(other, seen, table)

    def test_api_join_when_enabled(self) -> None:
        visitor = self.create_auth_user("demo.api@example.test")
        app.dependency_overrides[authenticated_identity] = lambda: str(visitor)
        self.addCleanup(app.dependency_overrides.clear)
        env = {"DEMO_MODE": "on", "DEMO_TEAM_ID": str(self.team)}
        with patch.dict(os.environ, env):
            client = TestClient(app)
            first = client.post("/v1/demo/join")
            second = client.post("/v1/demo/join")
            me = client.get("/v1/me").json()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["cache-control"], "private, no-store")
        self.assertEqual(second.json(), first.json())
        self.assertEqual(me["roles"], ["player"])
        self.assertEqual(me["player"]["id"], first.json()["player_id"])
        # A coach is left alone and told so.
        app.dependency_overrides[authenticated_identity] = lambda: str(self.coach)
        with patch.dict(os.environ, env):
            self.assertEqual(TestClient(app).post("/v1/demo/join").status_code, 409)
