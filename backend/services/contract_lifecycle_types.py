"""Explicit, reviewed contract commands. No inferred economic data or notices."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReasonedData(StrictModel):
    reason: str = Field(min_length=1)

    @field_validator("reason", check_fields=False)
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Eine nachvollziehbare Begründung ist erforderlich.")
        return value.strip()


class RenewalData(ReasonedData):
    operation: Literal["renewal"]
    new_contract_number: str = Field(min_length=1)
    new_start_date: date
    new_end_date: date | None  # Deliberate null means an unlimited successor.

    @field_validator("new_contract_number")
    @classmethod
    def contract_number(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Die neue Vertragsnummer ist erforderlich.")
        return value.strip()

    @model_validator(mode="after")
    def ordered(self):
        if self.new_end_date is not None and self.new_end_date < self.new_start_date:
            raise ValueError("Das Enddatum liegt vor dem Mietbeginn.")
        return self


class TerminationData(ReasonedData):
    operation: Literal["termination"]
    termination_end_date: date


LifecycleData = Annotated[RenewalData | TerminationData, Field(discriminator="operation")]


class Command(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_contract_etag: str = Field(min_length=1)


class DraftCreate(Command):
    data: LifecycleData


class RevisionCommand(Command):
    expected_revision: UUID


class DraftEdit(RevisionCommand):
    data: LifecycleData


class Confirmation(RevisionCommand):
    reviewed_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Die geprüfte Änderung muss ausdrücklich bestätigt werden.")
        return value


class PageCursor(StrictModel):
    created_at: str
    id: str
