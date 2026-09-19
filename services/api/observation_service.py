"""Transactional service functions for append-only manual observations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem
from services.api.schemas import Observation, ObservationCreate
from services.api.video import load_video, require_ready

OBSERVATION_COLUMNS = """
    o.id, o.video_id, o.player_id, o.t_start_ms, o.t_end_ms, o.source,
    o.event_type, o.created_by, o.created_at
"""


def observation_model(row: Any) -> Observation:
    return Observation(
        id=row.id,
        video_id=row.video_id,
        player_id=row.player_id,
        t_start_ms=row.t_start_ms,
        t_end_ms=row.t_end_ms,
        source=row.source,
        event_type=row.event_type,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def require_review_context(
    connection: Connection, video_id: UUID, player_id: UUID
) -> Any:
    """Return a ready coached video whose game and player share one team."""
    video = require_ready(load_video(connection, video_id))
    player = connection.execute(
        text("""
            SELECT p.id
            FROM app.player p
            JOIN app.game g ON g.team_id = p.team_id
            WHERE p.id = :player_id
              AND g.id = :game_id
              AND p.active
              AND p.deleted_at IS NULL
              AND p.deletion_pending_at IS NULL
        """),
        {"player_id": str(player_id), "game_id": str(video.game_id)},
    ).one_or_none()
    if player is None:
        raise Problem(
            422,
            "That player cannot be reviewed with this match video.",
            "observation-context-invalid",
        )
    return video


def create_observation(
    connection: Connection, video_id: UUID, request: ObservationCreate
) -> Observation:
    video = require_review_context(connection, video_id, request.player_id)
    if request.t_end_ms > video.duration_ms:
        raise Problem(
            422,
            "The clip must stay inside the match video.",
            "observation-bounds-invalid",
        )
    row = connection.execute(
        text(f"""
            INSERT INTO app.observation (
                id, video_id, player_id, t_start_ms, t_end_ms, source, created_by
            ) VALUES (
                COALESCE(CAST(:client_id AS uuid), gen_random_uuid()),
                :video_id, :player_id, :t_start_ms, :t_end_ms,
                'coach_manual', private.current_user_id()
            )
            ON CONFLICT (id) DO NOTHING
            RETURNING {OBSERVATION_COLUMNS.replace("o.", "")}
        """),
        {
            "client_id": str(request.client_id) if request.client_id else None,
            "video_id": str(video_id),
            "player_id": str(request.player_id),
            "t_start_ms": request.t_start_ms,
            "t_end_ms": request.t_end_ms,
        },
    ).one_or_none()
    if row is None:
        row = connection.execute(
            text(f"""
                SELECT {OBSERVATION_COLUMNS}
                FROM app.observation o
                WHERE o.id = :client_id
                  AND o.video_id = :video_id
                  AND o.player_id = :player_id
                  AND o.t_start_ms = :t_start_ms
                  AND o.t_end_ms = :t_end_ms
                  AND o.source = 'coach_manual'
                  AND o.created_by = private.current_user_id()
            """),
            {
                "client_id": str(request.client_id),
                "video_id": str(video_id),
                "player_id": str(request.player_id),
                "t_start_ms": request.t_start_ms,
                "t_end_ms": request.t_end_ms,
            },
        ).one_or_none()
        if row is None:
            raise Problem(
                409,
                "That draft identifier is already in use.",
                "observation-client-id-conflict",
            )
    return observation_model(row)


def list_observations(
    connection: Connection, video_id: UUID, player_id: UUID
) -> list[Observation]:
    require_review_context(connection, video_id, player_id)
    rows = connection.execute(
        text(f"""
            SELECT {OBSERVATION_COLUMNS}
            FROM app.observation o
            WHERE o.video_id = :video_id AND o.player_id = :player_id
            ORDER BY o.t_start_ms, o.created_at, o.id
        """),
        {"video_id": str(video_id), "player_id": str(player_id)},
    ).all()
    return [observation_model(row) for row in rows]
