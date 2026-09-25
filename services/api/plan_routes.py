"""Training plan endpoints (Block 09B W3, frozen 0018 contract)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.plan_service import (
    delete_plan,
    insert_plan,
    own_plans,
    team_plans,
    update_plan,
)
from services.api.routes import PRIVATE, load_team, require_coach, unavailable
from services.api.schemas import TrainingPlan, TrainingPlanCreate, TrainingPlanPatch

router = APIRouter(prefix="/v1")


@router.get(
    "/teams/{team_id}/plans", response_model=list[TrainingPlan], dependencies=PRIVATE
)
def list_team_plans(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[TrainingPlan]:
    with user_transaction(user_id) as connection:
        require_coach(load_team(connection, team_id))
        return team_plans(connection, team_id)


@router.post(
    "/teams/{team_id}/plans",
    response_model=TrainingPlan,
    status_code=201,
    dependencies=PRIVATE,
)
def create_team_plan(
    team_id: UUID,
    request: TrainingPlanCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> TrainingPlan:
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_team(connection, team_id))
            return insert_plan(connection, team_id, request)
    except DBAPIError:
        raise unavailable() from None


@router.patch("/plans/{plan_id}", response_model=TrainingPlan, dependencies=PRIVATE)
def patch_plan(
    plan_id: UUID,
    request: TrainingPlanPatch,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> TrainingPlan:
    try:
        with user_transaction(user_id) as connection:
            return update_plan(connection, plan_id, request)
    except DBAPIError:
        raise unavailable() from None


@router.delete("/plans/{plan_id}", status_code=204, dependencies=PRIVATE)
def remove_plan(
    plan_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Response:
    try:
        with user_transaction(user_id) as connection:
            delete_plan(connection, plan_id)
    except DBAPIError:
        raise unavailable() from None
    return Response(status_code=204)


@router.get("/player/plans", response_model=list[TrainingPlan], dependencies=PRIVATE)
def list_own_plans(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[TrainingPlan]:
    with user_transaction(user_id) as connection:
        return own_plans(connection)
