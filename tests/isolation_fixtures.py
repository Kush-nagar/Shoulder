"""Reusable isolation fixtures.

Task 5 owns the harness that later schema tasks extend. A suite builds one
`World` and then asserts authorization through the production-equivalent
`shoulder_api` login, never as the owner or a superuser.

The world is deliberately small and explicit: two teams, two coaches, two
players on each team, an authenticated account linked to
nothing, and one account whose membership is revoked mid-test.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from test_database import DatabaseTestCase


@dataclass(frozen=True)
class Team:
    id: UUID
    coach: UUID
    players: tuple[UUID, ...]
    """Account IDs of linked players, in creation order."""
    rows: tuple[UUID, ...]
    """`app.player` row IDs, in creation order."""


@dataclass(frozen=True)
class World:
    a: Team
    b: Team
    unlinked: UUID
    """Authenticated account with no membership and no player row."""
    unlinked_row: UUID
    """Roster row on team A that no account is linked to."""


class IsolationHarness(DatabaseTestCase):
    """Base for isolation suites. Subclasses get `self.world`."""

    def setUp(self) -> None:
        super().setUp()
        self.world = self.build_world()

    def build_world(self) -> World:
        coach_a = self.create_auth_user("coach.a@example.test", "Coach A")
        coach_b = self.create_auth_user("coach.b@example.test", "Coach B")
        player_a1 = self.create_auth_user("player.a1@example.test", "Player A1")
        player_a2 = self.create_auth_user("player.a2@example.test", "Player A2")
        player_b1 = self.create_auth_user("player.b1@example.test", "Player B1")
        player_b2 = self.create_auth_user("player.b2@example.test", "Player B2")
        unlinked = self.create_auth_user("unlinked@example.test", "Unlinked")

        team_a = self.admin_insert_team(coach_a, "Team A")
        team_b = self.admin_insert_team(coach_b, "Team B")
        row_a1 = self.admin_insert_player(
            team_a, user_id=player_a1, display_name="Player A1", jersey_number=1
        )
        row_a2 = self.admin_insert_player(
            team_a, user_id=player_a2, display_name="Player A2", jersey_number=2
        )
        row_b1 = self.admin_insert_player(
            team_b, user_id=player_b1, display_name="Player B1", jersey_number=1
        )
        row_b2 = self.admin_insert_player(
            team_b, user_id=player_b2, display_name="Player B2", jersey_number=2
        )
        # A roster row a coach created before collecting any address.
        unlinked_row = self.admin_insert_player(
            team_a, display_name="Unlinked roster", jersey_number=3
        )
        for team, account in (
            (team_a, player_a1),
            (team_a, player_a2),
            (team_b, player_b1),
            (team_b, player_b2),
        ):
            self.add_membership(team, account, "player")
        return World(
            a=Team(
                id=team_a,
                coach=coach_a,
                players=(player_a1, player_a2),
                rows=(row_a1, row_a2),
            ),
            b=Team(
                id=team_b,
                coach=coach_b,
                players=(player_b1, player_b2),
                rows=(row_b1, row_b2),
            ),
            unlinked=unlinked,
            unlinked_row=unlinked_row,
        )

    def add_membership(self, team_id: UUID, user_id: UUID, role: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, :role)
                """),
                {"team": team_id, "user": user_id, "role": role},
            )

    def revoke_membership(self, team_id: UUID, user_id: UUID) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    DELETE FROM app.team_membership
                    WHERE team_id = :team AND user_id = :user
                """),
                {"team": team_id, "user": user_id},
            )

    def read_as(
        self, user_id: UUID | str | None, sql: str, **parameters: object
    ) -> list[object]:
        """Run one read through the runtime role as `user_id`."""
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            return list(connection.execute(text(sql), parameters).scalars().all())
