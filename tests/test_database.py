"""Task 4 database tests against a real Postgres server.

`MIGRATION_DATABASE_URL` administers the schema; `DATABASE_URL` is the runtime
API role. Isolation is therefore proved through the same role production uses,
not through a superuser with SET ROLE. Run locally with `scripts/check-db.ps1`.
"""

import json
import os
import unittest
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, ProgrammingError

from services.api import db as api_db
from services.api.auth import authenticated_identity, get_verifier
from services.api.main import app
from services.api.routes import authorized_operator
from services.worker import jobs

ADMIN_URL = os.environ.get("MIGRATION_DATABASE_URL")
RUNTIME_URL = os.environ.get("DATABASE_URL")
OPERATOR_URL = os.environ.get("OPERATOR_DATABASE_URL")
# The background path logs in as its own role; see ADR 0018. Suites that do
# not use it still have to restore its password after a downgrade drops it.
WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
# Set only where a database is provisioned, so CI cannot skip this suite
# silently while the shared quality script runs without one.
REQUIRED = os.environ.get("REQUIRE_DATABASE_TESTS", "").lower() in ("1", "true")

TABLES = (
    "user_account",
    "team",
    "team_membership",
    "player",
    "development_goal",
    # 0005 — Project 02 ingest and durable work.
    "game",
    "video",
    "video_upload_part",
    "processing_job",
    # 0007 — Task 14 manual marking.
    "observation",
    # 0008 — Task 15 coach judgments.
    "judgment",
    "judgment_revision",
    # 0010 — Task 17 player evidence publication.
    "review_publication",
    "evidence_clip",
    "review_publication_item",
    # 0011 — Task 19 optional reflections and content-free replay markers.
    "player_reflection",
    "player_reflection_request",
    # 0012 - Task 20 content-free email outbox and reflection digest events.
    "email_delivery",
    "email_reflection_event",
    # 0013 - Task 22 retention, deletion manifests, and product events.
    "retention_policy_confirmation",
    "deletion_manifest",
    "deletion_manifest_object",
    "product_event",
    # 0014 - Block 08P player practice videos and AI coach feedback.
    "practice_video",
    "ai_coach_feedback",
    "ai_coach_usage",
)


def database_urls_configured(*urls: str | None) -> bool:
    """Every URL the harness opens must be present, or it cannot skip cleanly."""
    return all(bool(url) for url in urls)


def require_local_database(*urls: str | None) -> None:
    """Reject hosted targets and libpq overrides before destructive tests."""
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise ValueError("Destructive tests reject libpq connection overrides")
    destinations = set()
    for value in urls:
        url = make_url(value or "postgresql://")
        if (
            url.host not in ("127.0.0.1", "::1")
            or url.database != "postgres"
            or url.port not in (5432, 54322)
            or url.query
        ):
            raise ValueError("Destructive database tests require literal local URLs")
        destinations.add((url.host, url.port, url.database))
    if len(destinations) != 1:
        raise ValueError("Database test URLs must target the same local database")


# The suites below open an operator engine too, so a partial configuration
# must skip rather than fail while constructing it.
CONFIGURED = database_urls_configured(ADMIN_URL, RUNTIME_URL, OPERATOR_URL)


def sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


class ConfigurationTests(unittest.TestCase):
    def test_non_ascii_operator_token_fails_as_unauthorized(self) -> None:
        from unittest.mock import patch

        with patch.dict(os.environ, {"OPERATOR_BOOTSTRAP_TOKEN": "a" * 32}):
            with self.assertRaises(HTTPException) as caught:
                authorized_operator("\u00e9" * 32)
            self.assertEqual(caught.exception.status_code, 401)

    def test_database_tests_are_configured_where_required(self) -> None:
        """The isolation suite must never be skipped where it is required."""
        if REQUIRED:
            self.assertTrue(ADMIN_URL, "MIGRATION_DATABASE_URL is required")
            self.assertTrue(RUNTIME_URL, "DATABASE_URL is required")
            self.assertTrue(OPERATOR_URL, "OPERATOR_DATABASE_URL is required")

    def test_skip_guard_covers_every_url_the_harness_opens(self) -> None:
        """A partial configuration skips; it must not fail on engine creation."""
        for admin in ("url", None):
            for runtime in ("url", None):
                for operator in ("url", None):
                    with self.subTest(admin=admin, runtime=runtime, operator=operator):
                        self.assertEqual(
                            database_urls_configured(admin, runtime, operator),
                            bool(admin and runtime and operator),
                        )
        for suite in (DatabaseTestCase, ZMigrationTests):
            with self.subTest(suite=suite.__name__):
                self.assertEqual(
                    getattr(suite, "__unittest_skip__", False), not CONFIGURED
                )

    def test_product_schema_is_not_exposed_to_the_data_api(self) -> None:
        with open("supabase/config.toml", encoding="utf-8") as handle:
            config = handle.read()
        exposed = next(
            line for line in config.splitlines() if line.startswith("schemas =")
        )
        self.assertEqual(exposed, 'schemas = ["public"]')
        self.assertNotIn("app", exposed)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class DatabaseTestCase(unittest.TestCase):
    admin: Engine
    runtime: Engine
    operator: Engine

    @classmethod
    def setUpClass(cls) -> None:
        cls.admin = create_engine(str(ADMIN_URL))
        cls.runtime = create_engine(str(RUNTIME_URL))
        cls.operator = create_engine(str(OPERATOR_URL))
        with cls.runtime.connect() as connection:
            identity = connection.execute(
                text("SELECT session_user, current_user")
            ).one()
            if tuple(identity) != ("shoulder_api", "shoulder_api"):
                cls.admin.dispose()
                cls.runtime.dispose()
                cls.operator.dispose()
                raise AssertionError("Isolation tests require the shoulder_api login")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.admin.dispose()
        cls.runtime.dispose()
        cls.operator.dispose()

    def setUp(self) -> None:
        self.created_users: list[UUID] = []
        self.emails: dict[UUID, str] = {}
        self.addCleanup(self.cleanup)

    def cleanup(self) -> None:
        # Product rows first: team.created_by is ON DELETE RESTRICT by contract.
        with self.admin.connect() as connection, connection.begin():
            # Delete only workspaces owned by accounts created by this test.
            # Team foreign keys cascade to its roster and memberships.
            connection.execute(
                text("DELETE FROM app.team WHERE created_by = ANY(:users)"),
                {"users": self.created_users},
            )
            for user_id in self.created_users:
                connection.execute(
                    text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id}
                )

    def create_auth_user(self, email: str, display_name: str | None = None) -> UUID:
        user_id = uuid4()
        # Each run gets its own address so a failed cleanup cannot collide.
        email = f"{user_id.hex[:8]}.{email}"
        metadata = json.dumps({"display_name": display_name} if display_name else {})
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO auth.users
                        (id, instance_id, aud, role, email, raw_user_meta_data)
                    VALUES (
                        :id, '00000000-0000-0000-0000-000000000000',
                        'authenticated', 'authenticated', :email,
                        cast(:metadata AS jsonb)
                    )
                """),
                {"id": user_id, "email": email, "metadata": metadata},
            )
        self.created_users.append(user_id)
        self.emails[user_id] = email.lower()
        return user_id

    def as_user(self, connection: Connection, user_id: UUID | str | None) -> None:
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": None if user_id is None else str(user_id)},
        )

    def admin_insert_team(
        self, coach_id: UUID, name: str, *, retention_confirmed: bool = True
    ) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            team_id = connection.execute(
                text("""
                    INSERT INTO app.team
                        (name, season_label, season_end_at, created_by)
                    VALUES (:name, '2026 season', now() + interval '90 days', :coach)
                    RETURNING id
                """),
                {"name": name, "coach": coach_id},
            ).scalar_one()
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :coach, 'coach')
                """),
                {"team": team_id, "coach": coach_id},
            )
            if retention_confirmed:
                connection.execute(
                    text("""
                        INSERT INTO app.retention_policy_confirmation (
                            team_id, confirmed_by, operator_user_id,
                            confirmed_season_end_at, provider_backup_max_days,
                            notice_confirmed_at,
                            collateral_deletion_confirmed_at,
                            provider_backup_confirmed_at
                        ) SELECT id, :coach, :coach, season_end_at, 30,
                                 now(), now(), now()
                          FROM app.team WHERE id = :team
                    """),
                    {"team": team_id, "coach": coach_id},
                )
        return UUID(str(team_id))

    def admin_insert_player(self, team_id: UUID, **columns: Any) -> UUID:
        fields = {"team_id": team_id, "display_name": "Roster player", **columns}
        names = ", ".join(fields)
        values = ", ".join(f":{name}" for name in fields)
        with self.admin.connect() as connection, connection.begin():
            player_id = connection.execute(
                text(
                    f"INSERT INTO app.player ({names}) VALUES ({values}) RETURNING id"
                ),
                fields,
            ).scalar_one()
        return UUID(str(player_id))


class SchemaContractTests(DatabaseTestCase):
    def test_identity_binds_to_auth_users_without_a_second_uuid(self) -> None:
        with self.admin.connect() as connection:
            reference = connection.execute(
                text("""
                    SELECT confrelid::regclass::text
                    FROM pg_constraint
                    WHERE conrelid = 'app.user_account'::regclass AND contype = 'f'
                """)
            ).scalar_one()
            self.assertEqual(reference, "auth.users")
            default = connection.execute(
                text("""
                    SELECT column_default FROM information_schema.columns
                    WHERE table_schema = 'app' AND table_name = 'user_account'
                      AND column_name = 'id'
                """)
            ).scalar_one_or_none()
            # A generated default would create a second identity for a subject.
            self.assertIsNone(default)
            alternates = (
                connection.execute(
                    text("""
                    SELECT c.table_name || '.' || c.column_name
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'app'
                      AND c.data_type = 'uuid'
                      AND c.column_name IN (
                        'auth_user_id', 'supabase_user_id', 'account_id',
                        'external_user_id', 'identity_id'
                      )
                """)
                )
                .scalars()
                .all()
            )
            self.assertEqual(alternates, [])

    def test_every_foreign_key_is_indexed(self) -> None:
        with self.admin.connect() as connection:
            unindexed = (
                connection.execute(
                    text("""
                    SELECT c.conrelid::regclass::text || ' ' || c.conname
                    FROM pg_constraint c
                    WHERE c.contype = 'f'
                      AND c.connamespace = 'app'::regnamespace
                      AND NOT EXISTS (
                        SELECT 1 FROM pg_index i
                        WHERE i.indrelid = c.conrelid
                          AND (i.indkey::smallint[])[0:array_length(c.conkey, 1) - 1]
                              @> c.conkey
                      )
                """)
                )
                .scalars()
                .all()
            )
            self.assertEqual(unindexed, [])

    def test_protected_tables_enable_and_force_row_level_security(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                           c.relowner::regrole::text
                    FROM pg_class c
                    WHERE c.relnamespace = 'app'::regnamespace AND c.relkind = 'r'
                      AND c.relname <> 'alembic_version'
                    ORDER BY c.relname
                """)
            ).all()
        self.assertEqual([row.relname for row in rows], sorted(TABLES))
        for row in rows:
            self.assertTrue(row.relrowsecurity, row.relname)
            self.assertTrue(row.relforcerowsecurity, row.relname)
            self.assertEqual(row.relowner, "shoulder_migration", row.relname)

    def test_runtime_role_is_least_privileged(self) -> None:
        with self.admin.connect() as connection:
            role = connection.execute(
                text("""
                    SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
                    FROM pg_roles WHERE rolname = 'shoulder_api'
                """)
            ).one()
            self.assertEqual(
                (
                    role.rolsuper,
                    role.rolbypassrls,
                    role.rolcreatedb,
                    role.rolcreaterole,
                ),
                (False, False, False, False),
            )
            owned = connection.execute(
                text("""
                    SELECT count(*) FROM pg_class
                    WHERE relnamespace IN ('app'::regnamespace, 'private'::regnamespace)
                      AND relowner = 'shoulder_api'::regrole
                """)
            ).scalar_one()
            self.assertEqual(owned, 0)
            bypass_membership = connection.execute(
                text("""
                    SELECT count(*) FROM pg_auth_members m
                    JOIN pg_roles granted ON granted.oid = m.roleid
                    WHERE m.member = 'shoulder_api'::regrole
                      AND (granted.rolbypassrls OR granted.rolsuper)
                """)
            ).scalar_one()
            self.assertEqual(bypass_membership, 0)
            search_path = connection.execute(
                text("SELECT rolconfig FROM pg_roles WHERE rolname = 'shoulder_api'")
            ).scalar_one()
            self.assertIn("search_path=", "".join(search_path or []))

    def test_operator_and_runtime_privilege_separation(
        self,
    ) -> None:
        with self.runtime.connect() as connection:
            for role in ("shoulder_migration", "shoulder_operator"):
                self.assertFalse(
                    connection.execute(
                        text("SELECT pg_has_role(current_user, :role, 'MEMBER')"),
                        {"role": role},
                    ).scalar_one()
                )
        with self.operator.connect() as connection:
            # The operator can read only the three content-free Task 22 tables;
            # schema USAGE is necessary for those explicit SELECT grants.
            self.assertTrue(
                connection.execute(
                    text("SELECT has_schema_privilege(current_user, 'app', 'USAGE')")
                ).scalar_one()
            )
            self.assertFalse(
                connection.execute(
                    text("SELECT has_schema_privilege(current_user, 'app', 'CREATE')")
                ).scalar_one()
            )
            self.assertFalse(
                connection.execute(
                    text(
                        "SELECT rolsuper OR rolbypassrls "
                        "OR rolcreaterole OR rolcreatedb "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                ).scalar_one()
            )

    def test_browser_facing_roles_have_no_privileges(self) -> None:
        with self.admin.connect() as connection:
            for role in ("anon", "authenticated"):
                for schema in ("app", "private"):
                    self.assertFalse(
                        connection.execute(
                            text(
                                "SELECT has_schema_privilege(:role, :schema, 'USAGE')"
                            ),
                            {"role": role, "schema": schema},
                        ).scalar_one(),
                        f"{role} reaches schema {schema}",
                    )
                grants = connection.execute(
                    text("""
                        SELECT count(*) FROM information_schema.role_table_grants
                        WHERE table_schema IN ('app', 'private') AND grantee = :role
                    """),
                    {"role": role},
                ).scalar_one()
                self.assertEqual(grants, 0, role)
                executable = connection.execute(
                    text("""
                        SELECT count(*) FROM pg_proc p
                        WHERE p.pronamespace = 'private'::regnamespace
                          AND has_function_privilege(:role, p.oid, 'EXECUTE')
                    """),
                    {"role": role},
                ).scalar_one()
                self.assertEqual(executable, 0, role)

    def test_definer_helpers_pin_an_empty_search_path(self) -> None:
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT p.proname, p.prosecdef, p.proconfig
                    FROM pg_proc p
                    WHERE p.pronamespace = 'private'::regnamespace ORDER BY p.proname
                """)
            ).all()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("search_path=", "".join(row.proconfig or []), row.proname)

    def test_runtime_role_cannot_disable_row_level_security(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            with self.assertRaises(ProgrammingError):
                connection.execute(
                    text("ALTER TABLE app.player DISABLE ROW LEVEL SECURITY")
                )


class ProfileSynchronizationTests(DatabaseTestCase):
    def test_auth_user_creates_and_updates_the_profile(self) -> None:
        user_id = self.create_auth_user("Coach.One@Example.test", "Coach One")
        with self.admin.connect() as connection:
            row = connection.execute(
                text("SELECT email, display_name FROM app.user_account WHERE id = :id"),
                {"id": user_id},
            ).one()
        self.assertEqual(row.email, self.emails[user_id])
        self.assertEqual(row.display_name, "Coach One")

        renamed = f"Renamed.{user_id.hex[:8]}@Example.test"
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE auth.users SET email = :email WHERE id = :id"),
                {"email": renamed, "id": user_id},
            )
        with self.admin.connect() as connection:
            email = connection.execute(
                text("SELECT email FROM app.user_account WHERE id = :id"),
                {"id": user_id},
            ).scalar_one()
        self.assertEqual(email, renamed.lower())

    def test_display_name_falls_back_to_the_email_local_part(self) -> None:
        user_id = self.create_auth_user("no.metadata@example.test")
        with self.admin.connect() as connection:
            display_name = connection.execute(
                text("SELECT display_name FROM app.user_account WHERE id = :id"),
                {"id": user_id},
            ).scalar_one()
        self.assertEqual(display_name, self.emails[user_id].split("@")[0])

    def test_deleting_the_auth_user_removes_the_profile(self) -> None:
        user_id = self.create_auth_user("temporary@example.test")
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id}
            )
        with self.admin.connect() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM app.user_account WHERE id = :id"),
                {"id": user_id},
            ).scalar_one()
        self.assertEqual(remaining, 0)


class RosterConstraintTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.coach = self.create_auth_user("constraints.coach@example.test")
        self.team = self.admin_insert_team(self.coach, "Constraint FC")

    def test_duplicate_active_jersey_is_rejected(self) -> None:
        self.admin_insert_player(self.team, jersey_number=7)
        with self.assertRaises(DBAPIError) as caught:
            self.admin_insert_player(self.team, jersey_number=7)
        self.assertEqual(sqlstate(caught.exception), "23505")

    def test_jersey_frees_up_when_the_player_leaves(self) -> None:
        first = self.admin_insert_player(self.team, jersey_number=9)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.player SET active = false, deleted_at = now()"
                    " WHERE id = :id"
                ),
                {"id": first},
            )
        self.admin_insert_player(self.team, jersey_number=9)

    def test_duplicate_linked_player_is_rejected(self) -> None:
        player_user = self.create_auth_user("linked.player@example.test")
        self.admin_insert_player(self.team, user_id=player_user)
        with self.assertRaises(DBAPIError) as caught:
            self.admin_insert_player(self.team, user_id=player_user)
        self.assertEqual(sqlstate(caught.exception), "23505")

    def test_bounded_columns_reject_out_of_range_values(self) -> None:
        for column, value in (("jersey_number", 100), ("display_name", "")):
            with self.subTest(column=column), self.assertRaises(DBAPIError) as caught:
                self.admin_insert_player(self.team, **{column: value})
            self.assertEqual(sqlstate(caught.exception), "23514")


class BootstrapTests(DatabaseTestCase):
    def test_operator_bootstrap_creates_one_team_with_its_coach(self) -> None:
        coach = self.create_auth_user("bootstrap.coach@example.test")
        with self.operator.connect() as connection, connection.begin():
            team_id = connection.execute(
                text("""
                    SELECT private.bootstrap_initial_team(
                        :coach, 'Bootstrap FC', '2026 season',
                        now() + interval '120 days', 'U14'
                    )
                """),
                {"coach": coach},
            ).scalar_one()
        with self.admin.connect() as connection:
            role = connection.execute(
                text("""
                    SELECT role FROM app.team_membership
                    WHERE team_id = :team AND user_id = :coach
                """),
                {"team": team_id, "coach": coach},
            ).scalar_one()
        self.assertEqual(role, "coach")

        with (
            self.assertRaises(DBAPIError) as caught,
            self.operator.connect() as connection,
            connection.begin(),
        ):
            connection.execute(
                text("""
                    SELECT private.bootstrap_initial_team(
                        :coach, 'Second FC', '2026 season',
                        now() + interval '120 days', NULL
                    )
                """),
                {"coach": coach},
            )
        self.assertEqual(sqlstate(caught.exception), "23505")

    def test_bootstrap_rejects_an_unknown_account(self) -> None:
        with (
            self.assertRaises(DBAPIError) as caught,
            self.operator.connect() as connection,
            connection.begin(),
        ):
            connection.execute(
                text("""
                    SELECT private.bootstrap_initial_team(
                        :coach, 'Ghost FC', '2026 season',
                        now() + interval '120 days', NULL
                    )
                """),
                {"coach": uuid4()},
            )
        self.assertEqual(sqlstate(caught.exception), "23503")

    def test_signup_identity_cannot_write_teams_or_memberships(self) -> None:
        user = self.create_auth_user("selfsignup@example.test")
        for statement in (
            "INSERT INTO app.team (name, season_label, season_end_at, created_by)"
            " VALUES ('Self FC', 's', now(), :user)",
            "INSERT INTO app.team_membership (team_id, user_id, role)"
            " VALUES (gen_random_uuid(), :user, 'coach')",
        ):
            with self.subTest(statement=statement[:40]):
                with (
                    self.assertRaises(ProgrammingError) as caught,
                    self.runtime.connect() as connection,
                    connection.begin(),
                ):
                    self.as_user(connection, user)
                    connection.execute(text(statement), {"user": user})
                self.assertEqual(sqlstate(caught.exception), "42501")


class RuntimeIsolationTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.coach_a = self.create_auth_user("coach.a@example.test")
        self.coach_b = self.create_auth_user("coach.b@example.test")
        self.player_a = self.create_auth_user("player.a@example.test")
        self.player_b = self.create_auth_user("player.b@example.test")
        self.team_a = self.admin_insert_team(self.coach_a, "Team A")
        self.team_b = self.admin_insert_team(self.coach_b, "Team B")
        self.player_a_row = self.admin_insert_player(
            self.team_a, user_id=self.player_a, jersey_number=1
        )
        self.teammate_row = self.admin_insert_player(self.team_a, jersey_number=2)
        self.player_b_row = self.admin_insert_player(
            self.team_b, user_id=self.player_b, jersey_number=1
        )
        for team, user in ((self.team_a, self.player_a), (self.team_b, self.player_b)):
            with self.admin.connect() as connection, connection.begin():
                connection.execute(
                    text("""
                        INSERT INTO app.team_membership (team_id, user_id, role)
                        VALUES (:team, :user, 'player')
                    """),
                    {"team": team, "user": user},
                )

    def visible(self, user_id: UUID | str | None, sql: str) -> list[Any]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            return list(connection.execute(text(sql)).scalars().all())

    def test_coach_reads_only_their_own_team(self) -> None:
        self.assertEqual(
            self.visible(self.coach_a, "SELECT id FROM app.team"), [self.team_a]
        )
        self.assertEqual(
            self.visible(self.coach_a, "SELECT id FROM app.user_account"),
            [self.coach_a],
        )
        self.assertCountEqual(
            self.visible(self.coach_a, "SELECT id FROM app.player"),
            [self.player_a_row, self.teammate_row],
        )
        self.assertCountEqual(
            self.visible(self.coach_a, "SELECT user_id FROM app.team_membership"),
            [self.coach_a, self.player_a],
        )

    def test_player_reads_only_their_own_rows(self) -> None:
        self.assertEqual(
            self.visible(self.player_a, "SELECT id FROM app.player"),
            [self.player_a_row],
        )
        self.assertEqual(
            self.visible(self.player_a, "SELECT id FROM app.user_account"),
            [self.player_a],
        )
        self.assertEqual(
            self.visible(self.player_a, "SELECT id FROM app.team"), [self.team_a]
        )
        self.assertEqual(
            self.visible(self.player_a, "SELECT user_id FROM app.team_membership"),
            [self.player_a],
        )

    def test_cross_team_and_cross_player_reads_are_empty(self) -> None:
        for user in (self.coach_a, self.player_a):
            with self.subTest(user=str(user)):
                self.assertEqual(
                    self.visible(
                        user, f"SELECT id FROM app.team WHERE id = '{self.team_b}'"
                    ),
                    [],
                )
                self.assertEqual(
                    self.visible(
                        user,
                        f"SELECT id FROM app.player WHERE id = '{self.player_b_row}'",
                    ),
                    [],
                )
                self.assertEqual(
                    self.visible(
                        user,
                        f"SELECT id FROM app.user_account WHERE id = '{self.coach_b}'",
                    ),
                    [],
                )

    def test_soft_deleted_player_loses_their_own_row(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "UPDATE app.player SET deletion_pending_at = now() WHERE id = :id"
                ),
                {"id": self.player_a_row},
            )
        self.assertEqual(self.visible(self.player_a, "SELECT id FROM app.player"), [])

    def test_runtime_writes_outside_the_granted_surface_are_denied(self) -> None:
        """`0004` gave a coach a bounded write surface on the roster and goals.

        Everything outside it still raises. `user_account`, `team`, and
        `team_membership` remain fully read-only for the runtime role; on
        `app.player` and `app.development_goal` the grants stop at named
        columns, deletion is ungranted, and a cross-team insert violates the
        policy. Row-level filtering of a permitted verb is not an error, so it
        is proved by row counts in `tests/test_database_roster.py` instead.
        """
        statements = {
            "user_account": (
                "INSERT INTO app.user_account (id, email, display_name)"
                " VALUES (gen_random_uuid(), 'x@example.test', 'x')",
                "UPDATE app.user_account SET display_name = 'changed'",
                "DELETE FROM app.user_account",
            ),
            "team": (
                "INSERT INTO app.team (name, season_label, season_end_at, created_by)"
                f" VALUES ('X', 's', now(), '{self.coach_a}')",
                "UPDATE app.team SET name = 'changed'",
                "DELETE FROM app.team",
            ),
            "team_membership": (
                "INSERT INTO app.team_membership (team_id, user_id, role)"
                f" VALUES ('{self.team_b}', '{self.coach_a}', 'coach')",
                "UPDATE app.team_membership SET role = 'coach'",
                "DELETE FROM app.team_membership",
            ),
            "player": (
                # Granted verb, forbidden team: the policy refuses the new row.
                "INSERT INTO app.player (team_id, display_name)"
                f" VALUES ('{self.team_b}', 'Intruder')",
                # Ungranted columns: linking and moving teams are not writable.
                f"UPDATE app.player SET team_id = '{self.team_b}'",
                f"UPDATE app.player SET user_id = '{self.coach_a}'",
                "DELETE FROM app.player",
            ),
            "development_goal": (
                "INSERT INTO app.development_goal (player_id, title, created_by)"
                f" VALUES ('{self.player_b_row}', 'Intruder', '{self.coach_a}')",
                f"UPDATE app.development_goal SET player_id = '{self.player_b_row}'",
                f"UPDATE app.development_goal SET created_by = '{self.coach_a}'",
                "DELETE FROM app.development_goal",
            ),
        }
        for table, cases in statements.items():
            for statement in cases:
                with self.subTest(table=table, statement=statement.split()[0]):
                    with (
                        self.assertRaises(ProgrammingError) as caught,
                        self.runtime.connect() as connection,
                        connection.begin(),
                    ):
                        self.as_user(connection, self.coach_a)
                        connection.execute(text(statement))
                    self.assertEqual(sqlstate(caught.exception), "42501")

    def test_missing_and_malformed_identity_read_nothing(self) -> None:
        for user_id in (None, "", "not-a-uuid", "' OR true --"):
            for table in TABLES:
                with self.subTest(user_id=user_id, table=table):
                    if table in (
                        "player_reflection_request",
                        "email_delivery",
                        "email_reflection_event",
                        "deletion_manifest",
                        "deletion_manifest_object",
                        "product_event",
                    ):
                        with self.assertRaises(ProgrammingError) as caught:
                            self.visible(user_id, f"SELECT 1 FROM app.{table}")
                        self.assertEqual(sqlstate(caught.exception), "42501")
                        continue
                    self.assertEqual(
                        self.visible(user_id, f"SELECT 1 FROM app.{table}"), []
                    )

    def test_identity_does_not_survive_its_transaction(self) -> None:
        with self.runtime.connect() as connection:
            with connection.begin():
                self.as_user(connection, self.coach_a)
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

    def test_revoked_membership_removes_access_immediately(self) -> None:
        self.assertEqual(
            self.visible(self.coach_a, "SELECT id FROM app.team"), [self.team_a]
        )
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "DELETE FROM app.team_membership"
                    " WHERE team_id = :team AND user_id = :user"
                ),
                {"team": self.team_a, "user": self.coach_a},
            )
        self.assertEqual(self.visible(self.coach_a, "SELECT id FROM app.team"), [])
        self.assertEqual(self.visible(self.coach_a, "SELECT id FROM app.player"), [])

    def test_revoked_player_membership_removes_row_and_api_link(self) -> None:
        with self.admin.begin() as connection:
            connection.execute(
                text("DELETE FROM app.team_membership WHERE user_id = :user"),
                {"user": self.player_a},
            )
        self.assertEqual(self.visible(self.player_a, "SELECT id FROM app.player"), [])
        app.dependency_overrides[authenticated_identity] = lambda: str(self.player_a)
        self.addCleanup(app.dependency_overrides.clear)
        body = TestClient(app).get("/v1/me").json()
        self.assertEqual(body["roles"], [])
        self.assertEqual(body["team_ids"], [])
        self.assertIsNone(body["player"])

    def test_runtime_cannot_execute_operator_bootstrap(self) -> None:
        with self.runtime.begin() as connection:
            self.assertFalse(
                connection.execute(
                    text("""
                    SELECT has_function_privilege(current_user,
                        'private.bootstrap_initial_team(uuid,text,text,timestamptz,text)',
                        'EXECUTE')
                """)
                ).scalar_one()
            )


def restore_login_passwords(engine: Engine) -> None:
    """Re-apply the configured logins after a downgrade dropped their roles.

    `ALTER ROLE ... PASSWORD` is a utility statement, so Postgres accepts no
    bind parameter for the secret; `format('%L')` quotes it into the statement
    text, where a server with statement logging on would record it. That is
    acceptable only because `require_local_database` confines this suite to a
    local disposable server and `scripts/check-db.ps1` generates the password
    per run and clears it afterwards. Suppressing `log_statement` is not an
    option here: it is superuser-only and local `postgres` is not a superuser.
    """
    with engine.connect() as connection, connection.begin():
        for role, url in (
            ("shoulder_api", RUNTIME_URL),
            ("shoulder_operator", OPERATOR_URL),
            ("shoulder_worker", WORKER_URL),
        ):
            # A suite may run with only the three original URLs configured, and
            # `make_url("None")` would raise before any guard could skip it.
            if not url:
                continue
            password = make_url(str(url)).password
            if not password:
                continue
            statement = connection.execute(
                text(
                    "SELECT format('ALTER ROLE %I PASSWORD %L',"
                    " cast(:role AS text), cast(:password AS text))"
                ),
                {"role": role, "password": password},
            ).scalar_one()
            connection.exec_driver_sql(statement)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class ZMigrationTests(unittest.TestCase):
    """Runs last by name: it rebuilds the schema this suite depends on."""

    def test_zz_downgrade_and_clean_reupgrade(self) -> None:
        require_local_database(ADMIN_URL, RUNTIME_URL, OPERATOR_URL)
        config = Config("alembic.ini")
        engine = create_engine(str(ADMIN_URL))
        try:
            self.dispose_cached_role_engines()
            command.downgrade(config, "base")
            with engine.connect() as connection:
                self.assertEqual(self.table_count(connection), 0)
                self.assertEqual(self.function_count(connection), 0)
                self.assertEqual(self.trigger_count(connection), 0)
                self.assertFalse(
                    connection.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_roles "
                            "WHERE rolname IN ('shoulder_operator', "
                            "'shoulder_api', 'shoulder_migration', "
                            "'shoulder_worker'))"
                        )
                    ).scalar_one()
                )
            command.upgrade(config, "head")
            with engine.connect() as connection:
                self.assertEqual(self.table_count(connection), len(TABLES))
                # 0001 six, three `0004` roster/goal helpers, two `0005`
                # media membership helpers, the `0007` bounds helper,
                # `0008`'s four judgment visibility helpers plus its single
                # write function, and `0010`'s six player/publication helpers,
                # four coach transitions, three worker functions, finalize,
                # the failure trigger, the reserved-edit trigger, and 0011's
                # three runtime reflection helpers plus two internal helpers,
                # and 0012's three fenced worker helpers plus five outbox and
                # source-transition trigger functions. 0013 adds retention,
                # deletion, replay, event, and operator-confirmation helpers.
                # 0014 adds two fenced practice-video retention helpers.
                # 0015 adds the demo self-join (ADR 0021).
                self.assertEqual(self.function_count(connection), 84)
                # This helper intentionally counts only the baseline auth-sync
                # trigger; Task 22 trigger coverage lives in the policy suite.
                self.assertEqual(self.trigger_count(connection), 1)
        finally:
            command.upgrade(config, "head")
            # The downgrade dropped the login roles; later suites still need them.
            restore_login_passwords(engine)
            self.dispose_cached_role_engines()
            engine.dispose()

    @staticmethod
    def dispose_cached_role_engines() -> None:
        for factory in (api_db.get_engine, jobs.get_engine):
            if factory.cache_info().currsize:
                factory().dispose()
            factory.cache_clear()

    @staticmethod
    def table_count(connection: Connection) -> int:
        return int(
            connection.execute(
                text("""
                SELECT count(*) FROM pg_class
                WHERE relnamespace = 'app'::regnamespace AND relkind = 'r'
                  AND relname <> 'alembic_version'
            """)
            ).scalar_one()
        )

    @staticmethod
    def function_count(connection: Connection) -> int:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc"
                    " WHERE pronamespace = to_regnamespace('private')"
                )
            ).scalar_one()
        )

    @staticmethod
    def trigger_count(connection: Connection) -> int:
        return int(
            connection.execute(
                text("""
                SELECT count(*) FROM pg_trigger
                WHERE tgname = 'sync_user_account_from_auth' AND NOT tgisinternal
            """)
            ).scalar_one()
        )


class ApiIdentityTests(DatabaseTestCase):
    """`/v1/me` and the operator bootstrap against the real runtime role.

    Token verification itself is covered by `tests/test_auth.py`; here the
    verified subject is injected so the database-derived answer is what is
    under test.
    """

    def setUp(self) -> None:
        super().setUp()
        os.environ["OPERATOR_BOOTSTRAP_TOKEN"] = "operator-token-for-local-tests-only"
        self.addCleanup(os.environ.pop, "OPERATOR_BOOTSTRAP_TOKEN", None)
        self.addCleanup(app.dependency_overrides.clear)

    def client_for(self, user_id: UUID | None) -> TestClient:
        if user_id is not None:
            app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def test_me_returns_coach_roles_and_teams(self) -> None:
        coach = self.create_auth_user("me.coach@example.test", "Coach Me")
        team = self.admin_insert_team(coach, "Me FC")
        response = self.client_for(coach).get("/v1/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": str(coach),
                "email": self.emails[coach],
                "display_name": "Coach Me",
                "roles": ["coach"],
                "team_ids": [str(team)],
                "player": None,
            },
        )
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_me_returns_the_linked_player_for_a_player_identity(self) -> None:
        coach = self.create_auth_user("me.coach2@example.test")
        player = self.create_auth_user("me.player@example.test")
        team = self.admin_insert_team(coach, "Player FC")
        player_row = self.admin_insert_player(team, user_id=player, jersey_number=4)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": team, "user": player},
            )
        body = self.client_for(player).get("/v1/me").json()
        self.assertEqual(body["roles"], ["player"])
        self.assertEqual(body["team_ids"], [str(team)])
        self.assertEqual(body["player"], {"id": str(player_row), "team_id": str(team)})

    def test_me_gives_an_unlinked_identity_no_product_access(self) -> None:
        unlinked = self.create_auth_user("me.unlinked@example.test")
        coach = self.create_auth_user("me.othercoach@example.test")
        self.admin_insert_team(coach, "Other FC")
        body = self.client_for(unlinked).get("/v1/me").json()
        self.assertEqual(body["roles"], [])
        self.assertEqual(body["team_ids"], [])
        self.assertIsNone(body["player"])

    def test_me_requires_a_verified_identity(self) -> None:
        os.environ["SUPABASE_AUTH_ISSUER"] = "http://127.0.0.1:54321/auth/v1"
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = "local-placeholder"
        get_verifier.cache_clear()
        self.addCleanup(get_verifier.cache_clear)
        self.addCleanup(os.environ.pop, "SUPABASE_AUTH_ISSUER", None)
        self.addCleanup(os.environ.pop, "SUPABASE_PUBLISHABLE_KEY", None)
        response = TestClient(app).get("/v1/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_bootstrap_requires_the_operator_token(self) -> None:
        coach = self.create_auth_user("api.bootstrap@example.test")
        payload = {
            "coach_user_id": str(coach),
            "name": "Bootstrap API FC",
            "season_label": "2026 season",
            "season_end_at": "2027-06-30T00:00:00Z",
        }
        client = TestClient(app)
        self.assertEqual(client.post("/v1/teams", json=payload).status_code, 401)
        self.assertEqual(
            client.post(
                "/v1/teams", json=payload, headers={"X-Operator-Token": "wrong"}
            ).status_code,
            401,
        )
        headers = {"X-Operator-Token": os.environ["OPERATOR_BOOTSTRAP_TOKEN"]}
        created = client.post("/v1/teams", json=payload, headers=headers)
        self.assertEqual(created.status_code, 201)
        team_id = created.json()["team_id"]
        # The same operator call cannot create a second workspace.
        self.assertEqual(
            client.post("/v1/teams", json=payload, headers=headers).status_code, 409
        )
        body = self.client_for(coach).get("/v1/me").json()
        self.assertEqual(body["roles"], ["coach"])
        self.assertEqual(body["team_ids"], [team_id])

    def test_bootstrap_rejects_an_unknown_coach(self) -> None:
        response = TestClient(app).post(
            "/v1/teams",
            json={
                "coach_user_id": str(uuid4()),
                "name": "Ghost API FC",
                "season_label": "2026 season",
                "season_end_at": "2027-06-30T00:00:00Z",
            },
            headers={"X-Operator-Token": os.environ["OPERATOR_BOOTSTRAP_TOKEN"]},
        )
        self.assertEqual(response.status_code, 422)
