"""Project 02 schema, policies, and grants for games, video ingest, and jobs.

Every assertion runs through a real login: `shoulder_api` for the request path
and `shoulder_worker` for the background path. A denial here is Postgres's
answer, not the service's opinion.

`docs/03-schema.md` gives players no access to `game`, `video`,
`video_upload_part`, or `processing_job` at all, so the player cases assert
absence rather than a filtered subset.

Requires migration `0005` and the URLs `scripts/check-db.ps1` provides.
"""

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text

sys.path.append(str(Path(__file__).resolve().parent))

from isolation_fixtures import IsolationHarness  # noqa: E402
from test_database import REQUIRED  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
NEW_TABLES = ("game", "video", "video_upload_part", "processing_job")
# Postgres refusals these suites distinguish between.
INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"


class ConfigurationTests(unittest.TestCase):
    def test_worker_url_is_configured_where_a_database_is_required(self) -> None:
        """The worker role must be exercised wherever the database suites run."""
        if REQUIRED:
            self.assertTrue(WORKER_URL, "WORKER_DATABASE_URL is required")
            self.assertFalse(
                getattr(VideoIsolationTests, "__unittest_skip__", False),
                "the video isolation suite must run where a database is required",
            )


class VideoWorld(IsolationHarness):
    """Adds one game, one video, one part, and one job to each team."""

    worker: Engine

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.worker = create_engine(str(WORKER_URL)) if WORKER_URL else cls.runtime

    @classmethod
    def tearDownClass(cls) -> None:
        if WORKER_URL:
            cls.worker.dispose()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.game_a = self.admin_insert_game(self.world.a.id, self.world.a.coach)
        self.game_b = self.admin_insert_game(self.world.b.id, self.world.b.coach)
        self.video_a = self.admin_insert_video(self.game_a, self.world.a.coach)
        self.video_b = self.admin_insert_video(self.game_b, self.world.b.coach)
        self.admin_insert_part(self.video_a, 1)
        self.admin_insert_part(self.video_b, 1)
        self.job_a = self.admin_insert_job(self.video_a, "transcode")
        self.job_b = self.admin_insert_job(self.video_b, "transcode")

    def admin_insert_game(self, team_id: UUID, coach_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.game
                                (team_id, opponent, played_at, kind, created_by)
                            VALUES (:team, 'Visitors', now(), 'match', :coach)
                            RETURNING id
                        """),
                        {"team": team_id, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def admin_insert_video(self, game_id: UUID, coach_id: UUID, **columns: Any) -> UUID:
        video_id = uuid4()
        fields: dict[str, Any] = {
            "id": video_id,
            "game_id": game_id,
            "original_key": f"originals/{video_id}/source.mp4",
            "original_filename": "match.mp4",
            "content_type": "video/mp4",
            "size_bytes": 64 * 1024 * 1024,
            "multipart_upload_id": "upload-" + video_id.hex[:12],
            "uploaded_by": coach_id,
            **columns,
        }
        names = ", ".join(fields)
        values = ", ".join(f":{name}" for name in fields)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(f"INSERT INTO app.video ({names}) VALUES ({values})"), fields
            )
        return video_id

    def admin_insert_part(self, video_id: UUID, part_number: int) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.video_upload_part
                        (video_id, part_number, etag, size_bytes)
                    VALUES (:video, :number, :etag, 33554432)
                """),
                {
                    "video": video_id,
                    "number": part_number,
                    "etag": f"{video_id.hex}{part_number}",
                },
            )

    def admin_insert_job(self, video_id: UUID, kind: str, **columns: Any) -> UUID:
        fields: dict[str, Any] = {
            "video_id": video_id,
            "kind": kind,
            "idempotency_key": f"{kind}:{video_id}:v1",
            **columns,
        }
        names = ", ".join(fields)
        values = ", ".join(f":{name}" for name in fields)
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text(
                            f"INSERT INTO app.processing_job ({names})"
                            f" VALUES ({values}) RETURNING id"
                        ),
                        fields,
                    ).scalar_one()
                )
            )


class VideoSchemaTests(VideoWorld):
    def test_every_new_table_enables_and_forces_row_level_security(self) -> None:
        with self.admin.connect() as connection:
            for table in NEW_TABLES:
                with self.subTest(table=table):
                    enabled, forced = connection.execute(
                        text("""
                            SELECT relrowsecurity, relforcerowsecurity
                            FROM pg_class
                            WHERE oid = ('app.' || :table)::regclass
                        """),
                        {"table": table},
                    ).one()
                    self.assertTrue(enabled, f"RLS is not enabled on app.{table}")
                    self.assertTrue(forced, f"RLS is not forced on app.{table}")

    def test_no_browser_facing_role_holds_a_privilege(self) -> None:
        """The Data API must not reach these tables even if a schema is exposed."""
        with self.admin.connect() as connection:
            for role in ("PUBLIC", "anon", "authenticated"):
                for table in NEW_TABLES:
                    with self.subTest(role=role, table=table):
                        granted = connection.execute(
                            text("""
                                SELECT count(*)
                                FROM information_schema.role_table_grants
                                WHERE table_schema = 'app' AND table_name = :table
                                  AND grantee = :role
                            """),
                            {"table": table, "role": role},
                        ).scalar_one()
                        self.assertEqual(granted, 0)

    def test_video_status_rejects_a_value_outside_the_contract(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            "UPDATE app.video SET status = 'transcoding' WHERE id = :id",
            id=self.video_a,
        )
        self.assertEqual(state, CHECK_VIOLATION)

    def test_source_expiry_cannot_precede_upload_completion(self) -> None:
        """The retention clock has no meaning before the upload finished."""
        with self.assertRaises(Exception):
            with self.admin.connect() as connection, connection.begin():
                connection.execute(
                    text(
                        "UPDATE app.video SET source_expires_at = now() WHERE id = :id"
                    ),
                    {"id": self.video_a},
                )

    def test_a_job_cannot_run_without_a_lease(self) -> None:
        with self.assertRaises(Exception):
            with self.admin.connect() as connection, connection.begin():
                connection.execute(
                    text(
                        "UPDATE app.processing_job SET status = 'running'"
                        " WHERE id = :id"
                    ),
                    {"id": self.job_a},
                )

    def test_a_lease_is_whole_or_absent(self) -> None:
        with self.assertRaises(Exception):
            with self.admin.connect() as connection, connection.begin():
                connection.execute(
                    text(
                        "UPDATE app.processing_job SET locked_by = 'w1' WHERE id = :id"
                    ),
                    {"id": self.job_a},
                )

    def test_attempts_cannot_exceed_max_attempts(self) -> None:
        with self.assertRaises(Exception):
            with self.admin.connect() as connection, connection.begin():
                connection.execute(
                    text(
                        "UPDATE app.processing_job SET attempts = max_attempts + 1"
                        " WHERE id = :id"
                    ),
                    {"id": self.job_a},
                )

    def test_a_kind_outside_this_block_is_rejected(self) -> None:
        """Later kinds arrive with the tables they target."""
        with self.assertRaises(Exception):
            self.admin_insert_job(self.video_a, "clip_export")

    def test_transcode_and_thumbnail_require_a_video_target(self) -> None:
        with self.assertRaises(Exception):
            self.admin_insert_job(None, "transcode")  # type: ignore[arg-type]

    def test_idempotency_key_is_unique(self) -> None:
        with self.assertRaises(Exception):
            self.admin_insert_job(self.video_a, "transcode")

    def test_progress_stays_between_zero_and_one(self) -> None:
        for value in ("-0.1", "1.1"):
            with self.subTest(progress=value):
                with self.assertRaises(Exception):
                    with self.admin.connect() as connection, connection.begin():
                        connection.execute(
                            text(
                                f"UPDATE app.processing_job SET progress = {value}"
                                " WHERE id = :id"
                            ),
                            {"id": self.job_a},
                        )


class VideoIsolationTests(VideoWorld):
    """Load-bearing suite 1 extended to the Project 02 tables."""

    def test_a_coach_reads_only_their_own_team_rows(self) -> None:
        for user, expected in (
            (self.world.a.coach, [self.game_a]),
            (self.world.b.coach, [self.game_b]),
        ):
            with self.subTest(user=user):
                self.assertEqual(
                    self.read_as(user, "SELECT id FROM app.game ORDER BY id"), expected
                )

    def test_a_coach_outside_the_team_cannot_read_a_known_video_id(self) -> None:
        """A known UUID must read exactly like a random one: as nothing."""
        for target in (self.video_a, uuid4()):
            with self.subTest(target=target):
                self.assertEqual(
                    self.read_as(
                        self.world.b.coach,
                        "SELECT id FROM app.video WHERE id = :id",
                        id=target,
                    ),
                    [],
                )

    def test_players_have_no_access_to_any_ingest_table(self) -> None:
        players = (*self.world.a.players, *self.world.b.players, self.world.unlinked)
        for player in players:
            for table in NEW_TABLES:
                with self.subTest(player=player, table=table):
                    self.assertEqual(
                        self.read_as(player, f"SELECT count(*) FROM app.{table}"), [0]
                    )

    def test_a_player_cannot_insert_a_game_for_their_own_team(self) -> None:
        state = self.refused_as(
            self.world.a.players[0],
            """
            INSERT INTO app.game (team_id, played_at, created_by)
            VALUES (:team, now(), private.current_user_id())
            """,
            team=self.world.a.id,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_missing_identity_context_fails_closed(self) -> None:
        for table in NEW_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    self.read_as(None, f"SELECT count(*) FROM app.{table}"), [0]
                )

    def test_a_malformed_identity_context_fails_closed(self) -> None:
        """A bad context resolves to NULL, so it selects nothing at all."""
        for identity in ("", "not-a-uuid", "' OR true --", "00000000"):
            for table in NEW_TABLES:
                with self.subTest(identity=identity, table=table):
                    self.assertEqual(
                        self.read_as(identity, f"SELECT 1 FROM app.{table}"), []
                    )

    def test_revoked_membership_ends_video_access_on_the_next_transaction(self) -> None:
        self.assertEqual(
            self.read_as(
                self.world.a.coach,
                "SELECT id FROM app.video WHERE id = :id",
                id=self.video_a,
            ),
            [self.video_a],
        )
        self.revoke_membership(self.world.a.id, self.world.a.coach)
        self.assertEqual(
            self.read_as(
                self.world.a.coach,
                "SELECT id FROM app.video WHERE id = :id",
                id=self.video_a,
            ),
            [],
        )

    def test_a_coach_cannot_write_a_game_owned_by_another_account(self) -> None:
        """`created_by` is server-derived; a spoofed author is refused."""
        state = self.refused_as(
            self.world.a.coach,
            """
            INSERT INTO app.game (team_id, played_at, created_by)
            VALUES (:team, now(), :other)
            """,
            team=self.world.a.id,
            other=self.world.b.coach,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)
        self.assertEqual(self.games_on(self.world.a.id), 1)

    def test_a_coach_cannot_create_a_game_on_another_team(self) -> None:
        state = self.refused_as(
            self.world.b.coach,
            """
            INSERT INTO app.game (team_id, played_at, created_by)
            VALUES (:team, now(), private.current_user_id())
            """,
            team=self.world.a.id,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)
        self.assertEqual(self.games_on(self.world.a.id), 1)

    def games_on(self, team_id: UUID) -> int:
        """Owner read-back, to prove a refused write left the team alone."""
        rows = self.admin_read(
            "SELECT id FROM app.game WHERE team_id = :team", team=team_id
        )
        return len(rows)

    def test_a_video_can_only_be_created_in_the_uploading_state(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            """
            INSERT INTO app.video (
                game_id, original_key, original_filename, content_type,
                size_bytes, uploaded_by, status
            ) VALUES (
                :game, 'originals/x/source.mp4', 'x.mp4', 'video/mp4', 100,
                private.current_user_id(), 'ready'
            )
            """,
            game=self.game_a,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_the_runtime_role_cannot_retarget_a_video_at_another_object(self) -> None:
        """`original_key` has no UPDATE grant, so a key cannot be swapped."""
        state = self.refused_as(
            self.world.a.coach,
            "UPDATE app.video SET original_key = 'originals/other/source.mp4'"
            " WHERE id = :id",
            id=self.video_a,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_the_runtime_role_cannot_move_a_video_to_another_game(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            "UPDATE app.video SET game_id = :other WHERE id = :id",
            other=self.game_b,
            id=self.video_a,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_the_runtime_role_cannot_delete_a_video_row(self) -> None:
        """A video row survives so its retention deadlines stay findable."""
        state = self.refused_as(
            self.world.a.coach,
            "DELETE FROM app.video WHERE id = :id",
            id=self.video_a,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_a_coach_cannot_enqueue_a_job_that_is_already_running(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            """
            INSERT INTO app.processing_job (video_id, kind, idempotency_key, status)
            VALUES (:video, 'thumbnail', :key, 'running')
            """,
            video=self.video_a,
            key=f"thumbnail:{self.video_a}:spoofed",
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_a_coach_cannot_enqueue_work_against_another_team_video(self) -> None:
        state = self.refused_as(
            self.world.b.coach,
            """
            INSERT INTO app.processing_job (video_id, kind, idempotency_key)
            VALUES (:video, 'thumbnail', :key)
            """,
            video=self.video_a,
            key=f"thumbnail:{self.video_a}:cross-team",
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_a_coach_cannot_claim_or_finish_a_job(self) -> None:
        """Lease columns belong to the worker role alone."""
        state = self.refused_as(
            self.world.a.coach,
            "UPDATE app.processing_job SET status = 'succeeded' WHERE id = :id",
            id=self.job_a,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)


@unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
class WorkerRoleTests(VideoWorld):
    """ADR 0018: the worker's privileges are the audit surface, so assert them."""

    def worker_read(self, sql: str, **parameters: object) -> list[Any]:
        with self.worker.connect() as connection, connection.begin():
            return list(connection.execute(text(sql), parameters).scalars().all())

    def worker_refused(self, sql: str, **parameters: object) -> str | None:
        from sqlalchemy.exc import DBAPIError
        from test_database import sqlstate

        with self.assertRaises(DBAPIError) as caught:
            with self.worker.connect() as connection, connection.begin():
                connection.execute(text(sql), parameters)
        return sqlstate(caught.exception)

    def test_the_worker_logs_in_as_its_own_role(self) -> None:
        self.assertEqual(self.worker_read("SELECT current_user"), ["shoulder_worker"])

    def test_the_worker_cannot_bypass_row_level_security(self) -> None:
        bypass = self.worker_read(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'shoulder_worker'"
        )
        self.assertEqual(bypass, [False])

    def test_the_worker_sees_every_job_because_it_has_no_team(self) -> None:
        visible = self.worker_read("SELECT id FROM app.processing_job ORDER BY id")
        self.assertIn(self.job_a, visible)
        self.assertIn(self.job_b, visible)

    def test_the_worker_cannot_read_product_or_identity_tables(self) -> None:
        for table in ("user_account", "team", "team_membership", "player", "game"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.worker_refused(f"SELECT count(*) FROM app.{table}"),
                    INSUFFICIENT_PRIVILEGE,
                )

    def test_the_worker_cannot_enqueue_or_delete_work(self) -> None:
        self.assertEqual(
            self.worker_refused(
                "INSERT INTO app.processing_job (video_id, kind, idempotency_key)"
                " VALUES (:video, 'thumbnail', 'worker-invented')",
                video=self.video_a,
            ),
            INSUFFICIENT_PRIVILEGE,
        )
        self.assertEqual(
            self.worker_refused(
                "DELETE FROM app.processing_job WHERE id = :id", id=self.job_a
            ),
            INSUFFICIENT_PRIVILEGE,
        )

    def test_the_worker_cannot_rewrite_a_job_identity(self) -> None:
        for column, value in (
            ("kind", "'thumbnail'"),
            ("idempotency_key", "'rewritten'"),
            ("video_id", "NULL"),
            ("payload", "'{\"k\": 1}'::jsonb"),
        ):
            with self.subTest(column=column):
                self.assertEqual(
                    self.worker_refused(
                        f"UPDATE app.processing_job SET {column} = {value}"
                        " WHERE id = :id",
                        id=self.job_a,
                    ),
                    INSUFFICIENT_PRIVILEGE,
                )

    def test_the_worker_cannot_retarget_the_source_object(self) -> None:
        """`original_key` has no UPDATE grant on any runtime role, ever.

        This replaces an earlier assertion that the worker could write no
        storage key at all. That expectation was written when nothing produced
        a playback object and it named its own successor: "Task 11 widens this
        grant when it has a playback object to name." Migration `0006` is that
        widening, so `playback_key` is now writable by the worker that creates
        the object.

        The property that must still hold is narrower and more important. The
        source upload is the full match; `original_key` is the column that
        decides which source object exists, and no runtime role may rewrite it.
        `playback_key` is safe to grant because the API never reads a key from
        a row when signing: `create_playback_url` derives the key from the
        video's UUID, so a bad value in that column cannot retarget a coach URL.
        """
        self.assertEqual(
            self.worker_refused(
                "UPDATE app.video SET original_key = 'originals/other/source.mp4'"
                " WHERE id = :id",
                id=self.video_a,
            ),
            INSUFFICIENT_PRIVILEGE,
        )

    def test_the_worker_writes_only_the_columns_its_work_produces(self) -> None:
        """The `0006` widening is bounded: probe results and playback, no more."""
        with self.admin.connect() as connection:
            granted = {
                row[0]
                for row in connection.execute(
                    text("""
                        SELECT column_name FROM information_schema.column_privileges
                        WHERE table_schema = 'app' AND table_name = 'video'
                          AND grantee = 'shoulder_worker'
                          AND privilege_type = 'UPDATE'
                    """)
                ).all()
            }
        self.assertEqual(
            granted,
            {
                "status",
                "ready_at",
                "playback_key",
                "duration_ms",
                "width",
                "height",
                "fps",
                "first_terminal_failure_at",
            },
        )
        # The two columns that must never be worker-writable.
        self.assertNotIn("original_key", granted)
        self.assertNotIn("game_id", granted)

    def test_the_worker_has_no_private_helper_access(self) -> None:
        self.assertEqual(
            self.worker_refused("SELECT private.current_user_id()"),
            INSUFFICIENT_PRIVILEGE,
        )


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
