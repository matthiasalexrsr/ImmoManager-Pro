"""Who owns a property or a unit, and in which share (services/ownership.py)."""

from datetime import date, datetime, timezone
from typing import Literal, Optional

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


TRANSFER_KINDS = {"purchase": "Kauf", "gift": "Schenkung", "inheritance": "Erbschaft", "division": "Teilung",
                  "sale_external": "Verkauf an Dritte", "other": "Sonstiger Wechsel"}
TransferKind = Literal["purchase", "gift", "inheritance", "division", "sale_external", "other"]


class TransferReceiver(BaseModel):
    owner_contact_id: str
    percent: float = Field(gt=0, le=100)   # of the part that changes hands


class OwnershipTransferCreate(BaseModel):
    """A change of owners on a day: the giver passes a part of their share to the receivers."""
    property_id: str
    unit_id: Optional[str] = None          # None: the property's own shares (scope "object") or everything
    scope: Literal["object", "all"] = "object"   # "all": every share the giver holds in the property and its units
    effective_date: date                   # the first day of the new owners
    from_owner_contact_id: str
    fraction_percent: float = Field(default=100, gt=0, le=100)   # of the giver's share that changes hands
    kind: TransferKind = "purchase"
    receivers: list[TransferReceiver] = Field(default_factory=list)
    note: Optional[str] = None

    @model_validator(mode="after")
    def receivers_add_up(self) -> "OwnershipTransferCreate":
        ids = [r.owner_contact_id for r in self.receivers]
        if len(set(ids)) != len(ids):
            raise ValueError("Jeder Empfänger darf nur einmal vorkommen.")
        if self.from_owner_contact_id in ids:
            raise ValueError("Der Abgebende kann nicht zugleich Empfänger sein.")
        if self.kind == "sale_external":
            if self.receivers:
                raise ValueError("Bei einem Verkauf an Dritte gibt es keine erfassten Empfänger.")
        elif not self.receivers:
            raise ValueError("Bitte mindestens einen Empfänger angeben.")
        elif abs(sum(r.percent for r in self.receivers) - 100) > 1e-6:
            raise ValueError("Die Anteile der Empfänger ergeben zusammen 100 % des übertragenen Teils.")
        if self.scope == "all" and self.unit_id:
            raise ValueError("„Alle Anteile am Objekt“ gilt für das ganze Objekt; keine Einheit wählen.")
        return self


class OwnershipTransfer(BaseModel):
    """A recorded change of owners, as the journal keeps it (receivers as plain records)."""
    id: str = Field(..., min_length=1)
    property_id: str
    unit_id: Optional[str] = None
    scope: str = "object"
    effective_date: date
    from_owner_contact_id: str
    fraction_percent: float
    kind: str
    receivers: list[dict] = Field(default_factory=list)
    note: Optional[str] = None
    actor_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
