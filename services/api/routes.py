from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from services.api.auth import authenticated_identity
from services.api.schemas import AuthIdentity

router = APIRouter(prefix="/v1/auth")


@router.get("/identity", response_model=AuthIdentity)
def identity(
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> AuthIdentity:
    response.headers["Cache-Control"] = "private, no-store"
    return AuthIdentity(user_id=UUID(user_id))
