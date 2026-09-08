"""Task 5 row-level-security matrix and isolation harness.

Every authorization assertion runs through the production-equivalent
`shoulder_api` login. Reads that must be refused assert an empty result rather
than an error, so an unauthorized identity cannot learn whether a row exists;
writes assert `42501`, because the runtime holds no write privilege at all.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from isolation_fixtures import IsolationHarness
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from test_database import (
    ADMIN_URL,
    CONFIGURED,
    OPERATOR_URL,
    REQUIRED,
    RUNTIME_URL,
    TABLES,
    DatabaseTestCase,
    require_local_database,
    sqlstate,
)

# Opt-in is necessary but insufficient: setUpClass rejects nonlocal URLs before
# opening a connection. Mutations are uncommitted and always rolled back.
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


class MutationGuardTests(unittest.TestCase):
    def test_mandatory_configuration_cannot_skip(self) -> None:
        if REQUIRED:
            self.assertTrue(CONFIGURED, "All three database URLs are mandatory")

    def test_only_matching_literal_local_urls_are_accepted(self) -> None:
        local = "postgresql+psycopg://postgres@127.0.0.1:54322/postgres"
        require_local_database(local, local, local)
        for unsafe in (
            None,
            "postgresql://postgres@db.gzbwlancwxhtausyokxt.supabase.co:5432/postgres",
            "postgresql://postgres@localhost:54322/postgres",
            local + "?host=db.gzbwlancwxhtausyokxt.supabase.co",
            local + "?service=remote",
            local.replace("54322", "5432"),
            local.replace("/postgres", "/production"),
        ):
            with self.subTest(case=unsafe), self.assertRaises(ValueError):
                require_local_database(local, unsafe, local)

    def test_libpq_environment_cannot_redirect_local_mutations(self) -> None:
        local = "postgresql://postgres@127.0.0.1:54322/postgres"
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
            with patch.dict(os.environ, {key: "remote"}), self.assertRaises(ValueError):
                require_local_database(local, local, local)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class PolicySurfaceTests(DatabaseTestCase):
    """Snapshots that fail when a policy or grant is removed or broadened."""

    def test_policy_set_matches_the_reviewed_matrix(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT tablename, policyname, cmd, roles::text, qual, with_check,
                           permissive
                    FROM pg_policies WHERE schemaname = 'app'
                """)
            ).all()
        # Names and expression formatting are not authorization semantics.
        actual = [(r.tablename, r.cmd, r.roles) for r in rows]
        self.assertCountEqual(actual, [(t, c, r) for t, _, c, r in EXPECTED_POLICIES])
        for row in rows:
            with self.subTest(policy=row.policyname):
                self.assertEqual(row.permissive, "PERMISSIVE")
                if row.roles == "{shoulder_migration}":
                    self.assertEqual(row.qual, "true")
                    self.assertEqual(row.with_check, "true")
                    continue
                # The positive/negative matrix verifies predicate semantics;
                # spelling a particular helper name is not a security proof.
                self.assertTrue(row.qual)
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
                self.assertEqual(row.prosecdef, row.proname != "current_user_id")
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
    def test_cleanup_preserves_another_fixture_world(self) -> None:
        other = IsolationHarness()
        other.admin, other.runtime, other.operator = (
            self.admin,
            self.runtime,
            self.operator,
        )
        self.addCleanup(other.doCleanups)
        other.setUp()
        self.cleanup()
        self.assertEqual(
            other.read_as(other.world.a.coach, "SELECT id FROM app.team"),
            [other.world.a.id],
        )
        self.assertCountEqual(
            other.read_as(other.world.a.coach, "SELECT id FROM app.player"),
            [*other.world.a.rows, other.world.unlinked_row],
        )
        self.assertEqual(
            other.read_as(other.world.a.coach, "SELECT id FROM app.user_account"),
            [other.world.a.coach],
        )

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

    def test_roster_linked_names_and_deletion_filters(self) -> None:
        world = self.world
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, world.a.coach)
            rows = connection.execute(
                text("SELECT * FROM private.team_roster(:team)"), {"team": world.a.id}
            ).all()
        self.assertCountEqual(
            rows,
            [
                (world.a.rows[0], "Player A1", "Player A1"),
                (world.a.rows[1], "Player A2", "Player A2"),
                (world.unlinked_row, "Unlinked roster", None),
            ],
        )
        for column in ("deleted_at", "deletion_pending_at"):
            with self.subTest(column=column):
                with self.admin.begin() as connection:
                    connection.execute(
                        text(f"UPDATE app.player SET {column} = now() WHERE id = :id"),
                        {"id": world.a.rows[0]},
                    )
                self.assertNotIn(
                    "Player A1",
                    self.read_as(world.a.coach, self.ROSTER, team=world.a.id),
                )
                self.assertEqual(
                    self.read_as(world.a.players[0], "SELECT id FROM app.player"), []
                )
                with self.admin.begin() as connection:
                    connection.execute(
                        text(f"UPDATE app.player SET {column} = NULL WHERE id = :id"),
                        {"id": world.a.rows[0]},
                    )
        self.assertEqual(self.read_as(world.a.coach, self.ROSTER, team=None), [])
        for context in ("not-a-uuid", "' OR true --", ""):
            self.assertEqual(self.read_as(context, self.ROSTER, team=world.a.id), [])

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

    def test_revoking_either_dual_role_preserves_the_other(self) -> None:
        world = self.world
        self.add_membership(world.b.id, world.a.coach, "player")
        dual = self.admin_insert_player(world.b.id, user_id=world.a.coach)
        for revoked, surviving, expected in (
            (world.a.id, world.b.id, [dual]),
            (world.b.id, world.a.id, [*world.a.rows, world.unlinked_row]),
        ):
            self.revoke_membership(revoked, world.a.coach)
            # Dispose forces a fresh physical connection for each revocation.
            self.runtime.dispose()
            self.assertEqual(
                self.read_as(world.a.coach, "SELECT id FROM app.team"), [surviving]
            )
            self.assertCountEqual(
                self.read_as(world.a.coach, "SELECT id FROM app.player"), expected
            )
            self.assertEqual(
                self.read_as(world.a.coach, self.ROSTER_SQL, team=world.b.id), []
            )
            self.assertEqual(
                bool(self.read_as(world.a.coach, self.ROSTER_SQL, team=world.a.id)),
                surviving == world.a.id,
            )
            self.add_membership(
                revoked, world.a.coach, "coach" if revoked == world.a.id else "player"
            )

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
    def test_pool_checkout_reuses_backend_without_identity(self) -> None:
        engine = create_engine(str(RUNTIME_URL), pool_size=1, max_overflow=0)
        self.addCleanup(engine.dispose)
        for rollback in (False, True):
            with engine.connect() as connection:
                self.as_user(connection, self.world.a.coach)
                backend = connection.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar_one()
                self.assertEqual(
                    connection.execute(text("SELECT id FROM app.team")).scalar_one(),
                    self.world.a.id,
                )
                if not rollback:
                    connection.commit()
            with engine.connect() as connection, connection.begin():
                self.assertEqual(
                    connection.execute(text("SELECT pg_backend_pid()")).scalar_one(),
                    backend,
                )
                self.assertEqual(
                    list(connection.execute(text("SELECT id FROM app.team")).scalars()),
                    [],
                )
                self.as_user(connection, self.world.b.coach)
                self.assertEqual(
                    connection.execute(text("SELECT id FROM app.team")).scalar_one(),
                    self.world.b.id,
                )

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
        barrier = Barrier(3, timeout=15)

        def teams_for(user_id: UUID) -> list[object]:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, user_id)
                barrier.wait()
                return list(
                    connection.execute(text("SELECT id FROM app.team")).scalars()
                )

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

    @classmethod
    def setUpClass(cls) -> None:
        require_local_database(ADMIN_URL, RUNTIME_URL, OPERATOR_URL)
        super().setUpClass()

    def assert_mutation_detected(
        self, statement: str, sql: str, expected: list[object]
    ) -> None:
        # DDL and probes share one transaction. SET LOCAL ROLE makes the probe
        # subject to runtime RLS; normal matrix tests use the real runtime login.
        # Never commit weakened policies: rollback also handles assertion errors,
        # disconnects and process termination, without hand-reconstructed DDL.
        with self.admin.connect() as connection:
            before = connection.execute(
                text(
                    "SELECT oid, polname, polcmd, polpermissive, polroles, "
                    "polqual::text, polwithcheck::text FROM pg_policy ORDER BY oid"
                )
            ).all()
            connection.rollback()
            transaction = connection.begin()
            try:
                connection.execute(text(statement))
                connection.execute(text("SET LOCAL ROLE shoulder_api"))
                self.assertEqual(
                    connection.execute(text("SELECT current_user")).scalar_one(),
                    "shoulder_api",
                )
                self.as_user(connection, self.world.a.coach)
                actual = list(connection.execute(text(sql)).scalars())
                with self.assertRaises(AssertionError):
                    self.assertCountEqual(actual, expected)
            finally:
                transaction.rollback()
            after = connection.execute(
                text(
                    "SELECT oid, polname, polcmd, polpermissive, polroles, "
                    "polqual::text, polwithcheck::text FROM pg_policy ORDER BY oid"
                )
            ).all()
            self.assertEqual(after, before)

    def test_broadened_team_policy_is_detected(self) -> None:
        self.assert_mutation_detected(
            "ALTER POLICY team_member_select ON app.team USING (true)",
            "SELECT id FROM app.team",
            [self.world.a.id],
        )

    def test_removed_player_policy_is_detected(self) -> None:
        self.assert_mutation_detected(
            "DROP POLICY player_visible_select ON app.player",
            "SELECT id FROM app.player",
            [*self.world.a.rows, self.world.unlinked_row],
        )

    def test_membership_check_removal_is_detected(self) -> None:
        self.assert_mutation_detected(
            "ALTER POLICY team_membership_visible_select ON app.team_membership"
            " USING (true)",
            "SELECT user_id FROM app.team_membership",
            [self.world.a.coach, *self.world.a.players],
        )
