"""Opt-in team leaderboard endpoints (ADR 0023, Block 09B W2)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.leaderboard_service import board, join, leave, membership
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    Leaderboard,
    LeaderboardMembership,
    LeaderboardMembershipUpdate,
    LeaderboardMetric,
    LeaderboardPeriod,
)

router = APIRouter(prefix="/v1")
MEMBERSHIP = "/player/leaderboard-membership"


@router.get(MEMBERSHIP, response_model=LeaderboardMembership, dependencies=PRIVATE)
def read_membership(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> LeaderboardMembership:
    try:
        with user_transaction(user_id) as connection:
            return membership(connection)
    except DBAPIError:
        raise unavailable() from None


@router.put(MEMBERSHIP, response_model=LeaderboardMembership, dependencies=PRIVATE)
def join_board(
    request: LeaderboardMembershipUpdate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> LeaderboardMembership:
    try:
        with user_transaction(user_id) as connection:
            return join(connection, request.nickname)
    except DBAPIError:
        raise unavailable() from None


@router.delete(MEMBERSHIP, status_code=204, dependencies=PRIVATE)
def leave_board(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Response:
    try:
        with user_transaction(user_id) as connection:
            leave(connection)
    except DBAPIError:
        raise unavailable() from None
    return Response(status_code=204)


@router.get(
    "/teams/{team_id}/leaderboard", response_model=Leaderboard, dependencies=PRIVATE
)
def team_board(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
    metric: Annotated[LeaderboardMetric, Query()] = "distance",
    period: Annotated[LeaderboardPeriod, Query()] = "week",
) -> Leaderboard:
    try:
        with user_transaction(user_id) as connection:
            return board(connection, team_id, metric, period)
    except DBAPIError:
        raise unavailable() from None
