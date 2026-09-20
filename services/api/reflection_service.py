"""Serialized player-reflection writes and role-filtered reads."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from services.api.problems import Problem
from services.api.publication_service import sqlstate

CONFLICT = "P1901"
INVALID = "P1902"
NOT_VISIBLE = "42501"


def reflection_error(error: DBAPIError) -> Problem | None:
    code = sqlstate(error)
    if code == CONFLICT:
        return Problem(
            409,
            "That reflection changed or the request is no longer current.",
            "player-reflection-conflict",
        )
    if code == INVALID:
        return Problem(
            422,
            "That reflection request is invalid or expired.",
            "player-reflection-request-invalid",
        )
    if code == NOT_VISIBLE:
        return Problem(404, "That reflection is not available.")
    return None


REFLECTION_COLUMNS = """
    r.id, r.judgment_id, r.text, r.judgment_version_at_save, r.etag,
    r.created_at, r.updated_at,
    (j.id IS NOT NULL) AS evidence_available,
    current_revision.version AS current_published_version,
    (current_revision.version IS NOT NULL
     AND current_revision.version <> r.judgment_version_at_save)
        AS is_for_earlier_version
"""


def _reflection_query(where: str) -> str:
    # RLS hides a withdrawn judgment from its player while the reflection's
    # independent author policy keeps that reflection manageable. The left
    # joins therefore expose only current-version context, never old coach text.
    return f"""
        SELECT {REFLECTION_COLUMNS}
        FROM app.player_reflection r
        LEFT JOIN app.judgment j
          ON j.id = r.judgment_id
         AND j.publication_status = 'published'
        LEFT JOIN app.judgment_revision current_revision
          ON current_revision.id = j.current_revision_id
        WHERE {where}
    """


def reflection_model(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def own_reflections(connection: Connection) -> Sequence[Any]:
    return connection.execute(
        text(_reflection_query("true") + " ORDER BY r.updated_at DESC, r.id")
    ).all()


def coach_reflections(connection: Connection, player_id: UUID) -> Sequence[Any] | None:
    allowed = connection.execute(
        text("SELECT private.is_player_coach(:player_id)"),
        {"player_id": str(player_id)},
    ).scalar_one()
    if not allowed:
        return None
    return connection.execute(
        text(
            _reflection_query("r.player_id = :player_id")
            + " ORDER BY r.updated_at DESC, r.id"
        ),
        {"player_id": str(player_id)},
    ).all()


def load_reflection(connection: Connection, reflection_id: UUID) -> Any | None:
    return connection.execute(
        text(_reflection_query("r.id = :reflection_id")),
        {"reflection_id": str(reflection_id)},
    ).one_or_none()


def save_reflection(
    connection: Connection,
    *,
    judgment_id: UUID,
    intent: str,
    reflection_text: str,
    expected_reflection_id: UUID | None,
    expected_etag: UUID | None,
    request_created_at: Any,
    idempotency_key: str,
) -> Any:
    reflection_id = connection.execute(
        text("""
            SELECT (private.save_player_reflection(
                :judgment_id, :intent, :reflection_text,
                :expected_reflection_id, :expected_etag,
                :request_created_at, :idempotency_key
            )).id
        """),
        {
            "judgment_id": str(judgment_id),
            "intent": intent,
            "reflection_text": reflection_text,
            "expected_reflection_id": (
                str(expected_reflection_id) if expected_reflection_id else None
            ),
            "expected_etag": str(expected_etag) if expected_etag else None,
            "request_created_at": request_created_at,
            "idempotency_key": idempotency_key,
        },
    ).scalar_one()
    row = load_reflection(connection, UUID(str(reflection_id)))
    if row is None:  # Defensive: the author policy must expose the saved row.
        raise RuntimeError("saved reflection is not author-readable")
    return row


def delete_reflection(
    connection: Connection,
    *,
    judgment_id: UUID,
    expected_reflection_id: UUID,
    expected_etag: UUID,
    request_created_at: Any,
    idempotency_key: str,
) -> None:
    deleted = connection.execute(
        text("""
            SELECT private.delete_player_reflection(
                :judgment_id, :expected_reflection_id, :expected_etag,
                :request_created_at, :idempotency_key
            )
        """),
        {
            "judgment_id": str(judgment_id),
            "expected_reflection_id": str(expected_reflection_id),
            "expected_etag": str(expected_etag),
            "request_created_at": request_created_at,
            "idempotency_key": idempotency_key,
        },
    ).scalar_one()
    if not deleted:
        raise RuntimeError("active reflection deletion was not verified")
