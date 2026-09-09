from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

TeamRole = Literal["coach", "player"]
GoalStatus = Literal["active", "achieved", "paused", "retired"]

# `pydantic.EmailStr` needs the `email-validator` package, which this project
# does not carry; the address is re-validated in the database by
# `private.link_player_account`, which raises 22023 for an unusable one.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


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


class TeamSummary(BaseModel):
    team_id: UUID
    name: str
    age_group: str | None
    season_label: str
    role: TeamRole


class GoalSummary(BaseModel):
    id: UUID
    title: str
    status: GoalStatus


class RosterPlayer(BaseModel):
    """One roster row.

    `account_name` is the linked account's display name and comes only from
    `private.team_roster`, the Task 5 helper built for this consumer. It is the
    sole path to another account's name: `user_account` is self-only under RLS.
    It is never an address.

    That helper hides archived and deletion-pending rows, so `account_name` is
    null for them even when an account is attached. `account_linked` reads
    `player.user_id` directly and stays truthful for every row, so a screen
    never calls a linked player unlinked or offers to link them again.
    """

    id: UUID
    team_id: UUID
    display_name: str
    jersey_number: int | None
    position: str | None
    active: bool
    account_linked: bool = False
    account_name: str | None = None
    active_goal: GoalSummary | None = None


# Bulk rows are trimmed before validation, so single writes trim too; otherwise
# the same pasted name is stored differently depending on which route saved it.
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Position = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
]


class PlayerCreate(BaseModel):
    display_name: Name
    jersey_number: int | None = Field(default=None, ge=0, le=99)
    position: Position | None = None


class PlayerPatch(BaseModel):
    """Only the fields present in the request are written."""

    display_name: Name | None = None
    jersey_number: int | None = Field(default=None, ge=0, le=99)
    position: Position | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be cleared")
        return self


class BulkRow(BaseModel):
    """Deliberately permissive: a bad row earns a per-row error, not a 422 wall."""

    display_name: str
    jersey_number: int | None = None
    position: str | None = None


class BulkRequest(BaseModel):
    commit: bool = False
    rows: list[BulkRow] = Field(min_length=1, max_length=40)


class BulkRowResult(BaseModel):
    index: int
    display_name: str
    jersey_number: int | None
    position: str | None
    errors: list[str]


class BulkResult(BaseModel):
    committed: bool
    rows: list[BulkRowResult]
    created: list[UUID]


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)


class InviteResult(BaseModel):
    """ADR 0017: invitation links an existing account; it never creates one."""

    player_id: UUID
    user_id: UUID


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    ontology_key: str | None = Field(default=None, min_length=1, max_length=80)


class GoalPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    status: GoalStatus | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be cleared")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be cleared")
        return self


class Goal(BaseModel):
    id: UUID
    player_id: UUID
    title: str
    description: str | None
    ontology_key: str | None
    status: GoalStatus
    created_by: UUID
    created_at: datetime
    closed_at: datetime | None


# --- Games, video ingest, and durable work -------------------------------------
#
# No response model here carries `original_key`, `playback_key`,
# `multipart_upload_id`, or a signing credential: `docs/04-api.md` says a video
# response contains "Metadata and processing state; no storage keys".

GameKind = Literal["match", "scrimmage"]
VideoStatus = Literal[
    "uploading",
    "uploaded",
    "processing",
    "ready",
    "failed",
    "deletion_pending",
    "deleted",
]
# The stored extension allowlist lives in `services/api/storage.py`; this is the
# request-side view of it.
UploadExtension = Literal["mp4", "m4v", "mov"]


class GameCreate(BaseModel):
    team_id: UUID
    played_at: datetime
    kind: GameKind = "match"
    opponent: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class VideoSummary(BaseModel):
    """Processing state a coach screen can render. No storage key, by contract."""

    id: UUID
    game_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    status: VideoStatus
    part_size_bytes: int
    part_count: int
    uploaded_parts: int
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime
    upload_completed_at: datetime | None = None
    ready_at: datetime | None = None


class Game(BaseModel):
    id: UUID
    team_id: UUID
    opponent: str | None
    played_at: datetime
    kind: GameKind
    notes: str | None
    created_at: datetime
    videos: list[VideoSummary] = []


class GamePage(BaseModel):
    """Cursor pagination per `docs/04-api.md`; the cursor is opaque to a client."""

    games: list[Game]
    next_cursor: str | None = None


class UploadCreate(BaseModel):
    """What the browser knows before a byte moves.

    `size_bytes` is the exact file length, not an estimate: the part plan and
    the completion size check are both derived from it. The declared MIME type
    is validated against the extension but never trusted on its own.
    """

    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1, max_length=100)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class UploadSession(BaseModel):
    video_id: UUID
    part_size_bytes: int
    part_count: int
    status: VideoStatus


class SignPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=32)


class SignedPart(BaseModel):
    part_number: int
    url: str
    size_bytes: int
    """Exact byte length the client must PUT for this part."""


class SignedParts(BaseModel):
    expires_in: int
    parts: list[SignedPart]


class UploadedPart(BaseModel):
    part_number: int
    etag: str
    size_bytes: int


class UploadState(BaseModel):
    """Server-confirmed resume state. `docs/00-decisions.md` D5: authoritative."""

    video_id: UUID
    status: VideoStatus
    part_size_bytes: int
    part_count: int
    parts: list[UploadedPart]
    missing_part_numbers: list[int]


class UploadCompleted(BaseModel):
    video_id: UUID
    status: VideoStatus
    upload_completed_at: datetime
    source_expires_at: datetime
