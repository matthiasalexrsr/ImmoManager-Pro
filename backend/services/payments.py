"""Payment allocation rules shared by persistent and in-memory stores."""

from datetime import date, datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Literal

from pydantic import BaseModel, Field

from ..storage import ValidationError

EntityType = Literal["receivable", "rent_charge"]
_memory_lock = RLock()


class PaymentCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_date: date
    note: str | None = Field(default=None, max_length=2000)


class Payment(PaymentCreate):
    id: str
    entity_type: EntityType
    entity_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReceivableBalance(BaseModel):
    amount_paid: float = Field(ge=0)


def payment_total(entity_type: EntityType, target) -> Decimal:
    if entity_type == "receivable":
        return Decimal(str(target.amount_due))
    return sum((Decimal(str(getattr(target, field) or 0)) for field in
                ("cold_rent", "service_charge", "heating_charge", "other_charges")), Decimal("0"))


def validate_replay(payment: Payment, entity_type: EntityType, entity_id: str, payload: PaymentCreate) -> Payment:
    if (payment.entity_type != entity_type or payment.entity_id != entity_id
            or payment.model_dump(include=set(PaymentCreate.model_fields))
            != payload.model_dump(include=set(PaymentCreate.model_fields))):
        raise ValidationError("Diese Zahlungsreferenz wurde bereits für eine andere Zahlung verwendet.")
    return payment


def next_balance(entity_type: EntityType, target, payload: PaymentCreate) -> tuple[Decimal, str]:
    paid = Decimal(str(target.amount_paid or 0)) + payload.amount
    total = payment_total(entity_type, target)
    if target.status in {"paid", "cancelled", "void"} or paid > total:
        raise ValidationError("Der Zahlungsbetrag übersteigt den offenen Betrag oder der Posten ist abgeschlossen.")
    return paid.quantize(Decimal("0.01")), "paid" if paid == total else "partial"


def record_memory_payment(store, entity_type: EntityType, entity_id: str, payload: PaymentCreate) -> Payment:
    from uuid import uuid4

    with _memory_lock:
        target = getattr(store, f"get_{entity_type}")(entity_id)
        existing = store.payments.get(payload.idempotency_key)
        if existing:
            return validate_replay(existing, entity_type, entity_id, payload)
        paid, status = next_balance(entity_type, target, payload)
        payment = Payment(id=str(uuid4()), entity_type=entity_type, entity_id=entity_id, **payload.model_dump())
        target.amount_paid = float(paid)
        target.status = status
        target.updated_at = datetime.now(timezone.utc)
        store.payments[payload.idempotency_key] = payment
        return payment


def list_memory_payments(store, entity_type=None, entity_id=None) -> list[Payment]:
    return sorted((p for p in store.payments.values()
                   if (entity_type is None or p.entity_type == entity_type)
                   and (entity_id is None or p.entity_id == entity_id)),
                  key=lambda p: (p.payment_date, p.created_at, p.id))
