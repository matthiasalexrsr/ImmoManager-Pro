"""Positive packet budgets are not a cap on the amount of work in a job."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Family = Literal["overdue_rent_charge", "overdue_receivable", "correspondence", "recurring_task", "recurring_calendar"]
BASE_FAMILIES: tuple[Family, ...] = ("overdue_rent_charge", "overdue_receivable", "correspondence")
FAMILIES: tuple[Family, ...] = (*BASE_FAMILIES, "recurring_task", "recurring_calendar")


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1)
    as_of: date
    lookback_days: int = Field(default=366, ge=1, strict=True)
    days_ahead: int = Field(default=90, ge=1, strict=True)
    families: tuple[Family, ...] = BASE_FAMILIES
    full_catch_up: bool = Field(default=False, strict=True)

    @field_validator("families")
    @classmethod
    def unique_families(cls, values):
        if not values or len(values) != len(set(values)):
            raise ValueError("Select at least one distinct job family")
        return tuple(sorted(values))


class JobContinue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_items: int = Field(default=64, ge=1, strict=True)


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1)
    expected_revision: int = Field(ge=1, strict=True)


@dataclass(frozen=True)
class PacketPolicy:
    page_size: int = 64
    lease_seconds: float = 20.0
    packet_seconds: float = 2.0

    def __post_init__(self):
        if type(self.page_size) is not int or self.page_size <= 0:
            raise ValueError("page_size must be a positive integer")
        if (isinstance(self.lease_seconds, bool) or isinstance(self.packet_seconds, bool)
                or not isfinite(self.lease_seconds) or not isfinite(self.packet_seconds)
                or self.packet_seconds <= 0 or self.lease_seconds <= self.packet_seconds):
            raise ValueError("Use a positive packet time and a longer finite lease")
