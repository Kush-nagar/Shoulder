"""Player practice video and AI coach feedback data access (ADR 0021).

Every read and write runs as the verified user under row-level security:
`private.is_player_self(player_id)` is the only policy, so another player or a
coach sees no row at all. Object keys come from the generated id and a fixed
content-type allowlist; a caller never supplies one.
"""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem
from services.api.schemas import (
    AiCoachFeedback,
    AiCoachResult,
    Drill,
    PracticeFeatures,
    PracticeVideo,
)

PRACTICE_RETENTION = timedelta(days=90)
FEEDBACK_PER_DAY = 10
VIDEO_COLUMNS = """
    id, status, content_type, size_bytes, duration_ms, title, created_at,
    upload_completed_at, expires_at, object_key, player_id
"""
FEEDBACK_COLUMNS = """
    id, practice_video_id, development_goal_id, model, body, drills, created_at
"""


def own_player_id(connection: Connection) -> UUID:
    """The caller's own linked player row; a coach or stranger has none."""
    value = connection.execute(
        text("""
            SELECT p.id FROM app.player p
            WHERE private.is_player_self(p.id)
            ORDER BY p.created_at, p.id LIMIT 1
        """)
    ).scalar_one_or_none()
    if value is None:
        raise Problem(403, "Only a player can use practice videos.")
    return UUID(str(value))


def load_video(connection: Connection, video_id: UUID, *, lock: bool = False) -> Any:
    row = connection.execute(
        text(
            f"SELECT {VIDEO_COLUMNS} FROM app.practice_video WHERE id = :id"
            + (" FOR UPDATE" if lock else "")
        ),
        {"id": str(video_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That practice video is not available.")
    return row


def video_model(row: Any) -> PracticeVideo:
    return PracticeVideo(
        id=row.id,
        status=row.status,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_ms=row.duration_ms,
        title=row.title,
        created_at=row.created_at,
        upload_completed_at=row.upload_completed_at,
        expires_at=row.expires_at,
    )


def new_video_id(connection: Connection) -> UUID:
    return UUID(str(connection.execute(text("SELECT gen_random_uuid()")).scalar_one()))


def insert_video(
    connection: Connection,
    *,
    video_id: UUID,
    player_id: UUID,
    object_key: str,
    content_type: str,
    size_bytes: int,
    title: str | None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO app.practice_video (
                id, player_id, created_by_user_id, object_key, content_type,
                size_bytes, title, status
            ) VALUES (
                :id, :player_id, private.current_user_id(), :object_key,
                :content_type, :size_bytes, :title, 'uploading'
            )
        """),
        {
            "id": str(video_id),
            "player_id": str(player_id),
            "object_key": object_key,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "title": title,
        },
    )


def mark_ready(connection: Connection, video_id: UUID, duration_ms: int | None) -> Any:
    return connection.execute(
        text(f"""
            UPDATE app.practice_video SET
                status = 'ready',
                duration_ms = coalesce(:duration_ms, duration_ms),
                upload_completed_at = now(),
                expires_at = now() + make_interval(days => :days)
            WHERE id = :id AND status = 'uploading'
            RETURNING {VIDEO_COLUMNS}
        """),
        {
            "id": str(video_id),
            "duration_ms": duration_ms,
            "days": PRACTICE_RETENTION.days,
        },
    ).one()


def delete_video_row(connection: Connection, video_id: UUID) -> None:
    connection.execute(
        text("DELETE FROM app.practice_video WHERE id = :id"), {"id": str(video_id)}
    )


def own_videos(connection: Connection, player_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            text(f"""
                SELECT {VIDEO_COLUMNS} FROM app.practice_video
                WHERE player_id = :player_id AND status <> 'deleted'
                ORDER BY created_at DESC, id
            """),
            {"player_id": str(player_id)},
        ).all()
    )


def active_goal(connection: Connection, player_id: UUID) -> Any:
    """The player's active `development_goal`, looked up server-side only."""
    return connection.execute(
        text("""
            SELECT id, title FROM app.development_goal
            WHERE player_id = :player_id AND status = 'active'
            ORDER BY created_at DESC, id LIMIT 1
        """),
        {"player_id": str(player_id)},
    ).one_or_none()


def require_feedback_quota(connection: Connection, player_id: UUID) -> None:
    used = connection.execute(
        text("""
            SELECT count(*) FROM app.ai_coach_feedback
            WHERE player_id = :player_id AND created_at > now() - interval '1 day'
        """),
        {"player_id": str(player_id)},
    ).scalar_one()
    if used >= FEEDBACK_PER_DAY:
        raise Problem(
            429,
            "You have asked for ten AI suggestions today. Try again tomorrow.",
            "ai-feedback-rate-limited",
        )


def lock_player_feedback(connection: Connection, player_id: UUID) -> None:
    """Serialize the recount-and-insert so concurrent calls cannot overshoot."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 2101))"),
        {"key": str(player_id)},
    )


def insert_feedback(
    connection: Connection,
    *,
    video_id: UUID,
    player_id: UUID,
    goal_id: UUID | None,
    features: PracticeFeatures,
    result: AiCoachResult,
) -> Any:
    return connection.execute(
        text(f"""
            INSERT INTO app.ai_coach_feedback (
                practice_video_id, player_id, development_goal_id, features,
                model, body, drills
            ) VALUES (
                :video_id, :player_id, :goal_id, cast(:features AS jsonb),
                :model, :body, cast(:drills AS jsonb)
            ) RETURNING {FEEDBACK_COLUMNS}
        """),
        {
            "video_id": str(video_id),
            "player_id": str(player_id),
            "goal_id": str(goal_id) if goal_id else None,
            "features": features.model_dump_json(),
            "model": result.model,
            "body": result.body,
            "drills": json.dumps([drill.model_dump() for drill in result.drills]),
        },
    ).one()


def video_feedback(connection: Connection, video_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            text(f"""
                SELECT {FEEDBACK_COLUMNS} FROM app.ai_coach_feedback
                WHERE practice_video_id = :id ORDER BY created_at DESC, id
            """),
            {"id": str(video_id)},
        ).all()
    )


def feedback_model(row: Any) -> AiCoachFeedback:
    return AiCoachFeedback(
        id=row.id,
        practice_video_id=row.practice_video_id,
        development_goal_id=row.development_goal_id,
        model=row.model,
        body=row.body,
        drills=[Drill(**drill) for drill in row.drills],
        created_at=row.created_at,
    )
