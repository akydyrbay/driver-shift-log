import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures import trip_payload


class CorsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"TRIPS_DB": str(Path(directory) / "trips.sqlite3")}))
        self.client = self.enterContext(TestClient(app))

    def test_local_web_origins_can_read_and_post_json(self):
        for origin in ["http://localhost:8080", "http://127.0.0.1:8080"]:
            with self.subTest(origin=origin):
                response = self.client.options("/api/trips", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                response = self.client.post("/api/trips", json=trip_payload(), headers={"Origin": origin})
                self.assertIn(response.status_code, [200, 201])
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                response = self.client.get("/api/trips?date=2026-10-01", headers={"Origin": origin})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_other_origins_and_methods_are_not_allowed(self):
        for origin, method in [("https://untrusted.example", "POST"), ("http://localhost:8080", "DELETE")]:
            with self.subTest(origin=origin, method=method):
                response = self.client.options("/api/trips", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                })
                self.assertEqual(response.status_code, 400)
        response = self.client.get("/health", headers={"Origin": "https://untrusted.example"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_validation_errors_are_readable_by_local_web_client(self):
        response = self.client.post("/api/trips", json={}, headers={"Origin": "http://localhost:8080"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:8080")
