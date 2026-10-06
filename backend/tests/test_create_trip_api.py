import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.storage import SqliteTripStore
from tests.fixtures import trip_payload


class CreateTripApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "trips.sqlite3"
        self.enterContext(patch.dict(os.environ, {"TRIPS_DB": str(self.path)}))
        self.client = self.enterContext(TestClient(app))

    def summary(self):
        response = self.client.get("/api/summary", params={"date": "2026-10-01"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_creation_is_persisted_and_visible_in_daily_endpoints(self):
        payload = trip_payload()
        response = self.client.post("/api/trips", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json(), payload)
        persisted = SqliteTripStore(self.path).list_trips()
        self.assertEqual([trip.model_dump(mode="json") for trip in persisted], [payload])

        trips = self.client.get("/api/trips", params={"date": "2026-10-01"})
        self.assertEqual(trips.status_code, 200)
        self.assertEqual(trips.json(), [payload])
        self.assertEqual(
            self.summary(),
            {
                "date": "2026-10-01",
                "trip_count": 1,
                "revenue": 2400,
                "commission": 360,
                "take_home": 2040,
                "cash_revenue": 0,
                "card_revenue": 2400,
            },
        )

    def test_identical_retries_return_200_without_changing_records(self):
        payload = trip_payload()
        self.assertEqual(self.client.post("/api/trips", json=payload).status_code, 201)
        original = self.path.read_bytes()
        for _ in range(3):
            response = self.client.post("/api/trips", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), payload)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.summary()["trip_count"], 1)
        self.assertEqual(self.summary()["revenue"], 2400)

    def test_retry_after_storage_is_reopened_is_still_idempotent(self):
        payload = trip_payload()
        self.assertEqual(self.client.post("/api/trips", json=payload).status_code, 201)
        app.state.trip_store = SqliteTripStore(self.path)
        response = self.client.post("/api/trips", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), payload)
        self.assertEqual(len(SqliteTripStore(self.path).list_trips()), 1)

    def test_equivalent_timestamp_offsets_return_the_saved_representation(self):
        payload = trip_payload()
        self.assertEqual(self.client.post("/api/trips", json=payload).status_code, 201)
        response = self.client.post(
            "/api/trips",
            json=trip_payload(start="2026-10-01T03:10:00Z", end="2026-10-01T03:32:00Z"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), payload)
        self.assertEqual(self.summary()["trip_count"], 1)

    def test_conflicting_fields_return_409_and_preserve_the_original(self):
        self.assertEqual(self.client.post("/api/trips", json=trip_payload()).status_code, 201)
        original = self.path.read_bytes()
        for change in (
            {"amount": 2500},
            {"commission": 400},
            {"payment": "cash"},
            {"start": "2026-10-01T08:11:00+05:00"},
            {"end": "2026-10-01T08:33:00+05:00"},
        ):
            with self.subTest(change=change):
                response = self.client.post("/api/trips", json=trip_payload(**change))
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json(), {"detail": "Trip ID already exists with different data"}
                )
                self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.summary()["trip_count"], 1)

    def test_different_ids_are_distinct_trips(self):
        for identifier in ("first", "second"):
            response = self.client.post("/api/trips", json=trip_payload(id=identifier))
            self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.summary()["trip_count"], 2)

    def test_invalid_fields_return_descriptive_422_errors_without_changing_data(self):
        self.assertEqual(self.client.post("/api/trips", json=trip_payload()).status_code, 201)
        original = self.path.read_bytes()
        for change, message in (
            ({"amount": 0}, "greater than 0"),
            ({"amount": -1}, "greater than 0"),
            ({"amount": "2400"}, "integer"),
            ({"amount": True}, "integer"),
            ({"amount": 2**63}, "less than or equal to"),
            ({"commission": -1}, "greater than or equal to 0"),
            ({"commission": 2500}, "Commission must not exceed amount"),
            ({"end": "2026-10-01T08:10:00+05:00"}, "end must be later"),
            ({"end": "2026-10-01T08:09:00+05:00"}, "end must be later"),
            ({"start": "2026-10-01T08:10:00"}, "timezone"),
            ({"start": "not-a-date"}, "ISO 8601"),
            ({"payment": "transfer"}, "cash"),
            ({"id": ""}, "at least 1 character"),
            ({"unknown": "value"}, "Extra inputs"),
        ):
            with self.subTest(change=change):
                response = self.client.post("/api/trips", json=trip_payload(**change))
                self.assertEqual(response.status_code, 422, response.text)
                errors = response.json()["detail"]
                self.assertTrue(any(message in error["msg"] for error in errors), errors)
                self.assertEqual(errors[0]["loc"][0], "body")
                self.assertEqual(self.path.read_bytes(), original)

    def test_missing_fields_and_malformed_bodies_do_not_create_records(self):
        for field in trip_payload():
            payload = trip_payload()
            del payload[field]
            with self.subTest(field=field):
                response = self.client.post("/api/trips", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"][0]["loc"], ["body", field])
        for body in ("", '{"id":', "[]", "null"):
            with self.subTest(body=body):
                response = self.client.post(
                    "/api/trips", content=body, headers={"Content-Type": "application/json"}
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(SqliteTripStore(self.path).list_trips(), [])

    def test_concurrent_identical_submissions_create_one_trip(self):
        workers = 8
        barrier = Barrier(workers, timeout=10)

        def submit(_):
            barrier.wait()
            return self.client.post("/api/trips", json=trip_payload())

        with ThreadPoolExecutor(max_workers=workers) as executor:
            responses = list(executor.map(submit, range(workers)))
        self.assertEqual(sorted(response.status_code for response in responses), [200] * 7 + [201])
        for response in responses:
            self.assertEqual(response.json(), trip_payload())
        self.assertEqual(len(SqliteTripStore(self.path).list_trips()), 1)
        self.assertEqual(self.summary()["trip_count"], 1)

    def test_concurrent_conflicting_submissions_preserve_one_winner(self):
        workers = 8
        barrier = Barrier(workers, timeout=10)

        def submit(index):
            barrier.wait()
            return self.client.post("/api/trips", json=trip_payload(amount=2400 + index))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            responses = list(executor.map(submit, range(workers)))
        self.assertEqual(sorted(response.status_code for response in responses), [201] + [409] * 7)
        winner = next(response.json() for response in responses if response.status_code == 201)
        stored = SqliteTripStore(self.path).list_trips()
        self.assertEqual([trip.model_dump(mode="json") for trip in stored], [winner])
        self.assertEqual(self.summary()["revenue"], winner["amount"])

    def test_failed_save_returns_503_and_can_be_retried(self):
        self.assertEqual(
            self.client.post("/api/trips", json=trip_payload(id="original")).status_code,
            201,
        )
        original = SqliteTripStore(self.path).list_trips()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""
                CREATE TRIGGER fail_insert BEFORE INSERT ON trips
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)
        with self.assertLogs("app.main", level="ERROR"):
            response = self.client.post("/api/trips", json=trip_payload())
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json(), {"detail": "Trip storage is unavailable"})
        self.assertEqual(SqliteTripStore(self.path).list_trips(), original)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER fail_insert")
        response = self.client.post("/api/trips", json=trip_payload())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.summary()["trip_count"], 2)

    def test_openapi_describes_creation_replay_and_conflict(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/trips"]["post"]
        self.assertTrue(operation["requestBody"]["required"])
        self.assertTrue({"200", "201", "409", "422", "503"} <= operation["responses"].keys())
