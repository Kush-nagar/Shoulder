"""Player training and match sessions (ADR 0023, Block 09B W1).

The browser computes every aggregate from GPS fixes it keeps in memory; the
request body carries no coordinates, and `extra="forbid"` refuses any field
the contract does not name. The body is bounded before it is parsed.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.practice_routes import BoundedBodyRoute
from services.api.problems import Problem
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import SessionSummary, TrainingSession, TrainingSessionCreate
from services.api.tracking_service import (
    coach_sessions,
    delete_session,
    insert_session,
    load_session,
    own_player_id,
    player_sessions,
    session_model,
    summary,
)

router = APIRouter(prefix="/v1", route_class=BoundedBodyRoute)


@router.post(
    "/player/sessions",
    response_model=TrainingSession,
    status_code=201,
    dependencies=PRIVATE,
)
def create_session(
    request: TrainingSessionCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> TrainingSession:
    try:
        with user_transaction(user_id) as connection:
            row = insert_session(connection, own_player_id(connection), request)
    except DBAPIError:
        raise unavailable() from None
    return session_model(row)


@router.get(
    "/player/sessions", response_model=list[TrainingSession], dependencies=PRIVATE
)
def list_sessions(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[TrainingSession]:
    try:
        with user_transaction(user_id) as connection:
            rows = player_sessions(connection, own_player_id(connection))
    except DBAPIError:
        raise unavailable() from None
    return [session_model(row) for row in rows]


# Declared before `/{session_id}` so "summary" is never parsed as an id.
@router.get(
    "/player/sessions/summary", response_model=SessionSummary, dependencies=PRIVATE
)
def session_summary(
    user_id: Annotated[str, Depends(authenticated_identity)],
    weeks: Annotated[int, Query(ge=1, le=52)] = 12,
) -> SessionSummary:
    try:
        with user_transaction(user_id) as connection:
            return summary(connection, own_player_id(connection), weeks)
    except DBAPIError:
        raise unavailable() from None


@router.get(
    "/player/sessions/{session_id}",
    response_model=TrainingSession,
    dependencies=PRIVATE,
)
def read_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> TrainingSession:
    try:
        with user_transaction(user_id) as connection:
            row = load_session(connection, session_id)
    except DBAPIError:
        raise unavailable() from None
    return session_model(row)


@router.delete("/player/sessions/{session_id}", status_code=204, dependencies=PRIVATE)
def remove_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Response:
    try:
        with user_transaction(user_id) as connection:
            delete_session(connection, session_id)
    except DBAPIError:
        raise unavailable() from None
    return Response(status_code=204)


@router.get(
    "/players/{player_id}/sessions",
    response_model=list[TrainingSession],
    dependencies=PRIVATE,
)
def list_player_sessions(
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[TrainingSession]:
    try:
        with user_transaction(user_id) as connection:
            rows = coach_sessions(connection, player_id)
    except DBAPIError:
        raise unavailable() from None
    if rows is None:
        raise Problem(404, "That player is not available.")
    return [session_model(row) for row in rows]
