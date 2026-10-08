"""Records and requests of the maintenance project file (see db/maintenance_project_models.py).

The record models mirror their tables column for column: the in-memory store keeps
them in collections named like the tables, and snapshots export and import them.
Times are naive UTC like the database columns; JSON shows them with a "Z".
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from .domain.money import money


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


UtcDateTime = Annotated[datetime, AfterValidator(_naive_utc),
                        PlainSerializer(lambda value: value.isoformat() + "Z", return_type=str, when_used="json")]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cents(value: Optional[float], *, allow_negative: bool = False, label: str = "Betrag") -> Optional[float]:
    if value is None:
        return None
    amount = money(value)
    if amount == 0 or (amount < 0 and not allow_negative):
        raise ValueError(f"{label} muss {'ungleich' if allow_negative else 'größer als'} 0 sein")
    return float(amount)


def _text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _strip(cls, value):
    return _text(value) if isinstance(value, str) else value


# ─── Records ────────────────────────────────────────────────────────────────

class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(..., min_length=1)
    case_id: str


class MaintenanceWorkPackage(_Record):
    title: str
    description: Optional[str] = None
    phase: Optional[str] = None
    kind: Literal["work", "milestone"] = "work"
    status: Literal["planned", "in_progress", "done", "cancelled"] = "planned"
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    contact_id: Optional[str] = None
    sort_order: int = 0
    completed_at: Optional[UtcDateTime] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceDependency(_Record):
    predecessor_id: str
    successor_id: str
    created_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceParticipant(_Record):
    contact_id: str
    role: Literal["contractor", "expert", "other"] = "contractor"
    trade: Optional[str] = None
    notes: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceQuote(_Record):
    contact_id: Optional[str] = None
    supplier_name: str
    work_package_id: Optional[str] = None
    quote_number: Optional[str] = None
    quote_date: date
    valid_until: Optional[date] = None
    description: Optional[str] = None
    net_amount: float
    gross_amount: float
    status: Literal["received", "accepted", "rejected"] = "received"
    decided_at: Optional[UtcDateTime] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    document_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceOrder(_Record):
    quote_id: str
    contact_id: Optional[str] = None
    supplier_name: str
    order_number: Optional[str] = None
    order_date: date
    net_amount: float
    gross_amount: float
    status: Literal["active", "completed", "cancelled"] = "active"
    notes: Optional[str] = None
    completed_at: Optional[UtcDateTime] = None
    cancelled_at: Optional[UtcDateTime] = None
    cancel_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceChangeOrder(_Record):
    order_id: str
    title: str
    reason: Optional[str] = None
    net_amount: float
    gross_amount: float
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    decided_at: Optional[UtcDateTime] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    document_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceOrderInvoice(_Record):
    order_id: str
    invoice_id: str
    linked_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)


class InvoicePayment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(..., min_length=1)
    invoice_id: str
    booking_id: str
    amount: float
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceProtocol(_Record):
    work_package_id: Optional[str] = None
    order_id: Optional[str] = None
    protocol_type: Literal["acceptance", "inspection", "site_visit"]
    protocol_date: date
    title: Optional[str] = None
    participants: Optional[str] = None
    result: Optional[Literal["accepted", "accepted_with_defects", "refused"]] = None
    notes: Optional[str] = None
    defects: list[dict[str, Any]] = Field(default_factory=list)
    photo_ids: list[str] = Field(default_factory=list)
    status: Literal["draft", "final"] = "draft"
    finalized_at: Optional[UtcDateTime] = None
    finalized_by: Optional[str] = None
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    content_sha256: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceAppointment(_Record):
    calendar_event_id: str
    work_package_id: Optional[str] = None
    contact_id: Optional[str] = None
    kind: Literal["inspection", "execution", "acceptance", "other"] = "other"
    created_at: UtcDateTime = Field(default_factory=utcnow)


class MaintenanceCaseDocument(_Record):
    document_id: str
    role: Literal["damage_photo", "quote", "order", "invoice", "protocol", "report", "other"] = "other"
    created_at: UtcDateTime = Field(default_factory=utcnow)


# ─── Requests ───────────────────────────────────────────────────────────────

class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusTransition(_Request):
    status: Literal["open", "in_progress", "completed", "cancelled"]
    reason: Optional[str] = Field(None, max_length=2000)

    _clean = field_validator("reason")(_strip)


class WorkPackageCreate(_Request):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=10000)
    phase: Optional[str] = Field(None, max_length=100)
    kind: Literal["work", "milestone"] = "work"
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    contact_id: Optional[str] = None
    sort_order: int = 0

    _clean = field_validator("title", "description", "phase", "contact_id")(_strip)


class WorkPackagePatch(_Request):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=10000)
    phase: Optional[str] = Field(None, max_length=100)
    status: Optional[Literal["planned", "in_progress", "done", "cancelled"]] = None
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    contact_id: Optional[str] = None
    sort_order: Optional[int] = None

    _clean = field_validator("title", "description", "phase", "contact_id")(_strip)


class DependencyCreate(_Request):
    predecessor_id: str = Field(..., min_length=1)
    successor_id: str = Field(..., min_length=1)


class ParticipantCreate(_Request):
    contact_id: str = Field(..., min_length=1)
    role: Literal["contractor", "expert", "other"] = "contractor"
    trade: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)

    _clean = field_validator("trade", "notes")(_strip)


class AppointmentCreate(_Request):
    title: str = Field(..., min_length=1, max_length=300)
    event_date: date
    event_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    location: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    kind: Literal["inspection", "execution", "acceptance", "other"] = "other"
    work_package_id: Optional[str] = None
    contact_id: Optional[str] = None

    _clean = field_validator("title", "location", "description")(_strip)


class AppointmentPatch(_Request):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    event_date: Optional[date] = None
    event_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    location: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    kind: Optional[Literal["inspection", "execution", "acceptance", "other"]] = None
    work_package_id: Optional[str] = None
    contact_id: Optional[str] = None


def check_amounts(net: Optional[float], gross: Optional[float]) -> None:
    """Net and gross have the same sign and the gross amount is the larger one in magnitude."""
    if net is None or gross is None:
        return
    if (net > 0) != (gross > 0):
        raise ValueError("Netto- und Bruttobetrag müssen dasselbe Vorzeichen haben")
    if abs(money(gross)) < abs(money(net)):
        raise ValueError("Der Bruttobetrag darf betragsmäßig nicht kleiner als der Nettobetrag sein")


def _quote_amount(cls, value):
    return _cents(value, label="Der Angebotsbetrag")


def _change_amount(cls, value):
    return _cents(value, allow_negative=True, label="Der Nachtragsbetrag")


def _invoice_amount(cls, value):
    return _cents(value, label="Der Rechnungsbetrag")


def _payment_amount(cls, value):
    return _cents(value, label="Der Zahlbetrag")


class QuoteCreate(_Request):
    supplier_name: Optional[str] = Field(None, max_length=300)
    contact_id: Optional[str] = None
    work_package_id: Optional[str] = None
    quote_number: Optional[str] = Field(None, max_length=100)
    quote_date: date
    valid_until: Optional[date] = None
    description: Optional[str] = Field(None, max_length=10000)
    net_amount: float
    gross_amount: float
    document_id: Optional[str] = None

    _clean = field_validator("supplier_name", "contact_id", "quote_number", "description")(_strip)
    _money = field_validator("net_amount", "gross_amount")(
        _quote_amount)

    @model_validator(mode="after")
    def _consistent(self) -> "QuoteCreate":
        check_amounts(self.net_amount, self.gross_amount)
        if self.valid_until and self.valid_until < self.quote_date:
            raise ValueError("Die Bindefrist endet vor dem Angebotsdatum")
        return self


class QuotePatch(_Request):
    supplier_name: Optional[str] = Field(None, max_length=300)
    contact_id: Optional[str] = None
    work_package_id: Optional[str] = None
    quote_number: Optional[str] = Field(None, max_length=100)
    quote_date: Optional[date] = None
    valid_until: Optional[date] = None
    description: Optional[str] = Field(None, max_length=10000)
    net_amount: Optional[float] = None
    gross_amount: Optional[float] = None
    document_id: Optional[str] = None

    _money = field_validator("net_amount", "gross_amount")(
        _quote_amount)


class QuoteDecision(_Request):
    order_number: Optional[str] = Field(None, max_length=100)
    order_date: Optional[date] = None
    note: Optional[str] = Field(None, max_length=2000)
    reject_competing: bool = False

    _clean = field_validator("order_number", "note")(_strip)


class Decision(_Request):
    note: Optional[str] = Field(None, max_length=2000)

    _clean = field_validator("note")(_strip)


class ChangeOrderCreate(_Request):
    title: str = Field(..., min_length=1, max_length=300)
    reason: Optional[str] = Field(None, max_length=5000)
    net_amount: float
    gross_amount: float
    document_id: Optional[str] = None

    _clean = field_validator("title", "reason")(_strip)
    _money = field_validator("net_amount", "gross_amount")(
        _change_amount)

    @model_validator(mode="after")
    def _consistent(self) -> "ChangeOrderCreate":
        check_amounts(self.net_amount, self.gross_amount)
        return self


class ChangeOrderPatch(_Request):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    reason: Optional[str] = Field(None, max_length=5000)
    net_amount: Optional[float] = None
    gross_amount: Optional[float] = None
    document_id: Optional[str] = None

    _money = field_validator("net_amount", "gross_amount")(
        _change_amount)


class InvoiceDraft(_Request):
    """A new invoice of the order; the property is always the case's."""

    supplier: Optional[str] = Field(None, max_length=300)
    invoice_number: Optional[str] = Field(None, max_length=100)
    invoice_date: date
    due_date: Optional[date] = None
    net_amount: float
    vat_rate: float = 19.0
    gross_amount: float
    payment_terms: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)

    _money = field_validator("net_amount", "gross_amount")(
        _invoice_amount)

    @model_validator(mode="after")
    def _consistent(self) -> "InvoiceDraft":
        check_amounts(self.net_amount, self.gross_amount)
        return self


class InvoiceLinkCreate(_Request):
    invoice_id: Optional[str] = None
    invoice: Optional[InvoiceDraft] = None

    @model_validator(mode="after")
    def _one_source(self) -> "InvoiceLinkCreate":
        if (self.invoice_id is None) == (self.invoice is None):
            raise ValueError("Entweder eine vorhandene Rechnung (invoice_id) oder eine neue Rechnung angeben")
        return self


class InvoicePaymentCreate(_Request):
    booking_id: str = Field(..., min_length=1)
    amount: float

    _money = field_validator("amount")(_payment_amount)


class Defect(_Request):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    location: Optional[str] = Field(None, max_length=300)
    severity: Literal["minor", "major", "critical"] = "minor"
    due_date: Optional[date] = None
    photo_ids: list[str] = Field(default_factory=list, max_length=24)


class ProtocolCreate(_Request):
    protocol_type: Literal["acceptance", "inspection", "site_visit"] = "acceptance"
    protocol_date: date
    title: Optional[str] = Field(None, max_length=300)
    participants: Optional[str] = Field(None, max_length=2000)
    result: Optional[Literal["accepted", "accepted_with_defects", "refused"]] = None
    notes: Optional[str] = Field(None, max_length=20000)
    work_package_id: Optional[str] = None
    order_id: Optional[str] = None
    defects: list[Defect] = Field(default_factory=list, max_length=200)
    photo_ids: list[str] = Field(default_factory=list, max_length=24)


class ProtocolPatch(_Request):
    protocol_type: Optional[Literal["acceptance", "inspection", "site_visit"]] = None
    protocol_date: Optional[date] = None
    title: Optional[str] = Field(None, max_length=300)
    participants: Optional[str] = Field(None, max_length=2000)
    result: Optional[Literal["accepted", "accepted_with_defects", "refused"]] = None
    notes: Optional[str] = Field(None, max_length=20000)
    work_package_id: Optional[str] = None
    order_id: Optional[str] = None
    defects: Optional[list[Defect]] = Field(None, max_length=200)
    photo_ids: Optional[list[str]] = Field(None, max_length=24)


class ProtocolFinalize(_Request):
    idempotency_key: str = Field(..., min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


class CaseDocumentCreate(_Request):
    document_id: str = Field(..., min_length=1)
    role: Literal["damage_photo", "quote", "order", "invoice", "protocol", "report", "other"] = "other"
