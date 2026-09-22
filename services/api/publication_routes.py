"""Coach publication controls and player-safe evidence reads."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.problems import Problem
from services.api.publication_service import (
    cancel_publication,
    clip_for_signing,
    coach_evidence_sets,
    evidence_sets,
    load_publication,
    publication_error,
    request_publication,
    retry_publication,
    withdraw_judgment,
)
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    ClipUrl,
    ClipUrlRequest,
    CoachEvidenceSet,
    EvidenceDot,
    EvidenceItem,
    EvidenceSet,
    ReviewPublication,
    ReviewPublicationRequest,
)

router = APIRouter(prefix="/v1")


def _database_problem(error: DBAPIError) -> Problem:
    return publication_error(error) or unavailable()


@router.post(
    "/reviews/{game_id}/{player_id}/publish",
    response_model=ReviewPublication,
    status_code=202,
    dependencies=PRIVATE,
)
def publish_review(
    game_id: UUID,
    player_id: UUID,
    request: ReviewPublicationRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReviewPublication:
    if idempotency_key is None or not 1 <= len(idempotency_key) <= 200:
        raise Problem(
            422,
            "An Idempotency-Key header is required.",
            "idempotency-key-required",
        )
    try:
        with user_transaction(user_id) as connection:
            result = request_publication(
                connection,
                game_id=game_id,
                player_id=player_id,
                goal_id=request.goal_id,
                replaces_publication_id=request.replaces_publication_id,
                idempotency_key=idempotency_key,
                judgment_ids=[item.judgment_id for item in request.items],
                versions=[item.version for item in request.items],
            )
    except DBAPIError as error:
        raise _database_problem(error) from None
    return ReviewPublication(**result)


@router.get(
    "/review-publications/{publication_id}",
    response_model=ReviewPublication,
    dependencies=PRIVATE,
)
def get_publication(
    publication_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> ReviewPublication:
    try:
        with user_transaction(user_id) as connection:
            result = load_publication(connection, publication_id)
    except DBAPIError:
        raise unavailable() from None
    if result is None:
        raise Problem(404, "That review publication is not available.")
    return ReviewPublication(**result)


def _publication_transition(
    publication_id: UUID, user_id: str, retry: bool
) -> ReviewPublication:
    try:
        with user_transaction(user_id) as connection:
            result = (
                retry_publication(connection, publication_id)
                if retry
                else cancel_publication(connection, publication_id)
            )
    except DBAPIError as error:
        raise _database_problem(error) from None
    return ReviewPublication(**result)


@router.post(
    "/review-publications/{publication_id}/retry",
    response_model=ReviewPublication,
    status_code=202,
    dependencies=PRIVATE,
)
def retry(
    publication_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> ReviewPublication:
    return _publication_transition(publication_id, user_id, True)


@router.post(
    "/review-publications/{publication_id}/cancel",
    response_model=ReviewPublication,
    dependencies=PRIVATE,
)
def cancel(
    publication_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> ReviewPublication:
    return _publication_transition(publication_id, user_id, False)


@router.post(
    "/judgments/{judgment_id}/withdraw",
    status_code=204,
    dependencies=PRIVATE,
)
def withdraw(
    judgment_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Response:
    try:
        with user_transaction(user_id) as connection:
            withdraw_judgment(connection, judgment_id)
    except DBAPIError as error:
        raise _database_problem(error) from None
    return Response(status_code=204)


@router.get(
    "/me/goals/{goal_id}/evidence",
    response_model=list[EvidenceSet],
    dependencies=PRIVATE,
)
def player_evidence(
    goal_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[EvidenceSet]:
    try:
        with user_transaction(user_id) as connection:
            rows = evidence_sets(connection, goal_id)
            connection.execute(
                text("SELECT private.record_player_opened(:goal_id)"),
                {"goal_id": str(goal_id)},
            )
    except DBAPIError:
        raise unavailable() from None
    grouped: list[EvidenceSet] = []
    for row in rows:
        if not grouped or grouped[-1].publication_id != row.publication_id:
            grouped.append(
                EvidenceSet(
                    publication_id=row.publication_id,
                    game_label=row.game_label,
                    published_at=row.published_at,
                    items=[],
                )
            )
        verdict_copy: Literal["You did this.", "Chance to do this."] = (
            "You did this." if row.verdict == "applied" else "Chance to do this."
        )
        grouped[-1].items.append(
            EvidenceItem(
                judgment_id=row.judgment_id,
                published_revision_id=row.published_revision_id,
                verdict=row.verdict,
                verdict_copy=verdict_copy,
                comment=row.comment_text,
                clip_duration_ms=row.duration_ms,
                coach_display_name=row.coach_display_name,
            )
        )
    return grouped


@router.get(
    "/players/{player_id}/goals/{goal_id}/evidence",
    response_model=list[CoachEvidenceSet],
    dependencies=PRIVATE,
)
def coach_player_evidence(
    player_id: UUID,
    goal_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[CoachEvidenceSet]:
    try:
        with user_transaction(user_id) as connection:
            rows = coach_evidence_sets(connection, player_id, goal_id)
    except DBAPIError:
        raise unavailable() from None
    if rows is None:
        raise Problem(404, "That player is not available.")
    grouped: list[CoachEvidenceSet] = []
    for row in rows:
        if not grouped or grouped[-1].publication_id != row.publication_id:
            grouped.append(
                CoachEvidenceSet(
                    publication_id=row.publication_id,
                    game_id=row.game_id,
                    game_label=row.game_label,
                    published_at=row.published_at,
                    items=[],
                )
            )
        grouped[-1].items.append(
            EvidenceDot(judgment_id=row.judgment_id, verdict=row.verdict)
        )
    return grouped


@router.post(
    "/me/judgments/{judgment_id}/clip-url",
    response_model=ClipUrl,
    dependencies=PRIVATE,
)
def player_clip_url(
    judgment_id: UUID,
    request: ClipUrlRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> ClipUrl:
    try:
        with user_transaction(user_id) as connection:
            row = clip_for_signing(
                connection, judgment_id, request.expected_published_revision_id
            )
            if row is None:
                raise Problem(
                    409,
                    "The published evidence changed. Refresh the complete "
                    "evidence set.",
                    "published-revision-changed",
                )
            url = storage.sign_player_get(row.storage_key)
    except DBAPIError:
        raise unavailable() from None
    except storage.StorageError:
        raise unavailable() from None
    return ClipUrl(
        url=url,
        expires_in=storage.PLAYER_GET_URL_SECONDS,
        published_revision_id=row.published_revision_id,
    )
