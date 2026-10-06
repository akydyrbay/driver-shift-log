"""HTTP endpoints for daily trips and totals."""

import re
from datetime import date as CalendarDate
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BeforeValidator

from app.models import DailySummary, Trip
from app.reporting import summary_for_day, trips_for_day
from app.storage import DuplicateTripError, SqliteTripStore

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


def get_store(request: Request) -> SqliteTripStore:
    return request.app.state.trip_store


StoreDependency = Annotated[SqliteTripStore, Depends(get_store)]


@router.post(
    "/trips",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": Trip, "description": "Identical trip already exists"},
        409: {"description": "Trip ID already exists with different data"},
    },
)
def create_trip(trip: Trip, response: Response, store: StoreDependency) -> Trip:
    """Create a trip, or return the saved record for an identical retry."""
    try:
        return store.add_trip(trip)
    except DuplicateTripError as exc:
        if exc.existing != trip:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Trip ID already exists with different data",
            ) from exc
        response.status_code = status.HTTP_200_OK
        return exc.existing


@router.get("/trips")
def daily_trips(date: DayQuery, store: StoreDependency) -> list[Trip]:
    """Return trips that started on the selected day, earliest first."""
    return trips_for_day(store.list_trips(), date)


@router.get("/summary")
def daily_summary(date: DayQuery, store: StoreDependency) -> DailySummary:
    """Return totals for trips that started on the selected day."""
    return summary_for_day(store.list_trips(), date)
