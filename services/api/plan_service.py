"""Coach-authored weekly training plans (Block 09B W3).

Row-level security is the boundary; these queries also filter explicitly so a
coach who is also a player sees only what each endpoint promises.
"""

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api.problems import Problem
from services.api.schemas import (
    TrainingPlan,
    TrainingPlanCreate,
    TrainingPlanItem,
    TrainingPlanPatch,
)

COLUMNS = (
    "p.id, p.team_id, p.player_id, p.title, p.week_of, p.items,"
    " p.created_at, p.updated_at"
)


def monday(day: date) -> date:
    """Plans are filed by week; any day of the week names its Monday."""
    return day - timedelta(days=day.weekday())


def plan_model(row: Any) -> TrainingPlan:
    return TrainingPlan(
        id=row.id,
        team_id=row.team_id,
        player_id=row.player_id,
        title=row.title,
        week_of=row.week_of,
        items=[TrainingPlanItem.model_validate(item) for item in row.items],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _items(items: list[TrainingPlanItem]) -> str:
    return json.dumps([item.model_dump() for item in items])


def team_plans(connection: Connection, team_id: UUID) -> list[TrainingPlan]:
    rows = connection.execute(
        text(f"""
            SELECT {COLUMNS} FROM app.training_plan p
            WHERE p.team_id = :team_id
            ORDER BY p.week_of DESC, p.created_at DESC, p.id
            LIMIT 200
        """),
        {"team_id": str(team_id)},
    ).all()
    return [plan_model(row) for row in rows]


def insert_plan(
    connection: Connection, team_id: UUID, request: TrainingPlanCreate
) -> TrainingPlan:
    if request.player_id is not None:
        on_team = connection.execute(
            text("""
                SELECT 1 FROM app.player
                WHERE id = :player_id AND team_id = :team_id
                  AND deleted_at IS NULL AND deletion_pending_at IS NULL
            """),
            {"player_id": str(request.player_id), "team_id": str(team_id)},
        ).one_or_none()
        if on_team is None:
            raise Problem(422, "That player is not on this team.")
    row = connection.execute(
        text(f"""
            INSERT INTO app.training_plan AS p
                (team_id, player_id, created_by, title, week_of, items)
            VALUES (
                :team_id, :player_id, private.current_user_id(), :title,
                :week_of, CAST(:items AS jsonb)
            )
            RETURNING {COLUMNS}
        """),
        {
            "team_id": str(team_id),
            "player_id": None if request.player_id is None else str(request.player_id),
            "title": request.title,
            "week_of": monday(request.week_of),
            "items": _items(request.items),
        },
    ).one()
    return plan_model(row)


def load_coach_plan(connection: Connection, plan_id: UUID) -> Any:
    """404 when invisible; 403 when visible only as a player's plan."""
    row = connection.execute(
        text(
            "SELECT p.id, private.is_team_coach(p.team_id) AS is_coach"
            " FROM app.training_plan p WHERE p.id = :id"
        ),
        {"id": str(plan_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That plan is not available.")
    if not row.is_coach:
        raise Problem(403, "Only a coach of this team can do that.")
    return row


def update_plan(
    connection: Connection, plan_id: UUID, request: TrainingPlanPatch
) -> TrainingPlan:
    load_coach_plan(connection, plan_id)
    fields: dict[str, Any] = {}
    if "title" in request.model_fields_set:
        fields["title"] = request.title
    if request.week_of is not None:
        fields["week_of"] = monday(request.week_of)
    if request.items is not None:
        fields["items"] = _items(request.items)
    assignments = ", ".join(
        "items = CAST(:items AS jsonb)" if name == "items" else f"{name} = :{name}"
        for name in fields
    )
    row = connection.execute(
        text(f"""
            UPDATE app.training_plan AS p
            SET {assignments}, updated_at = now()
            WHERE p.id = :id
            RETURNING {COLUMNS}
        """),
        {"id": str(plan_id), **fields},
    ).one()
    return plan_model(row)


def delete_plan(connection: Connection, plan_id: UUID) -> None:
    load_coach_plan(connection, plan_id)
    connection.execute(
        text("DELETE FROM app.training_plan WHERE id = :id"), {"id": str(plan_id)}
    )


def own_plans(connection: Connection) -> list[TrainingPlan]:
    """The caller's own plans plus whole-team plans of their team."""
    player = connection.execute(
        text("""
            SELECT p.id, p.team_id FROM app.player p
            WHERE private.is_player_self(p.id)
            ORDER BY p.created_at, p.id LIMIT 1
        """)
    ).one_or_none()
    if player is None:
        raise Problem(403, "Only a player can read their plans.")
    rows = connection.execute(
        text(f"""
            SELECT {COLUMNS} FROM app.training_plan p
            WHERE p.player_id = :player_id
               OR (p.player_id IS NULL AND p.team_id = :team_id)
            ORDER BY p.week_of DESC, p.created_at DESC, p.id
            LIMIT 50
        """),
        {"player_id": str(player.id), "team_id": str(player.team_id)},
    ).all()
    return [plan_model(row) for row in rows]
