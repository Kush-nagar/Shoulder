"""Player reflection CRUD and coach read-only access."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.problems import Problem
from services.api.reflection_service import (
    coach_reflections,
    delete_reflection,
    own_reflections,
    reflection_error,
    reflection_model,
    save_reflection,
)
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    PlayerReflection,
    ReflectionDeleteRequest,
    ReflectionSaveRequest,
)

router = APIRouter(prefix="/v1")


def _idempotency_key(value: str) -> str:
    if not 1 <= len(value) <= 200:
        raise Problem(
            422,
            "An Idempotency-Key header is required.",
            "idempotency-key-required",
        )
    return value


def _database_problem(error: DBAPIError) -> Problem:
    return reflection_error(error) or unavailable()


@router.get(
    "/me/reflections",
    response_model=list[PlayerReflection],
    dependencies=PRIVATE,
)
def list_own_reflections(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[PlayerReflection]:
    try:
        with user_transaction(user_id) as connection:
            rows = own_reflections(connection)
    except DBAPIError:
        raise unavailable() from None
    return [PlayerReflection(**reflection_model(row)) for row in rows]


@router.get(
    "/players/{player_id}/reflections",
    response_model=list[PlayerReflection],
    dependencies=PRIVATE,
)
def list_player_reflections(
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[PlayerReflection]:
    try:
        with user_transaction(user_id) as connection:
            rows = coach_reflections(connection, player_id)
    except DBAPIError:
        raise unavailable() from None
    if rows is None:
        raise Problem(404, "That player is not available.")
    return [PlayerReflection(**reflection_model(row)) for row in rows]


@router.put(
    "/me/judgments/{judgment_id}/reflection",
    response_model=PlayerReflection,
    dependencies=PRIVATE,
)
def put_reflection(
    judgment_id: UUID,
    request: ReflectionSaveRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PlayerReflection:
    key = _idempotency_key(idempotency_key)
    try:
        with user_transaction(user_id) as connection:
            row = save_reflection(
                connection,
                judgment_id=judgment_id,
                intent=request.intent,
                reflection_text=request.text,
                expected_reflection_id=request.expected_reflection_id,
                expected_etag=request.expected_etag,
                request_created_at=request.request_created_at,
                idempotency_key=key,
            )
    except DBAPIError as error:
        raise _database_problem(error) from None
    return PlayerReflection(**reflection_model(row))


@router.delete(
    "/me/judgments/{judgment_id}/reflection",
    status_code=204,
    dependencies=PRIVATE,
)
def remove_reflection(
    judgment_id: UUID,
    request: ReflectionDeleteRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> Response:
    key = _idempotency_key(idempotency_key)
    try:
        with user_transaction(user_id) as connection:
            delete_reflection(
                connection,
                judgment_id=judgment_id,
                expected_reflection_id=request.expected_reflection_id,
                expected_etag=request.expected_etag,
                request_created_at=request.request_created_at,
                idempotency_key=key,
            )
    except DBAPIError as error:
        raise _database_problem(error) from None
    return Response(status_code=204)
