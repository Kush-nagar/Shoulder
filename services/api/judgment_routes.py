"""HTTP boundary for Task 15 coach judgments and their revision history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.judgment_service import create_judgment as create_judgment_service
from services.api.judgment_service import edit_judgment as edit_judgment_service
from services.api.judgment_service import list_revisions as list_revisions_service
from services.api.problems import Problem
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    Judgment,
    JudgmentCreate,
    JudgmentPatch,
    JudgmentRevision,
)

router = APIRouter(prefix="/v1")


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = str(version)


@router.post(
    "/observations/{observation_id}/judgments",
    response_model=Judgment,
    status_code=201,
    dependencies=PRIVATE,
)
def create_judgment(
    observation_id: UUID,
    request: JudgmentCreate,
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Judgment:
    try:
        with user_transaction(user_id) as connection:
            result = create_judgment_service(
                connection,
                observation_id,
                request.goal_id,
                request.verdict,
                request.comment_text,
                request.clip_start_ms,
                request.clip_end_ms,
            )
    except DBAPIError:
        raise unavailable() from None
    _etag(response, result["version"])
    return Judgment(**result)


@router.patch(
    "/judgments/{judgment_id}",
    response_model=Judgment,
    dependencies=PRIVATE,
)
def edit_judgment(
    judgment_id: UUID,
    request: JudgmentPatch,
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Judgment:
    if if_match is None:
        raise Problem(
            428,
            "An If-Match header with the current version is required.",
            "precondition-required",
            "Precondition required",
        )
    try:
        expected_version = int(if_match)
        if expected_version <= 0:
            raise ValueError
    except ValueError:
        raise Problem(400, "If-Match must be a positive version number.") from None
    try:
        with user_transaction(user_id) as connection:
            result = edit_judgment_service(
                connection,
                judgment_id,
                expected_version,
                request.verdict,
                request.comment_text,
                request.clip_start_ms,
                request.clip_end_ms,
            )
    except DBAPIError:
        raise unavailable() from None
    _etag(response, result["version"])
    return Judgment(**result)


@router.get(
    "/judgments/{judgment_id}/revisions",
    response_model=list[JudgmentRevision],
    dependencies=PRIVATE,
)
def list_revisions(
    judgment_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[JudgmentRevision]:
    try:
        with user_transaction(user_id) as connection:
            rows = list_revisions_service(connection, judgment_id)
    except DBAPIError:
        raise unavailable() from None
    return [JudgmentRevision(**dict(row._mapping)) for row in rows]
