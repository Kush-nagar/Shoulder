"""Public-demo self-join (ADR 0021). Inert unless `DEMO_MODE=on`.

A signed-in account with no team membership and no player row becomes a
player on the synthetic demo team named by `DEMO_TEAM_ID`. The database
function refuses any team not marked `age_group = 'DEMO'`, so a misconfigured
id can never add strangers to a real team.
"""

import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.problems import Problem
from services.api.routes import PRIVATE, unavailable

router = APIRouter(prefix="/v1/demo")


class DemoJoin(BaseModel):
    player_id: UUID


def demo_team_id() -> UUID | None:
    """The configured demo team, or None when the demo is off."""
    if os.environ.get("DEMO_MODE", "").strip().lower() != "on":
        return None
    try:
        return UUID(os.environ.get("DEMO_TEAM_ID", "").strip())
    except ValueError:
        return None


@router.post("/join", response_model=DemoJoin, dependencies=PRIVATE)
def join_demo(user_id: Annotated[str, Depends(authenticated_identity)]) -> DemoJoin:
    team_id = demo_team_id()
    if team_id is None:
        raise Problem(404, "Not found.")
    try:
        with user_transaction(user_id) as connection:
            player_id = connection.execute(
                text("SELECT private.demo_join(:team_id)"),
                {"team_id": str(team_id)},
            ).scalar_one()
    except DBAPIError:
        raise unavailable() from None
    if player_id is None:
        # Already a coach, or no synchronized profile: the demo never applies.
        raise Problem(409, "This account already has team access.")
    return DemoJoin(player_id=player_id)
