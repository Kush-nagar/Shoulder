"""Block 09B W3 coach training plans (migration 0018).

Validation tests run anywhere. Isolation runs through `shoulder_api` (RLS) at
the database and API layers and needs the local database from
`scripts/check-db.ps1`.
"""

import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.main import app
from services.api.plan_service import monday
from services.api.schemas import TrainingPlanCreate, TrainingPlanPatch

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import DatabaseTestCase, sqlstate  # noqa: E402

ITEMS = [{"drill_slug": "two-look-receive", "note": "Twice before every pass."}]


class PlanValidationTests(unittest.TestCase):
    def test_week_snaps_to_monday(self) -> None:
        self.assertEqual(monday(date(2026, 9, 24)), date(2026, 9, 21))
        self.assertEqual(monday(date(2026, 9, 21)), date(2026, 9, 21))
        self.assertEqual(monday(date(2026, 9, 27)), date(2026, 9, 21))

    def test_items_are_bounded(self) -> None:
        base = {"title": "Week", "week_of": "2026-09-21"}
        TrainingPlanCreate.model_validate({**base, "items": ITEMS * 8})
        for items in (
            [],
            ITEMS * 9,
            [{"drill_slug": "Bad Slug"}],
            [{"drill_slug": "ok", "note": "x" * 201}],
            [{"drill_slug": "ok", "extra": 1}],
        ):
            with self.subTest(items=items), self.assertRaises(ValidationError):
                TrainingPlanCreate.model_validate({**base, "items": items})
        with self.assertRaises(ValidationError):
            TrainingPlanCreate.model_validate({**base, "title": "", "items": ITEMS})

    def test_patch_needs_a_change_and_cannot_clear(self) -> None:
        for body in ({}, {"title": None}, {"items": None}, {"player_id": None}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                TrainingPlanPatch.model_validate(body)
        TrainingPlanPatch.model_validate({"title": "New"})


class PlanIsolationTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("plan.coach@example.test", "Coach")
        self.other_coach = self.create_auth_user("plan.other@example.test", "Other")
        self.user_a = self.create_auth_user("plan.a@example.test", "Player A")
        self.user_b = self.create_auth_user("plan.b@example.test", "Player B")
        self.user_x = self.create_auth_user("plan.x@example.test", "Player X")
        self.team = self.admin_insert_team(self.coach, "Plans FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Rivals FC")
        self.player_a = self.linked_player(self.team, self.user_a, 7)
        self.player_b = self.linked_player(self.team, self.user_b, 8)
        self.player_x = self.linked_player(self.other_team, self.user_x, 9)
        self.plan_a = self.admin_plan(self.team, self.player_a)
        self.plan_b = self.admin_plan(self.team, self.player_b)
        self.plan_team = self.admin_plan(self.team, None)
        self.plan_other = self.admin_plan(self.other_team, None)

    def linked_player(self, team: UUID, user_id: UUID, jersey: int) -> UUID:
        player = self.admin_insert_player(
            team, user_id=user_id, display_name=f"P{jersey}", jersey_number=jersey
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

    def admin_plan(self, team: UUID, player: UUID | None) -> UUID:
        coach = self.coach if team == self.team else self.other_coach
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.training_plan
                                (team_id, player_id, created_by, title, week_of, items)
                            VALUES (:team, :player, :coach, 'Week plan',
                                    DATE '2026-09-21', CAST(:items AS jsonb))
                            RETURNING id
                        """),
                        {
                            "team": team,
                            "player": player,
                            "coach": coach,
                            "items": '[{"drill_slug": "gate-scan", "note": ""}]',
                        },
                    ).scalar_one()
                )
            )

    def visible(self, user_id: UUID) -> set[UUID]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            return {
                UUID(str(row.id))
                for row in connection.execute(text("SELECT id FROM app.training_plan"))
            }

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    # -- database layer -------------------------------------------------------

    def test_database_reads_are_isolated(self) -> None:
        self.assertEqual(self.visible(self.user_a), {self.plan_a, self.plan_team})
        self.assertEqual(self.visible(self.user_b), {self.plan_b, self.plan_team})
        self.assertEqual(self.visible(self.user_x), {self.plan_other})
        self.assertEqual(
            self.visible(self.coach), {self.plan_a, self.plan_b, self.plan_team}
        )
        self.assertEqual(self.visible(self.other_coach), {self.plan_other})

    def test_database_writes_are_coach_only_and_same_team(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.user_a)
            changed = connection.execute(
                text("UPDATE app.training_plan SET title = 'x' WHERE id = :id"),
                {"id": self.plan_a},
            ).rowcount
            deleted = connection.execute(
                text("DELETE FROM app.training_plan WHERE id = :id"),
                {"id": self.plan_team},
            ).rowcount
            self.as_user(connection, self.other_coach)
            changed += connection.execute(
                text("UPDATE app.training_plan SET title = 'x' WHERE id = :id"),
                {"id": self.plan_a},
            ).rowcount
        self.assertEqual((changed, deleted), (0, 0))
        insert = """
            INSERT INTO app.training_plan
                (team_id, player_id, created_by, title, week_of, items)
            VALUES (:team, :player, :author, 't', DATE '2026-09-21',
                    '[{"drill_slug": "gate-scan"}]')
        """
        for user, team, player, author in (
            # A player cannot write a plan, even for themself.
            (self.user_a, self.team, self.player_a, self.user_a),
            # A coach cannot write into another team.
            (self.coach, self.other_team, None, self.coach),
            # Nor aim their own team's plan at another team's player.
            (self.coach, self.team, self.player_x, self.coach),
            # Nor file it under another author.
            (self.coach, self.team, None, self.other_coach),
        ):
            with self.subTest(user=user, team=team, player=player):
                with self.assertRaises(DBAPIError) as caught:
                    with self.runtime.connect() as connection, connection.begin():
                        self.as_user(connection, user)
                        connection.execute(
                            text(insert),
                            {
                                "team": team,
                                "player": player,
                                "author": author,
                            },
                        )
                self.assertEqual(sqlstate(caught.exception), "42501")

    # -- API layer ------------------------------------------------------------

    def test_api_player_reads_only_own_and_team_plans(self) -> None:
        listed = self.client_for(self.user_a).get("/v1/player/plans")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            {UUID(item["id"]) for item in listed.json()}, {self.plan_a, self.plan_team}
        )
        self.assertEqual(
            self.client_for(self.coach).get("/v1/player/plans").status_code, 403
        )

    def test_api_player_cannot_manage_plans(self) -> None:
        client = self.client_for(self.user_a)
        self.assertEqual(client.get(f"/v1/teams/{self.team}/plans").status_code, 403)
        self.assertEqual(
            client.post(
                f"/v1/teams/{self.team}/plans",
                json={"title": "t", "week_of": "2026-09-21", "items": ITEMS},
            ).status_code,
            403,
        )
        for plan, status in ((self.plan_team, 403), (self.plan_b, 404)):
            with self.subTest(plan=plan):
                self.assertEqual(
                    client.patch(f"/v1/plans/{plan}", json={"title": "x"}).status_code,
                    status,
                )
                self.assertEqual(client.delete(f"/v1/plans/{plan}").status_code, status)

    def test_api_coach_round_trip_and_cross_team_refusal(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/teams/{self.team}/plans",
            json={
                "title": "Scanning week",
                "week_of": "2026-09-24",
                "player_id": str(self.player_a),
                "items": ITEMS,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        body: dict[str, Any] = created.json()
        self.assertEqual(body["week_of"], "2026-09-21")
        plan_id = body["id"]
        patched = client.patch(f"/v1/plans/{plan_id}", json={"title": "Renamed"})
        self.assertEqual(patched.json()["title"], "Renamed")
        listed = {
            item["id"] for item in client.get(f"/v1/teams/{self.team}/plans").json()
        }
        self.assertIn(plan_id, listed)
        self.assertNotIn(str(self.plan_other), listed)
        self.assertEqual(client.delete(f"/v1/plans/{plan_id}").status_code, 204)

        # Another team's player, plan, or team is refused.
        refused = client.post(
            f"/v1/teams/{self.team}/plans",
            json={
                "title": "t",
                "week_of": "2026-09-21",
                "player_id": str(self.player_x),
                "items": ITEMS,
            },
        )
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(
            client.get(f"/v1/teams/{self.other_team}/plans").status_code, 403
        )
        self.assertEqual(
            client.patch(
                f"/v1/plans/{self.plan_other}", json={"title": "x"}
            ).status_code,
            404,
        )
        self.assertEqual(client.delete(f"/v1/plans/{self.plan_other}").status_code, 404)
        self.assertIn(self.plan_other, self.visible(self.other_coach))

    def test_erasing_a_player_removes_their_plans(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.player WHERE id = :id"), {"id": self.player_a}
            )
        self.assertEqual(self.visible(self.coach), {self.plan_b, self.plan_team})

    def test_unknown_plan_is_not_found(self) -> None:
        response = self.client_for(self.coach).delete(f"/v1/plans/{uuid4()}")
        self.assertEqual(response.status_code, 404)
