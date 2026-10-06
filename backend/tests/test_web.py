import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fixtures import trip_payload


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.web = self.directory / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<!doctype html><title>Flutter test</title>")
        (self.web / "main.dart.js").write_text("window.flutterTest = true;")
        (self.web / "canvaskit.wasm").write_bytes(b"\x00asm")
        self.database = self.directory / "data" / "trips.sqlite3"
        self.enterContext(patch.dict(os.environ, {
            "TRIPS_DB": str(self.database), "WEB_DIR": str(self.web),
        }))

    def client(self):
        return self.enterContext(TestClient(create_app()))

    def test_serves_index_and_assets_with_correct_types_and_revalidation(self):
        client = self.client()
        for url, content_type in [
            ("/", "text/html"), ("/index.html", "text/html"),
            ("/main.dart.js", "javascript"), ("/canvaskit.wasm", "application/wasm"),
        ]:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response.headers["content-type"])
                self.assertEqual(response.headers["cache-control"], "no-cache")
                cached = client.get(url, headers={"If-None-Match": response.headers["etag"]})
                self.assertEqual(cached.status_code, 304)
                self.assertEqual(cached.headers["cache-control"], "no-cache")
        self.assertEqual(client.head("/").status_code, 200)

    def test_api_health_and_docs_take_precedence_over_static_mount(self):
        client = self.client()
        response = client.post("/api/trips", json=trip_payload())
        self.assertEqual(response.status_code, 201)
        response = client.get("/api/trips?date=2026-10-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(client.get("/api/summary?date=2026-10-01").json()["revenue"], 2400)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        self.assertEqual(client.get("/docs").status_code, 200)
        self.assertIn("/api/trips", client.get("/openapi.json").json()["paths"])
        self.assertEqual(client.get("/api/trips").status_code, 422)

    def test_unknown_api_and_assets_are_not_replaced_with_html(self):
        (self.web / "api").mkdir()
        (self.web / "api" / "missing").write_text("Not an API response")
        client = self.client()
        for url in ["/api", "/api/missing", "/missing.js", "/missing-page"]:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertEqual(client.post("/main.dart.js").status_code, 405)

    def test_database_outside_web_directory_is_not_public(self):
        client = self.client()
        (self.web / "linked.sqlite3").symlink_to(self.database)
        for url in ["/data/trips.sqlite3", "/trips.sqlite3", "/linked.sqlite3",
                    "/%2e%2e/data/trips.sqlite3", "/app/storage.py"]:
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 404)

    def test_invalid_configured_web_directory_fails_early(self):
        empty = self.directory / "empty"
        empty.mkdir()
        for path in ["", " ", str(empty), str(self.directory / "missing")]:
            with self.subTest(path=path), patch.dict(os.environ, {"WEB_DIR": path}):
                with self.assertRaises(ValueError):
                    create_app()

    def test_api_only_development_does_not_require_a_flutter_build(self):
        del os.environ["WEB_DIR"]
        client = self.client()
        self.assertEqual(client.get("/").status_code, 404)
        self.assertEqual(client.get("/health").status_code, 200)
