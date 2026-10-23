"""Strict DTOs for Wohnungsgeberbestätigung review and publication."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


def _clean_single(value: str) -> str:
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("Bitte einen nicht leeren einzeiligen Text angeben.")
    return value


def _clean_multiline(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Bitte eine gültige, nicht leere Anschrift angeben.")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CertificateData(StrictModel):
    housing_provider_name: str
    housing_provider_address: str
    owner_same_as_provider: StrictBool
    owner_name: str | None = None
    move_in_date: date
    issue_date: date
    apartment_address: str
    apartment_label: str | None = None
    issuer_name: str
    issuer_role: Literal["housing_provider", "authorized_person"]
    residents: list[str] = Field(min_length=1)

    @field_validator("housing_provider_name", "owner_name", "apartment_label", "issuer_name")
    @classmethod
    def single_line(cls, value):
        return _clean_single(value) if value is not None else None

    @field_validator("housing_provider_address", "apartment_address")
    @classmethod
    def multiline(cls, value):
        return _clean_multiline(value)

    @field_validator("residents")
    @classmethod
    def resident_names(cls, values):
        return [_clean_single(value) for value in values]

    @model_validator(mode="after")
    def owner_binding(self):
        if self.owner_same_as_provider and self.owner_name is not None:
            raise ValueError("Bei identischem Eigentümer/Wohnungsgeber keinen abweichenden Eigentümernamen angeben.")
        if not self.owner_same_as_provider and self.owner_name is None:
            raise ValueError("Bei abweichendem Eigentümer ist dessen Name erforderlich.")
        return self


class SourceEtags(StrictModel):
    portfolio: str = Field(min_length=1)
    contract: str = Field(min_length=1)
    property: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    wizard_revision: str | None = None


class CorrectionReference(StrictModel):
    document_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)


class PreviewRequest(StrictModel):
    data: CertificateData
    source_etags: SourceEtags
    correction_of: CorrectionReference | None = None


class SaveRequest(PreviewRequest):
    idempotency_key: str = Field(min_length=1, max_length=100)
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_actual_move_in: StrictBool
    confirmed_authority: StrictBool
    confirmed_residents: StrictBool

    @model_validator(mode="after")
    def confirmations(self):
        if not (
            self.confirmed_actual_move_in
            and self.confirmed_authority
            and self.confirmed_residents
        ):
            raise ValueError("Tatsächlicher Einzug, Ausstellungsbefugnis und Personenliste müssen ausdrücklich bestätigt werden.")
        return self
