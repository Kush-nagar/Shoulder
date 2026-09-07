"""Verified Auth identity only; database permissions belong to Task 4."""

import json
import os
from functools import lru_cache
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class TokenVerifier:
    def __init__(self, issuer: str, publishable_key: str) -> None:
        self.issuer = issuer.rstrip("/")
        self.publishable_key = publishable_key
        self.jwks = jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    def verify(self, token: str) -> str:
        if len(token) > 16384:
            raise ValueError("Invalid token")
        header = jwt.get_unverified_header(token)
        # Header is only used to select an allowed public key, never identity.
        if header.get("alg") not in ("ES256", "RS256") or not header.get("kid"):
            raise ValueError("Invalid algorithm or key ID")
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
        except AttributeError:
            # PyJWT can raise this for a non-object member of the JWKS keys list.
            raise ValueError("Invalid signing key") from None
        if key.algorithm_name != header["alg"]:
            raise ValueError("Key algorithm mismatch")
        claims = jwt.decode(
            token,
            key.key,
            algorithms=[key.algorithm_name],
            issuer=self.issuer,
            audience="authenticated",
            options={"require": ["exp", "iss", "aud", "sub", "session_id"]},
        )
        if (
            not isinstance(claims["session_id"], str)
            or not UUID(claims["session_id"]).int
        ):
            raise ValueError("Invalid session ID")
        return str(UUID(claims["sub"]))

    def check_session(self, token: str, subject: str) -> None:
        # Auth v2.196.0 checks session_id existence here, unlike offline JWKS.
        # No privileged key or product database access is needed for revocation.
        request = Request(
            f"{self.issuer}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": self.publishable_key,
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                user = json.load(response)
            if not isinstance(user, dict) or user.get("id") != subject:
                raise ValueError("Invalid session")
        except HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise ValueError("Invalid session") from None
            raise HTTPException(503, "Authentication unavailable") from None
        except (URLError, TimeoutError, OSError):
            raise HTTPException(503, "Authentication unavailable") from None


@lru_cache
def get_verifier() -> TokenVerifier:
    issuer = os.environ.get("SUPABASE_AUTH_ISSUER")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not issuer or not key:
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    return TokenVerifier(issuer, key)


def authenticated_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> str:
    try:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ValueError("Missing bearer token")
        subject = verifier.verify(credentials.credentials)
        verifier.check_session(credentials.credentials, subject)
        return subject
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Authentication unavailable",
            headers={"Cache-Control": "private, no-store"},
        ) from None
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={
                "WWW-Authenticate": "Bearer",
                "Cache-Control": "private, no-store",
            },
        ) from None
