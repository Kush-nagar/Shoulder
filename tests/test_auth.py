import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch
from urllib.error import URLError
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient

from services.api.auth import TokenVerifier, get_verifier
from services.api.main import app


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.other_key = ec.generate_private_key(ec.SECP256R1())
        self.jwks: dict[str, Any] = {
            "keys": [
                {
                    **jwt.algorithms.ECAlgorithm.to_jwk(
                        self.key.public_key(), as_dict=True
                    ),
                    "kid": "test-key",
                    "alg": "ES256",
                    "use": "sig",
                }
            ]
        }
        fixture = self.jwks
        self.subject = str(uuid4())
        subject = self.subject
        self.active = {"value": True}
        active = self.active
        self.upstream: dict[str, Any] = {"jwks_status": 200, "user_status": 200}
        upstream = self.upstream

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                is_jwks = self.path.endswith("jwks.json")
                self.send_response(
                    upstream["jwks_status"]
                    if is_jwks
                    else upstream["user_status"]
                    if active["value"]
                    else 403
                )
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        fixture if self.path.endswith("jwks.json") else {"id": subject}
                    ).encode()
                )

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.issuer = f"http://127.0.0.1:{self.server.server_port}/auth/v1"
        self.verifier = TokenVerifier(self.issuer, "test-placeholder")
        self.app = app
        self.app.dependency_overrides[get_verifier] = lambda: self.verifier

        self.client = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test/v1/auth"
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()
        self.app.dependency_overrides.clear()

    def token(self, **overrides: Any) -> str:
        claims = {
            "sub": self.subject,
            "iss": self.issuer,
            "aud": "authenticated",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "session_id": str(uuid4()),
        }
        claims.update(overrides)
        return jwt.encode(
            claims, self.key, algorithm="ES256", headers={"kid": "test-key"}
        )

    async def test_valid_verified_subject_ignores_identity_headers(self) -> None:
        response = await self.client.get(
            "/identity",
            headers={
                "Authorization": f"Bearer {self.token()}",
                "X-User-Id": str(uuid4()),
                "X-Role": "coach",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user_id": self.subject})

    async def test_invalid_tokens_fail_closed(self) -> None:
        invalid_signature = jwt.encode(
            {
                "sub": self.subject,
                "iss": self.issuer,
                "aud": "authenticated",
                "exp": int(time.time()) + 300,
            },
            self.other_key,
            algorithm="ES256",
            headers={"kid": "test-key"},
        )
        for name, token in {
            "malformed": "not.a.token",
            "expired": self.token(exp=int(time.time()) - 1),
            "issuer": self.token(iss="https://other.invalid/auth/v1"),
            "audience": self.token(aud="other"),
            "subject": self.token(sub="not-a-uuid"),
            "numeric-session": self.token(session_id=123),
            "missing-session": self.token(session_id=None),
            "nil-session": self.token(
                session_id="00000000-0000-0000-0000-000000000000"
            ),
            "missing-exp": self.token(exp=None),
            "signature": invalid_signature,
            "algorithm": jwt.encode(
                {"sub": self.subject}, "test-only-" * 8, algorithm="HS256"
            ),
            "unsigned": jwt.encode({"sub": self.subject}, "", algorithm="none"),
        }.items():
            with self.subTest(name=name):
                response = await self.client.get(
                    "/identity", headers={"Authorization": f"Bearer {token}"}
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertNotIn(token, response.text)

    async def test_missing_or_invalid_scheme(self) -> None:
        for authorization in (None, "Basic abc", "Bearer", "Bearer a b"):
            response = await self.client.get(
                "/identity",
                headers={"Authorization": authorization} if authorization else {},
            )
            self.assertEqual(response.status_code, 401)

    async def test_revoked_session_fails_even_with_valid_signature(self) -> None:
        self.active["value"] = False
        response = await self.client.get(
            "/identity", headers={"Authorization": f"Bearer {self.token()}"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_jwks_rotation(self) -> None:
        self.verifier.verify(self.token())
        rotated = ec.generate_private_key(ec.SECP256R1())
        self.jwks["keys"].append(
            {
                **jwt.algorithms.ECAlgorithm.to_jwk(rotated.public_key(), as_dict=True),
                "kid": "rotated",
                "alg": "ES256",
                "use": "sig",
            }
        )
        token = jwt.encode(
            {
                "sub": self.subject,
                "session_id": str(uuid4()),
                "iss": self.issuer,
                "aud": "authenticated",
                "exp": int(time.time()) + 300,
            },
            rotated,
            algorithm="ES256",
            headers={"kid": "rotated"},
        )
        self.assertEqual(self.verifier.verify(token), self.subject)

    async def test_unknown_key_and_malformed_jwks_fail_closed(self) -> None:
        for keys in (
            [{**self.jwks["keys"][0], "kid": "unknown"}],
            [],
            [None],
            [{"kid": "test-key", "kty": "invalid"}],
        ):
            with self.subTest(keys=keys):
                self.jwks["keys"] = keys
                self.verifier = TokenVerifier(self.issuer, "test-placeholder")
                response = await self.client.get(
                    "/identity",
                    headers={"Authorization": f"Bearer {self.token()}"},
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Authentication required"})

    async def test_upstream_outages_fail_closed(self) -> None:
        for endpoint in ("jwks_status", "user_status"):
            with self.subTest(endpoint=endpoint):
                self.upstream.update(jwks_status=200, user_status=200)
                self.upstream[endpoint] = 503
                self.verifier = TokenVerifier(self.issuer, "test-placeholder")
                response = await self.client.get(
                    "/identity",
                    headers={"Authorization": f"Bearer {self.token()}"},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.headers.get("cache-control"), "private, no-store"
                )
                self.assertEqual(
                    response.json(), {"detail": "Authentication unavailable"}
                )

    async def test_network_and_configuration_errors_are_not_cached(self) -> None:
        for error in (URLError("fixture"), TimeoutError(), OSError()):
            with patch("services.api.auth.urlopen", side_effect=error):
                response = await self.client.get(
                    "/identity", headers={"Authorization": f"Bearer {self.token()}"}
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers.get("cache-control"), "private, no-store")
        self.app.dependency_overrides.clear()
        get_verifier.cache_clear()
        with patch.dict("os.environ", {}, clear=True):
            response = await self.client.get("/identity")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("cache-control"), "private, no-store")
