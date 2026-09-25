"""Block 09B W1 training and match sessions (ADR 0023).

Isolation runs through `shoulder_api` (RLS) at both the database and API
layers. Bounds are checked in the request model and again by the table.
"""

import dataclasses
import json
import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.main import app
from services.api.schemas import TrainingSessionCreate
from services.worker import jobs, retention

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
BASE = "/v1/player/sessions"


def body(**changes: Any) -> dict[str, Any]:
    end = datetime.now(UTC) - timedelta(minutes=5)
    value: dict[str, Any] = {
        "kind": "training",
        "started_at": (end - timedelta(minutes=60)).isoformat(),
        "ended_at": end.isoformat(),
        "duration_s": 3600,
        "distance_m": 6200,
        "top_speed_cms": 780,
        "sprint_count": 9,
        "half_split_s": 1800,
        "heatmap": [10] * 96,
        "heatmap_second_half": [0] * 95 + [1000],
        "gps_quality": "good",
        "note": "Wet pitch",
    }
    value.update(changes)
    return value


class SessionValidationTests(unittest.TestCase):
    def test_contract_example_is_accepted(self) -> None:
        TrainingSessionCreate.model_validate(body())
        TrainingSessionCreate.model_validate(
            body(half_split_s=None, heatmap_second_half=None, note=None)
        )

    def test_coordinates_and_unknown_fields_are_rejected(self) -> None:
        for extra in (
            {"lat": 51.5},
            {"latitude": 51.5, "longitude": -0.12},
            {"lng": -0.12},
            {"points": [[51.5, -0.12]]},
            {"track": {"coordinates": [[1, 2]]}},
            {"heatmap": [[51.5, -0.12]] * 96},
            {"note": "Met at 51.50735, -0.12776"},
        ):
            with self.subTest(extra=list(extra)):
                with self.assertRaises(ValidationError):
                    TrainingSessionCreate.model_validate(body(**extra))

    def test_bounds_are_enforced(self) -> None:
        end = datetime.now(UTC)
        for change in (
            {"duration_s": 59},
            {"duration_s": 14401},
            {"distance_m": 30001},
            {"distance_m": -1},
            {"top_speed_cms": 1301},
            {"sprint_count": 501},
            {"half_split_s": 0},
            {"half_split_s": 3600},
            {"heatmap": [0] * 95},
            {"heatmap": [0] * 97},
            {"heatmap": [1001] + [0] * 95},
            {"heatmap": [-1] + [0] * 95},
            {"heatmap_second_half": [0] * 12},
            {"half_split_s": None},  # a second-half heatmap needs a split
            {"gps_quality": "great"},
            {"kind": "friendly"},
            {"note": "x" * 281},
            {"ended_at": (end - timedelta(hours=3)).isoformat()},
            {"started_at": "2026-01-01T10:00:00"},  # naive
            {"ended_at": (end + timedelta(hours=1)).isoformat()},
            {"duration_s": 7200},  # longer than the elapsed hour
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    TrainingSessionCreate.model_validate(body(**change))

    def test_oversized_body_is_refused_before_parsing(self) -> None:
        app.dependency_overrides[authenticated_identity] = lambda: str(uuid4())
        self.addCleanup(app.dependency_overrides.clear)
        response = TestClient(app).post(
            BASE,
            content=json.dumps(body(pad="x" * 5000)),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class TrainingSessionTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.coach = self.create_auth_user("session.coach@example.test", "Coach")
        self.other_coach = self.create_auth_user("session.other@example.test", "Oc")
        self.user_a = self.create_auth_user("session.a@example.test", "Player A")
        self.user_b = self.create_auth_user("session.b@example.test", "Player B")
        self.team = self.admin_insert_team(self.coach, "Session FC")
        self.admin_insert_team(self.other_coach, "Other FC")
        self.player_a = self.linked_player(self.user_a, 7)
        self.player_b = self.linked_player(self.user_b, 8)
        self.session_a = self.admin_session(self.player_a)
        self.session_b = self.admin_session(self.player_b)

    def linked_player(self, user_id: UUID, jersey: int) -> UUID:
        player = self.admin_insert_player(
            self.team, user_id=user_id, display_name=f"P{jersey}", jersey_number=jersey
        )
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": self.team, "user": user_id},
            )
        return player

    def admin_session(self, player: UUID, *, age: str = "1 hour") -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text(f"""
                            INSERT INTO app.training_session (
                                player_id, kind, started_at, ended_at,
                                duration_s, distance_m, top_speed_cms,
                                sprint_count, heatmap, gps_quality, created_at
                            ) VALUES (
                                :player, 'match', now() - interval '{age}'
                                - interval '1 hour', now() - interval '{age}',
                                3600, 5000, 700, 4, array_fill(0::smallint,
                                ARRAY[96]), 'fair', now() - interval '{age}'
                            ) RETURNING id
                        """),
                        {"player": player},
                    ).scalar_one()
                )
            )

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def visible(self, user_id: UUID) -> set[UUID]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user_id)
            rows = connection.execute(text("SELECT id FROM app.training_session"))
            return {UUID(str(row.id)) for row in rows}

    def count(self, session_id: UUID) -> int:
        with self.admin.connect() as connection:
            return int(
                connection.execute(
                    text("SELECT count(*) FROM app.training_session WHERE id = :id"),
                    {"id": session_id},
                ).scalar_one()
            )

    # -- database layer -------------------------------------------------------

    def test_database_reads_are_player_self_and_team_coach(self) -> None:
        self.assertEqual(self.visible(self.user_a), {self.session_a})
        self.assertEqual(self.visible(self.user_b), {self.session_b})
        self.assertEqual(self.visible(self.coach), {self.session_a, self.session_b})
        self.assertEqual(self.visible(self.other_coach), set())

    def test_database_writes_are_refused_across_players_and_for_coaches(
        self,
    ) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.user_a)
            deleted = connection.execute(
                text("DELETE FROM app.training_session WHERE id = :id"),
                {"id": self.session_b},
            ).rowcount
        self.assertEqual(deleted, 0)
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.coach)
            deleted = connection.execute(
                text("DELETE FROM app.training_session WHERE id = :id"),
                {"id": self.session_a},
            ).rowcount
        self.assertEqual(deleted, 0)
        insert = """
            INSERT INTO app.training_session (
                player_id, kind, started_at, ended_at, duration_s, distance_m,
                top_speed_cms, sprint_count, heatmap, gps_quality
            ) VALUES (
                :player, 'training', now() - interval '2 hours', now(), 3600,
                1, 1, 0, array_fill(0::smallint, ARRAY[96]), 'good'
            )
        """
        for user, player in ((self.user_a, self.player_b), (self.coach, self.player_a)):
            with self.subTest(user=user):
                with self.assertRaises(DBAPIError) as caught:
                    with self.runtime.connect() as connection, connection.begin():
                        self.as_user(connection, user)
                        connection.execute(text(insert), {"player": player})
                self.assertEqual(sqlstate(caught.exception), "42501")
        with self.assertRaises(DBAPIError) as caught:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, self.user_a)
                connection.execute(
                    text("UPDATE app.training_session SET distance_m = 1")
                )
        self.assertEqual(sqlstate(caught.exception), "42501")
        self.assertEqual(self.count(self.session_b), 1)

    def test_database_bounds_hold_without_the_api(self) -> None:
        for column, value in (
            ("duration_s", "59"),
            ("distance_m", "30001"),
            ("top_speed_cms", "1301"),
            ("sprint_count", "501"),
            ("heatmap", "array_fill(0::smallint, ARRAY[95])"),
            ("heatmap", "array_fill(1001::smallint, ARRAY[96])"),
            ("heatmap", "array_fill(NULL::smallint, ARRAY[96])"),
            ("gps_quality", "'great'"),
            ("ended_at", "now() - interval '3 hours'"),
        ):
            with self.subTest(column=column, value=value):
                with self.assertRaises(DBAPIError) as caught:
                    with self.admin.connect() as connection, connection.begin():
                        connection.execute(
                            text(f"""
                                UPDATE app.training_session SET {column} = {value}
                                WHERE id = :id
                            """),
                            {"id": self.session_a},
                        )
                self.assertEqual(sqlstate(caught.exception), "23514")

    # -- API layer ------------------------------------------------------------

    def test_api_round_trip_and_summary(self) -> None:
        client = self.client_for(self.user_a)
        created = client.post(BASE, json=body())
        self.assertEqual(created.status_code, 201, created.text)
        session_id = created.json()["id"]
        self.assertEqual(created.json()["heatmap_second_half"][-1], 1000)
        listed = [item["id"] for item in client.get(BASE).json()]
        self.assertEqual(set(listed), {session_id, str(self.session_a)})
        self.assertEqual(client.get(f"{BASE}/{session_id}").status_code, 200)
        summary = client.get(f"{BASE}/summary", params={"weeks": 12}).json()
        self.assertEqual(len(summary["weeks"]), 12)
        self.assertEqual(summary["records"]["distance_m"]["value"], 6200)
        self.assertEqual(summary["records"]["distance_m"]["session_id"], session_id)
        self.assertEqual(client.get(f"{BASE}/summary?weeks=53").status_code, 422)
        self.assertEqual(client.delete(f"{BASE}/{session_id}").status_code, 204)
        self.assertEqual(client.get(f"{BASE}/{session_id}").status_code, 404)

    def test_api_isolates_every_endpoint(self) -> None:
        client = self.client_for(self.user_a)
        target = f"{BASE}/{self.session_b}"
        self.assertEqual(client.get(target).status_code, 404)
        self.assertEqual(client.delete(target).status_code, 404)
        self.assertEqual(
            client.get(f"/v1/players/{self.player_b}/sessions").status_code, 404
        )
        self.assertEqual(
            [item["id"] for item in client.get(BASE).json()], [str(self.session_a)]
        )
        self.assertNotIn(
            str(self.session_b),
            json.dumps(client.get(f"{BASE}/summary").json()),
        )
        self.assertEqual(self.count(self.session_b), 1)

    def test_coach_reads_own_team_only_and_cannot_write(self) -> None:
        coach = self.client_for(self.coach)
        rows = coach.get(f"/v1/players/{self.player_a}/sessions")
        self.assertEqual(rows.status_code, 200, rows.text)
        self.assertEqual([item["id"] for item in rows.json()], [str(self.session_a)])
        self.assertEqual(coach.get(BASE).status_code, 403)
        self.assertEqual(coach.post(BASE, json=body()).status_code, 403)
        self.assertEqual(coach.delete(f"{BASE}/{self.session_a}").status_code, 404)
        other = self.client_for(self.other_coach)
        self.assertEqual(
            other.get(f"/v1/players/{self.player_a}/sessions").status_code, 404
        )
        self.assertEqual(self.count(self.session_a), 1)

    # -- retention ------------------------------------------------------------

    @unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
    def test_retention_purges_sessions_older_than_365_days(self) -> None:
        old = self.admin_session(self.player_a, age="366 days")
        kept = self.admin_session(self.player_a, age="364 days")
        worker = f"sessions-{uuid4()}"
        with self.admin.connect() as connection, connection.begin():
            job_id = connection.execute(
                text("""
                    INSERT INTO app.processing_job (
                        kind, idempotency_key, status, attempts, max_attempts,
                        locked_at, locked_by, heartbeat_at
                    ) VALUES (
                        'retention_sweep', :key, 'running', 1, 5,
                        now(), :worker, now()
                    ) RETURNING id
                """),
                {"key": f"sessions:{uuid4()}", "worker": worker},
            ).scalar_one()
        job = jobs.Job(
            id=UUID(str(job_id)),
            kind="retention_sweep",
            video_id=None,
            email_delivery_id=None,
            player_id=None,
            deletion_manifest_id=None,
            attempts=1,
            max_attempts=5,
            payload={},
            locked_by=worker,
        )
        stale = dataclasses.replace(job, locked_by="not-the-holder")
        self.assertEqual(retention.purge_training_sessions(stale), 0)
        self.assertEqual(self.count(old), 1)
        self.assertGreaterEqual(retention.purge_training_sessions(job), 1)
        self.assertEqual((self.count(old), self.count(kept)), (0, 1))
        self.assertEqual(self.count(self.session_a), 1)

    def test_player_erasure_cascades(self) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.player WHERE id = :id"), {"id": self.player_a}
            )
        self.assertEqual(self.count(self.session_a), 0)
        self.assertEqual(self.count(self.session_b), 1)
