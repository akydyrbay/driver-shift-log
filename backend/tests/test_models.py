import unittest
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.models import Trip
from tests.fixtures import trip_payload


class TripTests(unittest.TestCase):
    def test_valid_trip_preserves_values_and_timezone(self):
        trip = Trip.model_validate(trip_payload())
        self.assertEqual(trip.amount, 2400)
        self.assertEqual(trip.commission, 360)
        self.assertEqual(trip.start.utcoffset(), timedelta(hours=5))
        self.assertEqual(trip.end - trip.start, timedelta(minutes=22))
        self.assertEqual(Trip.model_validate_json(trip.model_dump_json()), trip)

    def test_rejects_invalid_fields(self):
        cases = [
            {"id": ""},
            {"id": " \t"},
            {"id": 123},
            {"amount": 0},
            {"amount": -1},
            {"amount": 2.5},
            {"amount": 2400.0},
            {"amount": "2400"},
            {"amount": True},
            {"amount": 2**63},
            {"commission": -1},
            {"commission": 2401},
            {"commission": 1.5},
            {"commission": "360"},
            {"commission": False},
            {"commission": 2**63},
            {"payment": "transfer"},
            {"payment": "CASH"},
            {"extra": "not allowed"},
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                Trip.model_validate(trip_payload(**invalid))

    def test_every_field_is_required(self):
        for field in trip_payload():
            payload = trip_payload()
            del payload[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Trip.model_validate(payload)

    def test_rejects_invalid_or_timezone_naive_timestamps(self):
        for field in ("start", "end"):
            for value in (
                "not a date",
                "2026-02-30T08:10:00+05:00",
                "2026-10-01T08:10:00",
                "2026-10-01",
                "1790824200",
                1790824200,
                None,
                datetime(2026, 10, 1, 8, 10),
            ):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        Trip.model_validate(trip_payload(**{field: value}))

    def test_end_must_be_strictly_later_in_absolute_time(self):
        for end in (
            "2026-10-01T08:10:00+05:00",
            "2026-10-01T08:09:00+05:00",
            "2026-10-01T03:10:00Z",
            "2026-10-01T09:00:00+06:00",
        ):
            with self.subTest(end=end), self.assertRaises(ValidationError):
                Trip.model_validate(trip_payload(end=end))

        # An earlier clock reading can still be a later instant.
        trip = Trip.model_validate(trip_payload(end="2026-10-01T03:32:00Z"))
        self.assertEqual(trip.end - trip.start, timedelta(minutes=22))

    def test_accepts_both_payment_types_and_commission_boundaries(self):
        for payment in ("cash", "card"):
            for commission in (0, 2400):
                with self.subTest(payment=payment, commission=commission):
                    trip = Trip.model_validate(
                        trip_payload(payment=payment, commission=commission)
                    )
                    self.assertEqual(trip.payment, payment)
                    self.assertEqual(trip.commission, commission)

    def test_validated_trip_cannot_be_mutated(self):
        trip = Trip.model_validate(trip_payload())
        with self.assertRaises(ValidationError):
            trip.amount = -1
