"""Strict DTOs of the handover protocol API (services/handover_protocol.py)."""

from __future__ import annotations

import math
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

ProtocolType = Literal["move_in", "move_out"]
Condition = Literal["good", "fair", "poor"]
Responsible = Literal["tenant", "landlord", "open"]
KeyType = Literal["house_door", "apartment_door", "mailbox", "cellar", "garage", "other"]


def _identifier(value: str) -> str:
    """Parts carry client-chosen UUIDs, so a photo can name a defect before the next save."""
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Ungültige Kennung (UUID erwartet).") from None
    return value


def _single(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("Bitte einen Text angeben.")
        return None
    value = value.strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError("Bitte einen einzeiligen Text ohne Steuerzeichen angeben.")
    if not value:
        if required:
            raise ValueError("Bitte einen Text angeben.")
        return None
    return value


def _multi(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Der Text enthält Steuerzeichen.")
    return value or None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoomInput(StrictModel):
    id: str
    name: str = Field(max_length=200)
    condition: Condition | None = None
    notes: str | None = Field(None, max_length=4000)

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        return _identifier(value)

    @field_validator("name")
    @classmethod
    def name_text(cls, value):
        return _single(value, required=True)

    @field_validator("notes")
    @classmethod
    def notes_text(cls, value):
        return _multi(value)


class DefectInput(StrictModel):
    id: str
    room_id: str | None = None
    description: str = Field(max_length=4000)
    responsible: Responsible = "open"
    remedy: str | None = Field(None, max_length=2000)
    due_date: date | None = None

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        return _identifier(value)

    @field_validator("room_id")
    @classmethod
    def room_reference(cls, value):
        return _identifier(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def description_text(cls, value):
        value = _multi(value)
        if not value:
            raise ValueError("Bitte den Mangel beschreiben.")
        return value

    @field_validator("remedy")
    @classmethod
    def remedy_text(cls, value):
        return _multi(value)


class KeyInput(StrictModel):
    id: str
    key_type: KeyType
    label: str | None = Field(None, max_length=200)
    handed_over: int = Field(ge=0, le=999)
    returned: int | None = Field(None, ge=0, le=999)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        return _identifier(value)

    @field_validator("label")
    @classmethod
    def label_text(cls, value):
        return _single(value)

    @field_validator("notes")
    @classmethod
    def notes_text(cls, value):
        return _multi(value)


class MeterReadingInput(StrictModel):
    id: str
    meter_id: str | None = None
    meter_type: str | None = Field(None, max_length=30)
    meter_number: str | None = Field(None, max_length=50)
    reading_value: float = Field(ge=0)
    unit: str | None = Field(None, max_length=10)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        return _identifier(value)

    @field_validator("reading_value")
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value):
            raise ValueError("Ungültiger Zählerstand.")
        return value

    @field_validator("meter_type", "meter_number", "unit")
    @classmethod
    def single_text(cls, value):
        return _single(value)

    @field_validator("notes")
    @classmethod
    def notes_text(cls, value):
        return _multi(value)

    @model_validator(mode="after")
    def free_reading_names_its_medium(self):
        if self.meter_id is None and not self.meter_type:
            raise ValueError("Ein Zählerstand ohne Zähler der Einheit braucht eine Zählerart.")
        return self


class ContentRequest(StrictModel):
    """The whole draft at once: header fields and every room, defect, key and meter reading."""

    base_revision: str = Field(min_length=1, max_length=200)
    protocol_date: date
    tenant_present: StrictBool = True
    landlord_present: StrictBool = True
    overall_condition: Condition | None = None
    notes: str | None = Field(None, max_length=8000)
    tenant_signature: str | None = Field(None, max_length=200)
    landlord_signature: str | None = Field(None, max_length=200)
    rooms: list[RoomInput] = Field(default_factory=list, max_length=100)
    defects: list[DefectInput] = Field(default_factory=list, max_length=500)
    keys: list[KeyInput] = Field(default_factory=list, max_length=50)
    meter_readings: list[MeterReadingInput] = Field(default_factory=list, max_length=50)

    @field_validator("tenant_signature", "landlord_signature")
    @classmethod
    def signer_name(cls, value):
        return _single(value)

    @field_validator("notes")
    @classmethod
    def notes_text(cls, value):
        return _multi(value)

    @model_validator(mode="after")
    def references(self):
        ids = [item.id for group in (self.rooms, self.defects, self.keys, self.meter_readings) for item in group]
        if len(ids) != len(set(ids)):
            raise ValueError("Jede Zeile braucht eine eigene Kennung.")
        rooms = {room.id for room in self.rooms}
        if any(defect.room_id is not None and defect.room_id not in rooms for defect in self.defects):
            raise ValueError("Ein Mangel verweist auf einen Raum, der nicht im Protokoll steht.")
        meters = [reading.meter_id for reading in self.meter_readings if reading.meter_id is not None]
        if len(meters) != len(set(meters)):
            raise ValueError("Jeder Zähler wird höchstens einmal abgelesen.")
        return self


class CreateRequest(StrictModel):
    contract_id: str = Field(min_length=1, max_length=100)
    protocol_type: ProtocolType
    protocol_date: date | None = None


class PhotoPatch(StrictModel):
    caption: str | None = Field(None, max_length=500)
    room_id: str | None = None
    defect_id: str | None = None
    meter_reading_id: str | None = None

    @field_validator("caption")
    @classmethod
    def caption_text(cls, value):
        return _single(value)


class FollowUpRequest(StrictModel):
    resolved_at: date | None = None
    resolution_note: str | None = Field(None, max_length=4000)

    @field_validator("resolution_note")
    @classmethod
    def note_text(cls, value):
        return _multi(value)


class FinalizeRequest(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_content: StrictBool
    confirmed_signatures: StrictBool

    @model_validator(mode="after")
    def confirmations(self):
        if not (self.confirmed_content and self.confirmed_signatures):
            raise ValueError("Inhalt und Unterschriften müssen ausdrücklich bestätigt werden.")
        return self
