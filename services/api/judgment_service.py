"""Transactional service functions for coach judgments and revisions.

Every content write goes through the single database function
`private.write_judgment_revision`; this module never issues a raw INSERT or
UPDATE against `app.judgment` or `app.judgment_revision`. That mirrors the
database grants, which give the runtime role no other way to write either
table.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from services.api.problems import Problem

INVALID_PARAMETER = "22023"
GOAL_NOT_VISIBLE = "42501"
NOT_ORIGINAL_AUTHOR = "PJ001"
STALE_VERSION = "40001"
JUDGMENT_ALREADY_EXISTS = "23505"
JUDGMENT_NOT_FOUND = "P0002"

JUDGMENT_COLUMNS = """
    j.id, j.observation_id, j.goal_id, j.author_user_id, j.version,
    j.publication_status, j.current_revision_id, j.published_at,
    j.updated_at, j.created_at
"""


class StaleJudgment(Exception):
    """An edit lost a version race.

    Raised rather than answered here because the failing statement aborted the
    transaction that would have to read the winning snapshot.
    """


def sqlstate(error: DBAPIError) -> str | None:
    code: Any = getattr(error.orig, "sqlstate", None)
    return code if isinstance(code, str) else None


def _revision_snapshot(connection: Connection, judgment_id: UUID, version: int) -> Any:
    return connection.execute(
        text("""
            SELECT verdict, comment_text, clip_start_ms, clip_end_ms
            FROM app.judgment_revision
            WHERE judgment_id = :judgment_id AND version = :version
        """),
        {"judgment_id": str(judgment_id), "version": version},
    ).one()


def judgment_model(row: Any, snapshot: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "observation_id": row.observation_id,
        "goal_id": row.goal_id,
        "author_user_id": row.author_user_id,
        "version": row.version,
        "publication_status": row.publication_status,
        "current_revision_id": row.current_revision_id,
        "published_at": row.published_at,
        "updated_at": row.updated_at,
        "created_at": row.created_at,
        "verdict": snapshot.verdict,
        "comment_text": snapshot.comment_text,
        "clip_start_ms": snapshot.clip_start_ms,
        "clip_end_ms": snapshot.clip_end_ms,
    }


def _write(
    connection: Connection,
    *,
    judgment_id: UUID | None,
    observation_id: UUID | None,
    goal_id: UUID | None,
    expected_version: int | None,
    verdict: str,
    comment_text: str | None,
    clip_start_ms: int,
    clip_end_ms: int,
) -> dict[str, Any]:
    try:
        row = connection.execute(
            text(f"""
                SELECT {JUDGMENT_COLUMNS} FROM private.write_judgment_revision(
                    :judgment_id, :observation_id, :goal_id, :expected_version,
                    :verdict, :comment_text, :clip_start_ms, :clip_end_ms
                ) j
            """),
            {
                "judgment_id": str(judgment_id) if judgment_id else None,
                "observation_id": str(observation_id) if observation_id else None,
                "goal_id": str(goal_id) if goal_id else None,
                "expected_version": expected_version,
                "verdict": verdict,
                "comment_text": comment_text,
                "clip_start_ms": clip_start_ms,
                "clip_end_ms": clip_end_ms,
            },
        ).one()
    except DBAPIError as error:
        code = sqlstate(error)
        if code == INVALID_PARAMETER:
            raise Problem(
                422, "That judgment could not be saved.", "judgment-invalid"
            ) from None
        if code in (GOAL_NOT_VISIBLE, JUDGMENT_NOT_FOUND):
            raise Problem(404, "That judgment is not available.") from None
        if code == NOT_ORIGINAL_AUTHOR:
            raise Problem(
                403,
                "Only the coach who created this judgment can edit it.",
                "judgment-not-original-author",
            ) from None
        if code == STALE_VERSION:
            # The caller has to be told what it lost to, and this transaction
            # is already aborted, so the snapshot cannot be read here. The
            # route reads it in a fresh transaction and answers.
            raise StaleJudgment from None
        if code == JUDGMENT_ALREADY_EXISTS:
            raise Problem(
                409,
                "A judgment already exists for this observation and goal.",
                "judgment-already-exists",
            ) from None
        raise
    snapshot = _revision_snapshot(connection, row.id, row.version)
    return judgment_model(row, snapshot)


def create_judgment(
    connection: Connection,
    observation_id: UUID,
    goal_id: UUID,
    verdict: str,
    comment_text: str | None,
    clip_start_ms: int,
    clip_end_ms: int,
) -> dict[str, Any]:
    return _write(
        connection,
        judgment_id=None,
        observation_id=observation_id,
        goal_id=goal_id,
        expected_version=None,
        verdict=verdict,
        comment_text=comment_text,
        clip_start_ms=clip_start_ms,
        clip_end_ms=clip_end_ms,
    )


def edit_judgment(
    connection: Connection,
    judgment_id: UUID,
    expected_version: int,
    verdict: str,
    comment_text: str | None,
    clip_start_ms: int,
    clip_end_ms: int,
) -> dict[str, Any]:
    return _write(
        connection,
        judgment_id=judgment_id,
        observation_id=None,
        goal_id=None,
        expected_version=expected_version,
        verdict=verdict,
        comment_text=comment_text,
        clip_start_ms=clip_start_ms,
        clip_end_ms=clip_end_ms,
    )


def load_judgment(connection: Connection, judgment_id: UUID) -> dict[str, Any] | None:
    """The judgment as it stands now, with its latest revision's content.

    Read in its own transaction after a lost version race, which is why it
    does not reuse the write path's row. RLS decides visibility, so a caller
    who may not read this judgment gets nothing rather than a denial.
    """
    row = connection.execute(
        text(f"SELECT {JUDGMENT_COLUMNS} FROM app.judgment j WHERE j.id = :id"),
        {"id": str(judgment_id)},
    ).one_or_none()
    if row is None:
        return None
    return judgment_model(row, _revision_snapshot(connection, row.id, row.version))


def load_observation_judgment(
    connection: Connection, observation_id: UUID
) -> dict[str, Any] | None:
    """Load coach-only current draft state for review restoration."""
    row = connection.execute(
        text(f"""
            SELECT {JUDGMENT_COLUMNS}
            FROM app.judgment j
            WHERE j.observation_id = :observation_id
              AND private.is_judgment_coach(j.id)
        """),
        {"observation_id": str(observation_id)},
    ).one_or_none()
    if row is None:
        return None
    return judgment_model(row, _revision_snapshot(connection, row.id, row.version))


def list_revisions(connection: Connection, judgment_id: UUID) -> Sequence[Any]:
    """Immutable revision history, for the coaching team only.

    The coach predicate is stated here rather than left to row-level
    security, and independent review is why. `judgment_revision` carries a
    second SELECT policy for players, granting them the one revision their
    judgment currently publishes. That policy is correct and unreachable
    today, because nothing can publish before Task 17 -- but the moment Task
    17 lands, an endpoint relying on RLS alone would start answering a
    player's call to this route with a revision row: raw author id, the
    coach's draft comment, exact clip bounds. `docs/03-schema.md` makes this
    history coach-only, and a player's evidence comes from the published
    pointer through its own DTO, never from here.

    So the route is narrowed to what it is documented to be. A player gets an
    empty history rather than a filtered one, which tells them nothing about
    how many drafts exist.
    """
    return connection.execute(
        text("""
            SELECT r.id, r.judgment_id, r.version, r.author_user_id, r.verdict,
                   r.comment_text, r.clip_start_ms, r.clip_end_ms, r.created_at
            FROM app.judgment_revision r
            WHERE r.judgment_id = :judgment_id
              AND private.is_judgment_coach(:judgment_id)
            ORDER BY r.version
        """),
        {"judgment_id": str(judgment_id)},
    ).all()
