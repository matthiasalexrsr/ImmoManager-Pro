"""Explicit, reviewed DATEV profiles. Versions are immutable; no tax inference."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class DatevRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1)
    category_id: str = Field(min_length=1)
    flow: Literal["income", "expense"]
    account_type: str = Field(min_length=1)
    bank_gl: str = Field(pattern=r"^[0-9]{1,8}$")
    counter_gl: str = Field(pattern=r"^[0-9]{1,9}$")
    counter_kind: Literal["general", "person"] = "general"
    no_vat_nonautomatic: StrictBool


class DatevProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    previous_version_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    adviser: int = Field(ge=1001, le=9999999, strict=True)
    client: int = Field(ge=1, le=99999, strict=True)
    gl_length: int = Field(ge=4, le=8, strict=True)
    chart: str = Field(pattern=r"^(?:[0-9]{2}|[0-9]{4})?$", default="")
    freeze: int = Field(ge=0, le=1, strict=True)
    currency: Literal["EUR"]
    calendar_year: StrictBool
    document_reference: Literal["empty", "internal_booking_id"]
    reviewed_by: str = Field(min_length=1, max_length=200)
    review_confirmed: StrictBool
    rules: list[DatevRule] = Field(min_length=1)

    @model_validator(mode="after")
    def checked_profile(self):
        if not self.review_confirmed or not self.calendar_year or not self.reviewed_by.strip() or not self.name.strip():
            raise ValueError("A reviewed profile and reviewer reference are required")
        keys = [(rule.account_id, rule.category_id, rule.flow) for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise ValueError("Each account/category/direction needs one unambiguous mapping")
        for rule in self.rules:
            if not rule.no_vat_nonautomatic:
                raise ValueError("This export requires reviewed accounts without automatic VAT")
            maximum = self.gl_length + (rule.counter_kind == "person")
            if (len(rule.bank_gl) > self.gl_length or len(rule.counter_gl) > maximum
                    or int(rule.bank_gl) == 0 or int(rule.counter_gl) == 0
                    or int(rule.bank_gl) == int(rule.counter_gl)):
                raise ValueError("Invalid account numbers for this G/L account length")
        return self


class DatevPreviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_version_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def datev_dates(self):
        # DATEV's published header regex is 20xx. Application history remains
        # unrestricted; this is a format constraint, not a data retention rule.
        if self.start_date > self.end_date:
            raise ValueError("Start date must precede end date")
        if not 2000 <= self.start_date.year <= self.end_date.year <= 2099:
            raise ValueError("DATEV EXTF 700 header dates must be within 2000–2099; use the general booking CSV export for other years")
        return self
