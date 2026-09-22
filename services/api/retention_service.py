"""Retention confirmation and verified player-erasure database operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem


def require_real_data_onboarding_ready(connection: Connection, team_id: UUID) -> None:
    """Fence names, accounts, goals, games, and footage behind owner sign-off."""
    row = connection.execute(
        text("""
            SELECT confirmation.team_id IS NOT NULL AS retention_confirmed,
                   team.media_deletion_pending_at IS NULL AS media_open
            FROM app.team team
            LEFT JOIN app.retention_policy_confirmation confirmation
              ON confirmation.team_id = team.id
            WHERE team.id = :team_id AND private.is_team_coach(team.id)
        """),
        {"team_id": str(team_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That team is not available.")
    if not row.retention_confirmed:
        raise Problem(
            409,
            "Confirm the retention and deletion setup before adding real data.",
            "retention-confirmation-required",
        )
    if not row.media_open:
        raise Problem(
            409,
            "Team deletion is in progress. New data cannot be added yet.",
            "team-media-deletion-pending",
        )


def retention_status(connection: Connection, team_id: UUID) -> Any | None:
    return connection.execute(
        text("""
            SELECT team.id AS team_id,
                   confirmation.team_id IS NOT NULL AS confirmed,
                   team.season_end_at,
                   confirmation.confirmed_by,
                   confirmation.operator_user_id,
                   confirmation.provider_backup_max_days,
                   confirmation.created_at AS confirmed_at
            FROM app.team team
            LEFT JOIN app.retention_policy_confirmation confirmation
              ON confirmation.team_id = team.id
            WHERE team.id = :team_id
              AND private.is_team_coach(team.id)
        """),
        {"team_id": str(team_id)},
    ).one_or_none()


def confirm_retention(
    connection: Connection,
    team_id: UUID,
    provider_backup_max_days: int,
    season_cutoff_confirmed: bool,
    provider_backup_expiry_confirmed: bool,
    notice_confirmed: bool,
    collateral_confirmed: bool,
    operator_confirmed: bool,
) -> Any:
    connection.execute(
        text("""
            SELECT private.confirm_retention_policy(
                :team_id, :backup_days, :season_cutoff_confirmed,
                :provider_backup_expiry_confirmed, :notice_confirmed,
                :collateral_confirmed, :operator_confirmed
            )
        """),
        {
            "team_id": str(team_id),
            "backup_days": provider_backup_max_days,
            "season_cutoff_confirmed": season_cutoff_confirmed,
            "provider_backup_expiry_confirmed": provider_backup_expiry_confirmed,
            "notice_confirmed": notice_confirmed,
            "collateral_confirmed": collateral_confirmed,
            "operator_confirmed": operator_confirmed,
        },
    )
    return retention_status(connection, team_id)


def erasure_impact(connection: Connection, player_id: UUID) -> Any | None:
    return connection.execute(
        text("SELECT * FROM private.player_erasure_impact(:player_id)"),
        {"player_id": str(player_id)},
    ).one_or_none()


def request_erasure(
    connection: Connection,
    *,
    player_id: UUID,
    idempotency_key: str,
    expected_video_count: int,
    expected_other_player_clip_count: int,
    collateral_confirmed: bool,
    notice_confirmed: bool,
    unrelated_reviewed: bool,
) -> UUID:
    value = connection.execute(
        text("""
            SELECT (private.request_player_erasure(
                :player_id, :idempotency_key, :video_count, :clip_count,
                :collateral_confirmed, :notice_confirmed,
                :unrelated_reviewed
            )).id
        """),
        {
            "player_id": str(player_id),
            "idempotency_key": idempotency_key,
            "video_count": expected_video_count,
            "clip_count": expected_other_player_clip_count,
            "collateral_confirmed": collateral_confirmed,
            "notice_confirmed": notice_confirmed,
            "unrelated_reviewed": unrelated_reviewed,
        },
    ).scalar_one()
    return UUID(str(value))


def deletion_status(connection: Connection, manifest_id: UUID) -> Any | None:
    return connection.execute(
        text("SELECT * FROM private.deletion_manifest_status(:manifest_id)"),
        {"manifest_id": str(manifest_id)},
    ).one_or_none()


def team_deletion_statuses(connection: Connection, team_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            text("SELECT * FROM private.team_deletion_statuses(:team_id)"),
            {"team_id": str(team_id)},
        ).all()
    )


def confirm_backup_expired(connection: Connection, manifest_id: UUID) -> Any:
    connection.execute(
        text("SELECT private.confirm_manifest_backup_expired(:manifest_id)"),
        {"manifest_id": str(manifest_id)},
    )
    return deletion_status(connection, manifest_id)
