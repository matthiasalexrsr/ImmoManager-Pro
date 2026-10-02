"""Immutable credit commands and receipts, preserving exact decimal cents."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CreditTarget = Literal["receivable", "rent_charge"]


def credit_money(value) -> Decimal:
    """Check cents without quantizing, rounding, or expanding a huge exponent.

    Consumption is subsequently bounded by persisted source funds. There is no
    invented monetary ceiling or cap on the number of contracts or receipts.
    """
    if isinstance(value, bool):
        raise ValueError("Ein gültiger Centbetrag ist erforderlich.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Ein gültiger Centbetrag ist erforderlich.") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Der Betrag muss positiv und endlich sein.")
    _, digits, exponent = amount.as_tuple()
    assert isinstance(exponent, int)
    extra = -2 - exponent
    if extra > 0 and any(digits[-extra:]):
        raise ValueError("Der Betrag darf keine Bruchteile eines Cents enthalten.")
    return amount


class CreditCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=100)
    source_settlement_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    transaction_date: date
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value):
        return credit_money(value)

    @field_validator("idempotency_key", "source_settlement_id")
    @classmethod
    def nonblank_reference(cls, value):
        if not value.strip():
            raise ValueError("Eine Belegreferenz ist erforderlich.")
        return value


class CreditPayoutCreate(CreditCommand):
    method: Literal["cash", "bank"]
    booking_id: str | None = Field(default=None, min_length=1)
    confirmed_payment: bool

    @field_validator("confirmed_payment", mode="before")
    @classmethod
    def confirm_completed_payment(cls, value):
        if value is not True:
            raise ValueError("Die bereits erfolgte Auszahlung muss ausdrücklich bestätigt werden.")
        return value

    @model_validator(mode="after")
    def payout_method(self):
        if (self.method == "bank") != (self.booking_id is not None):
            raise ValueError("Bankauszahlungen benötigen eine negative Bankbuchung; Barauszahlungen haben keine Bankzuordnung.")
        return self


class CreditOffsetCreate(CreditCommand):
    target_type: CreditTarget
    target_id: str = Field(min_length=1)


class CreditReversalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=100)
    reversal_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason", "idempotency_key")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Stornogrund und Referenz sind erforderlich.")
        return value.strip()


class CreditReversal(CreditReversalCreate):
    id: str
    receipt_id: str
    amount: Decimal
    payment_reversal_id: str | None = None
    actor_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreditReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    contract_id: str
    source_settlement_id: str
    idempotency_key: str
    amount: Decimal
    transaction_date: date
    method: Literal["cash", "bank", "offset"]
    booking_id: str | None = None
    target_type: CreditTarget | None = None
    target_id: str | None = None
    payment_id: str | None = None
    note: str | None = None
    actor_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reversal: CreditReversal | None = None
