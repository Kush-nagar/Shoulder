"""HTTP boundary for Task 15 coach judgments and their revision history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.judgment_service import StaleJudgment
from services.api.judgment_service import create_judgment as create_judgment_service
from services.api.judgment_service import edit_judgment as edit_judgment_service
from services.api.judgment_service import list_revisions as list_revisions_service
from services.api.judgment_service import load_judgment as load_judgment_service
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
    """An entity-tag is a quoted string, so send one.

    It used to be sent bare. A client that correctly echoed it back as
    `If-Match: "3"` was then rejected with 400 by the parser below, which is
    the version precondition failing on the exact clients that implement HTTP
    properly.
    """
    response.headers["ETag"] = f'"{version}"'


def if_match_version(request: Request) -> int:
    """The version the request's `If-Match` names.

    Read from the raw headers rather than declared as a typed parameter, so
    that FastAPI does not also publish an inferred one. Declared optional it
    reached the contract as optional, which let a generated client omit the
    precondition this endpoint is built around; declared required, FastAPI
    answers a missing header with its own 422 instead of the 428 the
    specification asks for. Reading it here keeps both: the route documents a
    single required header through `openapi_extra`, and the runtime answers
    428 itself.
    """
    return _expected_version(request.headers.get("If-Match"))


def _expected_version(if_match: str | None) -> int:
    """The version an `If-Match` names, quoted or bare.

    `*` is refused rather than accepted as "any": this endpoint exists to
    reject an edit that did not see the current version, and a wildcard
    precondition is the one thing that cannot establish that. A weak
    validator (`W/"3"`) is refused for the same reason -- weak comparison is
    not a basis for deciding whether a write is safe.
    """
    if if_match is None:
        raise Problem(
            428,
            "An If-Match header with the current version is required.",
            "precondition-required",
            "Precondition required",
        )
    token = if_match.strip()
    if token == "*" or token.startswith("W/"):
        raise Problem(400, "If-Match must name an exact version.")
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    try:
        version = int(token)
    except ValueError:
        raise Problem(400, "If-Match must be a positive version number.") from None
    if version <= 0:
        raise Problem(400, "If-Match must be a positive version number.")
    return version


def _conflict(user_id: str, judgment_id: UUID) -> Problem:
    """The 409 for a lost version race, carrying what it lost to.

    `docs/04-api.md` requires the latest coach-authored snapshot so the client
    can recover its draft instead of discarding the coach's words. The write
    transaction is already aborted by the time this runs, so the snapshot is
    read fresh, under the same row-level security as any other read: a caller
    who may no longer read this judgment is told only that it conflicted.

    A database failure here is not a conflict without a snapshot. It used to
    be caught and flattened into one, which independent review pointed out
    masks an outage as a recoverable conflict at the exact moment the client
    needs the snapshot to recover. The failure propagates and the route
    answers 503; only a genuinely absent row -- hidden by row-level security
    -- omits the extension.
    """
    with user_transaction(user_id) as connection:
        current = load_judgment_service(connection, judgment_id)
    extensions = (
        {"current": Judgment(**current).model_dump(mode="json")} if current else None
    )
    return Problem(
        409,
        "This judgment changed since it was loaded.",
        "judgment-version-conflict",
        extensions=extensions,
    )


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
    # The header is declared required in the generated contract while the
    # runtime still answers a missing one with 428 rather than FastAPI's 422.
    # Typed as optional it was published as optional, so a generated client
    # could omit the precondition and still satisfy the contract -- which is
    # the mandatory `If-Match` this endpoint is built around, absent from the
    # only description of the API anyone codes against.
    openapi_extra={
        "parameters": [
            {
                "in": "header",
                "name": "If-Match",
                "required": True,
                "schema": {"type": "string"},
                "description": (
                    "The judgment version this edit was written against, as "
                    "returned by ETag. Quoted or bare; `*` and weak "
                    "validators are refused."
                ),
            }
        ]
    },
)
def edit_judgment(
    judgment_id: UUID,
    request: JudgmentPatch,
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
    expected_version: Annotated[int, Depends(if_match_version)] = 0,
) -> Judgment:
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
    except StaleJudgment:
        # Built in its own step: an exception raised inside an `except` block
        # is not caught by that statement's other handlers, so a database
        # failure while reading the snapshot would leave this route with an
        # unhandled error rather than the 503 it owes.
        try:
            conflict = _conflict(user_id, judgment_id)
        except DBAPIError:
            raise unavailable() from None
        raise conflict from None
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
