"""Hard-delete an unassociated Supabase Auth account from the worker only."""

import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


class AccountDeletionError(Exception):
    """Auth deletion failed without retaining provider response content."""


def delete_auth_user(user_id: UUID) -> None:
    """Delete one exact Auth user; absence is idempotent success."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not base_url or not secret_key:
        raise AccountDeletionError("auth account deletion is not configured")
    request = Request(
        f"{base_url}/auth/v1/admin/users/{user_id}",
        method="DELETE",
        headers={
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed admin URL
            if response.status not in (200, 204):
                raise AccountDeletionError("auth account deletion failed")
    except HTTPError as error:
        if error.code != 404:
            raise AccountDeletionError("auth account deletion failed") from None
    except (URLError, TimeoutError):
        raise AccountDeletionError("auth account deletion failed") from None
