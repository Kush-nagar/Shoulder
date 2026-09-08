import hmac
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import NO_STORE, operator_transaction, user_transaction
from services.api.schemas import (
    AuthIdentity,
    LinkedPlayer,
    Me,
    TeamBootstrap,
    TeamCreated,
    TeamRole,
)

router = APIRouter(prefix="/v1")

# Postgres SQLSTATEs raised deliberately by private.bootstrap_initial_team.
ALREADY_BOOTSTRAPPED = "23505"
UNKNOWN_ACCOUNT = "23503"


def authorized_operator(
    x_operator_token: Annotated[str | None, Header()] = None,
) -> None:
    """Bootstrap authorization. A signed-in session never reaches this path."""
    expected = os.environ.get("OPERATOR_BOOTSTRAP_TOKEN")
    if not expected or len(expected) < 32:
        raise HTTPException(503, "Service unavailable", headers=NO_STORE)
    if not x_operator_token or not hmac.compare_digest(x_operator_token, expected):
        raise HTTPException(401, "Authentication required", headers=NO_STORE)


@router.get("/auth/identity", response_model=AuthIdentity)
def identity(
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> AuthIdentity:
    response.headers["Cache-Control"] = "private, no-store"
    return AuthIdentity(user_id=UUID(user_id))


@router.get("/me", response_model=Me)
def me(
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Me:
    response.headers["Cache-Control"] = "private, no-store"
    with user_transaction(user_id) as connection:
        account = connection.execute(
            text(
                "SELECT a.email, a.display_name FROM app.user_account a"
                " WHERE a.id = :user_id"
            ),
            {"user_id": user_id},
        ).one_or_none()
        if account is None:
            # RLS returns no row for an identity without a synchronized profile.
            raise HTTPException(404, "Not found", headers=NO_STORE)
        memberships = connection.execute(
            text(
                "SELECT m.team_id, m.role FROM app.team_membership m"
                " WHERE m.user_id = :user_id ORDER BY m.created_at, m.team_id"
            ),
            {"user_id": user_id},
        ).all()
        linked = connection.execute(
            text(
                "SELECT p.id, p.team_id FROM app.player p"
                " WHERE p.user_id = :user_id ORDER BY p.created_at LIMIT 1"
            ),
            {"user_id": user_id},
        ).one_or_none()
    roles: list[TeamRole] = []
    for membership in memberships:
        if membership.role not in roles:
            roles.append(membership.role)
    return Me(
        user_id=UUID(user_id),
        email=account.email,
        display_name=account.display_name,
        roles=roles,
        team_ids=[membership.team_id for membership in memberships],
        player=LinkedPlayer(id=linked.id, team_id=linked.team_id) if linked else None,
    )


@router.post(
    "/teams",
    response_model=TeamCreated,
    status_code=201,
    dependencies=[Depends(authorized_operator)],
)
def bootstrap_team(request: TeamBootstrap, response: Response) -> TeamCreated:
    """Create the single initial team and its coach membership atomically."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with operator_transaction() as connection:
            team_id = connection.execute(
                text(
                    "SELECT private.bootstrap_initial_team("
                    ":coach_user_id, :name, :season_label,"
                    " :season_end_at, :age_group)"
                ),
                {
                    "coach_user_id": str(request.coach_user_id),
                    "name": request.name,
                    "season_label": request.season_label,
                    "season_end_at": request.season_end_at,
                    "age_group": request.age_group,
                },
            ).scalar_one()
    except DBAPIError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == ALREADY_BOOTSTRAPPED:
            raise HTTPException(409, "Conflict", headers=NO_STORE) from None
        if code == UNKNOWN_ACCOUNT:
            raise HTTPException(422, "Unprocessable entity", headers=NO_STORE) from None
        raise HTTPException(503, "Service unavailable", headers=NO_STORE) from None
    return TeamCreated(team_id=team_id)
