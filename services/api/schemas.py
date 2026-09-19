from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

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
    is checked for a contradiction with the extension and is otherwise a hint;
    Task 11 probes the stored bytes before anything trusts them.
    """

    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    # Optional and allowed to be empty: several browsers recognise no type for
    # `.mov`, and `docs/04-api.md` treats the declared type as a hint anyway.
    # The stored type is resolved from the validated extension.
    content_type: str | None = Field(default=None, max_length=100)
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


class PlaybackUrl(BaseModel):
    """One short-lived, object-specific coach playback URL.

    `docs/10-security-privacy.md` caps a coach URL at fifteen minutes. The
    object is the coach-only `playback/{video_id}/coach-720p.mp4`; no player
    endpoint ever returns it, and no request value chooses it.
    """

    video_id: UUID
    url: str
    expires_in: int
    duration_ms: int
    width: int
    height: int


class SpriteSheet(BaseModel):
    sheet: int
    url: str


class Timeline(BaseModel):
    """Scrubber thumbnails: bounded sheets and a deterministic tile geometry."""

    video_id: UUID
    expires_in: int
    tile_width: int
    tile_height: int
    columns: int
    rows: int
    interval_ms: int
    tile_count: int
    sheets: list[SpriteSheet]


# --- Manual observations ------------------------------------------------------


class ObservationCreate(BaseModel):
    client_id: UUID | None = None
    player_id: UUID
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.t_end_ms <= self.t_start_ms:
            raise ValueError("t_end_ms must be greater than t_start_ms")
        return self


class Observation(BaseModel):
    id: UUID
    video_id: UUID
    player_id: UUID
    t_start_ms: int
    t_end_ms: int
    source: Literal["coach_manual"]
    event_type: str | None
    created_by: UUID
    created_at: datetime


# --- Coach judgments and revisions --------------------------------------------
#
# `author_user_id` never appears on a request model: it is always the
# authenticated session, never a client-supplied value. `version` on a patch
# request is the `If-Match` header, not a body field.
#
# Both request models forbid extra fields, and independent review is why.
# Pydantic ignores unknown fields by default, so a create carrying
# `author_user_id` was accepted with 201 and quietly dropped. The security
# property held -- the author still came from the session -- but Task 15 asks
# for a spoofed author to be *rejected*, and a client that believes it set a
# server-managed field deserves to be told it did not. Refusing the request
# also catches a typo in a real field, which silent tolerance turns into a
# save that appears to have worked.

# `clip_*_ms` are bounded to a PostgreSQL `integer`, which is what
# `private.write_judgment_revision` declares them as. Without the ceiling a
# value like 2147483648 passed Pydantic and failed while binding the function,
# and the route reported that as 503 -- an outage, for what is a caller's
# out-of-range field.
MAX_INT32 = 2147483647

Verdict = Literal["applied", "opportunity", "not_relevant"]


class JudgmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: UUID
    verdict: Verdict
    comment_text: str | None = Field(default=None, min_length=1, max_length=400)
    clip_start_ms: int = Field(ge=0, le=MAX_INT32)
    clip_end_ms: int = Field(gt=0, le=MAX_INT32)

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.clip_end_ms <= self.clip_start_ms:
            raise ValueError("clip_end_ms must be greater than clip_start_ms")
        return self


class JudgmentPatch(BaseModel):
    """A full content snapshot: every edit replaces the whole draft."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    comment_text: str | None = Field(default=None, min_length=1, max_length=400)
    clip_start_ms: int = Field(ge=0, le=MAX_INT32)
    clip_end_ms: int = Field(gt=0, le=MAX_INT32)

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.clip_end_ms <= self.clip_start_ms:
            raise ValueError("clip_end_ms must be greater than clip_start_ms")
        return self


PublicationStatus = Literal["draft", "published", "withdrawn"]


class Judgment(BaseModel):
    id: UUID
    observation_id: UUID
    goal_id: UUID
    author_user_id: UUID
    version: int
    publication_status: PublicationStatus
    current_revision_id: UUID | None
    published_at: datetime | None
    updated_at: datetime
    created_at: datetime
    verdict: Verdict
    comment_text: str | None
    clip_start_ms: int
    clip_end_ms: int


class JudgmentRevision(BaseModel):
    id: UUID
    judgment_id: UUID
    version: int
    author_user_id: UUID
    verdict: Verdict
    comment_text: str | None
    clip_start_ms: int
    clip_end_ms: int
    created_at: datetime
