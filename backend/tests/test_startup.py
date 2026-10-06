import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.main import app
from app.storage import TripStorageError


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_configures_the_application_store(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trips.json"
            with patch.dict(os.environ, {"TRIPS_FILE": str(path)}):
                async with app.router.lifespan_context(app):
                    self.assertEqual(app.state.trip_store.path, path)
                    self.assertEqual(app.state.trip_store.list_trips(), [])

    async def test_startup_rejects_corrupted_existing_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trips.json"
            path.write_text("broken JSON", encoding="utf-8")
            with patch.dict(os.environ, {"TRIPS_FILE": str(path)}):
                with self.assertRaises(TripStorageError):
                    async with app.router.lifespan_context(app):
                        self.fail("Startup must not succeed with corrupted data")
            self.assertEqual(path.read_text(encoding="utf-8"), "broken JSON")
