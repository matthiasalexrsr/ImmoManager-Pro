"""Commands reference existing money; settlement edges never create cash."""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator


class SettlementCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    booking_id: str | None = None
    credit_id: str | None = None
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=12)
    effective_date: date
    reason: str = Field(min_length=3, max_length=1000)


class Settlement(BaseModel):
    id: str
    receivable_id: str
    booking_id: str | None = None
    credit_id: str | None = None
    reverses_id: str | None = None
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    effective_date: date
    reason: str
    actor_id: str | None = None
    request_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("amount")
    @classmethod
    def cents(cls, value):
        return value.quantize(Decimal("0.01"))

    @field_validator("created_at")
    @classmethod
    def utc(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def valid_source(self):
        if bool(self.booking_id) == bool(self.credit_id):
            raise ValueError("Genau eine vorhandene Zahlungsquelle ist erforderlich")
        if not self.amount or (self.amount < 0) != bool(self.reverses_id):
            raise ValueError("Rücknahmen müssen ihren ursprünglichen Ausgleich nennen")
        return self


class ReverseSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str
    idempotency_key: str = Field(min_length=8, max_length=120)
    effective_date: date
    reason: str = Field(min_length=3, max_length=1000)


class PlannedFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(min_length=1, max_length=120)
    day: date
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    label: str = Field(min_length=1, max_length=200)


class ReportDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2] = 2
    kind: Literal["cash-v2", "performance-period-v2", "liquidity-v2"]
    as_of: date
    months: Literal[3, 6, 12] = 12
    date_from: date | None = None
    date_to: date | None = None
    portfolio_id: str | None = None
    property_id: str | None = None
    unit_id: str | None = None
    rent_payment_day: int = Field(default=3, ge=1, le=31)
    rent_collection_percent: Decimal = Field(default=Decimal("100"), ge=0, le=100, decimal_places=2)
    arrears_collection_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    vacant_unit_ids: list[str] = Field(default_factory=list)
    planned_flows: list[PlannedFlow] = Field(default_factory=list)
    # one owner's part (services/ownership.py; "none": the part no owner is recorded for)
    owner_contact_id: str | None = None

    @model_serializer(mode="wrap")
    def _without_owner(self, handler):
        # a definition without an owner keeps the shape (and the hashes) it had before owners
        data = handler(self)
        if isinstance(data, dict) and data.get("owner_contact_id") is None:
            data.pop("owner_contact_id", None)
        return data


class SaveReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=120)
    expected_revision: str | None = None
    name: str = Field(min_length=1, max_length=160)
    definition: ReportDefinition


class SavedReport(BaseModel):
    id: str
    owner_id: str
    name: str
    definition: dict
    revision: str
    request_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at")
    @classmethod
    def utc(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
