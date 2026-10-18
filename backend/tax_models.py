"""User-reviewed cash classifications, independent of tax forms or vendor XML."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class TaxClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    treatment: Literal["income", "expense", "excluded"]
    form_line: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    exclusion_kind: Literal["internal_transfer", "deposit", "loan_principal", "personal", "other"] | None = None

    @model_validator(mode="after")
    def classification(self):
        if not self.reason.strip():
            raise ValueError("Every classification needs a review reason")
        if self.treatment == "excluded":
            if self.form_line or self.exclusion_kind is None:
                raise ValueError("Excluded amounts need an exclusion reason/type and no tax form line")
        elif not self.form_line or not self.form_line.strip() or self.exclusion_kind:
            raise ValueError("Transferred income/expense needs an explicitly reviewed form line")
        return self


class AnnualTaxRule(TaxClassification):
    account_id: str = Field(min_length=1)
    category_id: str | None = Field(default=None, min_length=1)


class WisoObjectPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    property_id: str = Field(min_length=1)
    object_number: int = Field(ge=1, le=9999, strict=True)
    target_object_label: str = Field(min_length=1, max_length=200)


class WisoLinePreparation(BaseModel):
    """A reviewed manual destination label is never a vendor field identifier."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    treatment: Literal["income", "expense"]
    form_line: str = Field(min_length=1, max_length=200)
    target_label: str = Field(min_length=1, max_length=200)
    review_reason: str = Field(min_length=1, max_length=1000)


class WisoPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_product: Literal["WISO Steuer Windows"] = "WISO Steuer Windows"
    tax_year: Literal[2026] = 2026
    evidence_version: Literal["hv365-21.02.1530-observed-2026-v1"] = "hv365-21.02.1530-observed-2026-v1"
    objects: list[WisoObjectPreparation] = Field(default_factory=list)
    lines: list[WisoLinePreparation] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_preparation(self):
        for keys in ([item.property_id for item in self.objects], [item.object_number for item in self.objects],
                     [(item.treatment, item.form_line) for item in self.lines]):
            if len(keys) != len(set(keys)):
                raise ValueError("WISO preparation needs unique object IDs, object numbers and treatment/form-line mappings")
        return self


class AnnualTaxProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    tax_year: int = Field(ge=1, le=9998, strict=True)
    name: str = Field(min_length=1, max_length=200)
    currency: Literal["EUR"] = "EUR"
    reviewed_by: str = Field(min_length=1, max_length=200)
    review_confirmed: StrictBool
    rules: list[AnnualTaxRule] = Field(min_length=1)
    wiso_preparation: WisoPreparation | None = None
    previous_version_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reviewed(self):
        if not self.review_confirmed or not self.name.strip() or not self.reviewed_by.strip():
            raise ValueError("The classification profile must be explicitly reviewed")
        keys = [(rule.account_id, rule.category_id) for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("Each account/category pair needs exactly one classification")
        if self.wiso_preparation and self.tax_year != self.wiso_preparation.tax_year:
            raise ValueError("The observed WISO preparation contract is limited to tax year 2026")
        return self


class AnnualTaxPart(TaxClassification):
    # Signed integer cents avoid float conversion and JavaScript integer limits.
    amount_cents: str = Field(pattern=r"^-?[1-9][0-9]*$", max_length=15)
    property_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def property_assignment(self):
        if self.treatment != "excluded" and not self.property_id:
            raise ValueError("Transferred amounts must be assigned to an explicit property")
        return self


class AnnualTaxOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    parts: list[AnnualTaxPart] = Field(min_length=1)
    correction_of_booking_id: str | None = None
    transfer_counter_booking_id: str | None = None

    @model_validator(mode="after")
    def explained(self):
        if not self.reason.strip():
            raise ValueError("A changed/object-split classification needs an explicit reason")
        return self


class AnnualTaxPreflightCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_version_id: str = Field(min_length=1)
    # The user chooses the cash cutoff; future dates cannot be actual cash evidence.
    as_of: date
    overrides: list[AnnualTaxOverride] = Field(default_factory=list)
    pending_review_reason: str | None = Field(default=None, min_length=1, max_length=1000)
    empty_cash_review_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_overrides(self):
        ids = [item.booking_id for item in self.overrides]
        if len(ids) != len(set(ids)):
            raise ValueError("Each booking can have only one explicit allocation override")
        if any(value is not None and not value.strip() for value in (self.pending_review_reason, self.empty_cash_review_reason)):
            raise ValueError("Ignoring unconfirmed/missing cash entries needs an explicit review reason")
        return self


class AnnualTaxProjectionCreate(AnnualTaxPreflightCreate):
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=100)
    previous_projection_id: str | None = None
    revision_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def revision(self):
        if bool(self.previous_projection_id) != bool(self.revision_reason and self.revision_reason.strip()):
            raise ValueError("A revision needs its previous projection and an explicit explanation")
        return self
