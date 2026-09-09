"""Project 01 roster and development-goal isolation matrix (migration `0004`).

Every assertion runs through the production-equivalent `shoulder_api` login,
never the owner or a superuser. The three refusal shapes stay distinct and are
never substituted for one another:

* a refusal asserts a SQLSTATE, because the statement never reached the table;
* a write a policy filtered out asserts zero affected rows *and* an unchanged
  row read back as the owner;
* an invisible row asserts an empty result, so an unauthorized identity cannot
  tell a hidden row from a missing one.

Names come from `docs/projects/project-01-roster-goals.md`, section
Shared Contracts, and are frozen: the snapshot suite fails when a later
migration widens a policy, a grant, or a helper.
"""

import unittest
from typing import Any
from uuid import UUID, uuid4

from isolation_fixtures import IsolationHarness
from sqlalchemy import text
from test_database import CONFIGURED, DatabaseTestCase

# An RLS `WITH CHECK` violation and a missing column privilege both report
# insufficient_privilege; either way no row is written.
DENIED = "42501"
DUPLICATE = "23505"
CHECK_VIOLATION = "23514"
INVALID_PARAMETER = "22023"
# PL/pgSQL `no_data_found`: the address has no account yet (ADR 0017).
NO_ACCOUNT = "P0002"

INSERT_PLAYER = (
    "INSERT INTO app.player (team_id, display_name, jersey_number, position)"
    " VALUES (:team, :name, :jersey, :position)"
)
INSERT_GOAL = (
    "INSERT INTO app.development_goal (player_id, title, created_by)"
    " VALUES (:player, :title, :author)"
)
LINK = "SELECT private.link_player_account(:player, :email)"
ARCHIVE = "UPDATE app.player SET active = false, deleted_at = now() WHERE id = :row"

GOAL_COLUMNS = {
    "id",
    "player_id",
    "title",
    "description",
    "ontology_key",
    "status",
    "created_by",
    "created_at",
    "closed_at",
}

# (table, policy, command, roles) exactly as migration 0004 leaves them.
EXPECTED_POLICIES = {
    ("player", "player_owner_maintenance", "ALL", "{shoulder_migration}"),
    ("player", "player_visible_select", "SELECT", "{shoulder_api}"),
    ("player", "player_coach_insert", "INSERT", "{shoulder_api}"),
    ("player", "player_coach_update", "UPDATE", "{shoulder_api}"),
    (
        "development_goal",
        "development_goal_owner_maintenance",
        "ALL",
        "{shoulder_migration}",
    ),
    ("development_goal", "development_goal_coach_select", "SELECT", "{shoulder_api}"),
    ("development_goal", "development_goal_coach_insert", "INSERT", "{shoulder_api}"),
    ("development_goal", "development_goal_coach_update", "UPDATE", "{shoulder_api}"),
    ("development_goal", "development_goal_player_select", "SELECT", "{shoulder_api}"),
}

# Column-level grants, not policy predicates, are what stop a coach moving a
# player between teams or linking an account outside the helper.
EXPECTED_INSERT_COLUMNS = {
    "player": {"team_id", "display_name", "jersey_number", "position"},
    "development_goal": GOAL_COLUMNS,
}
EXPECTED_UPDATE_COLUMNS = {
    "player": {"display_name", "jersey_number", "position", "active", "deleted_at"},
    "development_goal": {"title", "description", "ontology_key", "status", "closed_at"},
}

# proname -> (identity arguments, volatility)
NEW_HELPERS = {
    "is_player_coach": ("uuid", "s"),
    "is_player_self": ("uuid", "s"),
    "link_player_account": ("uuid, text", "v"),
}


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class PlayerWriteTests(IsolationHarness):
    """Migration `0004` roster writes, through the runtime role only."""

    def insert_player_as(
        self, coach: UUID, team: UUID, name: str, jersey: int | None = None
    ) -> UUID:
        created = self.read_as(
            coach,
            INSERT_PLAYER + " RETURNING id",
            team=team,
            name=name,
            jersey=jersey,
            position=None,
        )
        self.assertEqual(len(created), 1)
        return UUID(str(created[0]))

    def test_coach_inserts_only_onto_their_own_team(self) -> None:
        world = self.world
        row = self.insert_player_as(world.a.coach, world.a.id, "New A", 11)
        self.assertIn(row, self.read_as(world.a.coach, "SELECT id FROM app.player"))
        cases = (
            (world.a.coach, world.b.id),
            (world.b.coach, world.a.id),
            (world.a.players[0], world.a.id),
            (world.unlinked, world.a.id),
            (None, world.a.id),
        )
        for identity, team in cases:
            with self.subTest(identity=str(identity)):
                self.assertEqual(
                    self.refused_as(
                        identity,
                        INSERT_PLAYER,
                        team=team,
                        name="Intruder",
                        jersey=None,
                        position=None,
                    ),
                    DENIED,
                )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.player WHERE display_name = 'Intruder'"
            ),
            [(0,)],
        )

    def test_insert_cannot_link_an_account(self) -> None:
        """`user_id` is not insertable, so linking needs the definer helper."""
        world = self.world
        statement = (
            "INSERT INTO app.player (team_id, display_name, user_id)"
            " VALUES (:team, 'Self linked', :account)"
        )
        for account in (world.a.coach, world.unlinked):
            with self.subTest(account=str(account)):
                self.assertEqual(
                    self.refused_as(
                        world.a.coach, statement, team=world.a.id, account=account
                    ),
                    DENIED,
                )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.player WHERE display_name = 'Self linked'"
            ),
            [(0,)],
        )

    def test_coach_updates_the_granted_columns_on_their_own_roster(self) -> None:
        world = self.world
        self.assertEqual(
            self.write_as(
                world.a.coach,
                "UPDATE app.player SET display_name = :name, jersey_number = :jersey,"
                " position = :position, active = false, deleted_at = now()"
                " WHERE id = :row",
                name="Renamed A1",
                jersey=21,
                position="RB",
                row=world.a.rows[0],
            ),
            1,
        )
        self.assertEqual(
            self.admin_read(
                "SELECT display_name, jersey_number, position, active,"
                " deleted_at IS NOT NULL FROM app.player WHERE id = :row",
                row=world.a.rows[0],
            ),
            [("Renamed A1", 21, "RB", False, True)],
        )

    def test_another_team_and_the_player_cannot_update_a_row(self) -> None:
        world = self.world
        statement = "UPDATE app.player SET display_name = 'Changed' WHERE id = :row"
        for identity in (world.b.coach, world.a.players[0], world.unlinked, None):
            with self.subTest(identity=str(identity)):
                # The policy filters the row out of the scan, so the statement
                # succeeds against nothing rather than raising.
                self.assertEqual(
                    self.write_as(identity, statement, row=world.a.rows[0]), 0
                )
        self.assertEqual(
            self.admin_read(
                "SELECT display_name FROM app.player WHERE id = :row",
                row=world.a.rows[0],
            ),
            [("Player A1",)],
        )

    def test_no_identity_can_move_a_player_or_link_an_account(self) -> None:
        world = self.world
        cases = (("team_id", world.b.id), ("user_id", world.unlinked))
        identities = (
            world.a.coach,
            world.b.coach,
            world.a.players[0],
            world.unlinked,
        )
        for column, value in cases:
            for identity in identities:
                with self.subTest(column=column, identity=str(identity)):
                    self.assertEqual(
                        self.refused_as(
                            identity,
                            f"UPDATE app.player SET {column} = :value WHERE id = :row",
                            value=value,
                            row=world.a.rows[0],
                        ),
                        DENIED,
                    )
        self.assertEqual(
            self.admin_read(
                "SELECT team_id, user_id FROM app.player WHERE id = :row",
                row=world.a.rows[0],
            ),
            [(world.a.id, world.a.players[0])],
        )

    def test_duplicate_active_jersey_is_scoped_to_the_team(self) -> None:
        world = self.world
        first = self.insert_player_as(world.a.coach, world.a.id, "Seven A", 7)
        # The same number on the other team is a different roster slot.
        self.insert_player_as(world.b.coach, world.b.id, "Seven B", 7)
        self.assertEqual(
            self.refused_as(
                world.a.coach,
                INSERT_PLAYER,
                team=world.a.id,
                name="Seven again",
                jersey=7,
                position=None,
            ),
            DUPLICATE,
        )
        self.assertEqual(self.write_as(world.a.coach, ARCHIVE, row=first), 1)
        # Archiving frees the number for the next player.
        self.insert_player_as(world.a.coach, world.a.id, "Seven again", 7)

    def test_no_identity_can_delete_a_player(self) -> None:
        world = self.world
        for identity in (
            world.a.coach,
            world.b.coach,
            world.a.players[0],
            world.unlinked,
        ):
            with self.subTest(identity=str(identity)):
                self.assertEqual(
                    self.refused_as(
                        identity,
                        "DELETE FROM app.player WHERE id = :row",
                        row=world.a.rows[0],
                    ),
                    DENIED,
                )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.player WHERE id = :row", row=world.a.rows[0]
            ),
            [(1,)],
        )


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class LinkPlayerAccountTests(IsolationHarness):
    """`private.link_player_account` is the only path from roster to account."""

    def fresh_email(self) -> str:
        return f"{uuid4().hex[:8]}.linked@example.test"

    def link_as(self, identity: UUID, player_row: UUID, email: str) -> UUID:
        returned = self.read_as(identity, LINK, player=player_row, email=email)
        self.assertEqual(len(returned), 1)
        return UUID(str(returned[0]))

    def test_linking_resolves_the_account_and_its_player_membership(self) -> None:
        world = self.world
        email = self.emails[world.unlinked]
        # Mixed case proves the helper normalizes before it resolves.
        account = self.link_as(world.a.coach, world.unlinked_row, email.upper())
        self.assertEqual(account, world.unlinked)
        self.assertEqual(
            self.admin_read(
                "SELECT user_id FROM app.player WHERE id = :row",
                row=world.unlinked_row,
            ),
            [(account,)],
        )
        # Same transaction: the membership exists as soon as the call returns.
        self.assertEqual(
            self.admin_read(
                "SELECT role FROM app.team_membership"
                " WHERE team_id = :team AND user_id = :account",
                team=world.a.id,
                account=account,
            ),
            [("player",)],
        )
        # Linking resolves an account; it never mints a second one.
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.user_account WHERE email = :email",
                email=email,
            ),
            [(1,)],
        )

    def test_an_address_without_an_account_is_refused(self) -> None:
        """ADR 0017: the helper links only. Task 20 owns identity creation."""
        world = self.world
        email = self.fresh_email()
        self.assertEqual(
            self.refused_as(
                world.a.coach, LINK, player=world.unlinked_row, email=email
            ),
            NO_ACCOUNT,
        )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.user_account WHERE email = :email",
                email=email,
            ),
            [(0,)],
        )
        self.assertEqual(
            self.admin_read(
                "SELECT user_id FROM app.player WHERE id = :row",
                row=world.unlinked_row,
            ),
            [(None,)],
        )

    def test_only_the_players_own_coach_may_link(self) -> None:
        world = self.world
        cases = (
            (world.b.coach, world.unlinked_row),
            (world.a.players[0], world.unlinked_row),
            (world.a.players[0], world.a.rows[0]),
            (world.unlinked, world.unlinked_row),
            (None, world.unlinked_row),
        )
        for identity, row in cases:
            with self.subTest(identity=str(identity)):
                # A usable address, so authorization is the only reason to fail.
                self.assertEqual(
                    self.refused_as(
                        identity, LINK, player=row, email=self.emails[world.unlinked]
                    ),
                    DENIED,
                )
        self.assertEqual(
            self.admin_read(
                "SELECT user_id FROM app.player WHERE id = :row",
                row=world.unlinked_row,
            ),
            [(None,)],
        )

    def test_a_second_link_for_a_row_or_a_team_is_refused(self) -> None:
        world = self.world
        self.assertEqual(
            self.refused_as(
                world.a.coach,
                LINK,
                player=world.a.rows[0],
                email=self.emails[world.unlinked],
            ),
            DUPLICATE,
        )
        self.assertEqual(
            self.refused_as(
                world.a.coach,
                LINK,
                player=world.unlinked_row,
                email=self.emails[world.a.players[0]],
            ),
            DUPLICATE,
        )
        # A refused link leaves neither half of the transaction behind.
        self.assertEqual(
            self.admin_read(
                "SELECT user_id FROM app.player WHERE id = :row",
                row=world.unlinked_row,
            ),
            [(None,)],
        )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.team_membership"
                " WHERE team_id = :team AND user_id = :account",
                team=world.a.id,
                account=world.a.players[0],
            ),
            [(1,)],
        )

    def test_an_invalid_address_is_refused(self) -> None:
        world = self.world
        addresses: tuple[str | None, ...] = ("not-an-email", "", "   ", None)
        for email in addresses:
            with self.subTest(email=email):
                self.assertEqual(
                    self.refused_as(
                        world.a.coach, LINK, player=world.unlinked_row, email=email
                    ),
                    INVALID_PARAMETER,
                )


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class DevelopmentGoalTests(IsolationHarness):
    """One active goal per player, authored by that player's coach."""

    def setUp(self) -> None:
        super().setUp()
        world = self.world
        # Fixtures are written through the runtime role, so the coach INSERT
        # policy is exercised before any read assertion depends on it.
        self.goal_a1 = self.insert_goal(world.a.coach, world.a.rows[0], "Back foot")
        self.goal_a2 = self.insert_goal(world.a.coach, world.a.rows[1], "First touch")
        self.goal_b1 = self.insert_goal(world.b.coach, world.b.rows[0], "Scanning")

    def insert_goal(self, coach: UUID, player_row: UUID, title: str) -> UUID:
        created = self.read_as(
            coach,
            INSERT_GOAL + " RETURNING id",
            player=player_row,
            title=title,
            author=coach,
        )
        self.assertEqual(len(created), 1)
        return UUID(str(created[0]))

    def test_only_the_players_coach_inserts_a_goal(self) -> None:
        world = self.world
        for identity in (world.b.coach, world.a.players[0], world.unlinked, None):
            with self.subTest(identity=str(identity)):
                self.assertEqual(
                    self.refused_as(
                        identity,
                        INSERT_GOAL,
                        player=world.a.rows[0],
                        title="Not yours",
                        author=identity,
                    ),
                    DENIED,
                )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.development_goal WHERE title = 'Not yours'"
            ),
            [(0,)],
        )

    def test_the_author_must_be_the_caller(self) -> None:
        world = self.world
        for author in (world.b.coach, world.a.players[0], world.unlinked):
            with self.subTest(author=str(author)):
                self.assertEqual(
                    self.refused_as(
                        world.a.coach,
                        INSERT_GOAL,
                        player=world.unlinked_row,
                        title="Spoofed author",
                        author=author,
                    ),
                    DENIED,
                )

    def test_one_active_goal_per_player(self) -> None:
        world = self.world
        self.assertEqual(
            self.refused_as(
                world.a.coach,
                INSERT_GOAL,
                player=world.a.rows[0],
                title="Second active",
                author=world.a.coach,
            ),
            DUPLICATE,
        )
        self.assertEqual(
            self.write_as(
                world.a.coach,
                "UPDATE app.development_goal SET status = 'achieved',"
                " closed_at = now() WHERE id = :goal",
                goal=self.goal_a1,
            ),
            1,
        )
        # A closed goal frees the slot; the partial unique index is on active.
        self.insert_goal(world.a.coach, world.a.rows[0], "Next goal")

    def test_status_and_closed_at_stay_coherent(self) -> None:
        statements = (
            "UPDATE app.development_goal SET status = 'achieved' WHERE id = :goal",
            "UPDATE app.development_goal SET closed_at = now() WHERE id = :goal",
            "UPDATE app.development_goal SET status = 'bogus' WHERE id = :goal",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                self.assertEqual(
                    self.refused_as(self.world.a.coach, statement, goal=self.goal_a1),
                    CHECK_VIOLATION,
                )

    def test_coach_reads_and_updates_only_their_own_teams_goals(self) -> None:
        world = self.world
        self.assertCountEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.development_goal"),
            [self.goal_a1, self.goal_a2],
        )
        self.assertEqual(
            self.read_as(world.b.coach, "SELECT id FROM app.development_goal"),
            [self.goal_b1],
        )
        statement = (
            "UPDATE app.development_goal SET title = 'Rewritten' WHERE id = :goal"
        )
        self.assertEqual(self.write_as(world.b.coach, statement, goal=self.goal_a1), 0)
        self.assertEqual(
            self.admin_read(
                "SELECT title FROM app.development_goal WHERE id = :goal",
                goal=self.goal_a1,
            ),
            [("Back foot",)],
        )
        self.assertEqual(self.write_as(world.a.coach, statement, goal=self.goal_a1), 1)

    def test_player_reads_only_their_own_goal(self) -> None:
        world = self.world
        for account, goal in (
            (world.a.players[0], self.goal_a1),
            (world.a.players[1], self.goal_a2),
            (world.b.players[0], self.goal_b1),
        ):
            with self.subTest(account=str(account)):
                self.assertEqual(
                    self.read_as(account, "SELECT id FROM app.development_goal"), [goal]
                )
        by_id = "SELECT id FROM app.development_goal WHERE id = :goal"
        # A teammate's goal must read exactly like a goal that does not exist.
        for hidden in (self.goal_a2, self.goal_b1):
            with self.subTest(hidden=str(hidden)):
                self.assertEqual(
                    self.read_as(world.a.players[0], by_id, goal=hidden),
                    self.read_as(world.a.players[0], by_id, goal=uuid4()),
                )

    def test_a_player_cannot_write_any_goal(self) -> None:
        world = self.world
        player = world.a.players[0]
        self.assertEqual(
            self.write_as(
                player,
                "UPDATE app.development_goal SET title = 'Mine now' WHERE id = :goal",
                goal=self.goal_a1,
            ),
            0,
        )
        self.assertEqual(
            self.refused_as(
                player,
                INSERT_GOAL,
                player=world.a.rows[0],
                title="Self authored",
                author=player,
            ),
            DENIED,
        )
        self.assertEqual(
            self.admin_read(
                "SELECT title FROM app.development_goal WHERE id = :goal",
                goal=self.goal_a1,
            ),
            [("Back foot",)],
        )

    def test_an_unlinked_account_sees_no_goal(self) -> None:
        self.assertEqual(
            self.read_as(self.world.unlinked, "SELECT id FROM app.development_goal"), []
        )

    def test_revoked_membership_hides_the_goal(self) -> None:
        """A player removed from the team loses their goal, as `app.player` does.

        `player_visible_select` has required `private.is_team_member` since
        `0002`, so a revoked player cannot read their own roster row. A goal
        must not outlive that: it is coach-authored text about the player.
        """
        world = self.world
        self.revoke_membership(world.a.id, world.a.players[0])
        self.assertEqual(
            self.read_as(world.a.players[0], "SELECT id FROM app.development_goal"), []
        )
        # The coach still owns the record; only the player's view is gone.
        self.assertIn(
            self.goal_a1,
            self.read_as(world.a.coach, "SELECT id FROM app.development_goal"),
        )

    def test_an_archived_or_pending_player_loses_their_goal(self) -> None:
        world = self.world
        for column in ("deleted_at", "deletion_pending_at"):
            with self.subTest(column=column):
                self.set_player_timestamp(world.a.rows[0], column, "now()")
                self.assertEqual(
                    self.read_as(
                        world.a.players[0], "SELECT id FROM app.development_goal"
                    ),
                    [],
                )
                self.assertIn(
                    self.goal_a1,
                    self.read_as(world.a.coach, "SELECT id FROM app.development_goal"),
                )
                self.set_player_timestamp(world.a.rows[0], column, "NULL")
                self.assertEqual(
                    self.read_as(
                        world.a.players[0], "SELECT id FROM app.development_goal"
                    ),
                    [self.goal_a1],
                )

    def set_player_timestamp(self, row: UUID, column: str, value: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(f"UPDATE app.player SET {column} = {value} WHERE id = :row"),
                {"row": row},
            )

    def test_no_identity_can_delete_or_reassign_a_goal(self) -> None:
        world = self.world
        identities = (
            world.a.coach,
            world.b.coach,
            world.a.players[0],
            world.unlinked,
        )
        cases: tuple[tuple[str, str, dict[str, object]], ...] = (
            ("delete", "DELETE FROM app.development_goal WHERE id = :goal", {}),
            (
                "player_id",
                "UPDATE app.development_goal SET player_id = :value WHERE id = :goal",
                {"value": world.b.rows[0]},
            ),
            (
                "created_by",
                "UPDATE app.development_goal SET created_by = :value WHERE id = :goal",
                {"value": world.b.coach},
            ),
            (
                "id",
                "UPDATE app.development_goal SET id = :value WHERE id = :goal",
                {"value": uuid4()},
            ),
            (
                "created_at",
                "UPDATE app.development_goal SET created_at = now() WHERE id = :goal",
                {},
            ),
        )
        for name, statement, parameters in cases:
            for identity in identities:
                with self.subTest(column=name, identity=str(identity)):
                    self.assertEqual(
                        self.refused_as(
                            identity, statement, goal=self.goal_a1, **parameters
                        ),
                        DENIED,
                    )
        self.assertEqual(
            self.admin_read(
                "SELECT player_id, created_by FROM app.development_goal"
                " WHERE id = :goal",
                goal=self.goal_a1,
            ),
            [(world.a.rows[0], world.a.coach)],
        )

    def test_deleting_the_player_row_cascades_the_goal(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.player WHERE id = :row"),
                {"row": self.world.a.rows[0]},
            )
        self.assertEqual(
            self.admin_read(
                "SELECT count(*) FROM app.development_goal WHERE id = :goal",
                goal=self.goal_a1,
            ),
            [(0,)],
        )


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class RosterPolicySurfaceTests(DatabaseTestCase):
    """Snapshots that fail when `0004` policies, grants or helpers widen."""

    def roster_columns(self) -> list[Any]:
        with self.admin.connect() as connection:
            return list(
                connection.execute(
                    text("""
                    SELECT c.relname, a.attname,
                           has_column_privilege('shoulder_api', c.oid, a.attnum,
                                                'SELECT') AS may_select,
                           has_column_privilege('shoulder_api', c.oid, a.attnum,
                                                'INSERT') AS may_insert,
                           has_column_privilege('shoulder_api', c.oid, a.attnum,
                                                'UPDATE') AS may_update
                    FROM pg_class c
                    JOIN pg_attribute a ON a.attrelid = c.oid
                    WHERE c.relnamespace = 'app'::regnamespace
                      AND c.relname IN ('player', 'development_goal')
                      AND a.attnum > 0 AND NOT a.attisdropped
                """)
                ).all()
            )

    def test_roster_policy_set_matches_the_frozen_matrix(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT tablename, policyname, cmd, roles::text, qual, with_check,
                           permissive
                    FROM pg_policies
                    WHERE schemaname = 'app'
                      AND tablename IN ('player', 'development_goal')
                """)
            ).all()
        self.assertCountEqual(
            [(r.tablename, r.policyname, r.cmd, r.roles) for r in rows],
            EXPECTED_POLICIES,
        )
        for row in rows:
            with self.subTest(policy=row.policyname):
                self.assertEqual(row.permissive, "PERMISSIVE")
                if row.roles == "{shoulder_migration}":
                    self.assertEqual(row.qual, "true")
                    self.assertEqual(row.with_check, "true")
                elif row.cmd == "SELECT":
                    self.assertTrue(row.qual)
                    self.assertIsNone(row.with_check)
                else:
                    # A runtime write policy must constrain the new row.
                    self.assertTrue(row.with_check)
                    self.assertEqual(row.qual is None, row.cmd == "INSERT")

    def test_runtime_column_privileges_match_the_frozen_grants(self) -> None:
        rows = self.roster_columns()
        self.assertEqual(
            {r.attname for r in rows if r.relname == "development_goal"}, GOAL_COLUMNS
        )
        for table in ("player", "development_goal"):
            columns = [r for r in rows if r.relname == table]
            with self.subTest(table=table):
                self.assertEqual(
                    {r.attname for r in columns if r.may_insert},
                    EXPECTED_INSERT_COLUMNS[table],
                )
                self.assertEqual(
                    {r.attname for r in columns if r.may_update},
                    EXPECTED_UPDATE_COLUMNS[table],
                )
                # Reads stay table-wide; the policies do the narrowing.
                self.assertTrue(all(r.may_select for r in columns))

    def test_runtime_holds_no_delete_or_structural_privilege(self) -> None:
        with self.admin.connect() as connection:
            for table in ("app.player", "app.development_goal"):
                for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    with self.subTest(table=table, privilege=privilege):
                        self.assertFalse(
                            connection.execute(
                                text(
                                    "SELECT has_table_privilege('shoulder_api',"
                                    " :table, :privilege)"
                                ),
                                {"table": table, "privilege": privilege},
                            ).scalar_one()
                        )

    def test_new_helpers_are_definer_stable_and_runtime_executable(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT p.proname, p.prosecdef, p.provolatile,
                        p.proacl IS NULL AS default_acl,
                        pg_get_function_identity_arguments(p.oid) AS arguments,
                        has_function_privilege('shoulder_api', p.oid, 'EXECUTE')
                            AS runtime
                    FROM pg_proc p
                    WHERE p.pronamespace = 'private'::regnamespace
                      AND p.proname = ANY(:names)
                """),
                {"names": sorted(NEW_HELPERS)},
            ).all()
        self.assertEqual({r.proname for r in rows}, set(NEW_HELPERS))
        for row in rows:
            with self.subTest(function=row.proname):
                arguments, volatility = NEW_HELPERS[row.proname]
                self.assertEqual(row.arguments, arguments)
                self.assertEqual(row.provolatile, volatility)
                self.assertTrue(row.prosecdef)
                self.assertTrue(row.runtime)
                # A NULL ACL would leave EXECUTE with PUBLIC by default.
                self.assertFalse(row.default_acl)

    def test_browser_roles_and_public_reach_nothing_new(self) -> None:
        with self.admin.connect() as connection:
            public_table = connection.execute(
                text("""
                    SELECT count(*) FROM pg_class c,
                         unnest(coalesce(c.relacl, '{}'::aclitem[])) AS entry
                    WHERE c.oid = 'app.development_goal'::regclass
                      AND entry::text LIKE '=%'
                """)
            ).scalar_one()
            self.assertEqual(public_table, 0)
            public_functions = connection.execute(
                text("""
                    SELECT count(*) FROM pg_proc p,
                         unnest(coalesce(p.proacl, '{}'::aclitem[])) AS entry
                    WHERE p.pronamespace = 'private'::regnamespace
                      AND p.proname = ANY(:names) AND entry::text LIKE '=%'
                """),
                {"names": sorted(NEW_HELPERS)},
            ).scalar_one()
            self.assertEqual(public_functions, 0)
            for role in ("anon", "authenticated"):
                for table in ("app.player", "app.development_goal"):
                    for privilege in ("SELECT", "INSERT", "UPDATE"):
                        with self.subTest(role=role, table=table, privilege=privilege):
                            # Column-level grants would not show in a table check.
                            self.assertFalse(
                                connection.execute(
                                    text(
                                        "SELECT has_any_column_privilege(:role,"
                                        " :table, :privilege)"
                                    ),
                                    {
                                        "role": role,
                                        "table": table,
                                        "privilege": privilege,
                                    },
                                ).scalar_one()
                            )
                executable = connection.execute(
                    text("""
                        SELECT count(*) FROM pg_proc p
                        WHERE p.pronamespace = 'private'::regnamespace
                          AND p.proname = ANY(:names)
                          AND has_function_privilege(:role, p.oid, 'EXECUTE')
                    """),
                    {"role": role, "names": sorted(NEW_HELPERS)},
                ).scalar_one()
                self.assertEqual(executable, 0, role)

    def test_development_goal_indexes_and_row_level_security(self) -> None:
        with self.admin.connect() as connection:
            indexes = (
                connection.execute(
                    text("""
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'app' AND tablename = 'development_goal'
                """)
                )
                .scalars()
                .all()
            )
            table = connection.execute(
                text("""
                    SELECT relrowsecurity, relforcerowsecurity,
                           relowner::regrole::text AS owner
                    FROM pg_class WHERE oid = 'app.development_goal'::regclass
                """)
            ).one()
        self.assertEqual(
            set(indexes),
            {
                "development_goal_pkey",
                "development_goal_player_id_idx",
                "development_goal_created_by_idx",
                "development_goal_active_key",
            },
        )
        self.assertEqual(
            (table.relrowsecurity, table.relforcerowsecurity, table.owner),
            (True, True, "shoulder_migration"),
        )
