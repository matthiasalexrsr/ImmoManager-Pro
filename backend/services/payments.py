"""Payment allocation rules shared by persistent and in-memory stores."""

from datetime import date, datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..storage import ValidationError

EntityType = Literal["receivable", "rent_charge"]
_memory_lock = RLock()


class PaymentCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_date: date
    note: str | None = Field(default=None, max_length=2000)
    booking_id: str | None = Field(default=None, min_length=1)


class PaymentReversalCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    reversal_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("idempotency_key")
    @classmethod
    def nonblank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Eine Stornoreferenz ist erforderlich")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ein Stornogrund ist erforderlich")
        return value.strip()


class PaymentReversal(PaymentReversalCreate):
    model_config = ConfigDict(frozen=True)
    id: str
    payment_id: str
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Payment(PaymentCreate):
    id: str
    entity_type: EntityType
    entity_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reversal: PaymentReversal | None = None
    credit_receipt_id: str | None = None


class ReceivableBalance(BaseModel):
    amount_paid: float = Field(ge=0)


class FinancialConsistencyError(ValidationError):
    """An ordinary edit would contradict receipt-backed financial state."""


def payment_total(entity_type: EntityType, target) -> Decimal:
    if entity_type == "receivable":
        return Decimal(str(target.amount_due))
    return sum((Decimal(str(getattr(target, field) or 0)) for field in
                ("cold_rent", "service_charge", "heating_charge", "other_charges")), Decimal("0"))


def reconcile_financial_edit(entity_type: EntityType, target, payload) -> tuple[Decimal, str]:
    """Protect receipt-backed balances while allowing legitimate total edits."""
    paid = Decimal(str(target.amount_paid or 0)).quantize(Decimal("0.01"))
    proposed_paid = Decimal(str(getattr(payload, "amount_paid", paid))).quantize(Decimal("0.01"))
    total = payment_total(entity_type, payload).quantize(Decimal("0.01"))
    if total < 0:
        raise FinancialConsistencyError("Der Sollbetrag darf nicht negativ sein.")
    if proposed_paid != paid:
        raise FinancialConsistencyError("Der Zahlungsstand kann nur ueber Zahlungsbelege geaendert werden.")
    if paid > total:
        raise FinancialConsistencyError("Der Sollbetrag darf nicht unter den bereits bezahlten Betrag fallen.")
    if paid > 0:
        return paid, "paid" if paid == total else "partial"
    requested_status = getattr(payload, "status", "open")
    if requested_status in {"paid", "partial"}:
        raise FinancialConsistencyError("Bezahlstatus kann nur ueber Zahlungsbelege entstehen.")
    return paid, requested_status


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


def reversed_balance(entity_type: EntityType, target, payment: Payment) -> tuple[Decimal, str]:
    paid = Decimal(str(target.amount_paid or 0)) - payment.amount
    if paid < 0 or target.status in {"cancelled", "void"}:
        raise ValidationError("Der Zahlungsposten kann in seinem aktuellen Zustand nicht storniert werden.")
    total = payment_total(entity_type, target)
    return paid.quantize(Decimal("0.01")), "paid" if paid == total else "partial" if paid else "open"


def validate_booking(booking, contract, amount: Decimal, *, allocated: Decimal | None = None) -> Decimal:
    if Decimal(str(booking.amount)) <= 0:
        raise ValidationError("Nur positive Bankbuchungen können zugeordnet werden.")
    for field in ("tenant_id", "property_id", "unit_id"):
        assigned = getattr(booking, field)
        if assigned and assigned != getattr(contract, field):
            raise ValidationError("Die Bankbuchung gehört zu einem anderen Mieter, Objekt oder einer anderen Einheit.")
    paid = (allocated if allocated is not None else Decimal(str(booking.allocated_amount or 0))) + amount
    if paid < 0 or paid > Decimal(str(booking.amount)):
        raise ValidationError("Der Betrag übersteigt den noch zuordenbaren Betrag der Bankbuchung.")
    return paid.quantize(Decimal("0.01"))


def validate_reversal_replay(reversal: PaymentReversal, payment_id: str, payload: PaymentReversalCreate) -> PaymentReversal:
    if (reversal.payment_id != payment_id or
            reversal.model_dump(include=set(PaymentReversalCreate.model_fields)) != payload.model_dump()):
        raise ValidationError("Diese Stornoreferenz wurde bereits für einen anderen Vorgang verwendet.")
    return reversal


def record_memory_payment(store, entity_type: EntityType, entity_id: str, payload: PaymentCreate) -> Payment:
    from uuid import uuid4

    with _memory_lock:
        target = getattr(store, f"get_{entity_type}")(entity_id)
        existing = store.payments.get(payload.idempotency_key)
        if existing:
            return validate_replay(existing, entity_type, entity_id, payload)
        paid, status = next_balance(entity_type, target, payload)
        booking = store.get_booking(payload.booking_id) if payload.booking_id else None
        allocated = validate_booking(booking, store.get_contract(target.contract_id), payload.amount) if booking else None
        payment = Payment(id=str(uuid4()), entity_type=entity_type, entity_id=entity_id, **payload.model_dump())
        target.amount_paid = float(paid)
        target.status = status
        target.updated_at = datetime.now(timezone.utc)
        if booking is not None and allocated is not None:
            booking.allocated_amount = float(allocated)
        store.payments[payload.idempotency_key] = payment
        return payment


def reverse_memory_payment(store, entity_type: EntityType, entity_id: str, payment_id: str,
                           payload: PaymentReversalCreate, *, credit_internal=False) -> PaymentReversal:
    from uuid import uuid4

    from ..storage import NotFoundError

    with _memory_lock:
        target = getattr(store, f"get_{entity_type}")(entity_id)
        payment = next((p for p in store.payments.values() if p.id == payment_id
                        and p.entity_type == entity_type and p.entity_id == entity_id), None)
        if payment is None:
            raise NotFoundError("Zahlungsbeleg nicht gefunden")
        if payment.credit_receipt_id and not credit_internal:
            from .credit_ledger import reverse_linked_payment
            return reverse_linked_payment(store, payment, payload)
        existing = next((p.reversal for p in store.payments.values() if p.reversal
                         and p.reversal.idempotency_key == payload.idempotency_key), None)
        if existing:
            return validate_reversal_replay(existing, payment_id, payload)
        if payment.reversal:
            raise ValidationError("Dieser Zahlungsbeleg wurde bereits storniert.")
        paid, status = reversed_balance(entity_type, target, payment)
        booking = store.get_booking(payment.booking_id) if payment.booking_id else None
        allocated = Decimal(str(booking.allocated_amount)) - payment.amount if booking else None
        if allocated is not None and allocated < 0:
            raise ValidationError("Die Bankzuordnung ist inkonsistent. Bitte prüfen.")
        reversal = PaymentReversal(id=str(uuid4()), payment_id=payment_id, amount=payment.amount, **payload.model_dump())
        target.amount_paid, target.status = float(paid), status
        target.updated_at = datetime.now(timezone.utc)
        if booking is not None and allocated is not None:
            booking.allocated_amount = float(allocated)
        store.payments[payment.idempotency_key] = payment.model_copy(update={"reversal": reversal})
        return reversal


def import_memory_payment(store, payment: Payment) -> Payment:
    if payment.credit_receipt_id:
        raise FinancialConsistencyError("Guthabenverrechnungen benötigen das vollständige Serverbackup.")
    with _memory_lock:
        target = getattr(store, f"get_{payment.entity_type}")(payment.entity_id)
        existing = store.payments.get(payment.idempotency_key)
        if existing:
            validate_replay(existing, payment.entity_type, payment.entity_id, payment)
            if existing.reversal != payment.reversal:
                raise ValidationError("Der Zahlungsbeleg enthält abweichende Stornodaten.")
            return existing
        if any(item.id == payment.id for item in store.payments.values()):
            raise ValidationError("Zahlungsbeleg-ID existiert bereits.")
        if payment.reversal:
            if payment.reversal.payment_id != payment.id or payment.reversal.amount != payment.amount:
                raise ValidationError("Stornobeleg und Zahlungsbeleg passen nicht zusammen.")
            if any(item.reversal and (item.reversal.id == payment.reversal.id or
                   item.reversal.idempotency_key == payment.reversal.idempotency_key) for item in store.payments.values()):
                raise ValidationError("Stornobeleg existiert bereits.")
        booking = store.get_booking(payment.booking_id) if payment.booking_id else None
        if booking:
            active = sum((item.amount for item in store.payments.values()
                          if item.booking_id == booking.id and not item.reversal), Decimal("0"))
            allocated = validate_booking(booking, store.get_contract(target.contract_id),
                                         Decimal("0") if payment.reversal else payment.amount, allocated=active)
            booking.allocated_amount = float(allocated)
        store.payments[payment.idempotency_key] = payment
        return payment


def list_memory_payments(store, entity_type=None, entity_id=None) -> list[Payment]:
    return sorted((p for p in store.payments.values()
                   if (entity_type is None or p.entity_type == entity_type)
                   and (entity_id is None or p.entity_id == entity_id)),
                  key=lambda p: (p.payment_date, p.created_at, p.id))
