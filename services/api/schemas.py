from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TeamRole = Literal["coach", "player"]


class AuthIdentity(BaseModel):
    user_id: UUID


class LinkedPlayer(BaseModel):
    id: UUID
    team_id: UUID


class Me(BaseModel):
    """Database-derived identity. An unlinked account has empty roles/teams."""

    user_id: UUID
    email: str
    display_name: str
    roles: list[TeamRole]
    team_ids: list[UUID]
    player: LinkedPlayer | None = None


class TeamBootstrap(BaseModel):
    coach_user_id: UUID
    name: str = Field(min_length=1, max_length=100)
    season_label: str = Field(min_length=1, max_length=60)
    season_end_at: datetime
    age_group: str | None = Field(default=None, min_length=1, max_length=40)


class TeamCreated(BaseModel):
    team_id: UUID
