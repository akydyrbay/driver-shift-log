import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Trip
from app.storage import DEFAULT_TRIPS_FILE
from tests.fixtures import trip_payload


class DailyApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "trips.json"
        self.enterContext(patch.dict(os.environ, {"TRIPS_FILE": str(self.path)}))
        self.client = self.enterContext(TestClient(app))
        self.store = app.state.trip_store

    def add_trip(self, **changes):
        self.store.add_trip(Trip.model_validate(trip_payload(**changes)))

    def get_json(self, endpoint, day):
        response = self.client.get(endpoint, params={"date": day})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_empty_day(self, day):
        self.assertEqual(self.get_json("/api/trips", day), [])
        self.assertEqual(
            self.get_json("/api/summary", day),
            {
                "date": day,
                "trip_count": 0,
                "revenue": 0,
                "commission": 0,
                "take_home": 0,
                "cash_revenue": 0,
                "card_revenue": 0,
            },
        )

    def test_original_sample_list_and_summary(self):
        sample = json.loads(DEFAULT_TRIPS_FILE.read_text(encoding="utf-8"))
        for record in sample:
            self.store.add_trip(Trip.model_validate(record))

        self.assertEqual(self.get_json("/api/trips", "2026-10-01"), sample)
        self.assertEqual(
            self.get_json("/api/summary", "2026-10-01"),
            {
                "date": "2026-10-01",
                "trip_count": 2,
                "revenue": 3900,
                "commission": 585,
                "take_home": 3315,
                "cash_revenue": 1500,
                "card_revenue": 2400,
            },
        )

    def test_empty_store_returns_zero_totals_without_creating_file(self):
        self.assert_empty_day("2026-10-01")
        self.assertFalse(self.path.exists())

    def test_other_days_are_excluded(self):
        self.add_trip()
        self.assert_empty_day("2026-09-30")
        self.assert_empty_day("2026-10-02")

    def test_day_boundaries_use_start_in_almaty_timezone(self):
        self.add_trip(
            id="previous-day",
            start="2026-09-30T18:59:59Z",
            end="2026-09-30T19:01:00Z",
        )
        self.add_trip(
            id="day-start",
            start="2026-09-30T19:00:00Z",
            end="2026-09-30T19:10:00Z",
            amount=100,
            commission=0,
            payment="cash",
        )
        self.add_trip(
            id="day-end",
            start="2026-10-01T23:59:59+05:00",
            end="2026-10-02T00:10:00+05:00",
            amount=200,
            commission=20,
        )
        self.add_trip(
            id="next-day",
            start="2026-10-01T19:00:00Z",
            end="2026-10-01T19:10:00Z",
        )

        trips = self.get_json("/api/trips", "2026-10-01")
        self.assertEqual([trip["id"] for trip in trips], ["day-start", "day-end"])
        self.assertEqual(
            self.get_json("/api/summary", "2026-10-01"),
            {
                "date": "2026-10-01",
                "trip_count": 2,
                "revenue": 300,
                "commission": 20,
                "take_home": 280,
                "cash_revenue": 100,
                "card_revenue": 200,
            },
        )
        previous = self.get_json("/api/trips", "2026-09-30")
        following = self.get_json("/api/trips", "2026-10-02")
        self.assertEqual([trip["id"] for trip in previous], ["previous-day"])
        self.assertEqual([trip["id"] for trip in following], ["next-day"])

    def test_list_is_sorted_by_instant_then_id_without_rewriting_file(self):
        self.add_trip(id="later")
        self.add_trip(
            id="earlier-b",
            start="2026-10-01T04:00:00+01:00",
            end="2026-10-01T04:05:00+01:00",
        )
        self.add_trip(
            id="earlier-a",
            start="2026-10-01T08:00:00+05:00",
            end="2026-10-01T08:05:00+05:00",
        )
        original = self.path.read_bytes()
        trips = self.get_json("/api/trips", "2026-10-01")
        self.get_json("/api/summary", "2026-10-01")
        self.assertEqual([trip["id"] for trip in trips], ["earlier-a", "earlier-b", "later"])
        self.assertEqual(self.path.read_bytes(), original)

    def test_single_payment_and_commission_boundaries(self):
        for day, payment, commission in (
            ("2026-10-01", "cash", 0),
            ("2026-10-02", "card", 100),
        ):
            with self.subTest(payment=payment):
                self.add_trip(
                    id=payment,
                    start=f"{day}T08:00:00+05:00",
                    end=f"{day}T08:30:00+05:00",
                    amount=100,
                    commission=commission,
                    payment=payment,
                )
                summary = self.get_json("/api/summary", day)
                self.assertEqual(summary["trip_count"], 1)
                self.assertEqual(summary["revenue"], 100)
                self.assertEqual(summary["commission"], commission)
                self.assertEqual(summary["take_home"], 100 - commission)
                self.assertEqual(summary["cash_revenue"], 100 if payment == "cash" else 0)
                self.assertEqual(summary["card_revenue"], 100 if payment == "card" else 0)

    def test_missing_or_invalid_date_returns_422_for_both_endpoints(self):
        invalid_dates = (
            "", "not-a-date", "2026-02-30", "2026-02-29", "2026-13-01",
            "2026-1-01", "20261001", "01-10-2026", "1790812800",
            "2026-10-01T00:00:00Z", "2026-10-01 ",
        )
        for endpoint in ("/api/trips", "/api/summary"):
            self.assertEqual(self.client.get(endpoint).status_code, 422)
            for value in invalid_dates:
                with self.subTest(endpoint=endpoint, date=value):
                    response = self.client.get(endpoint, params={"date": value})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.json()["detail"][0]["loc"], ["query", "date"])

    def test_valid_leap_day_is_accepted(self):
        self.add_trip(
            start="2028-02-29T08:00:00+05:00",
            end="2028-02-29T08:30:00+05:00",
        )
        self.assertEqual(len(self.get_json("/api/trips", "2028-02-29")), 1)
        self.assertEqual(self.get_json("/api/summary", "2028-02-29")["trip_count"], 1)

    def test_requests_see_newly_saved_records(self):
        self.assert_empty_day("2026-10-01")
        self.add_trip()
        self.assertEqual(len(self.get_json("/api/trips", "2026-10-01")), 1)
        self.assertEqual(self.get_json("/api/summary", "2026-10-01")["revenue"], 2400)

    def test_corrupted_storage_returns_503_instead_of_empty_results(self):
        self.path.write_text("broken JSON", encoding="utf-8")
        for endpoint in ("/api/trips", "/api/summary"):
            with self.subTest(endpoint=endpoint), self.assertLogs("app.main", level="ERROR"):
                response = self.client.get(endpoint, params={"date": "2026-10-01"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Trip storage is unavailable"})

    def test_health_endpoint_still_works(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
