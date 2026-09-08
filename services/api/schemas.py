from uuid import UUID

from pydantic import BaseModel


class AuthIdentity(BaseModel):
    user_id: UUID
