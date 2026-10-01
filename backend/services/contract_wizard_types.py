"""Explicit user commands; no inferred payment, deposit receipt or signature."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from ..models import TenantCreate


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftData(StrictModel):
    property_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    tenant_id: str | None = Field(default=None, min_length=1)
    new_tenant: TenantCreate | None = None
    contract_number: str = Field(min_length=1)
    contract_status: Literal["draft", "active"] = "draft"
    start_date: date
    end_date: date | None = None
    notice_period: str | None = None
    deposit_amount: Decimal = Field(default=Decimal("0"), ge=0)
    index_rent: Literal["fixed", "index", "stepped"] = "fixed"
    service_charge_settlement: Literal["annual", "monthly"] = "annual"
    landlord_name: str = Field(min_length=1)
    landlord_address: str = Field(min_length=1)
    template_id: str | None = None
    terms: str = ""
    attachment_ids: list[str] = Field(default_factory=list)
    metadata_only_attachment_ids: list[str] = Field(default_factory=list)
    create_handover: StrictBool = False

    @field_validator("property_id", "unit_id", "contract_number", "landlord_name", "landlord_address")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Bitte einen gültigen, nicht leeren Wert angeben.")
        return value.strip()

    @field_validator("deposit_amount", mode="before")
    @classmethod
    def exact_cents(cls, value):
        if isinstance(value, bool):
            raise ValueError("Ein Centbetrag ist erforderlich.")
        try:
            result = Decimal(str(value))
            if not result.is_finite() or result < 0:
                raise ValueError
            _, digits, exponent = result.as_tuple()
            assert isinstance(exponent, int)
            extra = -2 - exponent
            if extra > 0 and any(digits[-extra:]):
                raise ValueError
            return result
        except (InvalidOperation, ValueError):
            raise ValueError("Kaution muss ein nicht negativer Centbetrag sein.") from None

    @model_validator(mode="after")
    def coherent(self):
        if (self.tenant_id is None) == (self.new_tenant is None):
            raise ValueError("Genau einen bestehenden oder neuen Mieter auswählen.")
        if self.new_tenant and (not self.new_tenant.full_name.strip() or self.new_tenant.archived):
            raise ValueError("Ein neuer aktiver Mieter mit vollständigem Namen ist erforderlich.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Das Enddatum liegt vor dem Mietbeginn.")
        if len(set(self.attachment_ids)) != len(self.attachment_ids) or any(not x.strip() for x in self.attachment_ids):
            raise ValueError("Anlagen müssen eindeutige Dokumentkennungen sein.")
        if (len(set(self.metadata_only_attachment_ids)) != len(self.metadata_only_attachment_ids)
                or not set(self.metadata_only_attachment_ids).issubset(self.attachment_ids)):
            raise ValueError("Reine Anlagenverweise müssen ausdrücklich aus den gewählten Anlagen stammen.")
        return self


class DraftCreate(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    data: DraftData


class RevisionCommand(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_revision: int = Field(ge=1, strict=True)


class DraftEdit(RevisionCommand):
    data: DraftData


class DraftCommit(RevisionCommand):
    reviewed_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool


class SignatureCreate(RevisionCommand):
    confirmed: StrictBool
    signed_date: date
    tenant_signer: str = Field(min_length=1)
    landlord_signer: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    note: str | None = None
    signed_document_id: str | None = None

    @field_validator("tenant_signer", "landlord_signer", "reference")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Eine nachvollziehbare Unterschriftsreferenz ist erforderlich.")
        return value.strip()


class TemplateCreate(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    portfolio_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    previous_id: str | None = None

    @field_validator("title", "body")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Vorlagentitel und Inhalt dürfen nicht leer sein.")
        return value
