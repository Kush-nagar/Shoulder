"""Task 5 row-level-security matrix and isolation harness.

Every authorization assertion runs through the production-equivalent
`shoulder_api` login. Reads that must be refused assert an empty result rather
than an error, so an unauthorized identity cannot learn whether a row exists;
writes assert `42501`, because the runtime holds no write privilege at all.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from isolation_fixtures import IsolationHarness
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from test_database import CONFIGURED, TABLES, DatabaseTestCase, sqlstate

# Policy mutation rewrites live policies, so it runs only where the script says
# the database is disposable. It never runs against a hosted project.
MUTABLE = os.environ.get("ALLOW_POLICY_MUTATION", "").lower() in ("1", "true")

EXPECTED_POLICIES = {
    ("player", "player_owner_maintenance", "ALL", "{shoulder_migration}"),
    ("player", "player_visible_select", "SELECT", "{shoulder_api}"),
    ("team", "team_member_select", "SELECT", "{shoulder_api}"),
    ("team", "team_owner_maintenance", "ALL", "{shoulder_migration}"),
    (
        "team_membership",
        "team_membership_owner_maintenance",
        "ALL",
        "{shoulder_migration}",
    ),
    ("team_membership", "team_membership_visible_select", "SELECT", "{shoulder_api}"),
    ("user_account", "user_account_owner_maintenance", "ALL", "{shoulder_migration}"),
    ("user_account", "user_account_self_select", "SELECT", "{shoulder_api}"),
}

EXPECTED_RUNTIME_FUNCTIONS = {
    "current_user_id",
    "is_team_coach",
    "is_team_member",
    "team_roster",
}


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class PolicySurfaceTests(DatabaseTestCase):
    """Snapshots that fail when a policy or grant is removed or broadened."""

    def test_policy_set_matches_the_reviewed_matrix(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT tablename, policyname, cmd, roles::text, qual, with_check
                    FROM pg_policies WHERE schemaname = 'app'
                """)
            ).all()
        actual = {(r.tablename, r.policyname, r.cmd, r.roles) for r in rows}
        self.assertEqual(actual, EXPECTED_POLICIES)
        for row in rows:
            with self.subTest(policy=row.policyname):
                if row.policyname.endswith("_owner_maintenance"):
                    continue
                # A runtime policy that stopped consulting the caller's identity,
                # directly or through a membership helper, would authorize on row
                # contents alone.
                qual = row.qual or ""
                self.assertTrue(
                    any(
                        name in qual
                        for name in (
                            "current_user_id",
                            "is_team_member",
                            "is_team_coach",
                        )
                    ),
                    qual,
                )
                self.assertNotEqual(qual.strip(), "true")
                # None of the runtime policies may authorize a write.
                self.assertIsNone(row.with_check)

    def test_protected_tables_keep_row_level_security_forced(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT relname, relrowsecurity, relforcerowsecurity,
                           relowner::regrole::text AS owner
                    FROM pg_class
                    WHERE relnamespace = 'app'::regnamespace AND relkind = 'r'
                      AND relname <> 'alembic_version'
                """)
            ).all()
        self.assertEqual({r.relname for r in rows}, set(TABLES))
        for row in rows:
            with self.subTest(table=row.relname):
                self.assertTrue(row.relrowsecurity)
                self.assertTrue(row.relforcerowsecurity)
                self.assertEqual(row.owner, "shoulder_migration")

    def test_runtime_and_operator_grants_match_the_contract(self) -> None:
        with self.admin.connect() as connection:
            table_grants = connection.execute(
                text("""
                    SELECT grantee, table_name, privilege_type
                    FROM information_schema.role_table_grants
                    WHERE table_schema IN ('app', 'private')
                      AND grantee IN ('shoulder_api', 'shoulder_operator',
                                      'anon', 'authenticated', 'PUBLIC')
                """)
            ).all()
            functions = (
                connection.execute(
                    text("""
                    SELECT p.proname
                    FROM pg_proc p
                    WHERE p.pronamespace = 'private'::regnamespace
                      AND has_function_privilege('shoulder_api', p.oid, 'EXECUTE')
                """)
                )
                .scalars()
                .all()
            )
            operator_functions = (
                connection.execute(
                    text("""
                    SELECT p.proname
                    FROM pg_proc p
                    WHERE p.pronamespace = 'private'::regnamespace
                      AND has_function_privilege('shoulder_operator', p.oid, 'EXECUTE')
                """)
                )
                .scalars()
                .all()
            )
        self.assertEqual(
            {(g.grantee, g.table_name, g.privilege_type) for g in table_grants},
            {("shoulder_api", table, "SELECT") for table in TABLES},
        )
        self.assertEqual(set(functions), EXPECTED_RUNTIME_FUNCTIONS)
        # Bootstrap authority stays with the operator role alone.
        self.assertEqual(set(operator_functions), {"bootstrap_initial_team"})

    def test_definer_helpers_cannot_escalate(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT p.proname, p.prosecdef, p.proowner::regrole::text AS owner,
                           coalesce(array_to_string(p.proconfig, ','), '') AS config
                    FROM pg_proc p
                    WHERE p.pronamespace = 'private'::regnamespace
                """)
            ).all()
            owner = connection.execute(
                text("""
                    SELECT rolsuper, rolbypassrls FROM pg_roles
                    WHERE rolname = 'shoulder_migration'
                """)
            ).one()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(function=row.proname):
                self.assertEqual(row.owner, "shoulder_migration")
                self.assertIn('search_path=""', row.config)
        # A definer helper is only safe because its owner cannot bypass RLS.
        self.assertEqual((owner.rolsuper, owner.rolbypassrls), (False, False))

    def test_runtime_cannot_assume_a_privileged_role(self) -> None:
        for role in ("shoulder_operator", "shoulder_migration", "postgres"):
            with self.subTest(role=role):
                with (
                    self.assertRaises(ProgrammingError) as caught,
                    self.runtime.connect() as connection,
                    connection.begin(),
                ):
                    connection.execute(text(f"SET ROLE {role}"))
                self.assertEqual(sqlstate(caught.exception), "42501")


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class AccessMatrixTests(IsolationHarness):
    def test_coach_reads_exactly_their_own_team(self) -> None:
        world = self.world
        self.assertEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.team"), [world.a.id]
        )
        self.assertCountEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.player"),
            [*world.a.rows, world.unlinked_row],
        )
        self.assertCountEqual(
            self.read_as(world.a.coach, "SELECT user_id FROM app.team_membership"),
            [world.a.coach, *world.a.players],
        )
        # Direct account access stays self-only even for a coach.
        self.assertEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.user_account"),
            [world.a.coach],
        )

    def test_player_reads_exactly_their_own_rows(self) -> None:
        world = self.world
        player = world.a.players[0]
        self.assertEqual(
            self.read_as(player, "SELECT id FROM app.player"), [world.a.rows[0]]
        )
        self.assertEqual(self.read_as(player, "SELECT id FROM app.team"), [world.a.id])
        self.assertEqual(
            self.read_as(player, "SELECT user_id FROM app.team_membership"), [player]
        )
        self.assertEqual(
            self.read_as(player, "SELECT id FROM app.user_account"), [player]
        )

    def test_teammate_rows_are_not_visible_to_a_player(self) -> None:
        world = self.world
        player, teammate_row = world.a.players[0], world.a.rows[1]
        self.assertEqual(
            self.read_as(
                player, "SELECT id FROM app.player WHERE id = :row", row=teammate_row
            ),
            [],
        )
        self.assertEqual(
            self.read_as(
                player,
                "SELECT id FROM app.user_account WHERE id = :account",
                account=world.a.players[1],
            ),
            [],
        )

    def test_cross_team_reads_are_empty_for_every_table(self) -> None:
        world = self.world
        cases = {
            "team": ("SELECT id FROM app.team WHERE id = :id", {"id": world.b.id}),
            "player": (
                "SELECT id FROM app.player WHERE id = :id",
                {"id": world.b.rows[0]},
            ),
            "team_membership": (
                "SELECT user_id FROM app.team_membership WHERE team_id = :id",
                {"id": world.b.id},
            ),
            "user_account": (
                "SELECT id FROM app.user_account WHERE id = :id",
                {"id": world.b.coach},
            ),
        }
        for identity in (world.a.coach, world.a.players[0]):
            for table, (sql, parameters) in cases.items():
                with self.subTest(identity=str(identity), table=table):
                    self.assertEqual(self.read_as(identity, sql, **parameters), [])

    def test_a_known_identifier_reads_the_same_as_an_unknown_one(self) -> None:
        """An unauthorized row must not be distinguishable from a missing row."""
        world = self.world
        for known, missing in (
            (world.b.id, uuid4()),
            (world.b.rows[0], uuid4()),
        ):
            with self.subTest(known=str(known)):
                table = "team" if known == world.b.id else "player"
                sql = f"SELECT id FROM app.{table} WHERE id = :id"
                self.assertEqual(
                    self.read_as(world.a.coach, sql, id=known),
                    self.read_as(world.a.coach, sql, id=missing),
                )

    def test_unlinked_identity_reads_nothing_beyond_its_own_account(self) -> None:
        world = self.world
        self.assertEqual(
            self.read_as(world.unlinked, "SELECT id FROM app.user_account"),
            [world.unlinked],
        )
        for table in ("team", "team_membership", "player"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.read_as(world.unlinked, f"SELECT 1 FROM app.{table}"), []
                )

    def test_membership_in_two_teams_reads_both_and_nothing_more(self) -> None:
        world = self.world
        # Coach A also plays for team B; each role stays scoped to its team.
        self.add_membership(world.b.id, world.a.coach, "player")
        dual_row = self.admin_insert_player(
            world.b.id,
            user_id=world.a.coach,
            display_name="Coach A as player",
            jersey_number=9,
        )
        self.assertCountEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.team"),
            [world.a.id, world.b.id],
        )
        self.assertCountEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.player"),
            [*world.a.rows, world.unlinked_row, dual_row],
        )
        # Coaching team A grants nothing over team B's other players.
        self.assertEqual(
            self.read_as(
                world.a.coach,
                "SELECT id FROM app.player WHERE id = :id",
                id=world.b.rows[0],
            ),
            [],
        )

    def test_every_table_and_verb_denies_runtime_writes(self) -> None:
        world = self.world
        statements = {
            "user_account": (
                "INSERT INTO app.user_account (id, email, display_name)"
                " VALUES (gen_random_uuid(), 'x@example.test', 'x')",
                "UPDATE app.user_account SET display_name = 'changed'",
                "DELETE FROM app.user_account",
            ),
            "team": (
                "INSERT INTO app.team (name, season_label, season_end_at, created_by)"
                f" VALUES ('X', 's', now(), '{world.a.coach}')",
                "UPDATE app.team SET name = 'changed'",
                "DELETE FROM app.team",
            ),
            "team_membership": (
                "INSERT INTO app.team_membership (team_id, user_id, role)"
                f" VALUES ('{world.b.id}', '{world.a.coach}', 'coach')",
                "UPDATE app.team_membership SET role = 'coach'",
                "DELETE FROM app.team_membership",
            ),
            "player": (
                "INSERT INTO app.player (team_id, display_name)"
                f" VALUES ('{world.a.id}', 'Intruder')",
                "UPDATE app.player SET display_name = 'changed'",
                "DELETE FROM app.player",
            ),
        }
        for identity in (world.a.coach, world.a.players[0]):
            for table, cases in statements.items():
                for statement in cases:
                    with self.subTest(
                        identity=str(identity),
                        table=table,
                        verb=statement.split()[0],
                    ):
                        with (
                            self.assertRaises(ProgrammingError) as caught,
                            self.runtime.connect() as connection,
                            connection.begin(),
                        ):
                            self.as_user(connection, identity)
                            connection.execute(text(statement))
                        self.assertEqual(sqlstate(caught.exception), "42501")

    def test_runtime_cannot_reach_operator_bootstrap(self) -> None:
        with (
            self.assertRaises(ProgrammingError) as caught,
            self.runtime.connect() as connection,
            connection.begin(),
        ):
            self.as_user(connection, self.world.a.coach)
            connection.execute(
                text("""
                    SELECT private.bootstrap_initial_team(
                        :coach, 'Escalated FC', '2026 season', now(), NULL
                    )
                """),
                {"coach": self.world.a.coach},
            )
        self.assertEqual(sqlstate(caught.exception), "42501")


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class RosterDisplayTests(IsolationHarness):
    ROSTER = "SELECT player_name FROM private.team_roster(:team)"

    def test_coach_sees_their_own_roster_display(self) -> None:
        world = self.world
        self.assertCountEqual(
            self.read_as(world.a.coach, self.ROSTER, team=world.a.id),
            ["Player A1", "Player A2", "Unlinked roster"],
        )

    def test_roster_display_never_returns_an_address(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.world.a.coach)
            columns = connection.execute(
                text("SELECT * FROM private.team_roster(:team) LIMIT 1"),
                {"team": self.world.a.id},
            ).keys()
        self.assertEqual(list(columns), ["player_id", "player_name", "account_name"])

    def test_roster_display_refuses_other_teams_and_non_coaches(self) -> None:
        world = self.world
        for identity, team in (
            (world.a.coach, world.b.id),
            (world.a.players[0], world.a.id),
            (world.unlinked, world.a.id),
            (None, world.a.id),
        ):
            with self.subTest(identity=str(identity)):
                self.assertEqual(self.read_as(identity, self.ROSTER, team=team), [])


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class RevocationTests(IsolationHarness):
    ROSTER_SQL = "SELECT player_name FROM private.team_roster(:team)"

    def test_revoked_coach_loses_the_team_on_the_next_transaction(self) -> None:
        world = self.world
        self.assertEqual(
            self.read_as(world.a.coach, "SELECT id FROM app.team"), [world.a.id]
        )
        self.revoke_membership(world.a.id, world.a.coach)
        for table in ("team", "team_membership", "player"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.read_as(world.a.coach, f"SELECT 1 FROM app.{table}"), []
                )
        self.assertEqual(
            self.read_as(world.a.coach, self.ROSTER_SQL, team=world.a.id), []
        )

    def test_revoked_player_loses_their_roster_row(self) -> None:
        world = self.world
        player = world.a.players[0]
        self.assertEqual(
            self.read_as(player, "SELECT id FROM app.player"), [world.a.rows[0]]
        )
        self.revoke_membership(world.a.id, player)
        self.assertEqual(self.read_as(player, "SELECT id FROM app.player"), [])
        self.assertEqual(self.read_as(player, "SELECT id FROM app.team"), [])

    def test_revocation_applies_inside_an_already_open_pool_connection(self) -> None:
        """A cached connection must not keep a revoked user's access."""
        world = self.world
        with self.runtime.connect() as connection:
            with connection.begin():
                self.as_user(connection, world.a.coach)
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM app.team")
                    ).scalar_one(),
                    1,
                )
            self.revoke_membership(world.a.id, world.a.coach)
            with connection.begin():
                self.as_user(connection, world.a.coach)
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM app.team")
                    ).scalar_one(),
                    0,
                )


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class ContextIsolationTests(IsolationHarness):
    def test_identity_does_not_outlive_its_transaction(self) -> None:
        world = self.world
        with self.runtime.connect() as connection:
            with connection.begin():
                self.as_user(connection, world.a.coach)
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM app.team")
                    ).scalar_one(),
                    1,
                )
            with connection.begin():
                self.assertEqual(
                    connection.execute(
                        text("SELECT current_setting('app.user_id', true)")
                    ).scalar_one(),
                    "",
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM app.team")
                    ).scalar_one(),
                    0,
                )

    def test_a_reused_connection_switches_identity_cleanly(self) -> None:
        world = self.world
        expected = [
            (world.a.coach, [world.a.id]),
            (world.b.coach, [world.b.id]),
            (world.unlinked, []),
            (world.a.players[0], [world.a.id]),
        ]
        with self.runtime.connect() as connection:
            for identity, teams in expected:
                with self.subTest(identity=str(identity)), connection.begin():
                    self.as_user(connection, identity)
                    self.assertEqual(
                        list(
                            connection.execute(
                                text("SELECT id FROM app.team")
                            ).scalars()
                        ),
                        teams,
                    )

    def test_a_rolled_back_identity_does_not_survive(self) -> None:
        world = self.world
        with self.runtime.connect() as connection:
            transaction = connection.begin()
            self.as_user(connection, world.a.coach)
            transaction.rollback()
            with connection.begin():
                self.assertEqual(
                    connection.execute(
                        text("SELECT count(*) FROM app.team")
                    ).scalar_one(),
                    0,
                )

    def test_missing_and_malformed_context_reads_nothing(self) -> None:
        for identity in (None, "", "not-a-uuid", "' OR true --", "00000000"):
            for table in TABLES:
                with self.subTest(identity=identity, table=table):
                    self.assertEqual(
                        self.read_as(identity, f"SELECT 1 FROM app.{table}"), []
                    )

    def test_concurrent_identities_do_not_interfere(self) -> None:
        world = self.world

        def teams_for(user_id: UUID) -> list[object]:
            return self.read_as(user_id, "SELECT id FROM app.team")

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(
                pool.map(teams_for, [world.a.coach, world.b.coach, world.a.players[0]])
            )
        self.assertEqual(results, [[world.a.id], [world.b.id], [world.a.id]])


@unittest.skipUnless(
    CONFIGURED and MUTABLE, "policy mutation runs only on a disposable database"
)
class PolicyMutationTests(IsolationHarness):
    """Prove the harness fails when a policy is weakened or removed."""

    def apply(self, statement: str) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(text(statement))

    def test_broadened_team_policy_is_detected(self) -> None:
        world = self.world
        original = (
            "ALTER POLICY team_member_select ON app.team"
            " USING (private.is_team_member(id))"
        )
        self.addCleanup(self.apply, original)
        self.apply("ALTER POLICY team_member_select ON app.team USING (true)")
        # Cross-team isolation must now fail.
        self.assertNotEqual(
            self.read_as(
                world.a.coach, "SELECT id FROM app.team WHERE id = :id", id=world.b.id
            ),
            [],
        )

    def test_removed_player_policy_is_detected(self) -> None:
        world = self.world
        original = """
            CREATE POLICY player_visible_select ON app.player
                FOR SELECT TO shoulder_api
                USING (
                    private.is_team_coach(team_id)
                    OR (
                        user_id = private.current_user_id()
                        AND private.is_team_member(team_id)
                        AND deleted_at IS NULL
                        AND deletion_pending_at IS NULL
                    )
                )
        """
        self.addCleanup(self.apply, original)
        self.apply("DROP POLICY player_visible_select ON app.player")
        # Losing the policy denies the coach's own roster: the suite notices.
        self.assertEqual(self.read_as(world.a.coach, "SELECT id FROM app.player"), [])

    def test_membership_check_removal_is_detected(self) -> None:
        world = self.world
        original = (
            "ALTER POLICY team_membership_visible_select ON app.team_membership"
            " USING (user_id = private.current_user_id()"
            " OR private.is_team_coach(team_id))"
        )
        self.addCleanup(self.apply, original)
        self.apply(
            "ALTER POLICY team_membership_visible_select ON app.team_membership"
            " USING (true)"
        )
        self.assertNotEqual(
            self.read_as(
                world.a.players[0],
                "SELECT user_id FROM app.team_membership WHERE team_id = :id",
                id=world.b.id,
            ),
            [],
        )
