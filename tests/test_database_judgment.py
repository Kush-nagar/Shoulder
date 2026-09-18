"""Task 15 judgment/revision schema, grants, and runtime-role isolation."""

import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

sys.path.append(str(Path(__file__).resolve().parent))

from isolation_fixtures import IsolationHarness  # noqa: E402
from test_database import CONFIGURED, sqlstate  # noqa: E402

INVALID_PARAMETER = "22023"
INSUFFICIENT_PRIVILEGE = "42501"
NOT_ORIGINAL_AUTHOR = "PJ001"
STALE_VERSION = "40001"
JUDGMENT_NOT_FOUND = "P0002"
UNIQUE_VIOLATION = "23505"

WRITE_SQL = """
    SELECT * FROM private.write_judgment_revision(
        :judgment_id, :observation_id, :goal_id, :expected_version,
        :verdict, :comment_text, :clip_start_ms, :clip_end_ms
    )
"""


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class JudgmentIsolationTests(IsolationHarness):
    def setUp(self) -> None:
        super().setUp()
        # `docs/03-schema.md` requires `judgment.observation_id` to be
        # ON DELETE RESTRICT, and the shared cleanup removes the team, which
        # cascades to the player, its goals and its observations. A judgment
        # left behind blocks that cascade, so this suite removes its own rows
        # first. Registered after the base cleanup and therefore run before
        # it, cleanups being last-in-first-out. Deleting real judgments is
        # Task 22's retention work, not something to widen this schema for.
        self.addCleanup(self.delete_judgments)
        self.game_a = self.admin_insert_game(self.world.a.id, self.world.a.coach)
        self.game_b = self.admin_insert_game(self.world.b.id, self.world.b.coach)
        self.video_a = self.admin_insert_video(self.game_a, self.world.a.coach)
        self.video_b = self.admin_insert_video(self.game_b, self.world.b.coach)
        self.observation_a = self.admin_insert_observation(
            self.video_a, self.world.a.rows[0], self.world.a.coach
        )
        self.observation_b = self.admin_insert_observation(
            self.video_b, self.world.b.rows[0], self.world.b.coach
        )
        self.goal_a = self.admin_insert_goal(self.world.a.rows[0], self.world.a.coach)
        self.goal_b = self.admin_insert_goal(self.world.b.rows[0], self.world.b.coach)

    def delete_judgments(self) -> None:
        """Remove every judgment this test created, revisions cascading."""
        with self.admin.connect() as connection, connection.begin():
            connection.execute(text("DELETE FROM app.judgment"))

    def admin_insert_game(self, team_id: UUID, coach_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.game (team_id, played_at, created_by)
                            VALUES (:team, now(), :coach) RETURNING id
                        """),
                        {"team": team_id, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def admin_insert_video(self, game_id: UUID, coach_id: UUID) -> UUID:
        video_id = uuid4()
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.video (
                        id, game_id, original_key, original_filename,
                        content_type, size_bytes, uploaded_by, status,
                        playback_key, duration_ms, width, height, fps, ready_at
                    ) VALUES (
                        :id, :game, :original_key, 'match.mp4', 'video/mp4', 1,
                        :coach, 'ready', :playback_key, 60000, 1280, 720, 30, now()
                    )
                """),
                {
                    "id": video_id,
                    "game": game_id,
                    "coach": coach_id,
                    "original_key": f"originals/{video_id}/source.mp4",
                    "playback_key": f"playback/{video_id}/coach-720p.mp4",
                },
            )
        return video_id

    def admin_insert_observation(
        self, video_id: UUID, player_row: UUID, coach_id: UUID
    ) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.observation (
                                video_id, player_id, t_start_ms, t_end_ms,
                                source, created_by
                            ) VALUES (
                                :video, :player, 1000, 4000, 'coach_manual', :coach
                            ) RETURNING id
                        """),
                        {"video": video_id, "player": player_row, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def admin_insert_goal(self, player_row: UUID, coach_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.development_goal
                                (player_id, title, created_by)
                            VALUES (:player, 'First touch', :coach)
                            RETURNING id
                        """),
                        {"player": player_row, "coach": coach_id},
                    ).scalar_one()
                )
            )

    def write_parameters(self, **overrides: Any) -> dict[str, Any]:
        """A create of the ordinary shape, with whatever the caller changes."""
        return {
            "judgment_id": None,
            "observation_id": self.observation_a,
            "goal_id": self.goal_a,
            "expected_version": None,
            "verdict": "applied",
            "comment_text": "Nice first touch.",
            "clip_start_ms": 1000,
            "clip_end_ms": 2000,
            **overrides,
        }

    # Not named `write_as`: the harness already has one, with a different
    # contract, and overriding it would hide the base method from every other
    # suite that shares this fixture.
    def judgment_write_as(self, user_id: UUID | str | None, **overrides: Any) -> Any:
        params = self.write_parameters(**overrides)
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            return connection.execute(text(WRITE_SQL), params).one()

    def refused_write_as(
        self, user_id: UUID | str | None, **overrides: Any
    ) -> str | None:
        params = self.write_parameters(**overrides)
        with self.assertRaises(DBAPIError) as caught:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, user_id)
                connection.execute(text(WRITE_SQL), params)
        return sqlstate(caught.exception)

    def admin_insert_judgment(self, **overrides: Any) -> Any:
        values = {
            "observation": self.observation_a,
            "goal": self.goal_a,
            "author": self.world.a.coach,
            **overrides,
        }
        with self.admin.connect() as connection, connection.begin():
            return connection.execute(
                text("""
                    INSERT INTO app.judgment (observation_id, goal_id, author_user_id)
                    VALUES (:observation, :goal, :author)
                    RETURNING id, version
                """),
                values,
            ).one()

    # --- Ownership, forced RLS, and Data API isolation --------------------

    def test_tables_are_owned_by_migration_role_with_forced_rls(self) -> None:
        with self.admin.connect() as connection:
            for table in ("app.judgment", "app.judgment_revision"):
                with self.subTest(table=table):
                    row = connection.execute(
                        text("""
                            SELECT relrowsecurity, relforcerowsecurity,
                                   relowner::regrole::text AS owner
                            FROM pg_class WHERE oid = CAST(:table AS regclass)
                        """),
                        {"table": table},
                    ).one()
                    self.assertEqual(tuple(row), (True, True, "shoulder_migration"))

    def test_data_api_roles_have_no_privileges(self) -> None:
        with self.admin.connect() as connection:
            for role in ("PUBLIC", "anon", "authenticated"):
                for table in ("judgment", "judgment_revision"):
                    with self.subTest(role=role, table=table):
                        count = connection.execute(
                            text("""
                                SELECT count(*)
                                FROM information_schema.role_table_grants
                                WHERE table_schema = 'app'
                                  AND table_name = :table
                                  AND grantee = :role
                            """),
                            {"table": table, "role": role},
                        ).scalar_one()
                        self.assertEqual(count, 0)

    # --- Creation: spoofed author / cross-team goal ------------------------

    def test_create_writes_judgment_and_revision_one_atomically(self) -> None:
        row = self.judgment_write_as(self.world.a.coach)
        judgment = self.admin_read(
            "SELECT version, author_user_id FROM app.judgment WHERE id = :id",
            id=row.id,
        )[0]
        self.assertEqual(judgment.version, 1)
        self.assertEqual(str(judgment.author_user_id), str(self.world.a.coach))
        revisions = self.admin_read(
            "SELECT version FROM app.judgment_revision WHERE judgment_id = :id",
            id=row.id,
        )
        self.assertEqual([revision.version for revision in revisions], [1])

    def test_author_is_always_the_session_identity_not_a_supplied_value(
        self,
    ) -> None:
        """There is no author parameter to spoof: the function derives it."""
        row = self.judgment_write_as(self.world.a.coach)
        judgment = self.admin_read(
            "SELECT author_user_id FROM app.judgment WHERE id = :id", id=row.id
        )[0]
        self.assertEqual(str(judgment.author_user_id), str(self.world.a.coach))

    def test_cross_team_goal_is_rejected(self) -> None:
        state = self.refused_write_as(
            self.world.a.coach,
            observation_id=self.observation_a,
            goal_id=self.goal_b,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_observation_and_goal_for_different_players_is_rejected(self) -> None:
        other_goal = self.admin_insert_goal(self.world.a.rows[1], self.world.a.coach)
        state = self.refused_write_as(
            self.world.a.coach,
            observation_id=self.observation_a,
            goal_id=other_goal,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_clip_bounds_outside_the_video_are_rejected(self) -> None:
        state = self.refused_write_as(
            self.world.a.coach, clip_start_ms=0, clip_end_ms=60001
        )
        self.assertEqual(state, INVALID_PARAMETER)

    def test_duplicate_observation_goal_pair_is_rejected(self) -> None:
        self.judgment_write_as(self.world.a.coach)
        with self.assertRaises(DBAPIError) as caught:
            self.judgment_write_as(self.world.a.coach)
        self.assertEqual(sqlstate(caught.exception), UNIQUE_VIOLATION)

    # --- Editing: original-author-only, versions, no-op/replay -------------

    def test_original_author_only_may_edit(self) -> None:
        """A second coach on the same team cannot edit another coach's draft."""
        created = self.judgment_write_as(self.world.a.coach)
        co_coach = self.create_auth_user("co.coach.a@example.test", "Co-coach A")
        self.add_membership(self.world.a.id, co_coach, "coach")
        state = self.refused_write_as(
            co_coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
        )
        self.assertEqual(state, NOT_ORIGINAL_AUTHOR)

    def test_edit_creates_a_new_revision_and_increments_version(self) -> None:
        created = self.judgment_write_as(self.world.a.coach)
        edited = self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            comment_text="Even better second touch.",
        )
        self.assertEqual(edited.version, 2)
        revisions = self.admin_read(
            "SELECT version, comment_text FROM app.judgment_revision"
            " WHERE judgment_id = :id ORDER BY version",
            id=created.id,
        )
        self.assertEqual([r.version for r in revisions], [1, 2])
        self.assertEqual(revisions[1].comment_text, "Even better second touch.")

    def test_no_op_replay_does_not_create_a_new_revision(self) -> None:
        created = self.judgment_write_as(self.world.a.coach)
        replayed = self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
        )
        self.assertEqual(replayed.version, 1)
        revisions = self.admin_read(
            "SELECT version FROM app.judgment_revision WHERE judgment_id = :id",
            id=created.id,
        )
        self.assertEqual(len(revisions), 1)

    def test_stale_version_is_rejected(self) -> None:
        created = self.judgment_write_as(self.world.a.coach)
        self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            comment_text="First edit.",
        )
        state = self.refused_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            comment_text="Stale edit.",
        )
        self.assertEqual(state, STALE_VERSION)

    def test_concurrent_edits_serialize_and_the_second_sees_the_new_version(
        self,
    ) -> None:
        """Two genuinely overlapping edits never both succeed against version 1.

        The second writer starts while the first still holds the row and has
        not committed, so it blocks on `FOR UPDATE` and only then reads the
        version. That is the behaviour the write path relies on, and it is
        the reason the check is inside the function rather than in the
        caller.

        An earlier version of this test committed the first transaction
        before opening the second, which independent review pointed out made
        it a second copy of the sequential stale-version test: the writers
        never overlapped and `FOR UPDATE` was never exercised.
        """
        created = self.judgment_write_as(self.world.a.coach)
        second_state: list[str | None] = []
        second_started = threading.Event()

        def second_writer() -> None:
            second_started.set()
            second_state.append(
                self.refused_write_as(
                    self.world.a.coach,
                    judgment_id=created.id,
                    observation_id=None,
                    goal_id=None,
                    expected_version=1,
                    comment_text="Loser.",
                )
            )

        first_conn = self.runtime.connect()
        first_txn = first_conn.begin()
        try:
            self.as_user(first_conn, self.world.a.coach)
            first_conn.execute(
                text(WRITE_SQL),
                {
                    "judgment_id": created.id,
                    "observation_id": None,
                    "goal_id": None,
                    "expected_version": 1,
                    "verdict": "applied",
                    "comment_text": "Winner.",
                    "clip_start_ms": 1000,
                    "clip_end_ms": 2000,
                },
            )
            # The row is held and uncommitted. The second writer must now be
            # waiting on the lock rather than deciding anything.
            thread = threading.Thread(target=second_writer, daemon=True)
            thread.start()
            self.assertTrue(second_started.wait(timeout=5))
            blocked = self.admin_read(
                """
                SELECT count(*) AS waiting FROM pg_stat_activity
                WHERE wait_event_type = 'Lock' AND state = 'active'
                  AND query ILIKE '%write_judgment_revision%'
                """
            )
            for _ in range(50):
                if int(blocked[0].waiting) > 0:
                    break
                time.sleep(0.1)
                blocked = self.admin_read(
                    """
                    SELECT count(*) AS waiting FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock' AND state = 'active'
                      AND query ILIKE '%write_judgment_revision%'
                    """
                )
            self.assertGreater(
                int(blocked[0].waiting),
                0,
                "the second writer must block on the held row, not proceed",
            )
            first_txn.commit()
        finally:
            if first_txn.is_active:
                first_txn.rollback()
            first_conn.close()

        thread.join(timeout=15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(second_state, [STALE_VERSION])
        revisions = self.admin_read(
            "SELECT version FROM app.judgment_revision WHERE judgment_id = :id",
            id=created.id,
        )
        self.assertEqual([r.version for r in revisions], [1, 2])

    def test_a_retry_of_an_accepted_edit_is_idempotent(self) -> None:
        """A client that lost the response retries with the version it knew.

        That version is now one behind, because its first attempt succeeded.
        Comparing versions before content answered the retry with a conflict,
        so an at-least-once client could never make the write idempotent --
        while `docs/04-api.md` requires an idempotent replay not to increment.
        Distinct from the no-op test above, which resubmits against the
        version that is still current.
        """
        created = self.judgment_write_as(self.world.a.coach)
        edited = self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="opportunity",
            comment_text="The edit that landed.",
        )
        self.assertEqual(edited.version, 2)

        # The same request again, still naming version 1.
        replayed = self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="opportunity",
            comment_text="The edit that landed.",
        )
        self.assertEqual(replayed.version, 2)
        revisions = self.admin_read(
            "SELECT version FROM app.judgment_revision WHERE judgment_id = :id",
            id=created.id,
        )
        self.assertEqual([r.version for r in revisions], [1, 2])

    def test_an_older_version_conflicts_even_when_content_coincides(self) -> None:
        """1=A, 2=B, 3=A: a client still on version 1 has seen neither change.

        Telling it the write applied would skip the conflict recovery the
        precondition exists for, because two revisions happened to coincide.
        The replay exemption covers the immediately preceding version only.
        """
        created = self.judgment_write_as(self.world.a.coach)
        # Each edit names the version it actually saw.
        self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="opportunity",
            comment_text="B.",
        )
        third = self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=2,
            verdict="applied",
            comment_text="Nice first touch.",
        )
        self.assertEqual(third.version, 3)

        # Version 1's content is byte-for-byte version 3's, and it must
        # still conflict.
        state = self.refused_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="applied",
            comment_text="Nice first touch.",
        )
        self.assertEqual(state, STALE_VERSION)

    def test_a_stale_edit_with_different_content_still_conflicts(self) -> None:
        """The precondition still does its job where an update could be lost."""
        created = self.judgment_write_as(self.world.a.coach)
        self.judgment_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="opportunity",
            comment_text="The edit that landed.",
        )
        state = self.refused_write_as(
            self.world.a.coach,
            judgment_id=created.id,
            observation_id=None,
            goal_id=None,
            expected_version=1,
            verdict="not_relevant",
            comment_text="Written against version 1, and different.",
        )
        self.assertEqual(state, STALE_VERSION)

    def test_rollback_after_a_rejected_edit_leaves_no_revision_gap(self) -> None:
        """A failed edit (invalid bounds) must not consume a version number."""
        created = self.judgment_write_as(self.world.a.coach)
        with self.assertRaises(DBAPIError):
            self.judgment_write_as(
                self.world.a.coach,
                judgment_id=created.id,
                observation_id=None,
                goal_id=None,
                expected_version=1,
                clip_start_ms=0,
                clip_end_ms=70000,
            )
        judgment = self.admin_read(
            "SELECT version FROM app.judgment WHERE id = :id", id=created.id
        )[0]
        self.assertEqual(judgment.version, 1)
        revisions = self.admin_read(
            "SELECT version FROM app.judgment_revision WHERE judgment_id = :id",
            id=created.id,
        )
        self.assertEqual([r.version for r in revisions], [1])

    def test_missing_judgment_id_is_reported_as_not_found(self) -> None:
        state = self.refused_write_as(
            self.world.a.coach,
            judgment_id=uuid4(),
            observation_id=None,
            goal_id=None,
            expected_version=1,
        )
        self.assertEqual(state, JUDGMENT_NOT_FOUND)

    def test_not_relevant_verdict_is_preserved_as_a_draft(self) -> None:
        row = self.judgment_write_as(self.world.a.coach, verdict="not_relevant")
        revision = self.admin_read(
            "SELECT verdict FROM app.judgment_revision WHERE judgment_id = :id",
            id=row.id,
        )[0]
        self.assertEqual(revision.verdict, "not_relevant")

    def test_rejected_snapshot_can_never_be_published_by_the_runtime_role(
        self,
    ) -> None:
        """No grant lets the runtime role set publication_status directly."""
        row = self.judgment_write_as(self.world.a.coach, verdict="not_relevant")
        state = self.refused_as_update(
            self.world.a.coach,
            "UPDATE app.judgment SET publication_status = 'published' WHERE id = :id",
            id=row.id,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def refused_as_update(
        self, user_id: UUID | str | None, sql: str, **parameters: Any
    ) -> str | None:
        with self.assertRaises((DBAPIError, ProgrammingError)) as caught:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, user_id)
                connection.execute(text(sql), parameters)
        return sqlstate(caught.exception)

    # --- No ordinary write path on either table -----------------------------

    def test_ordinary_role_cannot_write_judgment_directly(self) -> None:
        # The privilege check runs before any row is evaluated, so the INSERT
        # case needs no real observation/goal to prove the grant is absent.
        judgment = self.admin_insert_judgment()
        for statement in (
            "INSERT INTO app.judgment (observation_id, goal_id, author_user_id)"
            " VALUES (:observation, :goal, :coach)",
            "UPDATE app.judgment SET version = 99 WHERE id = :id",
            "DELETE FROM app.judgment WHERE id = :id",
        ):
            with self.subTest(verb=statement.split()[0]):
                state = self.refused_as_update(
                    self.world.a.coach,
                    statement,
                    observation=uuid4(),
                    goal=uuid4(),
                    coach=self.world.a.coach,
                    id=judgment.id,
                )
                self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_ordinary_role_cannot_write_judgment_revision_directly(self) -> None:
        judgment = self.admin_insert_judgment()
        for statement in (
            "INSERT INTO app.judgment_revision"
            " (judgment_id, version, author_user_id, verdict, comment_text,"
            "  clip_start_ms, clip_end_ms)"
            " VALUES (:id, 1, :coach, 'applied', 'Text', 0, 1000)",
            "UPDATE app.judgment_revision SET verdict = 'not_relevant'"
            " WHERE judgment_id = :id",
            "DELETE FROM app.judgment_revision WHERE judgment_id = :id",
        ):
            with self.subTest(verb=statement.split()[0]):
                state = self.refused_as_update(
                    self.world.a.coach,
                    statement,
                    id=judgment.id,
                    coach=self.world.a.coach,
                )
                self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    # --- Read isolation ------------------------------------------------------

    def test_players_and_other_teams_cannot_read_judgments(self) -> None:
        row = self.judgment_write_as(self.world.a.coach)
        for identity in (self.world.a.players[0], self.world.b.coach):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.read_as(
                        identity,
                        "SELECT id FROM app.judgment WHERE id = :id",
                        id=row.id,
                    ),
                    [],
                )
                self.assertEqual(
                    self.read_as(
                        identity,
                        "SELECT id FROM app.judgment_revision WHERE judgment_id = :id",
                        id=row.id,
                    ),
                    [],
                )

    def test_same_team_coach_can_read_the_judgment_and_its_revisions(self) -> None:
        row = self.judgment_write_as(self.world.a.coach)
        self.assertEqual(
            len(
                self.read_as(
                    self.world.a.coach,
                    "SELECT id FROM app.judgment WHERE id = :id",
                    id=row.id,
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self.read_as(
                    self.world.a.coach,
                    "SELECT id FROM app.judgment_revision WHERE judgment_id = :id",
                    id=row.id,
                )
            ),
            1,
        )
