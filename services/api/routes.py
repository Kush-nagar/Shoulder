import hmac
import os
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from services.api.auth import authenticated_identity
from services.api.db import NO_STORE, operator_transaction, user_transaction
from services.api.problems import Problem
from services.api.schemas import (
    AuthIdentity,
    BulkRequest,
    BulkResult,
    BulkRowResult,
    Goal,
    GoalCreate,
    GoalPatch,
    GoalSummary,
    InviteRequest,
    InviteResult,
    LinkedPlayer,
    Me,
    PlayerCreate,
    PlayerPatch,
    RosterPlayer,
    TeamBootstrap,
    TeamCreated,
    TeamRole,
    TeamSummary,
)

router = APIRouter(prefix="/v1")

# Postgres SQLSTATEs raised deliberately by private.bootstrap_initial_team.
ALREADY_BOOTSTRAPPED = "23505"
UNKNOWN_ACCOUNT = "23503"
# The same code, reached through a unique index rather than a raise: a duplicate
# active shirt number, an already-linked player, or a second active goal.
UNIQUE_VIOLATION = ALREADY_BOOTSTRAPPED
# private.link_player_account raises this for an address it cannot normalize.
INVALID_ADDRESS = "22023"
# ...and this when no account exists for the address yet. See ADR 0017.
NO_SUCH_ACCOUNT = "P0002"


def authorized_operator(
    x_operator_token: Annotated[str | None, Header()] = None,
) -> None:
    """Bootstrap authorization. A signed-in session never reaches this path."""
    expected = os.environ.get("OPERATOR_BOOTSTRAP_TOKEN")
    if not expected or len(expected) < 32:
        raise HTTPException(503, "Service unavailable", headers=NO_STORE)
    if not x_operator_token or not hmac.compare_digest(
        x_operator_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(401, "Authentication required", headers=NO_STORE)


@router.get("/auth/identity", response_model=AuthIdentity)
def identity(
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> AuthIdentity:
    response.headers["Cache-Control"] = "private, no-store"
    return AuthIdentity(user_id=UUID(user_id))


@router.get("/me", response_model=Me)
def me(
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Me:
    response.headers["Cache-Control"] = "private, no-store"
    with user_transaction(user_id) as connection:
        account = connection.execute(
            text(
                "SELECT a.email, a.display_name FROM app.user_account a"
                " WHERE a.id = :user_id"
            ),
            {"user_id": user_id},
        ).one_or_none()
        if account is None:
            # RLS returns no row for an identity without a synchronized profile.
            raise HTTPException(404, "Not found", headers=NO_STORE)
        memberships = connection.execute(
            text(
                "SELECT m.team_id, m.role FROM app.team_membership m"
                " WHERE m.user_id = :user_id ORDER BY m.created_at, m.team_id"
            ),
            {"user_id": user_id},
        ).all()
        linked = connection.execute(
            text(
                "SELECT p.id, p.team_id FROM app.player p"
                " WHERE p.user_id = :user_id ORDER BY p.created_at LIMIT 1"
            ),
            {"user_id": user_id},
        ).one_or_none()
    roles: list[TeamRole] = []
    for membership in memberships:
        if membership.role not in roles:
            roles.append(membership.role)
    return Me(
        user_id=UUID(user_id),
        email=account.email,
        display_name=account.display_name,
        roles=roles,
        team_ids=[membership.team_id for membership in memberships],
        player=LinkedPlayer(id=linked.id, team_id=linked.team_id) if linked else None,
    )


@router.post(
    "/teams",
    response_model=TeamCreated,
    status_code=201,
    dependencies=[Depends(authorized_operator)],
)
def bootstrap_team(request: TeamBootstrap, response: Response) -> TeamCreated:
    """Create the single initial team and its coach membership atomically."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with operator_transaction() as connection:
            team_id = connection.execute(
                text(
                    "SELECT private.bootstrap_initial_team("
                    ":coach_user_id, :name, :season_label,"
                    " :season_end_at, :age_group)"
                ),
                {
                    "coach_user_id": str(request.coach_user_id),
                    "name": request.name,
                    "season_label": request.season_label,
                    "season_end_at": request.season_end_at,
                    "age_group": request.age_group,
                },
            ).scalar_one()
    except DBAPIError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == ALREADY_BOOTSTRAPPED:
            raise HTTPException(409, "Conflict", headers=NO_STORE) from None
        if code == UNKNOWN_ACCOUNT:
            raise HTTPException(422, "Unprocessable entity", headers=NO_STORE) from None
        raise HTTPException(503, "Service unavailable", headers=NO_STORE) from None
    return TeamCreated(team_id=team_id)


# --- Roster and development goals ---------------------------------------------
#
# Authorization is the database's answer, never Python's: every statement runs
# through `user_transaction` as the NOBYPASSRLS runtime role, and each route
# reads the row through RLS first so an invisible row is 404 and a visible row
# the caller may not write is 403.

# `active` and `deleted_at` are read for the response; `deletion_pending_at`
# filters the roster list only.
PLAYER_COLUMNS = """
    p.id, p.team_id, p.display_name, p.jersey_number, p.position, p.active,
    p.user_id IS NOT NULL AS account_linked, r.account_name,
    g.id AS goal_id, g.title AS goal_title, g.status AS goal_status
"""
# `private.team_roster` is the only path to a linked account's display name:
# `user_account` is self-only under RLS, so a coach cannot read another
# account's row directly. It authorizes on the caller's own coach membership
# and hides deleted and deletion-pending rows, so an archived player reads back
# with no account name.
# NOTE: the lateral re-runs per row, which is fine for a roster capped at
# 40; give the helper a player-scoped variant if a team ever gets large.
PLAYER_SOURCE = """
    FROM app.player p
    LEFT JOIN LATERAL private.team_roster(p.team_id) r ON r.player_id = p.id
    LEFT JOIN app.development_goal g
        ON g.player_id = p.id AND g.status = 'active'
"""
PLAYER_BY_ID = f"""
    SELECT {PLAYER_COLUMNS}, private.is_player_coach(p.id) AS is_coach,
        (p.deleted_at IS NOT NULL OR p.deletion_pending_at IS NOT NULL)
            AS off_roster
    {PLAYER_SOURCE}
    WHERE p.id = :player_id
"""
# `docs/04-api.md`: "Active roster only by default". A coach can ask for the
# archived rows too, because archiving is soft and the roster screen offers them
# as a section; without this they would be unreachable after the first archive.
TEAM_ROSTER = f"""
    SELECT {PLAYER_COLUMNS}
    {PLAYER_SOURCE}
    WHERE p.team_id = :team_id
      AND (:include_archived OR p.deleted_at IS NULL)
      AND p.deletion_pending_at IS NULL
    ORDER BY p.active DESC, p.jersey_number NULLS LAST, p.display_name, p.id
"""
GOAL_RETURNING = """
    id, player_id, title, description, ontology_key, status,
    created_by, created_at, closed_at
"""
GOAL_COLUMNS = """
    g.id, g.player_id, g.title, g.description, g.ontology_key, g.status,
    g.created_by, g.created_at, g.closed_at
"""

# active -> achieved | paused | retired; paused -> active | retired.
TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"achieved", "paused", "retired"}),
    "paused": frozenset({"active", "retired"}),
    "achieved": frozenset(),
    "retired": frozenset(),
}


def private_response(response: Response) -> None:
    """Roster and goal data is personal; no shared cache may keep a copy."""
    response.headers["Cache-Control"] = "private, no-store"


PRIVATE = [Depends(private_response)]


def sqlstate(error: DBAPIError) -> str | None:
    code: str | None = getattr(error.orig, "sqlstate", None)
    return code


def unavailable() -> Problem:
    return Problem(503, "The request could not be completed.")


def load_team(connection: Connection, team_id: UUID) -> Any:
    row = connection.execute(
        text(
            "SELECT t.id, private.is_team_coach(t.id) AS is_coach"
            " FROM app.team t WHERE t.id = :team_id"
        ),
        {"team_id": str(team_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That team is not available.")
    return row


def load_player(connection: Connection, player_id: UUID) -> Any:
    row = connection.execute(
        text(PLAYER_BY_ID), {"player_id": str(player_id)}
    ).one_or_none()
    if row is None:
        raise Problem(404, "That player is not available.")
    return row


def require_coach(row: Any) -> Any:
    if not row.is_coach:
        raise Problem(403, "Only a coach of this team can do that.")
    return row


def roster_player(row: Any) -> RosterPlayer:
    return RosterPlayer(
        id=row.id,
        team_id=row.team_id,
        display_name=row.display_name,
        jersey_number=row.jersey_number,
        position=row.position,
        active=row.active,
        account_linked=row.account_linked,
        account_name=row.account_name,
        active_goal=(
            GoalSummary(id=row.goal_id, title=row.goal_title, status=row.goal_status)
            if row.goal_id is not None
            else None
        ),
    )


def goal_model(row: Any) -> Goal:
    return Goal(
        id=row.id,
        player_id=row.player_id,
        title=row.title,
        description=row.description,
        ontology_key=row.ontology_key,
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
        closed_at=row.closed_at,
    )


def assignments(fields: dict[str, Any]) -> str:
    """SET clause for an allowlist of column names taken from a Pydantic model."""
    return ", ".join(f'"{name}" = :{name}' for name in fields)


@router.get("/teams", response_model=list[TeamSummary], dependencies=PRIVATE)
def list_teams(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[TeamSummary]:
    with user_transaction(user_id) as connection:
        rows = connection.execute(
            text("""
                SELECT t.id, t.name, t.age_group, t.season_label, m.role
                FROM app.team t
                JOIN app.team_membership m ON m.team_id = t.id
                WHERE m.user_id = private.current_user_id()
                ORDER BY t.created_at, t.id
            """)
        ).all()
    return [
        TeamSummary(
            team_id=row.id,
            name=row.name,
            age_group=row.age_group,
            season_label=row.season_label,
            role=row.role,
        )
        for row in rows
    ]


@router.get(
    "/teams/{team_id}/players",
    response_model=list[RosterPlayer],
    dependencies=PRIVATE,
)
def list_players(
    team_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
    include_archived: bool = False,
) -> list[RosterPlayer]:
    with user_transaction(user_id) as connection:
        require_coach(load_team(connection, team_id))
        rows = connection.execute(
            text(TEAM_ROSTER),
            {"team_id": str(team_id), "include_archived": include_archived},
        ).all()
    return [roster_player(row) for row in rows]


@router.post(
    "/teams/{team_id}/players",
    response_model=RosterPlayer,
    status_code=201,
    dependencies=PRIVATE,
)
def create_player(
    team_id: UUID,
    request: PlayerCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> RosterPlayer:
    """Add one roster row. No address is collected here, by design."""
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_team(connection, team_id))
            player_id = connection.execute(
                text("""
                    INSERT INTO app.player
                        (team_id, display_name, jersey_number, position)
                    VALUES (:team_id, :display_name, :jersey_number, :position)
                    RETURNING id
                """),
                {"team_id": str(team_id), **request.model_dump()},
            ).scalar_one()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "That shirt number is already in use on this team.",
                "jersey-number-taken",
            ) from None
        raise unavailable() from None
    return RosterPlayer(
        id=player_id,
        team_id=team_id,
        display_name=request.display_name,
        jersey_number=request.jersey_number,
        position=request.position,
        active=True,
        account_linked=False,
        account_name=None,
        active_goal=None,
    )


@router.post(
    "/teams/{team_id}/players/bulk",
    response_model=BulkResult,
    status_code=201,
    responses={200: {"model": BulkResult}, 422: {"model": BulkResult}},
    dependencies=PRIVATE,
)
def create_players_bulk(
    team_id: UUID,
    request: BulkRequest,
    response: Response,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> BulkResult:
    """Preview or commit a pasted roster. A partial write never happens."""
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_team(connection, team_id))
            taken = {
                number
                for number in connection.execute(
                    text("""
                        SELECT p.jersey_number FROM app.player p
                        WHERE p.team_id = :team_id
                          AND p.active
                          AND p.deleted_at IS NULL
                          AND p.jersey_number IS NOT NULL
                    """),
                    {"team_id": str(team_id)},
                ).scalars()
            }
            results = check_bulk_rows(request.rows, taken)
            invalid = any(result.errors for result in results)
            if not request.commit or invalid:
                # Nothing is written on either path; the transaction only read.
                response.status_code = 422 if invalid else 200
                return BulkResult(committed=False, rows=results, created=[])
            created = [
                connection.execute(
                    text("""
                        INSERT INTO app.player
                            (team_id, display_name, jersey_number, position)
                        VALUES (:team_id, :display_name, :jersey_number, :position)
                        RETURNING id
                    """),
                    {
                        "team_id": str(team_id),
                        "display_name": result.display_name,
                        "jersey_number": result.jersey_number,
                        "position": result.position,
                    },
                ).scalar_one()
                for result in results
            ]
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "A shirt number in this list was taken while it was being added.",
                "jersey-number-taken",
            ) from None
        raise unavailable() from None
    return BulkResult(committed=True, rows=results, created=created)


def check_bulk_rows(rows: list[Any], taken: set[int]) -> list[BulkRowResult]:
    """Validate every row against itself, the request, and the active roster."""
    results: list[BulkRowResult] = []
    seen: set[int] = set()
    for index, row in enumerate(rows):
        display_name = row.display_name.strip()
        position = row.position.strip() if row.position is not None else None
        number = row.jersey_number
        errors: list[str] = []
        if not 1 <= len(display_name) <= 80:
            errors.append("display_name_length")
        if position is not None and not 1 <= len(position) <= 40:
            errors.append("position_length")
        if number is not None:
            if not 0 <= number <= 99:
                errors.append("jersey_number_range")
            elif number in seen:
                errors.append("jersey_number_duplicate_in_request")
            elif number in taken:
                errors.append("jersey_number_taken")
            else:
                seen.add(number)
        results.append(
            BulkRowResult(
                index=index,
                display_name=display_name,
                jersey_number=number,
                position=position,
                errors=errors,
            )
        )
    return results


@router.patch(
    "/players/{player_id}",
    response_model=RosterPlayer,
    dependencies=PRIVATE,
)
def update_player(
    player_id: UUID,
    request: PlayerPatch,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> RosterPlayer:
    fields = request.model_dump(exclude_unset=True)
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_player(connection, player_id))
            connection.execute(
                text(
                    f"UPDATE app.player SET {assignments(fields)} WHERE id = :player_id"
                ),
                {**fields, "player_id": str(player_id)},
            )
            row = load_player(connection, player_id)
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "That shirt number is already in use on this team.",
                "jersey-number-taken",
            ) from None
        raise unavailable() from None
    return roster_player(row)


@router.post(
    "/players/{player_id}/invite",
    response_model=InviteResult,
    status_code=201,
    dependencies=PRIVATE,
)
def invite_player(
    player_id: UUID,
    request: InviteRequest,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> InviteResult:
    """Link an account to a roster row. Delivery is a later task, not this one."""
    try:
        with user_transaction(user_id) as connection:
            player = require_coach(load_player(connection, player_id))
            if player.off_roster:
                # The helper refuses this too, but its one "not linkable" branch
                # cannot say which cause applied. Name it here instead of
                # telling a coach a player is linked when they are not.
                raise Problem(
                    409,
                    "That player is off the roster, so an account cannot be"
                    " linked to them.",
                    "player-off-roster",
                )
            account_id = connection.execute(
                text("SELECT private.link_player_account(:player_id, :email)"),
                {"player_id": str(player_id), "email": request.email},
            ).scalar_one()
    except DBAPIError as error:
        code = sqlstate(error)
        if code == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "That player is already linked to an account.",
                "player-already-linked",
            ) from None
        if code == INVALID_ADDRESS:
            raise Problem(
                422, "That email address cannot be used.", "invalid-email"
            ) from None
        if code == NO_SUCH_ACCOUNT:
            # ADR 0017: invitation links an existing account and never creates
            # one. `app.user_account.id` references `auth.users`, so the
            # identity must exist first; Task 20 owns creating it with email
            # delivery. Nothing is written on this path.
            raise Problem(
                422,
                "That person has not signed in to Shoulder yet.",
                "invitation-account-not-found",
            ) from None
        raise unavailable() from None
    return InviteResult(player_id=player_id, user_id=account_id)


@router.post(
    "/players/{player_id}/archive",
    response_model=RosterPlayer,
    dependencies=PRIVATE,
)
def archive_player(
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> RosterPlayer:
    """Soft removal only. Nothing is deleted and nothing is erased here."""
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_player(connection, player_id))
            connection.execute(
                text("""
                    UPDATE app.player
                    SET active = false, deleted_at = coalesce(deleted_at, now())
                    WHERE id = :player_id
                """),
                {"player_id": str(player_id)},
            )
            row = load_player(connection, player_id)
    except DBAPIError:
        raise unavailable() from None
    return roster_player(row)


@router.post(
    "/players/{player_id}/goals",
    response_model=Goal,
    status_code=201,
    dependencies=PRIVATE,
)
def create_goal(
    player_id: UUID,
    request: GoalCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Goal:
    try:
        with user_transaction(user_id) as connection:
            require_coach(load_player(connection, player_id))
            row = connection.execute(
                text(f"""
                    INSERT INTO app.development_goal
                        (player_id, title, description, ontology_key, created_by)
                    VALUES (
                        :player_id, :title, :description, :ontology_key,
                        private.current_user_id()
                    )
                    RETURNING {GOAL_RETURNING}
                """),
                {"player_id": str(player_id), **request.model_dump()},
            ).one()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "That player already has an active development goal.",
                "active-goal-exists",
            ) from None
        raise unavailable() from None
    return goal_model(row)


@router.get(
    "/players/{player_id}/goals",
    response_model=list[Goal],
    dependencies=PRIVATE,
)
def list_goals(
    player_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[Goal]:
    """A coach reads their player's goals; a player reads only their own."""
    with user_transaction(user_id) as connection:
        load_player(connection, player_id)
        rows = connection.execute(
            text(f"""
                SELECT {GOAL_COLUMNS}
                FROM app.development_goal g
                WHERE g.player_id = :player_id
                ORDER BY g.created_at DESC, g.id
            """),
            {"player_id": str(player_id)},
        ).all()
    return [goal_model(row) for row in rows]


@router.patch("/goals/{goal_id}", response_model=Goal, dependencies=PRIVATE)
def update_goal(
    goal_id: UUID,
    request: GoalPatch,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Goal:
    fields = request.model_dump(exclude_unset=True)
    try:
        with user_transaction(user_id) as connection:
            current = connection.execute(
                text("""
                    SELECT g.id, g.status,
                           private.is_player_coach(g.player_id) AS is_coach
                    FROM app.development_goal g WHERE g.id = :goal_id
                """),
                {"goal_id": str(goal_id)},
            ).one_or_none()
            if current is None:
                raise Problem(404, "That development goal is not available.")
            require_coach(current)
            status = fields.get("status")
            closing = ""
            if status is not None:
                if status not in TRANSITIONS[current.status]:
                    raise Problem(
                        409,
                        "That development goal status change is not allowed.",
                        "invalid-status-transition",
                    )
                # The table's check constraint ties `closed_at` to `active`, and
                # the clock is the database's, not this process's.
                closing = (
                    ', "closed_at" = NULL'
                    if status == "active"
                    else (', "closed_at" = now()')
                )
            row = connection.execute(
                text(
                    f"UPDATE app.development_goal SET {assignments(fields)}{closing}"
                    f" WHERE id = :goal_id RETURNING {GOAL_RETURNING}"
                ),
                {**fields, "goal_id": str(goal_id)},
            ).one()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise Problem(
                409,
                "That player already has an active development goal.",
                "active-goal-exists",
            ) from None
        raise unavailable() from None
    return goal_model(row)
