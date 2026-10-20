import unittest
from fastapi.testclient import TestClient
from main import app


class CorsTests(unittest.TestCase):
    def test_cloudflare_and_local_origins_receive_cors_headers(self):
        client = TestClient(app)
        for origin in ("https://traders-gita.pages.dev", "http://localhost:4200"):
            response = client.get("/api/status", headers={"Origin": origin})
            self.assertEqual(response.status_code, 200)
            self.assertIn("application/json", response.headers["content-type"])
            self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_write_method_preflights(self):
        client = TestClient(app)
        origin = "https://traders-gita.pages.dev"
        for method in ("POST", "PUT", "DELETE"):
            response = client.options("/api/watchlists", headers={
                "Origin": origin, "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
            self.assertIn(method, response.headers["access-control-allow-methods"])

    def test_unknown_origin_is_not_allowed(self):
        response = TestClient(app).options("/api/watchlists", headers={
            "Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)
