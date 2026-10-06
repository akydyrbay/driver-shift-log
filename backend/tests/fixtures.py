"""Small independent records for validation and persistence tests."""


def trip_payload(**overrides: object) -> dict[str, object]:
    return {
        "id": "test-trip",
        "start": "2026-10-01T08:10:00+05:00",
        "end": "2026-10-01T08:32:00+05:00",
        "amount": 2400,
        "payment": "card",
        "commission": 360,
        **overrides,
    }
