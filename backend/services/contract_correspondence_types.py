"""Explicit local letters and management dates; no inferred legal deadline."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LetterData(StrictModel):
    letter_date: date
    deadline_date: date
    deadline_basis: str = Field(min_length=1)
    deadline_confirmed: StrictBool
    recipient_name: str = Field(min_length=1)
    recipient_address: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str | None = None
    template_id: str | None = None
    lifecycle_command_id: str | None = None

    @field_validator("deadline_basis", "recipient_name", "recipient_address", "subject", "body")
    @classmethod
    def plain_text(cls, value):
        if value is not None:
            value.encode("utf-8")
            if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
                raise ValueError("Nicht leeren, gültigen Text angeben.")
        return value

    @model_validator(mode="after")
    def deliberate(self):
        if not self.deadline_confirmed:
            raise ValueError("Den Verwaltungsstichtag und seine Grundlage ausdrücklich bestätigen.")
        if (self.body is None) == (self.template_id is None):
            raise ValueError("Genau einen eigenen Text oder eine vorhandene Vorlagenfassung wählen.")
        return self


class CreateLetter(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_contract_etag: str = Field(min_length=1)
    data: LetterData


class RevisionCommand(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_contract_etag: str = Field(min_length=1)
    expected_revision: str = Field(min_length=1)


class EditLetter(RevisionCommand):
    data: LetterData


class ApproveLetter(RevisionCommand):
    reviewed_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def deliberate(cls, value):
        if not value:
            raise ValueError("Genau die geprüfte Schreibenfassung ausdrücklich freigeben.")
        return value


class ManualEvent(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_revision: str = Field(min_length=1)
    expected_event_revision: int = Field(ge=0, strict=True)
    kind: Literal["dispatched", "received"]
    event_date: date
    channel: Literal["post", "handover", "other"]
    reference: str = Field(min_length=1)
    note: str = Field(min_length=1)
    dispatch_event_id: str | None = None
    confirmed: StrictBool

    @field_validator("reference", "note")
    @classmethod
    def plain_text(cls, value):
        return LetterData.plain_text(value)

    @model_validator(mode="after")
    def deliberate(self):
        if not self.confirmed:
            raise ValueError("Das tatsächlich beobachtete Ereignis ausdrücklich bestätigen.")
        if (self.kind == "received") != (self.dispatch_event_id is not None):
            raise ValueError("Empfang genau einem gespeicherten Versandereignis zuordnen.")
        return self
