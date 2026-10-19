"""Models of the deposit file (Kautionsakte): stored rows mirror db/deposit_models.py field by field,
requests are strict DTOs of routers/deposits.py (services/deposits.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

Form = Literal["cash", "transfer", "deposit_account", "guarantee", "pledged_savings"]
ItemKind = Literal["defect", "other", "receivable", "rent_arrears", "retention"]
SettlementKind = Literal["final", "retention_release"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Stored rows ─────────────────────────────────────────────────────────────

class DepositInstalment(BaseModel):
    id: str = Field(..., min_length=1)
    deposit_id: str
    number: int
    due_date: date
    amount: float
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DepositInterestRate(BaseModel):
    id: str = Field(..., min_length=1)
    deposit_id: str
    valid_from: date
    rate_percent: str
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DepositSettlement(BaseModel):
    id: str = Field(..., min_length=1)
    deposit_id: str
    kind: str
    settlement_date: date
    handover_protocol_id: Optional[str] = None
    interest_amount: Optional[float] = None
    interest_reason: Optional[str] = None
    notes: Optional[str] = None
    status: str = "draft"
    result_amount: Optional[float] = None
    payout_booking_id: Optional[str] = None
    offset_booking_id: Optional[str] = None
    offset_credit_booking_id: Optional[str] = None
    claim_receivable_id: Optional[str] = None
    document_id: Optional[str] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DepositSettlementItem(BaseModel):
    id: str = Field(..., min_length=1)
    settlement_id: str
    position: int = 0
    kind: str
    description: str
    amount: float
    reason: Optional[str] = None
    handover_defect_id: Optional[str] = None
    receivable_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DepositPayment(BaseModel):
    id: str = Field(..., min_length=1)
    deposit_id: str
    booking_id: str
    kind: str = "receipt"
    amount: float
    settlement_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ─── Requests ────────────────────────────────────────────────────────────────

def _text(value: Optional[str], *, multi: bool = False) -> Optional[str]:
    if value is None:
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    allowed = "\n\t" if multi else ""
    if any(ord(char) < 32 and char not in allowed for char in value):
        raise ValueError("Der Text enthält Steuerzeichen.")
    return value or None


def _uuid(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Ungültige Kennung (UUID erwartet).") from None
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgreementRequest(StrictModel):
    """The agreement of a deposit: amount, form, instalments, where the money is held."""
    base_revision: Optional[str] = Field(None, max_length=200)
    contract_id: str = Field(min_length=1, max_length=64)
    amount: float = Field(gt=0, le=10_000_000)
    form: Form = "transfer"
    instalment_amounts: Optional[list[float]] = Field(None, min_length=1, max_length=3)
    instalment_count: int = Field(1, ge=1, le=3)
    cap_reason: Optional[str] = Field(None, max_length=2000)
    account_id: Optional[str] = Field(None, max_length=64)
    institution: Optional[str] = Field(None, max_length=200)
    account_reference: Optional[str] = Field(None, max_length=200)
    account_holder: Optional[str] = Field(None, max_length=200)
    held_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=4000)

    _single = field_validator("institution", "account_reference", "account_holder")(lambda v: _text(v))
    _multi = field_validator("cap_reason", "notes")(lambda v: _text(v, multi=True))


class ReceiptRequest(StrictModel):
    booking_id: str = Field(min_length=1, max_length=64)
    amount: Optional[float] = Field(None, description="Anteil der Buchung; ohne Angabe der noch freie Betrag")
    notes: Optional[str] = Field(None, max_length=2000)

    _multi = field_validator("notes")(lambda v: _text(v, multi=True))


class RateInput(StrictModel):
    valid_from: date
    rate_percent: str = Field(min_length=1, max_length=16)
    note: Optional[str] = Field(None, max_length=500)

    _single = field_validator("note")(lambda v: _text(v))


class RatesRequest(StrictModel):
    base_revision: str = Field(min_length=1, max_length=200)
    rates: list[RateInput] = Field(default_factory=list, max_length=200)


class SecurityRequest(StrictModel):
    """Guarantee or pledged savings book: provided and released, each with date and proof."""
    base_revision: str = Field(min_length=1, max_length=200)
    provided_on: Optional[date] = None
    proof_document_id: Optional[str] = Field(None, max_length=64)
    released_on: Optional[date] = None
    release_document_id: Optional[str] = Field(None, max_length=64)
    release_note: Optional[str] = Field(None, max_length=2000)

    _multi = field_validator("release_note")(lambda v: _text(v, multi=True))


class TakeoverRequest(StrictModel):
    """A deposit paid before this app's bookings: received and credited until the takeover day.

    All values empty removes the takeover."""
    base_revision: str = Field(min_length=1, max_length=200)
    carried_on: Optional[date] = None
    carried_amount: Optional[float] = Field(None, gt=0, le=10_000_000)
    carried_interest: Optional[float] = Field(None, ge=0, le=10_000_000)
    carried_note: Optional[str] = Field(None, max_length=2000)

    _multi = field_validator("carried_note")(lambda v: _text(v, multi=True))


class LegacyTakeoverRequest(StrictModel):
    """Deposits of the earlier plain records to take over as received on their receipt date."""
    deposit_ids: list[str] = Field(min_length=1, max_length=2000)

    @field_validator("deposit_ids")
    @classmethod
    def distinct(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Jede Kaution nur einmal angeben.")
        return value


class SettlementCreate(StrictModel):
    kind: SettlementKind = "final"
    settlement_date: Optional[date] = None


class ItemInput(StrictModel):
    id: Optional[str] = None
    kind: ItemKind
    description: str = Field(min_length=1, max_length=1000)
    amount: float = Field(gt=0, le=10_000_000)
    reason: Optional[str] = Field(None, max_length=2000)
    handover_defect_id: Optional[str] = None
    receivable_id: Optional[str] = Field(None, max_length=64)

    _id = field_validator("id", "handover_defect_id")(lambda v: _uuid(v))
    _single = field_validator("description")(lambda v: _text(v))
    _multi = field_validator("reason")(lambda v: _text(v, multi=True))


class SettlementContent(StrictModel):
    base_revision: str = Field(min_length=1, max_length=200)
    settlement_date: date
    interest_amount: Optional[float] = Field(None, ge=0, le=10_000_000)
    interest_reason: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=4000)
    items: list[ItemInput] = Field(default_factory=list, max_length=200)

    _multi = field_validator("interest_reason", "notes")(lambda v: _text(v, multi=True))


class FinalizeRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool
    payout_account_id: Optional[str] = Field(None, max_length=64)
