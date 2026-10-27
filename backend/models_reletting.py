"""API and store models of re-letting projects (Neuvermietung) and applicant attachments.

Read models mirror the tables of db/orm_models.py (RelettingProjectORM, LeadAttachmentORM)
field by field; the snapshot export/import relies on it.
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain.money import money

PROJECT_STATES = ("open", "closed", "cancelled")
PetPolicy = Literal["allowed", "on_request", "not_allowed"]
Certificate = Literal["consumption", "demand", "none"]
LeadState = Literal["new", "contacted", "viewing_scheduled", "offer_sent", "accepted", "rejected", "withdrawn"]
Employment = Literal["permanent", "temporary", "self_employed", "retired", "student", "other"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _amount(value: Optional[float]) -> Optional[float]:
    return None if value is None else float(money(value))


class RelettingOffer(BaseModel):
    """What the project offers and asks for: the figures of the exposé and the comparison."""

    model_config = ConfigDict(extra="forbid")

    available_from: Optional[date] = None
    target_rent: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    service_charge: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    heating_charge: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    deposit_amount: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    # the household's net income should be at least this many warm rents
    income_factor: float = Field(default=3.0, ge=1, le=10)
    max_persons: Optional[int] = Field(default=None, ge=1, le=30)
    pets: Optional[PetPolicy] = None
    headline: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)
    location_text: Optional[str] = Field(default=None, max_length=4000)
    features_text: Optional[str] = Field(default=None, max_length=4000)
    # the energy certificate's figures an advertisement has to state (§ 87 GEG)
    energy_certificate: Optional[Certificate] = None
    energy_value: Optional[float] = Field(default=None, ge=0, le=2000)
    energy_class: Optional[Literal["A+", "A", "B", "C", "D", "E", "F", "G", "H"]] = None
    energy_carrier: Optional[str] = Field(default=None, max_length=60)
    heating_type: Optional[str] = Field(default=None, max_length=60)
    year_built: Optional[int] = Field(default=None, ge=1000, le=2100)
    contact_name: Optional[str] = Field(default=None, max_length=200)
    contact_phone: Optional[str] = Field(default=None, max_length=60)
    contact_email: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=8000)

    @field_validator("target_rent", "service_charge", "heating_charge", "deposit_amount")
    @classmethod
    def _cents(cls, value: Optional[float]) -> Optional[float]:
        return _amount(value)

    @field_validator("contact_email")
    @classmethod
    def _email(cls, value: Optional[str]) -> Optional[str]:
        if value and "@" not in value:
            raise ValueError("Ungültige E-Mail-Adresse")
        return value or None


class RelettingStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: str = Field(min_length=1)


class RelettingUpdate(RelettingOffer):
    # the project's updated_at as the client read it: a newer change is not overwritten
    base_updated_at: Optional[datetime] = None


class RelettingProject(BaseModel):
    """A project row (all columns of reletting_projects)."""

    id: str = Field(..., min_length=1)
    unit_id: str
    status: Literal["open", "closed", "cancelled"] = "open"
    available_from: Optional[date] = None
    target_rent: Optional[float] = None
    service_charge: Optional[float] = None
    heating_charge: Optional[float] = None
    deposit_amount: Optional[float] = None
    income_factor: float = 3.0
    max_persons: Optional[int] = None
    pets: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    location_text: Optional[str] = None
    features_text: Optional[str] = None
    energy_certificate: Optional[str] = None
    energy_value: Optional[float] = None
    energy_class: Optional[str] = None
    energy_carrier: Optional[str] = None
    heating_type: Optional[str] = None
    year_built: Optional[int] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    listing_id: Optional[str] = None
    tenant_id: Optional[str] = None
    contract_id: Optional[str] = None
    deleted_applicants: int = 0
    closed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ApplicantInput(BaseModel):
    """An applicant as the project page records them."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=60)
    source: Optional[str] = Field(default=None, max_length=100)
    status: LeadState = "new"
    notes: Optional[str] = Field(default=None, max_length=8000)
    household_size: Optional[int] = Field(default=None, ge=1, le=20)
    net_income: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    employment: Optional[Employment] = None
    move_in_date: Optional[date] = None
    pets: Optional[str] = Field(default=None, max_length=200)
    doc_self_disclosure: bool = False
    doc_income: bool = False
    doc_credit_report: bool = False
    doc_landlord_reference: bool = False
    doc_id_checked: bool = False
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    base_updated_at: Optional[datetime] = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bitte den Namen angeben")
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, value: Optional[str]) -> Optional[str]:
        if value and "@" not in value:
            raise ValueError("Ungültige E-Mail-Adresse")
        return value or None

    @field_validator("net_income")
    @classmethod
    def _cents(cls, value: Optional[float]) -> Optional[float]:
        return _amount(value)


class ViewingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str = Field(min_length=1)
    scheduled_at: datetime
    status: Literal["scheduled", "completed", "cancelled", "no_show"] = "scheduled"
    agent: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=8000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str = Field(min_length=1)
    # an existing tenant record to use instead of creating one from the applicant
    tenant_id: Optional[str] = None
    # take the offered rent as the unit's rent, the default of the new contract
    apply_rent: bool = True


class CloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str = Field(min_length=1)


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_ids: list[str] = Field(min_length=1, max_length=500)
    confirmed: bool = False


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_ids: list[str] = Field(min_length=1, max_length=500)


class LeadAttachment(BaseModel):
    """A row of lead_attachments."""

    id: str = Field(..., min_length=1)
    lead_id: str
    kind: Literal["document", "photo"] = "document"
    title: str
    file_url: str
    size: Optional[int] = None
    created_at: datetime = Field(default_factory=_now)
