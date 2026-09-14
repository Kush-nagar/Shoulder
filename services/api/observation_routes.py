"""HTTP boundary for Task 14 manual observations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.observation_service import (
    create_observation as create_observation_service,
)
from services.api.observation_service import (
    list_observations as list_observations_service,
)
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import Observation, ObservationCreate

router = APIRouter(prefix="/v1")


@router.get(
    "/videos/{video_id}/observations",
    response_model=list[Observation],
    dependencies=PRIVATE,
)
def list_observations(
    video_id: UUID,
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[Observation]:
    try:
        with user_transaction(user_id) as connection:
            return list_observations_service(connection, video_id, player_id)
    except DBAPIError:
        raise unavailable() from None


@router.post(
    "/videos/{video_id}/observations",
    response_model=Observation,
    status_code=201,
    dependencies=PRIVATE,
)
def create_observation(
    video_id: UUID,
    request: ObservationCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Observation:
    try:
        with user_transaction(user_id) as connection:
            return create_observation_service(connection, video_id, request)
    except DBAPIError:
        raise unavailable() from None
