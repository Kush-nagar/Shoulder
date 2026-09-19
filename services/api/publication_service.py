"""Transactional review publication state machine access.

Cross-row transitions live in migration-owned database functions. This module
only shapes their results and keeps coach and player DTO queries separate.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from services.api.problems import Problem

CONFLICT = "P1702"
NOT_VISIBLE = "42501"
INVALID = "22023"

PUBLICATION_COLUMNS = """
    p.id, p.game_id, p.player_id, p.goal_id, p.requested_by, p.status,
    p.replaces_publication_id, p.requested_count, p.first_terminal_failure_at,
    p.cancelled_at, p.private_exports_expires_at, p.created_at, p.updated_at,
    p.published_at
"""


def sqlstate(error: DBAPIError) -> str | None:
    value: Any = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


def publication_error(error: DBAPIError) -> Problem | None:
    code = sqlstate(error)
    if code == CONFLICT:
        return Problem(
            409,
            "That publication request is stale or conflicts with another export.",
            "review-publication-conflict",
        )
    if code == NOT_VISIBLE:
        return Problem(404, "That review publication is not available.")
    if code == INVALID:
        return Problem(
            422,
            "That review publication request is invalid.",
            "review-publication-invalid",
        )
    return None


def _items(connection: Connection, publication_id: UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        text("""
            SELECT i.judgment_id, i.judgment_revision_id, i.ordinal,
                   i.requested_clip_version, i.evidence_clip_id,
                   c.status AS clip_status, r.version, r.verdict,
                   r.comment_text, r.clip_start_ms, r.clip_end_ms
            FROM app.review_publication_item i
            JOIN app.judgment_revision r ON r.id = i.judgment_revision_id
            JOIN app.evidence_clip c
              ON c.judgment_id = i.judgment_id
             AND c.version = i.requested_clip_version
            WHERE i.publication_id = :publication_id
              AND private.is_review_publication_coach(i.publication_id)
            ORDER BY i.ordinal
        """),
        {"publication_id": str(publication_id)},
    ).all()
    return [dict(row._mapping) for row in rows]


def publication_model(connection: Connection, row: Any) -> dict[str, Any]:
    result = dict(row._mapping)
    result["items"] = _items(connection, row.id)
    return result


def request_publication(
    connection: Connection,
    *,
    game_id: UUID,
    player_id: UUID,
    goal_id: UUID,
    replaces_publication_id: UUID | None,
    idempotency_key: str,
    judgment_ids: list[UUID],
    versions: list[int],
) -> dict[str, Any]:
    row = connection.execute(
        text(f"""
            SELECT {PUBLICATION_COLUMNS}
            FROM private.request_review_publication(
                :game_id, :player_id, :goal_id, :replaces_publication_id,
                :idempotency_key, :judgment_ids, :versions
            ) p
        """),
        {
            "game_id": str(game_id),
            "player_id": str(player_id),
            "goal_id": str(goal_id),
            "replaces_publication_id": (
                str(replaces_publication_id) if replaces_publication_id else None
            ),
            "idempotency_key": idempotency_key,
            "judgment_ids": judgment_ids,
            "versions": versions,
        },
    ).one()
    return publication_model(connection, row)


def load_publication(
    connection: Connection, publication_id: UUID
) -> dict[str, Any] | None:
    row = connection.execute(
        text(f"""
            SELECT {PUBLICATION_COLUMNS}
            FROM app.review_publication p
            WHERE p.id = :publication_id
              AND private.is_review_publication_coach(p.id)
        """),
        {"publication_id": str(publication_id)},
    ).one_or_none()
    return publication_model(connection, row) if row else None


def _transition(
    connection: Connection, function: str, publication_id: UUID
) -> dict[str, Any]:
    row = connection.execute(
        text(f"""
            SELECT {PUBLICATION_COLUMNS}
            FROM private.{function}(:publication_id) p
        """),
        {"publication_id": str(publication_id)},
    ).one()
    return publication_model(connection, row)


def retry_publication(connection: Connection, publication_id: UUID) -> dict[str, Any]:
    return _transition(connection, "retry_review_publication", publication_id)


def cancel_publication(connection: Connection, publication_id: UUID) -> dict[str, Any]:
    return _transition(connection, "cancel_review_publication", publication_id)


def withdraw_judgment(connection: Connection, judgment_id: UUID) -> None:
    connection.execute(
        text("SELECT private.withdraw_judgment(:judgment_id)"),
        {"judgment_id": str(judgment_id)},
    )


def evidence_sets(connection: Connection, goal_id: UUID) -> Sequence[Any]:
    """Current player snapshots only; no video identifier or storage key.

    `private.player_evidence` is the one authorized path to a game label and
    coach name; `app.game` and `app.user_account` stay closed to a player, so
    the projection is assembled inside the definer helper and re-checks the
    current published pointer chain for the caller.
    """
    return connection.execute(
        text("SELECT * FROM private.player_evidence(:goal_id)"),
        {"goal_id": str(goal_id)},
    ).all()


def clip_for_signing(
    connection: Connection, judgment_id: UUID, expected_revision_id: UUID
) -> Any | None:
    """Lock current pointer until its object-specific URL is minted."""
    return connection.execute(
        text("""
            SELECT storage_key, published_revision_id
            FROM private.player_clip_for_signing(
                :judgment_id, :expected_revision_id
            )
        """),
        {
            "judgment_id": str(judgment_id),
            "expected_revision_id": str(expected_revision_id),
        },
    ).one_or_none()
