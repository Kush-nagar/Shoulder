"""Coach/operator-facing retention confirmation and erasure controls."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.problems import Problem
from services.api.retention_service import (
    confirm_backup_expired,
    confirm_retention,
    deletion_status,
    erasure_impact,
    request_erasure,
    retention_status,
    team_deletion_statuses,
)
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    DeletionStatus,
    PlayerErasureImpact,
    PlayerErasureRequest,
    RetentionConfirmationRequest,
    RetentionStatus,
)

router = APIRouter(prefix="/v1")


def _sqlstate(error: DBAPIError) -> str | None:
    value: str | None = getattr(error.orig, "sqlstate", None)
    return value


def _database_problem(error: DBAPIError) -> Problem:
    code = _sqlstate(error)
    if code == "P2202":
        return Problem(
            409,
            "Retention setup must be confirmed before deletion can start.",
            "retention-confirmation-required",
        )
    if code == "P2203":
        return Problem(
            409,
            "The deletion impact changed. Review it again before confirming.",
            "deletion-impact-changed",
        )
    if code == "P2204":
        return Problem(
            409,
            "The confirmed backup expiry has not been reached yet.",
            "backup-not-expired",
        )
    if code == "P2205":
        return Problem(
            409,
            "A deletion for that player is already in progress.",
            "deletion-already-pending",
        )
    if code == "42501":
        return Problem(404, "That deletion record is not available.")
    if code == "22023":
        return Problem(422, "Complete every required confirmation.")
    return unavailable()


def _retention_model(row: Any) -> RetentionStatus:
    return RetentionStatus(**row._mapping)


def _deletion_model(row: Any) -> DeletionStatus:
    return DeletionStatus(**row._mapping)


@router.get(
    "/teams/{team_id}/retention-status",
    response_model=RetentionStatus,
    dependencies=PRIVATE,
)
def read_retention_status(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> RetentionStatus:
    with user_transaction(user_id) as connection:
        row = retention_status(connection, team_id)
    if row is None:
        raise Problem(404, "That team is not available.")
    return _retention_model(row)


@router.post(
    "/teams/{team_id}/retention-confirmation",
    response_model=RetentionStatus,
    dependencies=PRIVATE,
)
def record_retention_confirmation(
    team_id: UUID,
    request: RetentionConfirmationRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> RetentionStatus:
    try:
        with user_transaction(user_id) as connection:
            row = confirm_retention(
                connection,
                team_id,
                request.provider_backup_max_days,
                request.season_cutoff_confirmed,
                request.provider_backup_expiry_confirmed,
                request.notice_confirmed,
                request.collateral_deletion_confirmed,
                request.operator_confirmed,
            )
    except DBAPIError as error:
        raise _database_problem(error) from None
    if row is None:
        raise Problem(404, "That team is not available.")
    return _retention_model(row)


@router.get(
    "/players/{player_id}/erasure-impact",
    response_model=PlayerErasureImpact,
    dependencies=PRIVATE,
)
def read_erasure_impact(
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> PlayerErasureImpact:
    with user_transaction(user_id) as connection:
        row = erasure_impact(connection, player_id)
    if row is None:
        raise Problem(404, "That player is not available.")
    challenge = (
        f"DELETE {row.video_count} TEAM VIDEOS AND "
        f"{row.other_player_clip_count} OTHER PLAYER CLIPS"
    )
    return PlayerErasureImpact(**row._mapping, challenge=challenge)


@router.post(
    "/players/{player_id}/erasure",
    response_model=DeletionStatus,
    status_code=202,
    dependencies=PRIVATE,
)
def start_player_erasure(
    player_id: UUID,
    request: PlayerErasureRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DeletionStatus:
    try:
        canonical_idempotency_key = str(UUID(idempotency_key or ""))
    except ValueError:
        raise Problem(
            422,
            "A UUID Idempotency-Key header is required.",
            "idempotency-key-required",
        )
    expected_challenge = (
        f"DELETE {request.expected_video_count} TEAM VIDEOS AND "
        f"{request.expected_other_player_clip_count} OTHER PLAYER CLIPS"
    )
    if request.challenge != expected_challenge:
        raise Problem(
            422,
            "Type the displayed deletion challenge exactly.",
            "deletion-challenge-mismatch",
        )
    try:
        with user_transaction(user_id) as connection:
            manifest_id = request_erasure(
                connection,
                player_id=player_id,
                idempotency_key=canonical_idempotency_key,
                expected_video_count=request.expected_video_count,
                expected_other_player_clip_count=(
                    request.expected_other_player_clip_count
                ),
                collateral_confirmed=request.collateral_deletion_confirmed,
                notice_confirmed=request.notice_confirmed,
                unrelated_reviewed=request.unrelated_data_reviewed,
            )
            row = deletion_status(connection, manifest_id)
    except DBAPIError as error:
        raise _database_problem(error) from None
    if row is None:
        raise unavailable()
    return _deletion_model(row)


@router.get(
    "/deletions/{manifest_id}",
    response_model=DeletionStatus,
    dependencies=PRIVATE,
)
def read_deletion_status(
    manifest_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> DeletionStatus:
    with user_transaction(user_id) as connection:
        row = deletion_status(connection, manifest_id)
    if row is None:
        raise Problem(404, "That deletion record is not available.")
    return _deletion_model(row)


@router.get(
    "/teams/{team_id}/deletions",
    response_model=list[DeletionStatus],
    dependencies=PRIVATE,
)
def read_team_deletions(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[DeletionStatus]:
    with user_transaction(user_id) as connection:
        rows = team_deletion_statuses(connection, team_id)
    return [_deletion_model(row) for row in rows]


@router.post(
    "/deletions/{manifest_id}/backup-expired",
    response_model=DeletionStatus,
    dependencies=PRIVATE,
)
def record_backup_expiry(
    manifest_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> DeletionStatus:
    try:
        with user_transaction(user_id) as connection:
            row = confirm_backup_expired(connection, manifest_id)
    except DBAPIError as error:
        raise _database_problem(error) from None
    if row is None:
        raise Problem(404, "That deletion record is not available.")
    return _deletion_model(row)
