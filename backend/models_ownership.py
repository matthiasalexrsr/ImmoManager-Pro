"""Who owns a property or a unit, and in which share (services/ownership.py)."""

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class OwnershipShareCreate(BaseModel):
    owner_contact_id: str            # a contact of type "owner"
    property_id: str
    unit_id: Optional[str] = None    # None: the whole property
    share_percent: float = Field(gt=0, le=100)
    valid_from: Optional[date] = None    # None: since always
    valid_to: Optional[date] = None      # None: open; both days included
    note: Optional[str] = None

    @field_validator("share_percent")
    @classmethod
    def four_decimals(cls, value: float) -> float:
        rounded = round(value, 4)
        if abs(rounded - value) > 1e-9:
            raise ValueError("Ein Anteil hat höchstens vier Nachkommastellen (z. B. 33,3333 %).")
        return rounded

    @model_validator(mode="after")
    def period_in_order(self) -> "OwnershipShareCreate":
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Der Anteil endet vor seinem Beginn.")
        return self


class OwnershipShare(OwnershipShareCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
