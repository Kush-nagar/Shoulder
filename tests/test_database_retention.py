"""Task 22 database deadline, onboarding-gate, and restore-replay acceptance."""

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.main import app
from services.worker import jobs, retention

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class RetentionDatabaseTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.dependency_overrides.clear)
        self.teams_with_manifests: list[UUID] = []
        self.addCleanup(self.delete_durable_manifests)
        self.coach = self.create_auth_user("retention.coach@example.test", "Coach")

    def delete_durable_manifests(self) -> None:
        if not self.teams_with_manifests:
            return
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("DELETE FROM app.deletion_manifest WHERE team_id = ANY(:teams)"),
                {"teams": self.teams_with_manifests},
            )

    def client_for(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[authenticated_identity] = lambda: str(user_id)
        return TestClient(app)

    def game(self, team_id: UUID) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.game (team_id, played_at, created_by)
                            VALUES (:team, :played, :coach) RETURNING id
                        """),
                        {"team": team_id, "played": NOW, "coach": self.coach},
                    ).scalar_one()
                )
            )

    def video(
        self,
        game_id: UUID,
        *,
        status: str,
        created_at: datetime,
        completed_at: datetime | None = None,
        failed_at: datetime | None = None,
        rejected_at: datetime | None = None,
        source_expires_at: datetime | None = None,
    ) -> UUID:
        video_id = uuid4()
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.video (
                        id, game_id, original_key, original_filename,
                        content_type, size_bytes, uploaded_by, status,
                        created_at, upload_completed_at,
                        first_terminal_failure_at, rejected_at,
                        source_expires_at, derivatives_expires_at,
                        playback_key, duration_ms, width, height, fps, ready_at
                    ) VALUES (
                        :id, :game, :original_key, 'match.mp4', 'video/mp4', 1,
                        :coach, :status, :created, :completed, :failed, :rejected,
                        :source_expiry, :derivative_expiry,
                        :playback_key, 60000, 1280, 720, 30,
                        CASE WHEN :status = 'ready' THEN :created END
                    )
                """),
                {
                    "id": video_id,
                    "game": game_id,
                    "original_key": f"originals/{video_id}/source.mp4",
                    "coach": self.coach,
                    "status": status,
                    "created": created_at,
                    "completed": completed_at,
                    "failed": failed_at,
                    "rejected": rejected_at,
                    "source_expiry": source_expires_at,
                    "derivative_expiry": NOW + timedelta(days=100),
                    "playback_key": storage.playback_key(video_id),
                },
            )
        return video_id

    def sweep(self, at: datetime) -> int:
        worker = f"clock-{uuid4()}"
        with self.admin.connect() as connection, connection.begin():
            job = connection.execute(
                text("""
                    INSERT INTO app.processing_job (
                        kind, idempotency_key, status, attempts, max_attempts,
                        locked_at, locked_by, heartbeat_at
                    ) VALUES (
                        'retention_sweep', :key, 'running', 1, 5,
                        :at, :worker, :at
                    ) RETURNING id
                """),
                {"key": f"clock:{uuid4()}", "at": at, "worker": worker},
            ).scalar_one()
            return int(
                connection.execute(
                    text("SELECT private.prepare_retention_sweep(:job, :worker, :at)"),
                    {"job": job, "worker": worker, "at": at},
                ).scalar_one()
            )

    def test_confirmation_is_required_before_the_first_media_upload(self) -> None:
        team = self.admin_insert_team(
            self.coach, "Confirmation FC", retention_confirmed=False
        )
        game = self.game(team)
        client = self.client_for(self.coach)

        status = client.get(f"/v1/teams/{team}/retention-status")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertFalse(status.json()["confirmed"])
        with patch.object(storage, "create_multipart") as create_multipart:
            blocked = client.post(
                f"/v1/games/{game}/videos/uploads",
                json={
                    "filename": "match.mp4",
                    "content_type": "video/mp4",
                    "size_bytes": 1024,
                    "sha256": None,
                },
            )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["type"].rsplit("/", 1)[-1],
            "retention-confirmation-required",
        )
        create_multipart.assert_not_called()

        incomplete = client.post(
            f"/v1/teams/{team}/retention-confirmation",
            json={
                "provider_backup_max_days": 30,
                "season_cutoff_confirmed": True,
                "provider_backup_expiry_confirmed": True,
                "notice_confirmed": True,
                "collateral_deletion_confirmed": False,
                "operator_confirmed": True,
            },
        )
        self.assertEqual(incomplete.status_code, 422)
        confirmed = client.post(
            f"/v1/teams/{team}/retention-confirmation",
            json={
                "provider_backup_max_days": 30,
                "season_cutoff_confirmed": True,
                "provider_backup_expiry_confirmed": True,
                "notice_confirmed": True,
                "collateral_deletion_confirmed": True,
                "operator_confirmed": True,
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()["confirmed"])

        with (
            self.assertRaises(DBAPIError) as caught,
            self.admin.connect() as connection,
            connection.begin(),
        ):
            connection.execute(
                text(
                    "UPDATE app.team SET season_end_at = season_end_at"
                    " + interval '1 day' WHERE id = :team"
                ),
                {"team": team},
            )
        self.assertEqual(sqlstate(caught.exception), "P2201")

    def test_every_video_deadline_is_inclusive_and_the_sweep_is_idempotent(
        self,
    ) -> None:
        team = self.admin_insert_team(self.coach, "Clock FC")
        self.teams_with_manifests.append(team)
        game = self.game(team)
        videos = {
            "incomplete": self.video(
                game, status="uploading", created_at=NOW - timedelta(days=7)
            ),
            "rejected": self.video(
                game,
                status="failed",
                created_at=NOW - timedelta(days=2),
                failed_at=NOW - timedelta(hours=24),
                rejected_at=NOW - timedelta(hours=24),
            ),
            "stuck": self.video(
                game,
                status="processing",
                created_at=NOW - timedelta(days=15),
                completed_at=NOW - timedelta(days=14),
                source_expires_at=NOW + timedelta(days=76),
            ),
            "failed": self.video(
                game,
                status="failed",
                created_at=NOW - timedelta(days=11),
                completed_at=NOW - timedelta(days=10),
                failed_at=NOW - timedelta(days=7),
                source_expires_at=NOW + timedelta(days=80),
            ),
            "source": self.video(
                game,
                status="ready",
                created_at=NOW - timedelta(days=91),
                completed_at=NOW - timedelta(days=90),
                source_expires_at=NOW,
            ),
        }
        self.assertEqual(self.sweep(NOW - timedelta(microseconds=1)), 0)
        self.assertEqual(self.sweep(NOW), 5)
        with self.admin.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT scope_key, deadline_at
                    FROM app.deletion_manifest WHERE team_id = :team
                """),
                {"team": team},
            ).all()
        self.assertEqual(len(rows), 5)
        serialized = " ".join(row.scope_key for row in rows)
        for video_id in videos.values():
            self.assertIn(str(video_id), serialized)
        self.sweep(NOW)
        with self.admin.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT count(*) FROM app.deletion_manifest"
                        " WHERE team_id = :team"
                    ),
                    {"team": team},
                ).scalar_one(),
                5,
            )

    def test_restore_replay_blocks_access_and_manifests_store_no_content(self) -> None:
        player_account = self.create_auth_user("retention.player@example.test")
        team = self.admin_insert_team(self.coach, "Restore FC")
        self.teams_with_manifests.append(team)
        player = self.admin_insert_player(team, user_id=player_account)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.team_membership (team_id, user_id, role)
                    VALUES (:team, :user, 'player')
                """),
                {"team": team, "user": player_account},
            )
        game = self.game(team)
        video = self.video(game, status="uploading", created_at=NOW)
        manifest = uuid4()
        with self.operator.connect() as connection, connection.begin():
            replayed = connection.execute(
                text("""
                    SELECT private.replay_deletion_suppression(
                        :manifest, 'player_erasure', :team, :player,
                        :requested, :backup
                    )
                """),
                {
                    "manifest": manifest,
                    "team": team,
                    "player": player,
                    "requested": NOW,
                    "backup": NOW + timedelta(days=30),
                },
            ).scalar_one()
        self.assertEqual(replayed, manifest)
        with self.admin.connect() as connection:
            state = connection.execute(
                text("""
                    SELECT p.active, p.deletion_pending_at IS NOT NULL,
                           t.media_deletion_pending_at IS NOT NULL, v.status
                    FROM app.player p JOIN app.team t ON t.id = p.team_id
                    JOIN app.game g ON g.team_id = t.id
                    JOIN app.video v ON v.game_id = g.id
                    WHERE p.id = :player AND v.id = :video
                """),
                {"player": player, "video": video},
            ).one()
            columns = {
                row.column_name
                for row in connection.execute(
                    text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'app'
                          AND table_name IN (
                              'deletion_manifest', 'deletion_manifest_object',
                              'product_event'
                          )
                    """)
                ).all()
            }
            manifest_owner = connection.execute(
                text("""
                    SELECT requested_by, operator_user_id
                    FROM app.deletion_manifest WHERE id = :manifest
                """),
                {"manifest": manifest},
            ).one()
        self.assertEqual(tuple(state), (False, True, True, "deletion_pending"))
        self.assertEqual(tuple(manifest_owner), (self.coach, self.coach))
        visible = self.client_for(self.coach).get(f"/v1/deletions/{manifest}")
        self.assertEqual(visible.status_code, 200, visible.text)
        for forbidden in (
            "comment_text",
            "reflection_text",
            "payload",
            "original_filename",
            "signed_url",
            "email",
            "duration_ms",
            "size_bytes",
            "width",
            "height",
            "fps",
        ):
            self.assertNotIn(forbidden, columns)
        self.assertEqual(
            self.client_for(player_account).get("/v1/me").json()["player"], None
        )

    def test_season_and_product_history_expire_at_the_exact_boundary(self) -> None:
        team = self.admin_insert_team(
            self.coach, "Season Clock FC", retention_confirmed=False
        )
        self.teams_with_manifests.append(team)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("UPDATE app.team SET season_end_at = :cutoff WHERE id = :team"),
                {"cutoff": NOW - timedelta(days=365), "team": team},
            )
            connection.execute(
                text("""
                    INSERT INTO app.retention_policy_confirmation (
                        team_id, confirmed_by, operator_user_id,
                        confirmed_season_end_at, provider_backup_max_days,
                        notice_confirmed_at, collateral_deletion_confirmed_at,
                        provider_backup_confirmed_at
                    ) VALUES (
                        :team, :coach, :coach, :cutoff, 30, now(), now(), now()
                    )
                """),
                {
                    "team": team,
                    "coach": self.coach,
                    "cutoff": NOW - timedelta(days=365),
                },
            )
        player = self.admin_insert_player(team)
        game = self.game(team)
        video = self.video(game, status="uploading", created_at=NOW)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.observation (
                        video_id, player_id, t_start_ms, t_end_ms,
                        source, created_by
                    ) VALUES (:video, :player, 0, 1000, 'coach_manual', :coach)
                """),
                {"video": video, "player": player, "coach": self.coach},
            )
            event = connection.execute(
                text("""
                    UPDATE app.product_event SET
                        occurred_at = :occurred, expires_at = :expires
                    WHERE team_id = :team RETURNING id
                """),
                {
                    "occurred": NOW - timedelta(days=180),
                    "expires": NOW,
                    "team": team,
                },
            ).scalar_one()
        self.assertEqual(self.sweep(NOW - timedelta(microseconds=1)), 0)
        with self.admin.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT count(*) FROM app.product_event WHERE id = :id"),
                    {"id": event},
                ).scalar_one(),
                1,
            )
        self.assertEqual(self.sweep(NOW), 1)
        with self.admin.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT count(*) FROM app.product_event WHERE id = :id"),
                    {"id": event},
                ).scalar_one(),
                0,
            )
            manifest = connection.execute(
                text("""
                    SELECT kind, deadline_at FROM app.deletion_manifest
                    WHERE team_id = :team
                """),
                {"team": team},
            ).one()
        self.assertEqual(manifest.kind, "season_expiry")
        self.assertEqual(manifest.deadline_at, NOW)

    def test_manifest_expiry_records_partial_failure_and_retries(self) -> None:
        team = self.admin_insert_team(self.coach, "Ledger Cleanup FC")
        self.teams_with_manifests.append(team)
        manifest_id = uuid4()

        def running_sweep(worker: str) -> jobs.Job:
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
                    {"key": f"ledger:{uuid4()}", "worker": worker},
                ).scalar_one()
            return jobs.Job(
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

        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("""
                    INSERT INTO app.deletion_manifest (
                        id, kind, scope_key, team_id, requested_by,
                        operator_user_id, status, deadline_at,
                        backup_expires_at, backup_verified_at,
                        active_cleanup_verified_at, completed_at, expires_at
                    ) VALUES (
                        :id, 'season_expiry', :scope, :team, :coach, :coach,
                        'completed', now() - interval '60 days',
                        now() - interval '31 days', now() - interval '31 days',
                        now() - interval '31 days', now() - interval '31 days',
                        now() - interval '1 second'
                    )
                """),
                {
                    "id": manifest_id,
                    "scope": f"expired-ledger:{manifest_id}",
                    "team": team,
                    "coach": self.coach,
                },
            )

        first = running_sweep("ledger-failure")
        with patch.object(
            retention.storage, "delete_object", side_effect=Exception("private")
        ):
            with self.assertRaises(retention.RetentionError):
                retention.retention_sweep_job(first, lambda _progress: True)
        with self.admin.connect() as connection:
            failed = connection.execute(
                text("""
                    SELECT status, failure_code FROM app.deletion_manifest
                    WHERE id = :id
                """),
                {"id": manifest_id},
            ).one()
        self.assertEqual(tuple(failed), ("unresolved", "suppression_record_failed"))

        retry = running_sweep("ledger-retry")
        with (
            patch.object(retention.storage, "delete_object"),
            patch.object(retention.storage, "head_object", return_value=None),
        ):
            retention.retention_sweep_job(retry, lambda _progress: True)
        with self.admin.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT count(*) FROM app.deletion_manifest WHERE id = :id"),
                    {"id": manifest_id},
                ).scalar_one(),
                0,
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
