"""RFC 9457 problem details for every error this service returns.

A body carries `type`, `title`, `status`, `detail`, and `instance`. It never
carries a player name, an email address, a jersey number, SQL, a SQLSTATE, a
token, or a provider message: an error page is not a place to leak roster data,
and a 404 must not become an existence oracle.

One route may add RFC 9457 extension members, and only where a specification
requires the client to recover from the error with data it is already
authorised to read. `docs/04-api.md` requires the judgment edit conflict to
return the latest coach-authored snapshot, because a coach whose draft lost a
race cannot merge it back without seeing what it lost to. The reader is the
team's own coach and row-level security has already decided that. Nothing is
added implicitly: a route passes the member, or the body has none.
"""

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://shoulder.local/problems/"
NO_STORE = {"Cache-Control": "private, no-store"}

# Status code -> (default `type` slug, human title). A route may pass a more
# specific slug so a client can branch without parsing prose.
DEFAULTS: dict[int, tuple[str, str]] = {
    400: ("bad-request", "Bad request"),
    401: ("authentication-required", "Authentication required"),
    403: ("forbidden", "Forbidden"),
    404: ("not-found", "Not found"),
    405: ("method-not-allowed", "Method not allowed"),
    409: ("conflict", "Conflict"),
    422: ("validation-failed", "Unprocessable entity"),
    503: ("service-unavailable", "Service unavailable"),
}
GENERIC = ("error", "Error")
# The standard members. An extension may not shadow one of these.
RESERVED = ("type", "title", "status", "detail", "instance")


class Problem(Exception):
    """One error, already reduced to what is safe to send to a browser."""

    def __init__(
        self,
        status: int,
        detail: str,
        slug: str | None = None,
        title: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        default_slug, default_title = DEFAULTS.get(status, GENERIC)
        self.status = status
        self.slug = slug or default_slug
        self.title = title or default_title
        self.detail = detail
        self.extensions = extensions or {}
        super().__init__(detail)


def render(
    request: Request,
    status: int,
    slug: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> Response:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers={**NO_STORE, **(headers or {})},
        content={
            "type": f"{PROBLEM_BASE}{slug}",
            "title": title,
            "status": status,
            "detail": detail,
            # The path only. A query string could carry a caller-supplied value.
            "instance": request.url.path,
            # Never overwrite a standard member with an extension.
            **{k: v for k, v in (extensions or {}).items() if k not in RESERVED},
        },
    )


def problem_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, Problem):  # pragma: no cover - registered for Problem
        exc = Problem(500, "The request could not be completed.")
    return render(
        request,
        exc.status,
        exc.slug,
        exc.title,
        exc.detail,
        extensions=exc.extensions,
    )


def http_exception_handler(request: Request, exc: Exception) -> Response:
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    slug, title = DEFAULTS.get(status, GENERIC)
    # Details raised in this service are fixed strings; anything else is dropped.
    raw: Any = getattr(exc, "detail", None)
    detail = raw if isinstance(raw, str) else title
    headers: Any = getattr(exc, "headers", None)
    return render(
        request,
        status,
        slug,
        title,
        detail,
        headers if isinstance(headers, dict) else None,
    )


def validation_handler(request: Request, exc: Exception) -> Response:
    # Field names and submitted values stay out of the body deliberately.
    slug, title = DEFAULTS[422]
    return render(request, 422, slug, title, "One or more fields are invalid.")


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, problem_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
