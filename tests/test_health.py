import unittest

from httpx import ASGITransport, AsyncClient

from services.api.main import app


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_public_and_content_free(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})
            self.assertEqual((await client.get("/players")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
