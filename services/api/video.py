"""Games, multipart video ingest, and enqueueing durable work.

`docs/02-architecture.md` constraint 2: video bytes do not pass through this
service. Every route here moves metadata and short-lived, object-specific
signed URLs only.

Authorization stays the database's answer. Each route reads its row through
row-level security first, so an invisible row is a 404 and a visible row the
caller may not write is a 403, exactly as the roster routes behave.

Two values are never taken from a request: the object key, which is derived
from the generated `video.id` and a fixed extension allowlist, and the part
list at completion, which is read back from storage rather than claimed by the
client.
"""

import base64
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from services.api import storage
from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.problems import Problem
from services.api.routes import (
    PRIVATE,
    load_team,
    require_coach,
    unavailable,
)
from services.api.schemas import (
    Game,
    GameCreate,
    GamePage,
    SignedPart,
    SignedParts,
    SignPartsRequest,
    UploadCompleted,
    UploadCreate,
    UploadedPart,
    UploadSession,
    UploadState,
    VideoSummary,
)

router = APIRouter(prefix="/v1")

GAME_COLUMNS = """
    g.id, g.team_id, g.opponent, g.played_at, g.kind, g.notes, g.created_at
"""
GAME_RETURNING = "id, team_id, opponent, played_at, kind, notes, created_at"
VIDEO_COLUMNS = """
    v.id, v.game_id, v.original_filename, v.content_type, v.size_bytes,
    v.status, v.duration_ms, v.width, v.height, v.created_at,
    v.upload_completed_at, v.source_expires_at, v.ready_at,
    (SELECT count(*) FROM app.video_upload_part p WHERE p.video_id = v.id)
        AS uploaded_parts
"""
# Operational columns the service needs and no response model contains.
VIDEO_INTERNAL = f"""
    SELECT {VIDEO_COLUMNS}, v.original_key, v.multipart_upload_id,
        private.is_video_coach(v.id) AS is_coach
    FROM app.video v WHERE v.id = :video_id
"""
GAMES_PAGE_LIMIT = 50
# `docs/10-security-privacy.md`: the source clock starts at upload completion,
# derivatives expire with the season, and a retry never extends either.
SOURCE_RETENTION_DAYS = 90
DERIVATIVE_RETENTION_DAYS = 365
# `docs/02-architecture.md`: completion enqueues transcode and thumbnail work.
# The keys are deterministic, so a repeated completion collapses to one job.
JOB_KINDS = ("transcode", "thumbnail")


def job_key(kind: str, video_id: UUID) -> str:
    return f"{kind}:{video_id}:v1"


def video_summary(row: Any) -> VideoSummary:
    return VideoSummary(
        id=row.id,
        game_id=row.game_id,
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        status=row.status,
        part_size_bytes=storage.PART_SIZE_BYTES,
        part_count=storage.part_count(row.size_bytes),
        uploaded_parts=row.uploaded_parts,
        duration_ms=row.duration_ms,
        width=row.width,
        height=row.height,
        created_at=row.created_at,
        upload_completed_at=row.upload_completed_at,
        ready_at=row.ready_at,
    )


def game_model(row: Any, videos: list[VideoSummary]) -> Game:
    return Game(
        id=row.id,
        team_id=row.team_id,
        opponent=row.opponent,
        played_at=row.played_at,
        kind=row.kind,
        notes=row.notes,
        created_at=row.created_at,
        videos=videos,
    )


def load_game(connection: Connection, game_id: UUID) -> Any:
    row = connection.execute(
        text(
            f"SELECT {GAME_COLUMNS}, private.is_game_coach(g.id) AS is_coach"
            " FROM app.game g WHERE g.id = :game_id"
        ),
        {"game_id": str(game_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That match is not available.")
    return row


def load_video(connection: Connection, video_id: UUID) -> Any:
    row = connection.execute(
        text(VIDEO_INTERNAL), {"video_id": str(video_id)}
    ).one_or_none()
    if row is None:
        raise Problem(404, "That match video is not available.")
    return row


def videos_for(connection: Connection, game_ids: list[UUID]) -> dict[UUID, list[Any]]:
    grouped: dict[UUID, list[Any]] = {game_id: [] for game_id in game_ids}
    if not game_ids:
        return grouped
    rows = connection.execute(
        text(
            f"SELECT {VIDEO_COLUMNS} FROM app.video v"
            " WHERE v.game_id = ANY(:game_ids) ORDER BY v.created_at, v.id"
        ),
        {"game_ids": [str(game_id) for game_id in game_ids]},
    ).all()
    for row in rows:
        grouped[row.game_id].append(row)
    return grouped


def encode_cursor(played_at: datetime, game_id: UUID) -> str:
    """Opaque to a client: a keyset position, never a row offset."""
    raw = f"{played_at.isoformat()}|{game_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding).decode()
        played_at, separator, game_id = decoded.partition("|")
        if not separator:
            raise ValueError("cursor is missing its separator")
        return datetime.fromisoformat(played_at), UUID(game_id)
    except (ValueError, UnicodeDecodeError):
        raise Problem(422, "That page cursor is not valid.") from None


def media_extension(filename: str) -> str:
    """One extension from the allowlist, for a key the caller cannot influence."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in storage.ALLOWED_MEDIA:
        raise Problem(
            422,
            "Shoulder accepts MP4, M4V, and MOV match files.",
            "unsupported-media-type",
        )
    return extension


def display_filename(filename: str) -> str:
    """Display only, with path data stripped per `docs/03-schema.md`."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:255] or "match-video"


def storage_unavailable() -> Problem:
    """One shape for every storage failure; a provider message never escapes."""
    return Problem(
        503, "Match storage could not be reached. Try again.", "storage-unavailable"
    )


@router.post("/games", response_model=Game, status_code=201, dependencies=PRIVATE)
def create_game(
    request: GameCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Game:
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_team(connection, request.team_id))
            row = connection.execute(
                text(f"""
                    INSERT INTO app.game
                        (team_id, opponent, played_at, kind, notes, created_by)
                    VALUES (
                        :team_id, :opponent, :played_at, :kind, :notes,
                        private.current_user_id()
                    )
                    RETURNING {GAME_RETURNING}
                """),
                {
                    "team_id": str(request.team_id),
                    "opponent": request.opponent,
                    "played_at": request.played_at,
                    "kind": request.kind,
                    "notes": request.notes,
                },
            ).one()
    except DBAPIError:
        raise unavailable() from None
    return game_model(row, [])


@router.get("/teams/{team_id}/games", response_model=GamePage, dependencies=PRIVATE)
def list_games(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
    cursor: str | None = None,
) -> GamePage:
    position = decode_cursor(cursor) if cursor else None
    with user_transaction(user_id) as connection:
        require_coach(load_team(connection, team_id))
        rows = connection.execute(
            text(f"""
                SELECT {GAME_COLUMNS} FROM app.game g
                WHERE g.team_id = :team_id
                  AND (
                    cast(:played_at AS timestamptz) IS NULL
                    OR (g.played_at, g.id)
                       < (cast(:played_at AS timestamptz), cast(:game_id AS uuid))
                  )
                ORDER BY g.played_at DESC, g.id DESC
                LIMIT :limit
            """),
            {
                "team_id": str(team_id),
                "played_at": position[0] if position else None,
                "game_id": str(position[1]) if position else None,
                "limit": GAMES_PAGE_LIMIT + 1,
            },
        ).all()
        page = rows[:GAMES_PAGE_LIMIT]
        videos = videos_for(connection, [row.id for row in page])
    return GamePage(
        games=[
            game_model(row, [video_summary(video) for video in videos[row.id]])
            for row in page
        ],
        next_cursor=(
            encode_cursor(page[-1].played_at, page[-1].id)
            if len(rows) > GAMES_PAGE_LIMIT
            else None
        ),
    )


@router.get("/games/{game_id}", response_model=Game, dependencies=PRIVATE)
def read_game(
    game_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Game:
    """Game and video state. Per-player review state arrives with Block 04."""
    with user_transaction(user_id) as connection:
        row = require_coach(load_game(connection, game_id))
        videos = videos_for(connection, [game_id])
    return game_model(row, [video_summary(video) for video in videos[game_id]])


@router.post(
    "/games/{game_id}/videos/uploads",
    response_model=UploadSession,
    status_code=201,
    dependencies=PRIVATE,
)
def create_upload(
    game_id: UUID,
    request: UploadCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> UploadSession:
    """Allocate one multipart upload for an authorized coach.

    Size, extension, declared type, and part count are all bounded before a
    single URL is signed, per `docs/10-security-privacy.md`. The declared MIME
    type is checked against the extension but is a hint either way: Task 11
    probes the stored bytes before anything trusts them.
    """
    extension = media_extension(request.filename)
    if request.size_bytes > storage.MAX_UPLOAD_BYTES:
        raise Problem(
            422,
            "That match file is larger than Shoulder accepts.",
            "upload-too-large",
        )
    try:
        content_type = storage.declared_media(extension, request.content_type)
    except storage.StorageError:
        raise Problem(
            422,
            "That file type does not match its extension.",
            "unsupported-media-type",
        ) from None
    parts = storage.part_count(request.size_bytes)
    if parts > storage.MAX_PARTS:
        raise Problem(422, "That match file needs too many parts.", "upload-too-large")

    upload_id: str | None = None
    key: str | None = None
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_game(connection, game_id))
            # The id is generated first so the key depends only on it; the row
            # is written in the same statement that reserves the id.
            video_id = connection.execute(text("SELECT gen_random_uuid()")).scalar_one()
            key = storage.original_key(UUID(str(video_id)), extension)
            upload_id = storage.create_multipart(key, content_type)
            connection.execute(
                text("""
                    INSERT INTO app.video (
                        id, game_id, original_key, original_filename, content_type,
                        size_bytes, sha256, multipart_upload_id, uploaded_by, status
                    ) VALUES (
                        :id, :game_id, :original_key, :original_filename,
                        :content_type, :size_bytes, :sha256, :multipart_upload_id,
                        private.current_user_id(), 'uploading'
                    )
                """),
                {
                    "id": video_id,
                    "game_id": str(game_id),
                    "original_key": key,
                    "original_filename": display_filename(request.filename),
                    "content_type": content_type,
                    "size_bytes": request.size_bytes,
                    "sha256": request.sha256,
                    "multipart_upload_id": upload_id,
                },
            )
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        # The row was refused, so nothing will ever complete this upload.
        # Leaving it would rely on the abandoned-upload sweeper instead.
        if key and upload_id:
            try:
                storage.abort_multipart(key, upload_id)
            except storage.StorageError:
                pass
        raise unavailable() from None
    return UploadSession(
        video_id=UUID(str(video_id)),
        part_size_bytes=storage.PART_SIZE_BYTES,
        part_count=parts,
        status="uploading",
    )


@router.post(
    "/videos/{video_id}/upload-parts/sign",
    response_model=SignedParts,
    dependencies=PRIVATE,
)
def sign_upload_parts(
    video_id: UUID,
    request: SignPartsRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> SignedParts:
    """Short-lived PUT URLs, each naming one object, one verb, and one part."""
    with user_transaction(user_id) as connection:
        video = require_coach(load_video(connection, video_id))
    if video.status != "uploading" or not video.multipart_upload_id:
        raise Problem(409, "That upload is no longer open.", "upload-not-in-progress")
    total = storage.part_count(video.size_bytes)
    requested = sorted(set(request.part_numbers))
    if any(number < 1 or number > total for number in requested):
        raise Problem(422, "That part number is not part of this upload.")
    try:
        parts = [
            SignedPart(
                part_number=number,
                url=storage.sign_part(
                    video.original_key, video.multipart_upload_id, number
                ),
                size_bytes=storage.expected_part_size(video.size_bytes, number),
            )
            for number in requested
        ]
    except storage.StorageError:
        raise storage_unavailable() from None
    return SignedParts(expires_in=storage.PART_URL_SECONDS, parts=parts)


def reconcile_parts(connection: Connection, video: Any) -> list[storage.StoredPart]:
    """Persist what storage holds. `docs/03-schema.md`: the browser is a cache.

    The client never asserts a part. Sizes are checked against the part plan so
    a short or oversized part cannot be recorded as complete.
    """
    stored = storage.list_parts(video.original_key, video.multipart_upload_id)
    total = storage.part_count(video.size_bytes)
    usable = [
        part
        for part in stored
        if 1 <= part.part_number <= total
        and part.size_bytes
        == storage.expected_part_size(video.size_bytes, part.part_number)
    ]
    for part in usable:
        connection.execute(
            text("""
                INSERT INTO app.video_upload_part
                    (video_id, part_number, etag, size_bytes)
                VALUES (:video_id, :part_number, :etag, :size_bytes)
                ON CONFLICT (video_id, part_number) DO UPDATE
                    SET etag = excluded.etag,
                        size_bytes = excluded.size_bytes,
                        completed_at = now()
            """),
            {
                "video_id": str(video.id),
                "part_number": part.part_number,
                "etag": part.etag,
                "size_bytes": part.size_bytes,
            },
        )
    return usable


@router.get(
    "/videos/{video_id}/upload-state",
    response_model=UploadState,
    dependencies=PRIVATE,
)
def read_upload_state(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> UploadState:
    """The authoritative resume record (`docs/00-decisions.md` D5)."""
    try:
        with user_transaction(user_id) as connection:
            video = require_coach(load_video(connection, video_id))
            if video.status == "uploading" and video.multipart_upload_id:
                reconcile_parts(connection, video)
            rows = connection.execute(
                text("""
                    SELECT part_number, etag, size_bytes
                    FROM app.video_upload_part
                    WHERE video_id = :video_id ORDER BY part_number
                """),
                {"video_id": str(video_id)},
            ).all()
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    total = storage.part_count(video.size_bytes)
    present = {row.part_number for row in rows}
    return UploadState(
        video_id=video_id,
        status=video.status,
        part_size_bytes=storage.PART_SIZE_BYTES,
        part_count=total,
        parts=[
            UploadedPart(
                part_number=row.part_number, etag=row.etag, size_bytes=row.size_bytes
            )
            for row in rows
        ],
        missing_part_numbers=[
            number for number in range(1, total + 1) if number not in present
        ],
    )


@router.post(
    "/videos/{video_id}/upload-complete",
    response_model=UploadCompleted,
    dependencies=PRIVATE,
)
def complete_upload(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> UploadCompleted:
    """Finish the upload, start the retention clock, and enqueue the work.

    Three phases, because assembling a multi-gigabyte object takes storage tens
    of seconds and the API pool is small: authorize and reconcile in one short
    transaction, talk to storage holding no lock, then transition and enqueue in
    a second short transaction that authorizes again.

    Idempotent by contract. The conditional UPDATE in `complete_video` is the
    only transition out of `uploading`, so it settles a completion race: the
    loser updates no row and reports the winner's answer.
    """
    try:
        with user_transaction(user_id) as connection:
            video = require_coach(load_video(connection, video_id))
            if video.status == "uploaded":
                return completed_response(video)
            if video.status != "uploading" or not video.multipart_upload_id:
                raise Problem(
                    409, "That upload can no longer be completed.", "upload-not-open"
                )
            assembled = already_assembled(video)
            stored = [] if assembled else reconcile_parts(connection, video)
            total = storage.part_count(video.size_bytes)
            if not assembled and sorted(part.part_number for part in stored) != list(
                range(1, total + 1)
            ):
                raise Problem(
                    409,
                    "Some parts of this match file have not arrived yet.",
                    "upload-incomplete",
                )
            key = video.original_key
            upload_id = video.multipart_upload_id
            game_id = video.game_id
            declared = video.size_bytes

        # No transaction is open here, so no row lock waits on storage.
        size = declared if assembled else assemble(key, upload_id, stored)

        with user_transaction(user_id) as connection:
            # Authorized again: a membership can be revoked while storage works.
            video = require_coach(load_video(connection, video_id))
            if size != declared:
                # Committed before the 409 is raised. Raising inside the
                # transaction would roll the terminal state back, leaving the
                # row `uploading` forever with an assembled object behind it and
                # no `first_terminal_failure_at` for the Task 22 sweeper.
                mark_failed(connection, video_id)
                rejected = True
            else:
                rejected = False
                row = complete_video(connection, video_id, game_id)
                if row is None:
                    # Someone else finished first, or an abort won the race.
                    return settled_response(load_video(connection, video_id))
                for kind in JOB_KINDS:
                    connection.execute(
                        text("""
                            INSERT INTO app.processing_job
                                (video_id, kind, idempotency_key)
                            VALUES (:video_id, :kind, :key)
                            ON CONFLICT (idempotency_key) DO NOTHING
                        """),
                        {
                            "video_id": str(video_id),
                            "kind": kind,
                            "key": job_key(kind, video_id),
                        },
                    )
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    if rejected:
        raise Problem(
            409,
            "The stored match file does not match the upload.",
            "upload-size-mismatch",
        )
    return UploadCompleted(
        video_id=video_id,
        status="uploaded",
        upload_completed_at=row.upload_completed_at,
        source_expires_at=row.source_expires_at,
    )


def already_assembled(video: Any) -> bool:
    """Did an earlier attempt finish the multipart upload and then fall over?

    There is a window between assembling the object and committing the
    transition. A database fault inside it would otherwise leave the row
    `uploading` with an upload id storage has already discarded, so every later
    completion would fail on `ListParts` and the coach could never finish.
    Recognising the finished object makes completion self-healing.
    """
    try:
        storage.list_parts(video.original_key, video.multipart_upload_id)
    except storage.StorageError:
        return bool(storage.head_object(video.original_key) == video.size_bytes)
    return False


def assemble(key: str, upload_id: str, stored: list[storage.StoredPart]) -> int | None:
    """Complete the multipart upload and report the stored length.

    A concurrent completion is not a failure. When storage refuses because the
    upload is already gone, the object it left behind is the answer: if it is
    there, this request's work was done by the other one, and reporting 503 for
    an upload that actually succeeded would be a lie.
    """
    try:
        storage.complete_multipart(key, upload_id, stored)
    except storage.StorageError:
        if storage.head_object(key) is None:
            raise
    return storage.head_object(key)


def settled_response(video: Any) -> UploadCompleted:
    """Report a race the conditional UPDATE lost.

    Only `uploaded` is a completion. An abort can win instead, and that row has
    no completion timestamps to report, so it is a conflict rather than a
    success.
    """
    if video.status != "uploaded":
        raise Problem(409, "That upload can no longer be completed.", "upload-not-open")
    return completed_response(video)


def complete_video(connection: Connection, video_id: UUID, game_id: UUID) -> Any:
    """The only transition out of `uploading`, so it settles a completion race.

    `docs/10-security-privacy.md`: both deadlines are set once, here, and no
    retry can move them, because no later statement writes them again.
    """
    return connection.execute(
        text(f"""
            UPDATE app.video SET
                status = 'uploaded',
                multipart_upload_id = NULL,
                upload_completed_at = now(),
                source_expires_at = now() + interval '{SOURCE_RETENTION_DAYS} days',
                derivatives_expires_at = (
                    SELECT t.season_end_at
                         + interval '{DERIVATIVE_RETENTION_DAYS} days'
                    FROM app.game g JOIN app.team t ON t.id = g.team_id
                    WHERE g.id = :game_id
                )
            WHERE id = :video_id AND status = 'uploading'
            RETURNING upload_completed_at, source_expires_at
        """),
        {"video_id": str(video_id), "game_id": str(game_id)},
    ).one_or_none()


def completed_response(video: Any) -> UploadCompleted:
    return UploadCompleted(
        video_id=video.id,
        status=video.status,
        upload_completed_at=video.upload_completed_at,
        source_expires_at=video.source_expires_at,
    )


def mark_failed(connection: Connection, video_id: UUID) -> None:
    """Terminal state for an attempt that produced no usable object.

    `first_terminal_failure_at` is set once with `coalesce`, never reset: it is
    the deadline `docs/10-security-privacy.md` measures cleanup from.
    """
    connection.execute(
        text("""
            UPDATE app.video SET
                status = 'failed',
                multipart_upload_id = NULL,
                first_terminal_failure_at =
                    coalesce(first_terminal_failure_at, now())
            WHERE id = :video_id AND status = 'uploading'
        """),
        {"video_id": str(video_id)},
    )
    connection.execute(
        text("DELETE FROM app.video_upload_part WHERE video_id = :video_id"),
        {"video_id": str(video_id)},
    )


@router.post(
    "/videos/{video_id}/upload-abort",
    response_model=VideoSummary,
    dependencies=PRIVATE,
)
def abort_upload(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> VideoSummary:
    """Abandon an incomplete upload. Safe to repeat.

    The video row is kept in a terminal state so the Task 22 sweeper can find
    it; `docs/10-security-privacy.md` gives an abandoned upload seven days from
    initiation regardless of how many resumes it saw.
    """
    try:
        with user_transaction(user_id) as connection:
            video = require_coach(load_video(connection, video_id))
            if video.status == "uploaded":
                raise Problem(
                    409,
                    "That match file finished uploading and cannot be abandoned.",
                    "upload-already-complete",
                )
            if video.status == "uploading" and video.multipart_upload_id:
                storage.abort_multipart(video.original_key, video.multipart_upload_id)
            mark_failed(connection, video_id)
            row = load_video(connection, video_id)
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    return video_summary(row)


@router.get("/videos/{video_id}", response_model=VideoSummary, dependencies=PRIVATE)
def read_video(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> VideoSummary:
    with user_transaction(user_id) as connection:
        row = require_coach(load_video(connection, video_id))
    return video_summary(row)
