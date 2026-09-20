"""Content-free email templates and Resend delivery for Task 20.

The durable event and recipient lookup live in Postgres. This module accepts
only IDs selected by the fenced worker helper, builds one allowlisted product
URL, and sends it with the event identity as Resend's idempotency key.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import text

from services.worker import jobs

RESEND_URL = "https://api.resend.com/emails"
SUBJECTS = {
    "evidence_ready": "Your Shoulder clips are ready",
    "video_ready": "A Shoulder video is ready",
    "video_failed": "A Shoulder video needs attention",
    "reflection_digest": "New activity in Shoulder",
}
COPY = {
    "evidence_ready": (
        "Your coach published a set of clips for you.",
        "Open your clips",
    ),
    "video_ready": (
        "A match video is ready to review.",
        "Open the match",
    ),
    "video_failed": (
        "Shoulder could not prepare a match video. Open the match to try the"
        " recovery action.",
        "Open the match",
    ),
    "reflection_digest": (
        "A player added a reflection. Sign in to Shoulder to read it.",
        "View reflections",
    ),
}
_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


class DeliveryError(Exception):
    """Email input, configuration, or provider delivery was unsafe or invalid."""


@dataclass(frozen=True)
class Message:
    recipient: str
    subject: str
    html: str
    text: str
    event_key: str
    target_url: str


def verified_origin(value: str, *, allow_local_http: bool = False) -> str:
    """Accept one exact HTTPS origin, with an explicit loopback test escape."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise DeliveryError("The application origin is invalid.") from None
    host = parsed.hostname
    if (
        not host
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or value != f"{parsed.scheme}://{parsed.netloc}"
    ):
        raise DeliveryError("The application origin must be an exact origin.")
    local_http = (
        allow_local_http
        and parsed.scheme == "http"
        and host in {"127.0.0.1", "localhost", "::1"}
    )
    if parsed.scheme != "https" and not local_http:
        raise DeliveryError("Email links require HTTPS outside loopback tests.")
    if port is not None and not 1 <= port <= 65535:
        raise DeliveryError("The application origin port is invalid.")
    return value


def _target_path(
    kind: str,
    *,
    publication_id: UUID | None,
    goal_id: UUID | None,
    game_id: UUID | None,
    player_id: UUID | None,
) -> str:
    if kind == "evidence_ready" and publication_id and goal_id:
        return f"/player/goals/{goal_id}?publication={publication_id}"
    if kind in {"video_ready", "video_failed"} and game_id:
        return f"/coach/games/{game_id}"
    if kind == "reflection_digest" and player_id:
        return f"/coach/players/{player_id}"
    raise DeliveryError("The email event has no allowlisted target.")


def render_message(
    *,
    kind: str,
    recipient: str,
    event_key: str,
    origin: str,
    publication_id: UUID | None = None,
    goal_id: UUID | None = None,
    game_id: UUID | None = None,
    player_id: UUID | None = None,
    allow_local_http: bool = False,
) -> Message:
    """Render a fixed template. No player-authored or coach-authored text enters."""
    subject = SUBJECTS.get(kind)
    content = COPY.get(kind)
    if subject is None or content is None:
        raise DeliveryError("The email event kind is invalid.")
    if not _EMAIL.fullmatch(recipient) or len(recipient) > 320:
        raise DeliveryError("The email recipient is invalid.")
    if not 1 <= len(event_key) <= 200 or any(
        character in event_key for character in "\r\n"
    ):
        raise DeliveryError("The email event identity is invalid.")
    safe_origin = verified_origin(origin, allow_local_http=allow_local_http)
    path = _target_path(
        kind,
        publication_id=publication_id,
        goal_id=goal_id,
        game_id=game_id,
        player_id=player_id,
    )
    target = f"{safe_origin}{path}"
    notice, action = content
    safe_target = escape(target, quote=True)
    html = (
        "<!doctype html><html><body>"
        f"<p>{escape(notice)}</p>"
        f'<p><a href="{safe_target}">{escape(action)}</a></p>'
        "</body></html>"
    )
    return Message(
        recipient=recipient,
        subject=subject,
        html=html,
        text=f"{notice}\n\n{action}: {target}",
        event_key=event_key,
        target_url=target,
    )


def _valid_sender(sender: str) -> bool:
    if not 3 <= len(sender) <= 320 or any(char in sender for char in "\r\n"):
        return False
    if "<" not in sender:
        return bool(_EMAIL.fullmatch(sender))
    if not sender.endswith(">") or sender.count("<") != 1:
        return False
    display, address = sender.rsplit("<", 1)
    return bool(display.strip() and _EMAIL.fullmatch(address[:-1]))


def send_with_resend(
    message: Message,
    *,
    api_key: str,
    sender: str,
    timeout_seconds: float = 15,
) -> str:
    """Send one message through Resend without exposing provider error bodies."""
    if not api_key or any(char in api_key for char in "\r\n"):
        raise DeliveryError("Resend is not configured.")
    if not _valid_sender(sender):
        raise DeliveryError("The verified email sender is invalid.")
    payload = json.dumps(
        {
            "from": sender,
            "to": [message.recipient],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        RESEND_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": message.event_key,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            result: Any = json.loads(response.read(65537))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        raise DeliveryError("Resend did not accept the email.") from None
    provider_id = result.get("id") if isinstance(result, dict) else None
    if (
        not isinstance(provider_id, str)
        or not 1 <= len(provider_id) <= 100
        or any(character in provider_id for character in "\r\n")
    ):
        raise DeliveryError("Resend returned an invalid email identity.")
    return provider_id


def delivery_job(job: jobs.Job, keep_going: Any) -> None:
    """Send or suppress one delivery while its durable queue lease is live."""
    if job.email_delivery_id is None:
        raise DeliveryError("The email job has no delivery target.")
    if not keep_going(None):
        raise jobs.Cancelled
    with jobs.transaction() as connection:
        row = connection.execute(
            text("SELECT * FROM private.email_delivery_input(:job, :worker)"),
            {"job": str(job.id), "worker": job.locked_by},
        ).one_or_none()
    if row is None:
        # A cascading account/event deletion can remove the target after claim.
        # There is then nothing to send and no content to recover.
        return
    if not row.sendable:
        with jobs.transaction() as connection:
            suppressed = connection.execute(
                text("SELECT private.suppress_email_delivery(:job, :worker)"),
                {"job": str(job.id), "worker": job.locked_by},
            ).scalar_one()
        if not suppressed:
            raise DeliveryError("The stale email notice could not be suppressed.")
        return

    origin = os.environ.get("APP_ORIGIN", "")
    message = render_message(
        kind=row.kind,
        recipient=row.recipient_email,
        event_key=row.event_key,
        origin=origin,
        publication_id=row.publication_id,
        goal_id=row.goal_id,
        game_id=row.game_id,
        player_id=row.player_id,
        allow_local_http=(
            os.environ.get("EMAIL_ALLOW_LOCAL_HTTP", "").lower() == "true"
        ),
    )
    provider_id = send_with_resend(
        message,
        api_key=os.environ.get("RESEND_API_KEY", ""),
        sender=os.environ.get("EMAIL_FROM", ""),
    )
    with jobs.transaction() as connection:
        completed = connection.execute(
            text("""
                SELECT private.complete_email_delivery(
                    :job, :worker, :provider_id
                )
            """),
            {
                "job": str(job.id),
                "worker": job.locked_by,
                "provider_id": provider_id,
            },
        ).scalar_one()
    if not completed:
        # The provider request remains safe to retry because its idempotency
        # key is the stable database event identity.
        raise DeliveryError("The delivered email could not be recorded.")


HANDLERS: dict[str, Any] = {"email_delivery": delivery_job}
