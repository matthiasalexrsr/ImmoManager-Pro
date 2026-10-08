"""API and store models of property service contracts (Objektverträge).

Read models mirror the tables of db/service_contract_models.py field by field (the
snapshot export/import relies on it). Amounts are cents (domain.money); unit prices
are exact decimal strings with up to six places.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

from .domain.money import money
from .domain.service_contract_terms import Terms
from .models import InvoiceCreate

CONTRACT_TYPES = (
    "electricity", "gas", "district_heating", "water", "waste", "cleaning", "caretaker", "elevator", "garden",
    "winter_service", "chimney_sweep", "heating_maintenance", "cable_tv", "other",
)
ADVANCE_INTERVALS = ("monthly", "bimonthly", "quarterly", "semiannual", "annual")
RenewalMode = Literal["none", "fixed", "indefinite"]
NoticeUnit = Literal["day", "week", "month"]
NoticeTo = Literal["term_end", "any_day", "month_end", "quarter_end", "year_end"]
AdvanceInterval = Literal["monthly", "bimonthly", "quarterly", "semiannual", "annual"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cents(value: Optional[float], *, label: str, allow_negative: bool = False) -> Optional[float]:
    if value is None:
        return None
    rounded = money(value)
    if rounded < 0 and not allow_negative:
        raise ValueError(f"{label} darf nicht negativ sein")
    if abs(rounded) >= Decimal("10000000000"):
        raise ValueError(f"{label} ist nicht plausibel")
    return float(rounded)


def _exact_price(value) -> Decimal:
    try:
        price = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Preis ist keine Zahl") from exc
    if not price.is_finite() or price < 0:
        raise ValueError("Preis darf nicht negativ sein")
    if price >= Decimal("10000000"):
        raise ValueError("Preis ist nicht plausibel")
    exponent = price.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -6:
        raise ValueError("Preis hat höchstens sechs Nachkommastellen")
    return price.normalize() if price != 0 else Decimal("0")


# stored and sent as text: "0.3247" stays 0.3247 on every database and in JSON
ExactPrice = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class UnitPrice(BaseModel):
    label: str = Field(min_length=1, max_length=80)        # Arbeitspreis, HT, NT, Leerung …
    unit: str = Field(min_length=1, max_length=20)         # kWh, m³, Stück, h …
    price: ExactPrice

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, value):
        return _exact_price(value)


class ServiceContractCreate(BaseModel):
    contract_type: str
    title: str = Field(min_length=1, max_length=200)
    provider_contact_id: str = Field(min_length=1)
    contract_number: Optional[str] = Field(default=None, max_length=100)
    customer_number: Optional[str] = Field(default=None, max_length=100)
    start_date: date
    end_date: Optional[date] = None
    minimum_term_months: Optional[int] = Field(default=None, ge=1, le=600)
    renewal_mode: RenewalMode = "none"
    renewal_months: Optional[int] = Field(default=None, ge=1, le=120)
    notice_period_value: Optional[int] = Field(default=None, ge=0, le=3650)
    notice_period_unit: Optional[NoticeUnit] = None
    notice_to: NoticeTo = "term_end"
    reminder_days: int = Field(default=30, ge=0, le=365)
    cancelled_on: Optional[date] = None
    cancellation_effective: Optional[date] = None
    recoverable: bool = False
    recoverable_percent: float = Field(default=100.0, ge=0, le=100)
    cost_category: Optional[str] = Field(default=None, max_length=100)
    payment_method: Optional[str] = Field(default=None, max_length=30)
    notes: Optional[str] = None

    @field_validator("contract_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in CONTRACT_TYPES:
            raise ValueError(f"Unbekannte Vertragsart: {value}")
        return value

    @model_validator(mode="after")
    def validate_terms(self):
        if self.renewal_mode != "indefinite":
            self.notice_to = "term_end"          # fixed terms end at a term end; the anchor does not apply
        if self.renewal_mode != "fixed":
            self.renewal_months = None
        problems = Terms.of(self).problems()
        if problems:
            raise ValueError("; ".join(problems))
        return self


class ServiceContract(ServiceContractCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class LocationInput(BaseModel):
    property_id: str = Field(min_length=1)
    unit_id: Optional[str] = None
    meter_id: Optional[str] = None
    supply_point: Optional[str] = Field(default=None, max_length=60)
    share_weight: float = Field(default=1.0, gt=0, le=1_000_000)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Der Standort endet vor seinem Beginn")
        return self


class ServiceContractLocationCreate(LocationInput):
    service_contract_id: str = Field(min_length=1)


class ServiceContractLocation(ServiceContractLocationCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TariffInput(BaseModel):
    valid_from: date
    label: Optional[str] = Field(default=None, max_length=120)
    base_price: Optional[float] = None
    base_price_period: Literal["month", "year"] = "month"
    unit_prices: list[UnitPrice] = Field(default_factory=list, max_length=12)
    price_guarantee_until: Optional[date] = None
    advance_amount: Optional[float] = None
    advance_interval: Optional[AdvanceInterval] = None
    advance_day: int = Field(default=1, ge=1, le=31)
    prices_include_vat: bool = True
    vat_rate: float = Field(default=19.0, ge=0, le=100)
    notes: Optional[str] = None

    @field_validator("base_price")
    @classmethod
    def validate_base_price(cls, value: Optional[float]) -> Optional[float]:
        return _cents(value, label="Grundpreis")

    @field_validator("advance_amount")
    @classmethod
    def validate_advance(cls, value: Optional[float]) -> Optional[float]:
        return _cents(value, label="Abschlag")

    @field_validator("unit_prices", mode="before")
    @classmethod
    def validate_unit_prices(cls, value):
        return [] if value is None else value

    @model_validator(mode="after")
    def validate_advance_plan(self):
        if self.advance_amount and not self.advance_interval:
            raise ValueError("Zum Abschlag fehlt der Zahlungsrhythmus")
        if self.advance_interval and not self.advance_amount:
            raise ValueError("Zum Zahlungsrhythmus fehlt der Abschlag")
        if self.price_guarantee_until and self.price_guarantee_until < self.valid_from:
            raise ValueError("Die Preisgarantie endet vor dem Beginn des Tarifs")
        return self


class ServiceContractTariffCreate(TariffInput):
    service_contract_id: str = Field(min_length=1)


class ServiceContractTariff(ServiceContractTariffCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ServiceContractInvoiceFields(BaseModel):
    kind: Literal["regular", "settlement"] = "regular"
    period_start: date
    period_end: date
    advances_credited: float = 0.0
    consumption: Optional[float] = Field(default=None, ge=0)
    consumption_unit: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = None

    @field_validator("advances_credited")
    @classmethod
    def validate_credited(cls, value: float) -> float:
        rounded = _cents(value, label="Angerechnete Abschläge")
        return 0.0 if rounded is None else rounded

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_end < self.period_start:
            raise ValueError("Der Leistungszeitraum endet vor seinem Beginn")
        if self.kind == "regular" and self.advances_credited:
            raise ValueError("Abschläge werden nur in einer Abrechnung angerechnet")
        return self


class ServiceContractInvoiceCreate(ServiceContractInvoiceFields):
    service_contract_id: str = Field(min_length=1)
    invoice_id: str = Field(min_length=1)


class ServiceContractInvoice(ServiceContractInvoiceCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ServiceContractPaymentCreate(BaseModel):
    service_contract_id: str = Field(min_length=1)
    booking_id: str = Field(min_length=1)
    amount: float               # paid to the provider (positive) or refunded by it (negative)
    service_contract_invoice_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        rounded = _cents(value, label="Betrag", allow_negative=True)
        if not rounded:
            raise ValueError("Betrag darf nicht 0 sein")
        return rounded


class ServiceContractPayment(ServiceContractPaymentCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        return value     # stored rows stay readable as they are


class ServiceContractDocumentCreate(BaseModel):
    service_contract_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)


class ServiceContractDocument(ServiceContractDocumentCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# --- requests -----------------------------------------------------------------------------------

class ServiceContractCreateRequest(ServiceContractCreate):
    locations: list[LocationInput] = Field(min_length=1, max_length=500)
    tariff: Optional[TariffInput] = None


class CancellationRequest(BaseModel):
    cancelled_on: date
    effective_date: Optional[date] = None      # default: the earliest end the notice reaches


class InvoiceLinkRequest(ServiceContractInvoiceFields):
    invoice_id: Optional[str] = None
    invoice: Optional[InvoiceCreate] = None    # create the bill and link it in one step

    @model_validator(mode="after")
    def validate_source(self):
        if (self.invoice_id is None) == (self.invoice is None):
            raise ValueError("Bitte eine vorhandene Rechnung wählen oder eine neue erfassen")
        return self


class PaymentLinkRequest(BaseModel):
    booking_id: str = Field(min_length=1)
    amount: Optional[float] = None             # default: what of the booking is not yet allocated
    service_contract_invoice_id: Optional[str] = None
    notes: Optional[str] = None


class CostTransferRequest(BaseModel):
    billing_period_id: str = Field(min_length=1)
    allocation_key_id: str = Field(min_length=1)
    invoice_link_ids: Optional[list[str]] = None


class DocumentLinkRequest(BaseModel):
    document_id: str = Field(min_length=1)
