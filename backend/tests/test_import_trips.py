import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from app.import_trips import main
from app.models import Trip
from app.storage import DEFAULT_IMPORT_FILE, DuplicateTripError, SqliteTripStore, TripStorageError
from tests.fixtures import trip_payload


class ImportTripsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "trips.sqlite3"
        self.source = Path(directory) / "trips.json"
        self.store = SqliteTripStore(self.path)
        self.store.initialize()

    def write_source(self, records):
        self.source.write_text(json.dumps(records), encoding="utf-8")

    def test_sample_import_preserves_source_and_is_repeatable(self):
        original = DEFAULT_IMPORT_FILE.read_bytes()
        self.assertEqual(self.store.import_json(DEFAULT_IMPORT_FILE), 2)
        self.assertEqual(self.store.import_json(DEFAULT_IMPORT_FILE), 0)
        trips = self.store.list_trips()
        self.assertEqual([trip.id for trip in trips], ["t1", "t2"])
        self.assertEqual(sum(trip.amount for trip in trips), 3900)
        self.assertEqual(DEFAULT_IMPORT_FILE.read_bytes(), original)

    def test_import_merges_new_records_and_skips_identical_ones(self):
        self.store.add_trip(Trip.model_validate(trip_payload(id="existing")))
        self.write_source([trip_payload(id="existing"), trip_payload(id="new")])
        self.assertEqual(self.store.import_json(self.source), 1)
        self.assertEqual([trip.id for trip in self.store.list_trips()], ["existing", "new"])

    def test_conflict_rolls_back_entire_import(self):
        existing = Trip.model_validate(trip_payload(id="existing"))
        self.store.add_trip(existing)
        self.write_source([trip_payload(id="new"), trip_payload(id="existing", amount=2500)])
        original = self.source.read_bytes()
        with self.assertRaises(DuplicateTripError):
            self.store.import_json(self.source)
        self.assertEqual(self.store.list_trips(), [existing])
        self.assertEqual(self.source.read_bytes(), original)

    def test_database_failure_rolls_back_partial_import(self):
        self.write_source([trip_payload(id="first"), trip_payload(id="fail")])
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""
                CREATE TRIGGER fail_insert BEFORE INSERT ON trips WHEN NEW.id = 'fail'
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)
        with self.assertRaises(TripStorageError):
            self.store.import_json(self.source)
        self.assertEqual(self.store.list_trips(), [])

    def test_invalid_json_records_or_duplicate_source_ids_leave_database_unchanged(self):
        existing = Trip.model_validate(trip_payload(id="existing"))
        self.store.add_trip(existing)
        for contents in (
            "", "broken JSON", "{}", "null",
            json.dumps([trip_payload(id="new"), trip_payload(amount=0)]),
            json.dumps([trip_payload(), trip_payload()]),
        ):
            with self.subTest(contents=contents):
                self.source.write_text(contents, encoding="utf-8")
                with self.assertRaises(TripStorageError):
                    self.store.import_json(self.source)
                self.assertEqual(self.store.list_trips(), [existing])
                self.assertEqual(self.source.read_text(encoding="utf-8"), contents)

    def test_missing_source_is_reported(self):
        with self.assertRaises(TripStorageError):
            self.store.import_json(self.source)
        self.assertEqual(self.store.list_trips(), [])

    def test_command_reports_success_and_failure(self):
        self.write_source([trip_payload()])
        args = [str(self.source), "--database", str(self.path)]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 0)
        self.assertIn("Imported 1 trip(s)", output.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 0)
        self.assertIn("Imported 0 trip(s)", output.getvalue())
        self.write_source([trip_payload(amount=2500)])
        with redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(args), 1)
        self.assertIn("Import failed", error.getvalue())
        self.assertEqual(self.store.list_trips()[0].amount, 2400)
