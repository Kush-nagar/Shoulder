"""Training session data access (ADR 0023, Block 09B W1).

Every read and write runs as the verified user under row-level security: the
player sees and deletes only their own rows, and their team coach only reads.
Nothing here ranks or compares players; totals and records are the caller's
own.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem
from services.api.schemas import (
    PersonalRecord,
    PersonalRecords,
    SessionSummary,
    SessionWeek,
    TrainingSession,
    TrainingSessionCreate,
)

COLUMNS = """
    id, kind, started_at, ended_at, duration_s, distance_m, top_speed_cms,
    sprint_count, half_split_s, heatmap, heatmap_second_half, gps_quality,
    note, created_at
"""
# ponytail: no pagination; a year of daily sessions is 365 rows. Page when
# LIST_LIMIT is ever reached.
LIST_LIMIT = 500
RECORD_METRICS = ("distance_m", "top_speed_cms", "sprint_count", "duration_s")


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
        raise Problem(403, "Only a player can record sessions.")
    return UUID(str(value))


def session_model(row: Any) -> TrainingSession:
    return TrainingSession.model_validate(row._mapping)


def insert_session(
    connection: Connection, player_id: UUID, request: TrainingSessionCreate
) -> Any:
    return connection.execute(
        text(f"""
            INSERT INTO app.training_session (
                player_id, kind, started_at, ended_at, duration_s, distance_m,
                top_speed_cms, sprint_count, half_split_s, heatmap,
                heatmap_second_half, gps_quality, note
            ) VALUES (
                :player_id, :kind, :started_at, :ended_at, :duration_s,
                :distance_m, :top_speed_cms, :sprint_count, :half_split_s,
                cast(:heatmap AS smallint[]),
                cast(:heatmap_second_half AS smallint[]), :gps_quality, :note
            ) RETURNING {COLUMNS}
        """),
        {"player_id": str(player_id), **request.model_dump()},
    ).one()


def load_session(connection: Connection, session_id: UUID) -> Any:
    row = connection.execute(
        text(
            f"SELECT {COLUMNS} FROM app.training_session"
            " WHERE id = :id AND private.is_player_self(player_id)"
        ),
        {"id": str(session_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That session is not available.")
    return row


def delete_session(connection: Connection, session_id: UUID) -> None:
    deleted = connection.execute(
        text(
            "DELETE FROM app.training_session"
            " WHERE id = :id AND private.is_player_self(player_id)"
        ),
        {"id": str(session_id)},
    ).rowcount
    if not deleted:
        raise Problem(404, "That session is not available.")


def player_sessions(connection: Connection, player_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            text(f"""
                SELECT {COLUMNS} FROM app.training_session
                WHERE player_id = :player_id
                ORDER BY started_at DESC, id LIMIT :limit
            """),
            {"player_id": str(player_id), "limit": LIST_LIMIT},
        ).all()
    )


def coach_sessions(connection: Connection, player_id: UUID) -> list[Any] | None:
    """None unless the caller coaches this player's team."""
    allowed = connection.execute(
        text("SELECT private.is_player_coach(:id)"), {"id": str(player_id)}
    ).scalar_one()
    return player_sessions(connection, player_id) if allowed else None


def summary(connection: Connection, player_id: UUID, weeks: int) -> SessionSummary:
    week_rows = connection.execute(
        text("""
            WITH week AS (
                SELECT generate_series(
                    date_trunc('week', now() AT TIME ZONE 'UTC')
                        - make_interval(weeks => :weeks - 1),
                    date_trunc('week', now() AT TIME ZONE 'UTC'),
                    interval '1 week'
                )::date AS week_start
            )
            SELECT week.week_start,
                   count(s.id) AS sessions,
                   coalesce(sum(s.distance_m), 0) AS distance_m,
                   coalesce(sum(s.duration_s), 0) AS duration_s,
                   coalesce(sum(s.sprint_count), 0) AS sprint_count
            FROM week
            LEFT JOIN app.training_session s
                ON s.player_id = :player_id
               AND date_trunc('week', s.started_at AT TIME ZONE 'UTC')::date
                   = week.week_start
            GROUP BY week.week_start
            ORDER BY week.week_start
        """),
        {"player_id": str(player_id), "weeks": weeks},
    ).all()
    records: dict[str, PersonalRecord | None] = {}
    for metric in RECORD_METRICS:  # fixed allowlist, never caller input
        row = connection.execute(
            text(f"""
                SELECT id, started_at, {metric} AS value
                FROM app.training_session
                WHERE player_id = :player_id AND {metric} > 0
                ORDER BY {metric} DESC, started_at, id LIMIT 1
            """),
            {"player_id": str(player_id)},
        ).one_or_none()
        records[metric] = (
            PersonalRecord(
                session_id=row.id, started_at=row.started_at, value=row.value
            )
            if row
            else None
        )
    return SessionSummary(
        weeks=[SessionWeek.model_validate(row._mapping) for row in week_rows],
        records=PersonalRecords(**records),
    )
