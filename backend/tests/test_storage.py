import multiprocessing
import os
import sqlite3
import unittest
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import chdir, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from pydantic import ValidationError

from app.models import Trip
from app.storage import DEFAULT_DATABASE, DuplicateTripError, SqliteTripStore, TripStorageError
from tests.fixtures import trip_payload


def add_in_process(path, identifier):
    store = SqliteTripStore(path)
    try:
        store.add_trip(Trip.model_validate(trip_payload(id=identifier)))
        return True
    except DuplicateTripError:
        return False


class SqliteTripStoreTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "trips.sqlite3"
        self.store = SqliteTripStore(self.path)
        self.store.initialize()
        self.trip = Trip.model_validate(trip_payload())

    def test_initializes_empty_database_and_nested_directories(self):
        nested = SqliteTripStore(self.path.parent / "nested" / "trips.sqlite3")
        nested.initialize()
        self.assertEqual(nested.list_trips(), [])
        self.assertTrue(nested.path.is_file())

    def test_initialization_preserves_existing_records(self):
        self.store.add_trip(self.trip)
        reopened = SqliteTripStore(self.path)
        reopened.initialize()
        self.assertEqual(reopened.list_trips(), [self.trip])

    def test_persists_records_after_reopening(self):
        second = Trip.model_validate(trip_payload(id="second", payment="cash"))
        self.store.add_trip(self.trip)
        SqliteTripStore(self.path).add_trip(second)
        self.assertEqual(SqliteTripStore(self.path).list_trips(), [self.trip, second])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_existing_id_is_not_overwritten(self):
        self.store.add_trip(self.trip)
        for candidate in (self.trip, Trip.model_validate(trip_payload(amount=2500))):
            with self.subTest(candidate=candidate):
                with self.assertRaises(DuplicateTripError) as caught:
                    self.store.add_trip(candidate)
                self.assertEqual(caught.exception.existing, self.trip)
                self.assertEqual(self.store.list_trips(), [self.trip])

    def test_revalidates_records_before_saving(self):
        invalid = self.trip.model_copy(update={"amount": -1})
        with self.assertRaises(ValidationError):
            self.store.add_trip(invalid)
        self.assertEqual(self.store.list_trips(), [])

    def test_maximum_sqlite_integer_round_trips_without_loss(self):
        trip = Trip.model_validate(trip_payload(amount=2**63 - 1, commission=2**63 - 1))
        self.store.add_trip(trip)
        self.assertEqual(self.store.list_trips(), [trip])

    def test_sql_metacharacters_in_ids_are_stored_as_data(self):
        trip = Trip.model_validate(trip_payload(id="x'); DROP TABLE trips; --"))
        self.store.add_trip(trip)
        self.assertEqual(self.store.list_trips(), [trip])

    def test_database_constraints_reject_invalid_direct_inserts(self):
        statement = """INSERT INTO trips (id, start, end, amount, payment, commission)
                       VALUES (:id, :start, :end, :amount, :payment, :commission)"""
        self.store.add_trip(self.trip)
        invalid = [
            trip_payload(),
            trip_payload(id=""),
            trip_payload(id="bad", amount=0),
            trip_payload(id="bad", amount=1.5, commission=0),
            trip_payload(id="bad", payment="transfer"),
            trip_payload(id="bad", commission=-1),
            trip_payload(id="bad", commission=2500),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with closing(sqlite3.connect(self.path)) as connection:
                    with self.assertRaises(sqlite3.IntegrityError), connection:
                        connection.execute(statement, payload)
        self.assertEqual(self.store.list_trips(), [self.trip])

    def test_invalid_stored_timestamp_is_reported(self):
        self.store.add_trip(self.trip)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE trips SET start = 'invalid'")
        with self.assertRaises(TripStorageError):
            self.store.list_trips()

    def test_corrupted_database_is_not_overwritten(self):
        bad_path = self.path.parent / "bad.sqlite3"
        bad_path.write_bytes(b"not a SQLite database")
        with self.assertRaises(TripStorageError):
            SqliteTripStore(bad_path).initialize()
        self.assertEqual(bad_path.read_bytes(), b"not a SQLite database")

    def test_directory_instead_of_database_is_an_error(self):
        with self.assertRaises(TripStorageError):
            SqliteTripStore(self.path.parent).initialize()

    def test_missing_database_is_not_silently_recreated(self):
        missing = self.path.parent / "missing.sqlite3"
        store = SqliteTripStore(missing)
        with self.assertRaises(TripStorageError):
            store.list_trips()
        with self.assertRaises(TripStorageError):
            store.add_trip(self.trip)
        self.assertFalse(missing.exists())

    def test_unknown_schema_version_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(TripStorageError, "schema version"):
            self.store.initialize()

    def test_lock_timeout_is_reported_and_retry_succeeds(self):
        impatient = SqliteTripStore(self.path, timeout=0.01)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(TripStorageError) as caught:
                impatient.add_trip(self.trip)
            self.assertIsInstance(caught.exception.__cause__, sqlite3.OperationalError)
            connection.rollback()
        impatient.add_trip(self.trip)
        self.assertEqual(self.store.list_trips(), [self.trip])

    def test_concurrent_additions_do_not_lose_records(self):
        workers = 12
        barrier = Barrier(workers, timeout=10)

        def add(index):
            barrier.wait()
            SqliteTripStore(self.path).add_trip(Trip.model_validate(trip_payload(id=f"trip-{index}")))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(add, range(workers)))
        self.assertEqual(
            {trip.id for trip in self.store.list_trips()},
            {f"trip-{index}" for index in range(workers)},
        )

    def test_separate_processes_share_duplicate_protection(self):
        with ProcessPoolExecutor(
            max_workers=4, mp_context=multiprocessing.get_context("spawn")
        ) as executor:
            results = list(executor.map(add_in_process, [str(self.path)] * 8, ["shared"] * 8))
            self.assertEqual(sum(results), 1)
            identifiers = [f"process-{index}" for index in range(4)]
            self.assertTrue(all(executor.map(add_in_process, [str(self.path)] * 4, identifiers)))
        self.assertEqual(
            {trip.id for trip in self.store.list_trips()}, {"shared", *identifiers}
        )

    def test_path_can_be_configured_through_environment(self):
        with patch.dict(os.environ, {"TRIPS_DB": str(self.path)}):
            self.assertEqual(SqliteTripStore.from_environment().path, self.path)

    def test_default_path_is_independent_of_working_directory(self):
        with patch.dict(os.environ):
            os.environ.pop("TRIPS_DB", None)
            os.environ.pop("TRIPS_FILE", None)
            with chdir(self.path.parent):
                self.assertEqual(SqliteTripStore.from_environment().path, DEFAULT_DATABASE)

    def test_rejects_empty_environment_path(self):
        for value in ("", " "):
            with self.subTest(value=value), patch.dict(os.environ, {"TRIPS_DB": value}):
                with self.assertRaises(ValueError):
                    SqliteTripStore.from_environment()

    def test_legacy_environment_requires_explicit_migration(self):
        with patch.dict(os.environ, {"TRIPS_FILE": "old-trips.json"}):
            os.environ.pop("TRIPS_DB", None)
            with self.assertRaisesRegex(ValueError, "import"):
                SqliteTripStore.from_environment()
