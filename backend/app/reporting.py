"""Select trips and calculate totals using the driver's local calendar day."""

from collections.abc import Iterable
from datetime import date, timezone
from zoneinfo import ZoneInfo

from app.models import DailySummary, Trip

DAY_TIMEZONE = ZoneInfo("Asia/Almaty")


def trips_for_day(trips: Iterable[Trip], day: date) -> list[Trip]:
    selected = [
        trip for trip in trips if trip.start.astimezone(DAY_TIMEZONE).date() == day
    ]
    return sorted(
        selected, key=lambda trip: (trip.start.astimezone(timezone.utc), trip.id)
    )


def summary_for_day(trips: Iterable[Trip], day: date) -> DailySummary:
    selected = trips_for_day(trips, day)
    revenue = sum(trip.amount for trip in selected)
    commission = sum(trip.commission for trip in selected)
    return DailySummary(
        date=day,
        trip_count=len(selected),
        revenue=revenue,
        commission=commission,
        take_home=revenue - commission,
        cash_revenue=sum(trip.amount for trip in selected if trip.payment == "cash"),
        card_revenue=sum(trip.amount for trip in selected if trip.payment == "card"),
    )
