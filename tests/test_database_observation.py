"""Task 14 observation schema, grants, and runtime-role isolation."""

import sys
import unittest
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

sys.path.append(str(Path(__file__).resolve().parent))

from isolation_fixtures import IsolationHarness  # noqa: E402
from test_database import CONFIGURED, sqlstate  # noqa: E402

CHECK_VIOLATION = "23514"
INSUFFICIENT_PRIVILEGE = "42501"


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class ObservationIsolationTests(IsolationHarness):
    def setUp(self) -> None:
        super().setUp()
        self.game_a = self.admin_insert_game(self.world.a.id, self.world.a.coach)
        self.game_b = self.admin_insert_game(self.world.b.id, self.world.b.coach)
        self.video_a = self.admin_insert_video(self.game_a, self.world.a.coach)
        self.video_b = self.admin_insert_video(self.game_b, self.world.b.coach)

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

    @staticmethod
    def insert_sql() -> str:
        return """
            INSERT INTO app.observation (
                video_id, player_id, t_start_ms, t_end_ms, source, created_by
            ) VALUES (
                :video, :player, :start, :end, 'coach_manual', :creator
            )
        """

    def admin_insert_observation(self, **overrides: Any) -> UUID:
        values = {
            "video": self.video_a,
            "player": self.world.a.rows[0],
            "start": 1000,
            "end": 4000,
            "creator": self.world.a.coach,
            **overrides,
        }
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text(self.insert_sql() + " RETURNING id"), values
                    ).scalar_one()
                )
            )

    def test_observation_is_owned_by_migration_role_with_forced_rls(self) -> None:
        with self.admin.connect() as connection:
            row = connection.execute(
                text("""
                    SELECT relrowsecurity, relforcerowsecurity,
                           relowner::regrole::text AS owner
                    FROM pg_class WHERE oid = 'app.observation'::regclass
                """)
            ).one()
        self.assertEqual(tuple(row), (True, True, "shoulder_migration"))

    def test_data_api_roles_have_no_observation_privileges(self) -> None:
        with self.admin.connect() as connection:
            for role in ("PUBLIC", "anon", "authenticated"):
                with self.subTest(role=role):
                    count = connection.execute(
                        text("""
                            SELECT count(*)
                            FROM information_schema.role_table_grants
                            WHERE table_schema = 'app'
                              AND table_name = 'observation'
                              AND grantee = :role
                        """),
                        {"role": role},
                    ).scalar_one()
                    self.assertEqual(count, 0)

    def test_same_team_coach_can_append_and_read_an_observation(self) -> None:
        self.assertEqual(
            self.write_as(
                self.world.a.coach,
                self.insert_sql(),
                video=self.video_a,
                player=self.world.a.rows[0],
                start=1000,
                end=4000,
                creator=self.world.a.coach,
            ),
            1,
        )
        self.assertEqual(
            len(
                self.read_as(
                    self.world.a.coach,
                    "SELECT id FROM app.observation WHERE video_id = :video",
                    video=self.video_a,
                )
            ),
            1,
        )

    def test_players_and_other_teams_cannot_read_observations(self) -> None:
        observation = self.admin_insert_observation()
        for identity in (self.world.a.players[0], self.world.b.coach):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.read_as(
                        identity,
                        "SELECT id FROM app.observation WHERE id = :id",
                        id=observation,
                    ),
                    [],
                )

    def test_wrong_team_player_is_rejected_by_the_database(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            self.insert_sql(),
            video=self.video_a,
            player=self.world.b.rows[0],
            start=1000,
            end=4000,
            creator=self.world.a.coach,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_spoofed_creator_is_rejected_by_the_database(self) -> None:
        state = self.refused_as(
            self.world.a.coach,
            self.insert_sql(),
            video=self.video_a,
            player=self.world.a.rows[0],
            start=1000,
            end=4000,
            creator=self.world.b.coach,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_database_rejects_bounds_outside_the_video(self) -> None:
        # PostgreSQL applies an INSERT policy's WITH CHECK before ordinary
        # table constraints, so every runtime rejection has the RLS SQLSTATE.
        for start, end in (
            (-1, 4000),
            (4000, 4000),
            (5000, 4000),
            (59000, 60001),
        ):
            with self.subTest(start=start, end=end):
                state = self.refused_as(
                    self.world.a.coach,
                    self.insert_sql(),
                    video=self.video_a,
                    player=self.world.a.rows[0],
                    start=start,
                    end=end,
                    creator=self.world.a.coach,
                )
                self.assertEqual(state, INSUFFICIENT_PRIVILEGE)

    def test_table_constraints_reject_malformed_bounds(self) -> None:
        for start, end in ((-1, 4000), (4000, 4000), (5000, 4000)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(DBAPIError) as caught:
                    with self.admin.connect() as connection, connection.begin():
                        connection.execute(
                            text(self.insert_sql()),
                            {
                                "video": self.video_a,
                                "player": self.world.a.rows[0],
                                "start": start,
                                "end": end,
                                "creator": self.world.a.coach,
                            },
                        )
                self.assertEqual(sqlstate(caught.exception), CHECK_VIOLATION)

    def test_observations_are_append_only_for_the_runtime_role(self) -> None:
        observation = self.admin_insert_observation()
        for statement in (
            "UPDATE app.observation SET t_start_ms = 0 WHERE id = :id",
            "DELETE FROM app.observation WHERE id = :id",
        ):
            with self.subTest(verb=statement.split()[0]):
                with (
                    self.assertRaises(ProgrammingError) as caught,
                    self.runtime.connect() as connection,
                    connection.begin(),
                ):
                    self.as_user(connection, self.world.a.coach)
                    connection.execute(text(statement), {"id": observation})
                self.assertEqual(sqlstate(caught.exception), INSUFFICIENT_PRIVILEGE)

    def test_client_generated_id_still_obeys_observation_rls(self) -> None:
        statement = """
            INSERT INTO app.observation (
                id, video_id, player_id, t_start_ms, t_end_ms, source, created_by
            ) VALUES (
                :id, :video, :player, 1000, 4000, 'coach_manual', :creator
            )
        """
        state = self.refused_as(
            self.world.b.coach,
            statement,
            id=uuid4(),
            video=self.video_a,
            player=self.world.a.rows[0],
            creator=self.world.b.coach,
        )
        self.assertEqual(state, INSUFFICIENT_PRIVILEGE)
