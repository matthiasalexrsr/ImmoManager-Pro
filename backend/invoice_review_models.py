"""Records and requests of the invoice review (see db/invoice_review_models.py).

The record models mirror their tables column for column: the in-memory store keeps them
in collections named like the tables, and snapshots export and import them. Times are
naive UTC like the database columns; JSON shows them with a "Z".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain.money import money
from .maintenance_models import UtcDateTime, utcnow


def _text(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _positive(value: Optional[float], label: str = "Betrag") -> Optional[float]:
    if value is None:
        return None
    amount = money(value)
    if amount <= 0:
        raise ValueError(f"{label} muss größer als 0 sein")
    return float(amount)


# ─── Records ────────────────────────────────────────────────────────────────

class InvoiceReview(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default=..., min_length=1)
    invoice_id: str
    kind: Literal["invoice", "credit_note"] = "invoice"
    credit_for_invoice_id: Optional[str] = None
    received_on: date
    document_id: Optional[str] = None
    document_sha256: Optional[str] = None
    status: Literal["received", "query", "approved", "partially_approved", "rejected"] = "received"
    factual_result: Optional[Literal["confirmed", "objected"]] = None
    factual_note: Optional[str] = None
    factual_by: Optional[str] = None
    factual_at: Optional[UtcDateTime] = None
    arithmetic_result: Optional[Literal["confirmed", "objected"]] = None
    arithmetic_note: Optional[str] = None
    arithmetic_by: Optional[str] = None
    arithmetic_at: Optional[UtcDateTime] = None
    checklist: dict[str, Any] = Field(default_factory=dict)
    vat_lines: list[dict[str, Any]] = Field(default_factory=list)
    skonto_percent: Optional[float] = None
    skonto_days: Optional[int] = None
    skonto_until: Optional[date] = None
    due_on: Optional[date] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    cost_category: Optional[str] = None
    recoverable: bool = False
    change_order_id: Optional[str] = None
    duplicate_of_invoice_id: Optional[str] = None
    approved_amount: Optional[float] = None
    decision_reason: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[UtcDateTime] = None
    dispute_status: Optional[Literal["open", "resolved"]] = None
    dispute_outcome: Optional[Literal["credit", "partial_payment", "written_off"]] = None
    dispute_settled_amount: Optional[float] = None
    dispute_written_off: Optional[float] = None
    dispute_reason: Optional[str] = None
    dispute_resolved_by: Optional[str] = None
    dispute_resolved_at: Optional[UtcDateTime] = None
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


class InvoiceReviewEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default=..., min_length=1)
    invoice_id: str
    seq: int
    action: str
    status_after: Optional[str] = None
    amount: Optional[float] = None
    reason: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_role: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)


class InvoiceCostTransfer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default=..., min_length=1)
    invoice_id: str
    cost_item_id: str
    billing_period_id: str
    amount: float
    created_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)


class InvoiceReviewSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = "default"
    four_eyes_limit: Optional[float] = None
    small_invoice_limit: float = 250.0
    duplicate_window_days: int = 14
    updated_by: Optional[str] = None
    created_at: UtcDateTime = Field(default_factory=utcnow)
    updated_at: UtcDateTime = Field(default_factory=utcnow)


# ─── Requests ───────────────────────────────────────────────────────────────

class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VatLineInput(_Request):
    rate: float = Field(ge=0, le=100)
    net: float
    vat: float

    @field_validator("net", "vat")
    @classmethod
    def _cents(cls, value: float) -> float:
        amount = money(value)
        if amount < 0:
            raise ValueError("Beträge einer Steuerzeile dürfen nicht negativ sein")
        return float(amount)


class InvoiceDraft(_Request):
    """A new invoice recorded together with its receipt (the existing invoice fields)."""
    property_id: Optional[str] = None
    supplier: str = Field(min_length=1, max_length=300)
    invoice_number: Optional[str] = Field(default=None, max_length=100)
    invoice_date: date
    due_date: Optional[date] = None
    performance_start: Optional[date] = None
    performance_end: Optional[date] = None
    net_amount: float
    vat_rate: float = Field(default=19.0, ge=0, le=100)
    vat_amount: float = 0.0
    gross_amount: float
    payment_terms: Optional[str] = Field(default=None, max_length=500)
    payment_reference: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=5000)

    _strip = field_validator("supplier", "invoice_number", "payment_terms", "payment_reference", "category",
                             "notes", mode="before")(classmethod(lambda cls, v: _text(v)))

    @field_validator("net_amount", "gross_amount", "vat_amount")
    @classmethod
    def _money(cls, value: float) -> float:
        return float(money(value))

    @model_validator(mode="after")
    def _performance_period(self):
        if bool(self.performance_start) != bool(self.performance_end):
            raise ValueError("Leistungsbeginn und Leistungsende gemeinsam angeben")
        if self.performance_start and self.performance_end and self.performance_end < self.performance_start:
            raise ValueError("Der Leistungszeitraum endet vor seinem Beginn")
        return self


class _ReceiptFields(_Request):
    received_on: Optional[date] = None
    document_id: Optional[str] = None
    skonto_percent: Optional[float] = Field(default=None, gt=0, lt=100)
    skonto_days: Optional[int] = Field(default=None, ge=0, le=365)
    payment_days: Optional[int] = Field(default=None, ge=0, le=365)
    vat_lines: Optional[list[VatLineInput]] = Field(default=None, max_length=10)
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    cost_category: Optional[str] = Field(default=None, max_length=100)
    recoverable: Optional[bool] = None
    change_order_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)

    _strip = field_validator("cost_category", "note", "document_id", "property_id", "unit_id", "change_order_id",
                             mode="before")(classmethod(lambda cls, v: _text(v)))

    @model_validator(mode="after")
    def _skonto(self):
        if (self.skonto_percent is None) != (self.skonto_days is None):
            raise ValueError("Skonto braucht Prozentsatz und Frist (Tage) zusammen")
        return self


class ReceiptRequest(_ReceiptFields):
    """Start the review of an existing invoice (or, at /invoice-review/receipts, a new one)."""
    invoice: Optional[InvoiceDraft] = None
    kind: Literal["invoice", "credit_note"] = "invoice"
    credit_for_invoice_id: Optional[str] = None
    accept_duplicate: bool = False
    duplicate_reason: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _credit(self):
        if self.kind == "credit_note" and not self.credit_for_invoice_id:
            raise ValueError("Eine Gutschrift nennt die Rechnung, die sie mindert")
        if self.kind == "invoice" and self.credit_for_invoice_id:
            raise ValueError("Nur eine Gutschrift nennt eine andere Rechnung")
        if self.accept_duplicate and not _text(self.duplicate_reason):
            raise ValueError("Bitte begründen, warum die Rechnung trotz Dublettenverdacht erfasst wird")
        return self


class ReceiptPatch(_ReceiptFields):
    """Change receipt data and the free cost assignment while no decision is made."""
    reason: Optional[str] = Field(default=None, max_length=2000)


class CheckRequest(_Request):
    result: Literal["confirmed", "objected"]
    note: Optional[str] = Field(default=None, max_length=5000)
    checklist: Optional[dict[str, Optional[bool]]] = None

    _strip = field_validator("note", mode="before")(classmethod(lambda cls, v: _text(v)))

    @model_validator(mode="after")
    def _note(self):
        if self.result == "objected" and not self.note:
            raise ValueError("Eine Beanstandung braucht eine Begründung")
        return self


class DecisionRequest(_Request):
    decision: Literal["approve", "partial", "reject", "query"]
    amount: Optional[float] = None
    reason: Optional[str] = Field(default=None, max_length=5000)

    _strip = field_validator("reason", mode="before")(classmethod(lambda cls, v: _text(v)))

    @model_validator(mode="after")
    def _rules(self):
        if self.decision == "partial":
            self.amount = _positive(self.amount, "Freigegebener Betrag")
            if self.amount is None:
                raise ValueError("Eine Teilfreigabe nennt den freigegebenen Betrag")
        elif self.amount is not None:
            raise ValueError("Nur eine Teilfreigabe nennt einen Betrag")
        if self.decision != "approve" and not self.reason:
            raise ValueError("Teilfreigabe, Ablehnung und Rückfrage brauchen eine Begründung")
        return self


class DisputeResolution(_Request):
    outcome: Literal["credit", "partial_payment", "written_off"]
    amount: Optional[float] = None
    reason: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _amount(self):
        if self.outcome == "partial_payment":
            self.amount = _positive(self.amount, "Nachträglich anerkannter Betrag")
            if self.amount is None:
                raise ValueError("Eine Teilzahlung nennt den nachträglich anerkannten Betrag")
        elif self.amount is not None:
            raise ValueError("Nur eine Teilzahlung nennt einen Betrag")
        return self


class CostTransferRequest(_Request):
    billing_period_id: str = Field(min_length=1)
    allocation_key_id: str = Field(min_length=1)
    description: Optional[str] = Field(default=None, max_length=500)


class SettingsUpdate(_Request):
    four_eyes_limit: Optional[float] = None
    small_invoice_limit: float = Field(default=250.0, ge=0, le=100000)
    duplicate_window_days: int = Field(default=14, ge=0, le=365)

    @field_validator("four_eyes_limit")
    @classmethod
    def _limit(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        amount = money(value)
        if amount < 0:
            raise ValueError("Die Grenze darf nicht negativ sein")
        return float(amount)

    @field_validator("small_invoice_limit")
    @classmethod
    def _small(cls, value: float) -> float:
        return float(money(Decimal(str(value))))
