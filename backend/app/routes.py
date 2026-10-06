"""HTTP endpoints for daily trips and totals."""

import re
from datetime import date as CalendarDate
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BeforeValidator

from app.models import DailySummary, Trip
from app.reporting import summary_for_day, trips_for_day
from app.storage import JsonTripStore

router = APIRouter(
    prefix="/api",
    tags=["trips"],
    responses={503: {"description": "Trip storage is unavailable"}},
)


def parse_day(value: object) -> CalendarDate:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Date must use YYYY-MM-DD format")
    return CalendarDate.fromisoformat(value)


DayQuery = Annotated[
    CalendarDate,
    BeforeValidator(parse_day),
    Query(description="Calendar day in Asia/Almaty, in YYYY-MM-DD format"),
]


def get_store(request: Request) -> JsonTripStore:
    return request.app.state.trip_store


StoreDependency = Annotated[JsonTripStore, Depends(get_store)]


@router.get("/trips")
def daily_trips(date: DayQuery, store: StoreDependency) -> list[Trip]:
    """Return trips that started on the selected day, earliest first."""
    return trips_for_day(store.list_trips(), date)


@router.get("/summary")
def daily_summary(date: DayQuery, store: StoreDependency) -> DailySummary:
    """Return totals for trips that started on the selected day."""
    return summary_for_day(store.list_trips(), date)
