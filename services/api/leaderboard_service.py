"""Opt-in team leaderboard (ADR 0023, Block 09B W2).

Membership rows are player-self under row-level security. The board is read
only through `private.team_leaderboard`, which checks the caller's team
membership itself and returns nickname, total and an is-me flag, nothing else.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem
from services.api.routes import load_team
from services.api.schemas import (
    Leaderboard,
    LeaderboardEntry,
    LeaderboardMembership,
    LeaderboardMetric,
    LeaderboardPeriod,
)

# ponytail: app.team has no season start column; a season is the last 365
# days, which is also how long sessions are kept.
SEASON = timedelta(days=365)


def own_player(connection: Connection) -> Any:
    """The caller's own linked player row; a coach or stranger has none."""
    row = connection.execute(
        text("""
            SELECT p.id, p.team_id FROM app.player p
            WHERE private.is_player_self(p.id)
            ORDER BY p.created_at, p.id LIMIT 1
        """)
    ).one_or_none()
    if row is None:
        raise Problem(403, "Only a player can join a team board.")
    return row


def membership(connection: Connection) -> LeaderboardMembership:
    player = own_player(connection)
    row = connection.execute(
        text(
            "SELECT nickname, joined_at FROM app.leaderboard_member"
            " WHERE player_id = :id"
        ),
        {"id": str(player.id)},
    ).one_or_none()
    return LeaderboardMembership(
        team_id=player.team_id,
        nickname=row.nickname if row else None,
        joined_at=row.joined_at if row else None,
    )


def join(connection: Connection, nickname: str) -> LeaderboardMembership:
    player = own_player(connection)
    connection.execute(
        text("""
            INSERT INTO app.leaderboard_member (player_id, nickname)
            VALUES (:id, :nickname)
            ON CONFLICT (player_id) DO UPDATE SET nickname = excluded.nickname
        """),
        {"id": str(player.id), "nickname": nickname},
    )
    return membership(connection)


def leave(connection: Connection) -> None:
    player = own_player(connection)
    connection.execute(
        text("DELETE FROM app.leaderboard_member WHERE player_id = :id"),
        {"id": str(player.id)},
    )


def period_start(period: LeaderboardPeriod, now: datetime) -> datetime:
    """Week: Monday 00:00 UTC. Season: the last 365 days."""
    now = now.astimezone(UTC)
    if period == "season":
        return now - SEASON
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def board(
    connection: Connection,
    team_id: UUID,
    metric: LeaderboardMetric,
    period: LeaderboardPeriod,
) -> Leaderboard:
    load_team(connection, team_id)  # 404 unless the caller is on this team
    since = period_start(period, datetime.now(UTC))
    rows = connection.execute(
        text(
            "SELECT nickname, value, is_me"
            " FROM private.team_leaderboard(:team_id, :metric, :since)"
        ),
        {"team_id": str(team_id), "metric": metric, "since": since},
    ).all()
    return Leaderboard(
        metric=metric,
        period=period,
        since=since,
        entries=[LeaderboardEntry.model_validate(row._mapping) for row in rows],
    )
