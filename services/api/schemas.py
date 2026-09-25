import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
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
    current_publication_id: UUID | None
    current_revision_id: UUID | None
    current_clip_id: UUID | None
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


# --- Player-only clip publication -------------------------------------------


class ReviewPublicationItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgment_id: UUID
    version: int = Field(gt=0)


class ReviewPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: UUID
    replaces_publication_id: UUID | None = None
    items: list[ReviewPublicationItemRequest] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def distinct_judgments(self) -> Self:
        if len({item.judgment_id for item in self.items}) != len(self.items):
            raise ValueError("publication items must name distinct judgments")
        return self


ReviewPublicationStatus = Literal[
    "exporting", "published", "failed", "cancelled", "superseded", "withdrawn"
]


class ReviewPublicationItem(BaseModel):
    judgment_id: UUID
    judgment_revision_id: UUID
    ordinal: int
    requested_clip_version: int
    evidence_clip_id: UUID | None
    clip_status: Literal["pending", "ready", "failed", "deleted"]
    version: int
    verdict: Verdict
    comment_text: str
    clip_start_ms: int
    clip_end_ms: int


class ReviewPublication(BaseModel):
    id: UUID
    game_id: UUID
    player_id: UUID
    goal_id: UUID
    requested_by: UUID
    status: ReviewPublicationStatus
    replaces_publication_id: UUID | None
    requested_count: int
    first_terminal_failure_at: datetime | None
    cancelled_at: datetime | None
    private_exports_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    items: list[ReviewPublicationItem]


class EvidenceItem(BaseModel):
    judgment_id: UUID
    published_revision_id: UUID
    verdict: Literal["applied", "opportunity"]
    verdict_copy: Literal["You did this.", "Chance to do this."]
    comment: str
    clip_duration_ms: int
    coach_display_name: str


class EvidenceSet(BaseModel):
    publication_id: UUID
    game_label: str
    published_at: datetime
    items: list[EvidenceItem]


class EvidenceDot(BaseModel):
    judgment_id: UUID
    verdict: Literal["applied", "opportunity"]


class CoachEvidenceSet(BaseModel):
    publication_id: UUID
    game_id: UUID
    game_label: str
    published_at: datetime
    items: list[EvidenceDot]


class ClipUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_published_revision_id: UUID


class ClipUrl(BaseModel):
    url: str
    expires_in: int
    published_revision_id: UUID


# --- Optional player reflections --------------------------------------------


class ReflectionSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["create", "edit"]
    text: str = Field(min_length=1, max_length=1000)
    expected_reflection_id: UUID | None = None
    expected_etag: UUID | None = None
    request_created_at: datetime

    @model_validator(mode="after")
    def valid_intent(self) -> Self:
        if not self.text.strip():
            raise ValueError("reflection text cannot be blank")
        if self.request_created_at.tzinfo is None:
            raise ValueError("request_created_at must include a timezone")
        expected = (self.expected_reflection_id, self.expected_etag)
        if self.intent == "create" and expected != (None, None):
            raise ValueError("create cannot name an existing reflection")
        if self.intent == "edit" and any(value is None for value in expected):
            raise ValueError("edit requires the existing reflection and ETag")
        return self


class ReflectionDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_reflection_id: UUID
    expected_etag: UUID
    request_created_at: datetime

    @model_validator(mode="after")
    def timezone_required(self) -> Self:
        if self.request_created_at.tzinfo is None:
            raise ValueError("request_created_at must include a timezone")
        return self


class PlayerReflection(BaseModel):
    id: UUID
    judgment_id: UUID
    text: str
    judgment_version_at_save: int
    etag: UUID
    created_at: datetime
    updated_at: datetime
    evidence_available: bool
    current_published_version: int | None
    is_for_earlier_version: bool


# --- Retention and verified deletion -----------------------------------------


class RetentionConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_backup_max_days: int = Field(ge=1, le=30)
    season_cutoff_confirmed: bool
    provider_backup_expiry_confirmed: bool
    notice_confirmed: bool
    collateral_deletion_confirmed: bool
    operator_confirmed: bool

    @model_validator(mode="after")
    def every_confirmation_required(self) -> Self:
        if not (
            self.season_cutoff_confirmed
            and self.provider_backup_expiry_confirmed
            and self.notice_confirmed
            and self.collateral_deletion_confirmed
            and self.operator_confirmed
        ):
            raise ValueError("all retention confirmations are required")
        return self


class RetentionStatus(BaseModel):
    team_id: UUID
    confirmed: bool
    season_end_at: datetime
    confirmed_by: UUID | None = None
    operator_user_id: UUID | None = None
    provider_backup_max_days: int | None = None
    confirmed_at: datetime | None = None


class PlayerErasureImpact(BaseModel):
    player_id: UUID
    team_id: UUID
    video_count: int
    other_player_clip_count: int
    remaining_player_count: int
    remaining_goal_count: int
    remaining_linked_account_count: int
    can_request: bool
    challenge: str


class PlayerErasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_video_count: int = Field(ge=0)
    expected_other_player_clip_count: int = Field(ge=0)
    challenge: str = Field(min_length=1, max_length=120)
    collateral_deletion_confirmed: bool
    notice_confirmed: bool
    unrelated_data_reviewed: bool

    @model_validator(mode="after")
    def every_erasure_confirmation_required(self) -> Self:
        if not (
            self.collateral_deletion_confirmed
            and self.notice_confirmed
            and self.unrelated_data_reviewed
        ):
            raise ValueError("all deletion confirmations are required")
        return self


DeletionManifestStatus = Literal[
    "pending", "running", "awaiting_backup", "completed", "unresolved"
]


class DeletionStatus(BaseModel):
    id: UUID
    kind: Literal[
        "video_source",
        "video_all",
        "export_cleanup",
        "season_expiry",
        "player_erasure",
        "reflection_erasure",
    ]
    status: DeletionManifestStatus
    requested_at: datetime
    active_cleanup_verified_at: datetime | None
    backup_expires_at: datetime
    backup_verified_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    video_count: int
    other_player_clip_count: int


# Block 08P (ADR 0021): player practice videos and AI coach feedback.

PracticeContentType = Literal["video/mp4", "video/quicktime", "video/webm"]
PracticeStatus = Literal["uploading", "ready", "deleted"]
Angle = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class PracticeVideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: PracticeContentType
    size_bytes: int = Field(ge=1, le=524288000)
    title: str | None = Field(default=None, max_length=80)


class PracticeUploadSession(BaseModel):
    """One presigned PUT; the browser must send exactly `content_type`."""

    id: UUID
    upload_url: str
    content_type: PracticeContentType
    expires_in_seconds: int


class PracticeVideoComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_ms: int | None = Field(default=None, ge=1, le=600000)


class PracticeVideo(BaseModel):
    id: UUID
    status: PracticeStatus
    content_type: PracticeContentType
    size_bytes: int
    duration_ms: int | None
    title: str | None
    created_at: datetime
    upload_completed_at: datetime | None
    expires_at: datetime | None


class PracticeVideoDetail(PracticeVideo):
    # Short-lived, object-specific; null until the upload is ready.
    playback_url: str | None
    playback_expires_in_seconds: int | None


class AnglePercentiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p10: Angle
    p50: Angle
    p90: Angle


class StanceWidth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p50: float = Field(ge=0, le=10, allow_inf_nan=False)


class PracticeFeatures(BaseModel):
    """Aggregate, non-identifying movement features. No landmarks, ever.

    `extra="forbid"` rejects any extra key, so a landmark array cannot ride
    along; every field is a bounded scalar or a small scalar object.
    """

    model_config = ConfigDict(extra="forbid")

    frames_analyzed: int = Field(ge=1, le=200000)
    fps: float = Field(gt=0, le=240, allow_inf_nan=False)
    duration_ms: int = Field(ge=1, le=600000)
    knee_flexion_deg: AnglePercentiles
    hip_flexion_deg: AnglePercentiles
    trunk_lean_deg: AnglePercentiles
    head_turns: int = Field(ge=0, le=10000)
    head_turns_per_min: float = Field(ge=0, le=600, allow_inf_nan=False)
    stance_width_ratio: StanceWidth
    visibility_mean: float = Field(ge=0, le=1, allow_inf_nan=False)


class Drill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    why: str = Field(min_length=1, max_length=300)
    how: str = Field(min_length=1, max_length=400)


class AiCoachResult(BaseModel):
    """What `services.api.ai_coach.generate_feedback` returns after filtering."""

    body: str = Field(min_length=1, max_length=1200)
    drills: list[Drill] = Field(max_length=3)
    model: str = Field(min_length=1, max_length=200)


class AiCoachFeedback(BaseModel):
    """An AI suggestion, never a `judgment`; labelled as such in the UI."""

    id: UUID
    practice_video_id: UUID
    development_goal_id: UUID | None
    model: str
    body: str
    drills: list[Drill]
    created_at: datetime


# Block 09B W1 (ADR 0023): player-recorded training and match sessions.

SessionKind = Literal["training", "match"]
GpsQuality = Literal["good", "fair", "poor"]
HeatmapCell = Annotated[int, Field(ge=0, le=1000)]
Heatmap = Annotated[list[HeatmapCell], Field(min_length=96, max_length=96)]
# A decimal-degree pair ("51.50735, -0.12776") in free text is a location.
COORDINATE_PATTERN = re.compile(
    r"-?\d{1,3}\.\d{4,}\s*[,;/ ]\s*-?\d{1,3}\.\d{4,}"  # 51.50735, -0.12776
    r"|\d{1,3}\s*°"  # 51°30'N
    r"|\d{1,3}\.\d{4,}\s*[NSEWnsew](?![A-Za-z])"  # 51.50735N
)
SESSION_CLOCK_SKEW = timedelta(minutes=10)


class TrainingSessionCreate(BaseModel):
    """Aggregates only. `extra="forbid"` refuses any lat/long or point array."""

    model_config = ConfigDict(extra="forbid")

    kind: SessionKind
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_s: int = Field(ge=60, le=14400)
    distance_m: int = Field(ge=0, le=30000)
    top_speed_cms: int = Field(ge=0, le=1300)
    sprint_count: int = Field(ge=0, le=500)
    half_split_s: int | None = Field(default=None, gt=0)
    heatmap: Heatmap
    heatmap_second_half: Heatmap | None = None
    gps_quality: GpsQuality
    note: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        elapsed = (self.ended_at - self.started_at).total_seconds()
        if elapsed <= 0:
            raise ValueError("ended_at must be after started_at")
        if self.duration_s > elapsed + 60:
            raise ValueError("duration_s exceeds the elapsed time")
        if self.ended_at > datetime.now(UTC) + SESSION_CLOCK_SKEW:
            raise ValueError("ended_at is in the future")
        if self.half_split_s is not None and self.half_split_s >= self.duration_s:
            raise ValueError("half_split_s must fall inside the session")
        if self.heatmap_second_half is not None and self.half_split_s is None:
            raise ValueError("heatmap_second_half needs half_split_s")
        if self.note is not None and COORDINATE_PATTERN.search(self.note):
            raise ValueError("note must not contain coordinates")
        return self


class TrainingSession(BaseModel):
    id: UUID
    kind: SessionKind
    started_at: datetime
    ended_at: datetime
    duration_s: int
    distance_m: int
    top_speed_cms: int
    sprint_count: int
    half_split_s: int | None
    heatmap: list[int]
    heatmap_second_half: list[int] | None
    gps_quality: GpsQuality
    note: str | None
    created_at: datetime


class SessionWeek(BaseModel):
    """Totals for one UTC ISO week starting Monday; zero-filled."""

    week_start: date
    sessions: int
    distance_m: int
    duration_s: int
    sprint_count: int


class PersonalRecord(BaseModel):
    """The player's own best, as a plain fact; never compared with anyone."""

    session_id: UUID
    started_at: datetime
    value: int


class PersonalRecords(BaseModel):
    distance_m: PersonalRecord | None
    top_speed_cms: PersonalRecord | None
    sprint_count: PersonalRecord | None
    duration_s: PersonalRecord | None


class SessionSummary(BaseModel):
    weeks: list[SessionWeek]
    records: PersonalRecords


# Block 09B W3: coach-authored weekly training plans. Slugs name static drills
# in `apps/web/content/drills.ts`; only their shape is checked here.
DRILL_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class TrainingPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_slug: str = Field(min_length=1, max_length=60, pattern=DRILL_SLUG_PATTERN)
    note: str = Field(default="", max_length=200)


class TrainingPlanCreate(BaseModel):
    """`player_id` null means the whole team. `week_of` snaps to its Monday."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    week_of: date
    player_id: UUID | None = None
    items: list[TrainingPlanItem] = Field(min_length=1, max_length=8)


class TrainingPlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=80)
    week_of: date | None = None
    items: list[TrainingPlanItem] | None = Field(
        default=None, min_length=1, max_length=8
    )

    @model_validator(mode="after")
    def at_least_one_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        return self


class TrainingPlan(BaseModel):
    id: UUID
    team_id: UUID
    player_id: UUID | None
    title: str
    week_of: date
    items: list[TrainingPlanItem]
    created_at: datetime
    updated_at: datetime


# Block 09B W2 (ADR 0023): opt-in team leaderboard of tracking totals only.
LeaderboardMetric = Literal["distance", "sprints", "top_speed", "sessions"]
LeaderboardPeriod = Literal["week", "season"]
NICKNAME_PATTERN = re.compile(r"[A-Za-z0-9 ]{2,20}")
# ponytail: a short screen, not a moderation system. Substrings have no
# innocent spelling inside ordinary names; the whole words are short ones that
# would otherwise hit names ("ass" in "Cassie", "cock" in "Hancock").
NICKNAME_BLOCKED_SUBSTRINGS = (
    "fuck", "shit", "cunt", "nigg", "fagg", "bitch", "whore", "slut", "porn",
    "wank", "twat", "retard", "pedo", "hitler",
)  # fmt: skip
NICKNAME_BLOCKED_WORDS = frozenset(
    {
        "ass", "arse", "fag", "dick", "cock", "sex", "rape", "nazi", "kkk",
        "tits", "piss", "penis", "anal", "homo", "spaz",
        # Contact details spelled out with spaces instead of "@" or ".".
        "www", "http", "https", "com", "net", "org", "gmail", "hotmail",
        "yahoo", "outlook", "icloud", "insta", "snap", "tiktok", "whatsapp",
        "instagram", "ig", "discord", "telegram", "kik", "snapchat", "twitter",
    }
)  # fmt: skip
LEET = str.maketrans("013457", "oieast")


def screen_nickname(value: str) -> str:
    """Collapse spaces, then refuse slurs, profanity and contact details."""
    nickname = " ".join(value.split())
    if not NICKNAME_PATTERN.fullmatch(nickname):
        raise ValueError("Use 2 to 20 letters, numbers or spaces")
    words = nickname.lower().split()
    squashed = "".join(words)
    blocked = (
        # A phone number: six or more digits anywhere, spaced or not.
        sum(c.isdigit() for c in squashed) >= 6
        or any(
            word in NICKNAME_BLOCKED_WORDS
            or word.translate(LEET) in NICKNAME_BLOCKED_WORDS
            for word in words
        )
        or any(
            bad in form
            for form in (squashed, squashed.translate(LEET))
            for bad in NICKNAME_BLOCKED_SUBSTRINGS
        )
    )
    if blocked:
        raise ValueError("Choose a different nickname")
    return nickname


class LeaderboardMembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(max_length=60)

    @model_validator(mode="after")
    def screened(self) -> Self:
        self.nickname = screen_nickname(self.nickname)
        return self


class LeaderboardMembership(BaseModel):
    """The caller's own opt-in state; `nickname` is null when not joined."""

    team_id: UUID
    nickname: str | None
    joined_at: datetime | None


class LeaderboardEntry(BaseModel):
    """Nickname and a whole-number total only; never a player id or name."""

    nickname: str
    value: int
    is_me: bool


class Leaderboard(BaseModel):
    metric: LeaderboardMetric
    period: LeaderboardPeriod
    since: datetime
    entries: list[LeaderboardEntry]
