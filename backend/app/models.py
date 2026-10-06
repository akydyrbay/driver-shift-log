"""Validated trip records shared by the API and file storage."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Trip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    id: Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]
    start: AwareDatetime
    end: AwareDatetime
    amount: Annotated[int, Field(strict=True, gt=0)]
    payment: Literal["cash", "card"]
    commission: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("start", "end", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime:
        # Reject epoch numbers (including numeric strings) accepted by Pydantic
        # by default: the external contract is ISO 8601 with a UTC offset.
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        raise ValueError("Timestamp must be an ISO 8601 datetime with a UTC offset")

    @model_validator(mode="after")
    def check_time_and_commission(self) -> Self:
        if self.end.astimezone(timezone.utc) <= self.start.astimezone(timezone.utc):
            raise ValueError("Trip end must be later than start")
        if self.commission > self.amount:
            raise ValueError("Commission must not exceed amount")
        return self
