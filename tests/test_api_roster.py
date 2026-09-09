"""Project 01 roster and development-goal routes against the real runtime role.

These run through `shoulder_api`, the same `NOBYPASSRLS` login production uses,
so a 403 or 404 here is the database's answer and not the API's opinion. Token
verification itself is covered by `tests/test_auth.py`; the verified subject is
injected so the database-derived answer is what is under test.

Requires migration `0004` and the URLs `scripts/check-db.ps1` provides.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from services.api.auth import authenticated_identity, get_verifier
from services.api.main import app

# `unittest discover -s tests` puts this directory on the path; a direct
# `python -m unittest tests.test_api_roster` does not.
sys.path.append(str(Path(__file__).resolve().parent))

from test_database import (  # noqa: E402
    ADMIN_URL,
    REQUIRED,
    RUNTIME_URL,
    DatabaseTestCase,
)


class ConfigurationTests(unittest.TestCase):
    def test_api_roster_tests_are_configured_where_required(self) -> None:
        """This suite must never be skipped where a database is required."""
        if REQUIRED:
            self.assertTrue(ADMIN_URL, "MIGRATION_DATABASE_URL is required")
            self.assertTrue(RUNTIME_URL, "DATABASE_URL is required")
            self.assertFalse(
                getattr(RosterApiTests, "__unittest_skip__", False),
                "the roster API suite must run where a database is required",
            )


class RosterApiTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("roster.coach@example.test", "Coach A")
        self.other_coach = self.create_auth_user("roster.coach.b@example.test", "B")
        self.player = self.create_auth_user("roster.player@example.test", "Player A1")
        self.team = self.admin_insert_team(self.coach, "Roster FC")
        self.other_team = self.admin_insert_team(self.other_coach, "Other FC")
        self.player_row = self.admin_insert_player(
            self.team, user_id=self.player, display_name="Player A1", jersey_number=7
        )
        self.unlinked_row = self.admin_insert_player(
            self.team, display_name="Unlinked A2", jersey_number=8
        )
        self.other_row = self.admin_insert_player(
            self.other_team, display_name="Player B1", jersey_number=9
        )
        self.add_membership(self.team, self.player, "player")

    def add_membership(self, team_id: UUID, user_id: UUID, role: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, :role)
                """),
                {"team": team_id, "user": user_id, "role": role},
            )

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def linked_account(self, player_row: UUID) -> UUID | None:
        """Owner read-back: the link and its membership, or None for neither."""
        with self.admin.connect() as connection:
            linked = connection.execute(
                text("SELECT user_id FROM app.player WHERE id = :row"),
                {"row": player_row},
            ).scalar_one()
            if linked is None:
                return None
            membership = connection.execute(
                text(
                    "SELECT count(*) FROM app.team_membership m"
                    " JOIN app.player p ON p.team_id = m.team_id"
                    " WHERE p.id = :row AND m.user_id = :user AND m.role = 'player'"
                ),
                {"row": player_row, "user": linked},
            ).scalar_one()
            self.assertEqual(membership, 1, "link and membership must be atomic")
            return UUID(str(linked))

    def count_players(self, team_id: UUID) -> int:
        with self.admin.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM app.player"
                        " WHERE team_id = :team AND deleted_at IS NULL"
                    ),
                    {"team": team_id},
                ).scalar_one()
            )

    def goal_for(self, player_row: UUID, **overrides: Any) -> str:
        body = {"title": "Receive on the back foot", **overrides}
        created = self.client_for(self.coach).post(
            f"/v1/players/{player_row}/goals", json=body
        )
        self.assertEqual(created.status_code, 201, created.text)
        return str(created.json()["id"])

    # --- authentication and authorization ---------------------------------

    def test_every_route_requires_a_verified_identity(self) -> None:
        os.environ["SUPABASE_AUTH_ISSUER"] = "http://127.0.0.1:54321/auth/v1"
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = "local-placeholder"
        get_verifier.cache_clear()
        self.addCleanup(get_verifier.cache_clear)
        self.addCleanup(os.environ.pop, "SUPABASE_AUTH_ISSUER", None)
        self.addCleanup(os.environ.pop, "SUPABASE_PUBLISHABLE_KEY", None)
        client = TestClient(app)
        for method, path, body in (
            ("get", "/v1/teams", None),
            ("get", f"/v1/teams/{self.team}/players", None),
            ("post", f"/v1/teams/{self.team}/players", {"display_name": "X"}),
            (
                "post",
                f"/v1/teams/{self.team}/players/bulk",
                {"rows": [{"display_name": "X"}]},
            ),
            ("patch", f"/v1/players/{self.player_row}", {"display_name": "X"}),
            (
                "post",
                f"/v1/players/{self.player_row}/invite",
                {"email": "someone@example.test"},
            ),
            ("post", f"/v1/players/{self.player_row}/archive", None),
            ("post", f"/v1/players/{self.player_row}/goals", {"title": "X"}),
            ("get", f"/v1/players/{self.player_row}/goals", None),
            ("patch", f"/v1/goals/{uuid4()}", {"status": "paused"}),
        ):
            with self.subTest(path=path, method=method):
                response = client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_player_cannot_use_a_coach_route_on_a_visible_row(self) -> None:
        client = self.client_for(self.player)
        # The player can see this row through RLS, so this is 403, not 404.
        self.assertEqual(
            client.get(f"/v1/players/{self.player_row}/goals").status_code, 200
        )
        for method, path, body in (
            ("patch", f"/v1/players/{self.player_row}", {"display_name": "Renamed"}),
            ("post", f"/v1/players/{self.player_row}/archive", None),
            ("post", f"/v1/players/{self.player_row}/goals", {"title": "Mine"}),
            (
                "post",
                f"/v1/players/{self.player_row}/invite",
                {"email": "self@example.test"},
            ),
            ("get", f"/v1/teams/{self.team}/players", None),
        ):
            with self.subTest(path=path, method=method):
                response = client.request(method, path, json=body)
                self.assertEqual(response.status_code, 403, response.text)

    def test_coach_outside_the_team_gets_not_found(self) -> None:
        client = self.client_for(self.other_coach)
        for method, path, body in (
            ("patch", f"/v1/players/{self.player_row}", {"display_name": "Renamed"}),
            ("post", f"/v1/players/{self.player_row}/archive", None),
            ("post", f"/v1/players/{self.player_row}/goals", {"title": "Theirs"}),
            ("get", f"/v1/players/{self.player_row}/goals", None),
            ("get", f"/v1/teams/{self.team}/players", None),
            ("post", f"/v1/teams/{self.team}/players", {"display_name": "Theirs"}),
        ):
            with self.subTest(path=path, method=method):
                response = client.request(method, path, json=body)
                self.assertEqual(response.status_code, 404, response.text)

    def test_a_problem_body_is_rfc9457_and_leaks_nothing(self) -> None:
        response = self.client_for(self.other_coach).patch(
            f"/v1/players/{self.player_row}", json={"display_name": "Renamed"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        body = response.json()
        self.assertEqual(
            sorted(body), ["detail", "instance", "status", "title", "type"]
        )
        self.assertTrue(body["type"].startswith("https://shoulder.local/problems/"))
        self.assertEqual(body["status"], 404)
        for leak in ("Player A1", "@", "app.player", "23505", "SELECT"):
            self.assertNotIn(leak, response.text)

    # --- reading the roster ------------------------------------------------

    def test_teams_and_roster_read_back_for_the_coach(self) -> None:
        client = self.client_for(self.coach)
        teams = client.get("/v1/teams")
        self.assertEqual(teams.status_code, 200)
        self.assertEqual(
            [(team["team_id"], team["role"]) for team in teams.json()],
            [(str(self.team), "coach")],
        )
        roster = client.get(f"/v1/teams/{self.team}/players")
        self.assertEqual(roster.status_code, 200)
        rows = roster.json()
        self.assertEqual([row["jersey_number"] for row in rows], [7, 8])
        # Only `private.team_roster` can expose a linked account's name, and
        # never an address; an unlinked row reads back null.
        self.assertEqual(
            [row["account_name"] for row in rows],
            ["Player A1", None],
        )
        self.assertNotIn("@", roster.text)
        self.assertIsNone(rows[0]["active_goal"])

    # --- creating and editing roster rows ----------------------------------

    def test_create_player_collects_no_address(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/teams/{self.team}/players",
            json={"display_name": "New Player", "jersey_number": 11, "position": "GK"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertIsNone(body["account_name"])
        self.assertTrue(body["active"])
        self.assertEqual(self.count_players(self.team), 3)

    def test_duplicate_active_jersey_is_a_conflict(self) -> None:
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/teams/{self.team}/players",
            json={"display_name": "Clash", "jersey_number": 7},
        )
        self.assertEqual(created.status_code, 409, created.text)
        patched = client.patch(
            f"/v1/players/{self.unlinked_row}", json={"jersey_number": 7}
        )
        self.assertEqual(patched.status_code, 409, patched.text)

    def test_field_validation_is_unprocessable(self) -> None:
        client = self.client_for(self.coach)
        for body in (
            {"display_name": ""},
            {"display_name": "x" * 81},
            {"display_name": "Ok", "jersey_number": 100},
            {"display_name": "Ok", "jersey_number": -1},
            {"display_name": "Ok", "position": "p" * 41},
        ):
            with self.subTest(body=body):
                response = client.post(f"/v1/teams/{self.team}/players", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        # An empty patch changes nothing and is refused rather than ignored.
        self.assertEqual(
            client.patch(f"/v1/players/{self.unlinked_row}", json={}).status_code, 422
        )

    def test_patch_updates_only_the_fields_sent(self) -> None:
        response = self.client_for(self.coach).patch(
            f"/v1/players/{self.unlinked_row}", json={"position": "CB"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["position"], "CB")
        self.assertEqual(body["display_name"], "Unlinked A2")
        self.assertEqual(body["jersey_number"], 8)

    # --- bulk ---------------------------------------------------------------

    def test_bulk_preview_writes_nothing(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/teams/{self.team}/players/bulk",
            json={
                "commit": False,
                "rows": [
                    {"display_name": "Preview One", "jersey_number": 21},
                    {"display_name": "Preview Two", "jersey_number": 22},
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["committed"])
        self.assertEqual(body["created"], [])
        self.assertEqual([row["errors"] for row in body["rows"]], [[], []])
        self.assertEqual(self.count_players(self.team), 2)

    def test_bulk_commit_with_one_bad_row_writes_nothing(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/teams/{self.team}/players/bulk",
            json={
                "commit": True,
                "rows": [
                    {"display_name": "Valid One", "jersey_number": 21},
                    {"display_name": "", "jersey_number": 22},
                    {"display_name": "Taken", "jersey_number": 7},
                    {"display_name": "Repeat", "jersey_number": 21},
                ],
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        body = response.json()
        self.assertFalse(body["committed"])
        self.assertEqual(body["created"], [])
        self.assertEqual(
            [row["errors"] for row in body["rows"]],
            [
                [],
                ["display_name_length"],
                ["jersey_number_taken"],
                ["jersey_number_duplicate_in_request"],
            ],
        )
        self.assertEqual(self.count_players(self.team), 2)

    def test_bulk_commit_writes_every_valid_row(self) -> None:
        rows = [
            {"display_name": f"Bulk {index}", "jersey_number": 20 + index}
            for index in range(20)
        ]
        response = self.client_for(self.coach).post(
            f"/v1/teams/{self.team}/players/bulk", json={"commit": True, "rows": rows}
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["committed"])
        self.assertEqual(len(body["created"]), 20)
        self.assertEqual(self.count_players(self.team), 22)

    def test_bulk_rejects_an_oversized_request(self) -> None:
        response = self.client_for(self.coach).post(
            f"/v1/teams/{self.team}/players/bulk",
            json={
                "commit": False,
                "rows": [{"display_name": f"Row {index}"} for index in range(41)],
            },
        )
        self.assertEqual(response.status_code, 422)

    # --- invitation ---------------------------------------------------------

    def test_invite_links_an_existing_account_and_its_membership(self) -> None:
        invitee = self.create_auth_user("roster.invitee@example.test", "Invitee")
        response = self.client_for(self.coach).post(
            f"/v1/players/{self.unlinked_row}/invite",
            json={"email": self.emails[invitee]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["user_id"], str(invitee))
        self.assertEqual(body["player_id"], str(self.unlinked_row))
        with self.admin.connect() as connection:
            linked = connection.execute(
                text("SELECT user_id FROM app.player WHERE id = :id"),
                {"id": self.unlinked_row},
            ).scalar_one()
            role = connection.execute(
                text("""
                    SELECT role FROM app.team_membership
                    WHERE team_id = :team AND user_id = :user
                """),
                {"team": self.team, "user": invitee},
            ).scalar_one()
        self.assertEqual(UUID(str(linked)), invitee)
        self.assertEqual(role, "player")

    def test_invite_refuses_an_address_with_no_account_yet(self) -> None:
        """ADR 0017: invitation links; it never creates an Auth identity."""
        response = self.client_for(self.coach).post(
            f"/v1/players/{self.unlinked_row}/invite",
            json={"email": f"new.{uuid4().hex[:8]}@example.test"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["type"],
            "https://shoulder.local/problems/invitation-account-not-found",
        )
        # Nothing was written: the row is still unlinked and has no membership.
        self.assertIsNone(self.linked_account(self.unlinked_row))

    def test_invite_refuses_a_linked_player_and_a_bad_address(self) -> None:
        client = self.client_for(self.coach)
        already = client.post(
            f"/v1/players/{self.player_row}/invite",
            json={"email": self.emails[self.coach]},
        )
        self.assertEqual(already.status_code, 409, already.text)
        self.assertEqual(
            client.post(
                f"/v1/players/{self.unlinked_row}/invite",
                json={"email": "not-an-email"},
            ).status_code,
            422,
        )

    def test_invite_names_an_off_roster_player_rather_than_calling_it_linked(
        self,
    ) -> None:
        """An archived player is refused, and the reason is the true one.

        `private.link_player_account` folds "already linked", "archived", and
        "deletion pending" into one branch, so the database alone would tell a
        coach a player is linked to an account when they are not.
        """
        client = self.client_for(self.coach)
        self.assertEqual(
            client.post(f"/v1/players/{self.unlinked_row}/archive").status_code, 200
        )
        response = client.post(
            f"/v1/players/{self.unlinked_row}/invite",
            json={"email": self.emails[self.player]},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["type"],
            "https://shoulder.local/problems/player-off-roster",
        )
        # Refused before any write: the row is still unlinked.
        self.assertIsNone(self.linked_account(self.unlinked_row))

    def test_archived_players_are_reachable_only_when_asked_for(self) -> None:
        """Archiving is soft, so an archived player must stay retrievable.

        The roster screen renders them as a section and links to their detail
        page; if the list could never return them again, the copy promising
        nothing is deleted would be false.
        """
        client = self.client_for(self.coach)
        self.assertEqual(
            client.post(f"/v1/players/{self.unlinked_row}/archive").status_code, 200
        )
        default = client.get(f"/v1/teams/{self.team}/players")
        self.assertEqual(default.status_code, 200)
        self.assertNotIn(str(self.unlinked_row), [row["id"] for row in default.json()])
        included = client.get(
            f"/v1/teams/{self.team}/players", params={"include_archived": "true"}
        )
        self.assertEqual(included.status_code, 200)
        archived = [row for row in included.json() if not row["active"]]
        self.assertEqual([row["id"] for row in archived], [str(self.unlinked_row)])
        # Active rows still sort first, so the roster screen groups them.
        self.assertTrue(included.json()[0]["active"])
        # The goals of an archived player remain readable to their coach.
        self.assertEqual(
            client.get(f"/v1/players/{self.unlinked_row}/goals").status_code, 200
        )

    def test_an_archived_linked_player_still_reads_as_linked(self) -> None:
        """`private.team_roster` hides archived rows, but the link is real.

        Reporting only `account_name` would call a linked player unlinked and
        offer to link them again, which `player-off-roster` then refuses.
        """
        client = self.client_for(self.coach)
        roster = client.get(f"/v1/teams/{self.team}/players").json()
        linked = next(row for row in roster if row["id"] == str(self.player_row))
        self.assertTrue(linked["account_linked"])
        self.assertEqual(linked["account_name"], "Player A1")

        self.assertEqual(
            client.post(f"/v1/players/{self.player_row}/archive").status_code, 200
        )
        included = client.get(
            f"/v1/teams/{self.team}/players", params={"include_archived": "true"}
        ).json()
        archived = next(row for row in included if row["id"] == str(self.player_row))
        self.assertFalse(archived["active"])
        # The name is withheld by the helper; the link itself is still reported.
        self.assertIsNone(archived["account_name"])
        self.assertTrue(archived["account_linked"])

    def test_names_are_stored_trimmed_by_every_write_path(self) -> None:
        """Bulk trims, so the single routes must trim identically."""
        client = self.client_for(self.coach)
        created = client.post(
            f"/v1/teams/{self.team}/players",
            json={"display_name": "  Spaced Name  ", "position": "  Winger  "},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["display_name"], "Spaced Name")
        self.assertEqual(created.json()["position"], "Winger")
        patched = client.patch(
            f"/v1/players/{created.json()['id']}",
            json={"display_name": "  Retrimmed  "},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["display_name"], "Retrimmed")

    # --- archive ------------------------------------------------------------

    def test_archive_is_soft_and_idempotent(self) -> None:
        client = self.client_for(self.coach)
        first = client.post(f"/v1/players/{self.unlinked_row}/archive")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["active"])
        second = client.post(f"/v1/players/{self.unlinked_row}/archive")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        with self.admin.connect() as connection:
            still_there = connection.execute(
                text("SELECT count(*) FROM app.player WHERE id = :id"),
                {"id": self.unlinked_row},
            ).scalar_one()
        self.assertEqual(still_there, 1)
        # The archived row leaves the roster but the shirt number is free again.
        self.assertEqual(len(client.get(f"/v1/teams/{self.team}/players").json()), 1)
        reused = client.post(
            f"/v1/teams/{self.team}/players",
            json={"display_name": "Replacement", "jersey_number": 8},
        )
        self.assertEqual(reused.status_code, 201, reused.text)

    # --- development goals ---------------------------------------------------

    def test_goal_is_created_and_read_by_the_coach_and_the_player(self) -> None:
        goal_id = self.goal_for(self.player_row)
        coach_view = self.client_for(self.coach).get(
            f"/v1/players/{self.player_row}/goals"
        )
        self.assertEqual([goal["id"] for goal in coach_view.json()], [goal_id])
        player_view = self.client_for(self.player).get(
            f"/v1/players/{self.player_row}/goals"
        )
        self.assertEqual(player_view.status_code, 200)
        self.assertEqual([goal["id"] for goal in player_view.json()], [goal_id])
        roster = self.client_for(self.coach).get(f"/v1/teams/{self.team}/players")
        self.assertEqual(roster.json()[0]["active_goal"]["id"], goal_id)

    def test_a_second_active_goal_is_a_conflict(self) -> None:
        self.goal_for(self.player_row)
        second = self.client_for(self.coach).post(
            f"/v1/players/{self.player_row}/goals", json={"title": "Another"}
        )
        self.assertEqual(second.status_code, 409, second.text)

    def test_goal_transitions_follow_the_table(self) -> None:
        client = self.client_for(self.coach)
        goal_id = self.goal_for(self.player_row)
        paused = client.patch(f"/v1/goals/{goal_id}", json={"status": "paused"})
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertIsNotNone(paused.json()["closed_at"])
        # Paused frees the active slot, so a new goal may be created.
        replacement = self.goal_for(self.player_row, title="Replacement goal")
        # ...and re-activating the paused one is refused while that goal is active.
        clash = client.patch(f"/v1/goals/{goal_id}", json={"status": "active"})
        self.assertEqual(clash.status_code, 409, clash.text)
        retired = client.patch(f"/v1/goals/{replacement}", json={"status": "retired"})
        self.assertEqual(retired.status_code, 200, retired.text)
        reactivated = client.patch(f"/v1/goals/{goal_id}", json={"status": "active"})
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        self.assertIsNone(reactivated.json()["closed_at"])

    def test_terminal_and_repeated_statuses_are_refused(self) -> None:
        client = self.client_for(self.coach)
        goal_id = self.goal_for(self.player_row)
        self.assertEqual(
            client.patch(
                f"/v1/goals/{goal_id}", json={"status": "achieved"}
            ).status_code,
            200,
        )
        for status in ("active", "paused", "retired", "achieved"):
            with self.subTest(status=status):
                response = client.patch(f"/v1/goals/{goal_id}", json={"status": status})
                self.assertEqual(response.status_code, 409, response.text)

    def test_goal_field_validation_and_editing(self) -> None:
        client = self.client_for(self.coach)
        goal_id = self.goal_for(self.player_row)
        for body in ({"title": ""}, {"title": "x" * 101}, {}, {"status": "unknown"}):
            with self.subTest(body=body):
                response = client.patch(f"/v1/goals/{goal_id}", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        renamed = client.patch(f"/v1/goals/{goal_id}", json={"title": "Renamed goal"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["title"], "Renamed goal")
        self.assertEqual(renamed.json()["status"], "active")

    def test_goal_creation_validates_its_fields(self) -> None:
        client = self.client_for(self.coach)
        for body in (
            {"title": ""},
            {"title": "x" * 101},
            {"title": "Ok", "description": "d" * 1001},
            {"title": "Ok", "ontology_key": "k" * 81},
        ):
            with self.subTest(body=body):
                response = client.post(
                    f"/v1/players/{self.player_row}/goals", json=body
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_a_missing_goal_is_not_found(self) -> None:
        response = self.client_for(self.coach).patch(
            f"/v1/goals/{uuid4()}", json={"status": "paused"}
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
