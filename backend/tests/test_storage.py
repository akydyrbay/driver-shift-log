import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from pydantic import ValidationError

from app.models import Trip
from app.storage import (
    DEFAULT_TRIPS_FILE,
    DuplicateTripError,
    JsonTripStore,
    TripStorageError,
)
from tests.fixtures import trip_payload


class JsonTripStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "trips.json"
        self.store = JsonTripStore(self.path)
        self.trip = Trip.model_validate(trip_payload())

    def test_reads_original_example(self):
        trips = JsonTripStore(DEFAULT_TRIPS_FILE).list_trips()
        self.assertEqual([trip.id for trip in trips], ["t1", "t2"])
        self.assertEqual([trip.amount for trip in trips], [2400, 1500])
        self.assertEqual([trip.payment for trip in trips], ["card", "cash"])

    def test_missing_file_is_empty_and_read_has_no_side_effects(self):
        self.assertEqual(self.store.list_trips(), [])
        self.assertFalse(self.path.exists())

    def test_persists_records_after_reopening(self):
        second = Trip.model_validate(trip_payload(id="second", payment="cash"))
        self.store.add_trip(self.trip)
        JsonTripStore(self.path).add_trip(second)
        self.assertEqual(JsonTripStore(self.path).list_trips(), [self.trip, second])
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored[0], trip_payload())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_creates_parent_directory_on_first_write(self):
        nested = JsonTripStore(self.path.parent / "data" / "nested" / "trips.json")
        nested.add_trip(self.trip)
        self.assertEqual(JsonTripStore(nested.path).list_trips(), [self.trip])

    def test_returns_independent_lists(self):
        self.store.add_trip(self.trip)
        self.store.list_trips().clear()
        self.assertEqual(self.store.list_trips(), [self.trip])

    def test_refuses_to_read_or_overwrite_invalid_files(self):
        for contents in (
            "",
            "[{broken json",
            "{}",
            "null",
            json.dumps([trip_payload(amount=0)]),
            json.dumps([trip_payload(), trip_payload()]),
        ):
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                with self.assertRaises(TripStorageError):
                    self.store.list_trips()
                with self.assertRaises(TripStorageError):
                    self.store.add_trip(self.trip)
                self.assertEqual(self.path.read_text(encoding="utf-8"), contents)

    def test_directory_instead_of_file_is_an_error(self):
        self.path.mkdir()
        with self.assertRaises(TripStorageError):
            self.store.list_trips()

    def test_existing_id_is_not_overwritten(self):
        self.store.add_trip(self.trip)
        original = self.path.read_bytes()
        for candidate in (
            self.trip,
            Trip.model_validate(trip_payload(amount=2500)),
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(DuplicateTripError) as caught:
                    self.store.add_trip(candidate)
                self.assertEqual(caught.exception.existing, self.trip)
                self.assertEqual(self.path.read_bytes(), original)

    def test_revalidates_records_before_saving(self):
        invalid = self.trip.model_copy(update={"amount": -1})
        with self.assertRaises(ValidationError):
            self.store.add_trip(invalid)
        self.assertFalse(self.path.exists())

    def test_write_failures_preserve_original_file_and_clean_temporary_file(self):
        self.store.add_trip(self.trip)
        original = self.path.read_bytes()
        second = Trip.model_validate(trip_payload(id="second"))
        for operation in ("os.fsync", "os.replace"):
            with self.subTest(operation=operation):
                with patch(f"app.storage.{operation}", side_effect=OSError("disk error")):
                    with self.assertRaises(TripStorageError):
                        self.store.add_trip(second)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

        # A failed transaction must release the lock for the next attempt.
        self.store.add_trip(second)
        self.assertEqual(self.store.list_trips(), [self.trip, second])

    def test_concurrent_additions_across_instances_do_not_lose_records(self):
        workers = 12
        barrier = Barrier(workers, timeout=10)

        def add(index):
            store = JsonTripStore(self.path.parent / "." / self.path.name)
            trip = Trip.model_validate(trip_payload(id=f"trip-{index}"))
            barrier.wait()
            store.add_trip(trip)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(add, range(workers)))

        self.assertEqual(
            {trip.id for trip in self.store.list_trips()},
            {f"trip-{index}" for index in range(workers)},
        )

    def test_cleanup_failure_does_not_hide_the_write_error(self):
        self.store.add_trip(self.trip)
        original = self.path.read_bytes()
        write_error = OSError("disk error")
        with (
            patch("app.storage.os.replace", side_effect=write_error),
            patch("pathlib.Path.unlink", side_effect=PermissionError("cleanup error")),
            self.assertLogs("app.storage", level="WARNING"),
        ):
            with self.assertRaises(TripStorageError) as caught:
                self.store.add_trip(Trip.model_validate(trip_payload(id="second")))
        self.assertIs(caught.exception.__cause__, write_error)
        self.assertEqual(self.path.read_bytes(), original)

    def test_concurrent_same_id_has_only_one_successful_write(self):
        workers = 8
        barrier = Barrier(workers, timeout=10)

        def add(_):
            store = JsonTripStore(self.path)
            barrier.wait()
            try:
                store.add_trip(self.trip)
                return True
            except DuplicateTripError:
                return False

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(add, range(workers)))

        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.list_trips(), [self.trip])

    def test_path_can_be_configured_through_environment(self):
        with patch.dict(os.environ, {"TRIPS_FILE": str(self.path)}):
            store = JsonTripStore.from_environment()
        self.assertEqual(store.path, self.path)
        store.add_trip(self.trip)
        self.assertEqual(self.store.list_trips(), [self.trip])

    def test_default_path_is_independent_of_working_directory(self):
        with patch.dict(os.environ):
            os.environ.pop("TRIPS_FILE", None)
            with chdir(self.path.parent):
                self.assertEqual(JsonTripStore.from_environment().path, DEFAULT_TRIPS_FILE)

    def test_rejects_empty_environment_path(self):
        for value in ("", " \t"):
            with self.subTest(value=value), patch.dict(os.environ, {"TRIPS_FILE": value}):
                with self.assertRaises(ValueError):
                    JsonTripStore.from_environment()
