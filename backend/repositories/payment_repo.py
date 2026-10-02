"""Atomic receipt allocation and append-only reversal transactions."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.orm_models import BookingORM, InvoiceORM, PaymentORM, PaymentReversalORM, ReceivableORM, RentChargeORM
from ..services.payments import (
    EntityType,
    Payment,
    PaymentCreate,
    PaymentReversal,
    PaymentReversalCreate,
    next_balance,
    reversed_balance,
    validate_payment_booking,
    validate_replay,
    validate_reversal_replay,
)
from ..storage import NotFoundError, ValidationError


def _read_reversal(row: PaymentReversalORM) -> PaymentReversal:
    return PaymentReversal(**{column.key: getattr(row, column.key) for column in row.__table__.columns})


def _read(db: Session, row: PaymentORM) -> Payment:
    reversal = db.scalar(select(PaymentReversalORM).where(PaymentReversalORM.payment_id == row.id))
    return Payment(
        id=row.id, idempotency_key=row.idempotency_key, amount=Decimal(str(row.amount)),
        payment_date=row.payment_date, note=row.note, created_at=row.created_at, booking_id=row.booking_id,
        entity_type="receivable" if row.receivable_id else "rent_charge" if row.rent_charge_id else "invoice",
        entity_id=row.receivable_id or row.rent_charge_id or row.invoice_id or "",
        reversal=_read_reversal(reversal) if reversal else None,
        credit_receipt_id=_credit_receipt_id(db, row),
    )


def _credit_receipt_id(db, row):
    if not row.idempotency_key.startswith("credit-offset:"):
        return None
    from ..db.credit_models import CreditReceiptORM
    return db.scalar(select(CreditReceiptORM.id).where(CreditReceiptORM.payment_id == row.id))


def list_payments(db: Session, entity_type=None, entity_id=None) -> list[Payment]:
    query = select(PaymentORM).order_by(PaymentORM.payment_date, PaymentORM.created_at, PaymentORM.id)
    if entity_type:
        column = getattr(PaymentORM, f"{entity_type}_id")
        query = query.where(column == entity_id) if entity_id else query.where(column.is_not(None))
    return [_read(db, row) for row in db.scalars(query)]


def _target(db, entity_type, entity_id):
    cls = {"receivable": ReceivableORM, "rent_charge": RentChargeORM, "invoice": InvoiceORM}[entity_type]
    row = db.get(cls, entity_id, populate_existing=True)
    if row is None:
        raise NotFoundError("Zahlungsposten nicht gefunden")
    return cls, row


def _update_target(db, cls, target, paid, status):
    # Compare-and-swap also protects concurrent total/status edits.
    fields = ("gross_amount",) if cls == InvoiceORM else ("amount_due",) if cls == ReceivableORM else (
        "cold_rent", "service_charge", "heating_charge", "other_charges"
    )
    predicates = [cls.id == target.id, cls.amount_paid == target.amount_paid, cls.status == target.status]
    parent_field = "property_id" if cls == InvoiceORM else "contract_id"
    predicates.append(getattr(cls, parent_field) == getattr(target, parent_field))
    predicates.extend(getattr(cls, field) == getattr(target, field) for field in fields)
    result = db.execute(update(cls).where(*predicates).values(
        amount_paid=float(paid), status=status, updated_at=datetime.now(timezone.utc)
    ).execution_options(synchronize_session=False))
    if cast(CursorResult, result).rowcount != 1:
        raise ValidationError("Der Posten wurde zwischenzeitlich geändert. Bitte neu laden.")


def _lock_target(db, entity_type, entity_id):
    if entity_type == "invoice":
        if db.get_bind().dialect.name == "sqlite":
            connection = db.connection()
            driver = connection.connection.driver_connection
            if driver is not None and not driver.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        if db.scalar(select(InvoiceORM).where(InvoiceORM.id == entity_id).with_for_update()
                     .execution_options(populate_existing=True)) is None:
            raise NotFoundError("Rechnung nicht gefunden")
    else:
        from ..services.credit_ledger import lock_contract
        _, target = _target(db, entity_type, entity_id)
        lock_contract(db, target.contract_id)


def _booking(db, booking_id):
    booking = db.scalar(select(BookingORM).where(BookingORM.id == booking_id).with_for_update()
                        .execution_options(populate_existing=True))
    if booking is None:
        raise NotFoundError("Bankbuchung nicht gefunden")
    return booking


def _update_booking(db, booking, allocated):
    predicates = [BookingORM.id == booking.id, BookingORM.allocated_amount == booking.allocated_amount]
    predicates.extend(getattr(BookingORM, field) == getattr(booking, field) for field in
                      ("amount", "account_id", "tenant_id", "property_id", "unit_id", "booking_date"))
    result = db.execute(update(BookingORM).where(*predicates).values(
        allocated_amount=float(allocated), updated_at=datetime.now(timezone.utc)
    ).execution_options(synchronize_session=False))
    if cast(CursorResult, result).rowcount != 1:
        raise ValidationError("Die Bankbuchung wurde zwischenzeitlich geändert. Bitte neu laden.")


def record_payment(db: Session, entity_type: EntityType, entity_id: str, payload: PaymentCreate, *, commit=True,
                   expected_contract_id=None) -> Payment:
    if entity_type == "invoice":
        from ..services.invoice_payment_schema import require_invoice_payment_schema
        require_invoice_payment_schema(db.connection())
        _lock_target(db, entity_type, entity_id)
    cls, target = _target(db, entity_type, entity_id)
    if expected_contract_id is not None and target.contract_id != expected_contract_id:
        raise ValidationError("Die Forderung gehört nicht mehr zum Vertrag der Guthabenquelle.")
    existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payload.idempotency_key))
    if existing:
        return validate_replay(_read(db, existing), entity_type, entity_id, payload)
    try:
        _lock_target(db, entity_type, entity_id)
        cls, target = _target(db, entity_type, entity_id)
        if expected_contract_id is not None and target.contract_id != expected_contract_id:
            raise ValidationError("Die Forderung gehört nicht mehr zum Vertrag der Guthabenquelle.")
        paid, status = next_balance(entity_type, target, payload)
        if payload.booking_id:
            booking = _booking(db, payload.booking_id)
            from .sql_store import SQLAlchemyStore
            allocated = validate_payment_booking(SQLAlchemyStore(db), entity_type, target, booking, payload.amount)
            if entity_type == "invoice" and payload.payment_date != booking.booking_date:
                raise ValidationError("Zahlungsdatum und Bankbuchungsdatum müssen übereinstimmen.")
            _update_booking(db, booking, allocated)
        _update_target(db, cls, target, paid, status)
        row = PaymentORM(id=str(uuid4()), **payload.model_dump(), **{f"{entity_type}_id": entity_id})
        db.add(row)
        db.flush()
        payment = _read(db, row)
        if commit:
            db.commit()
            db.expire_all()
        return payment
    except (IntegrityError, ValidationError):
        if not commit:
            raise
        db.rollback()
        existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payload.idempotency_key))
        if existing:
            return validate_replay(_read(db, existing), entity_type, entity_id, payload)
        raise
    except Exception:
        if commit:
            db.rollback()
        raise


def reverse_payment(db: Session, entity_type: EntityType, entity_id: str, payment_id: str,
                    payload: PaymentReversalCreate, *, commit=True, credit_internal=False) -> PaymentReversal:
    cls, target = _target(db, entity_type, entity_id)
    row = db.get(PaymentORM, payment_id)
    if row is None or getattr(row, f"{entity_type}_id") != entity_id:
        raise NotFoundError("Zahlungsbeleg nicht gefunden")
    payment = _read(db, row)
    if payment.credit_receipt_id and not credit_internal:
        from ..repositories.sql_store import SQLAlchemyStore
        from ..services.credit_ledger import reverse_linked_payment
        return reverse_linked_payment(SQLAlchemyStore(db), payment, payload)
    existing = db.scalar(select(PaymentReversalORM).where(PaymentReversalORM.idempotency_key == payload.idempotency_key))
    if existing:
        return validate_reversal_replay(_read_reversal(existing), payment_id, payload)
    payment = _read(db, row)
    if payment.reversal:
        raise ValidationError("Dieser Zahlungsbeleg wurde bereits storniert.")
    try:
        if not credit_internal:
            _lock_target(db, entity_type, entity_id)
        cls, target = _target(db, entity_type, entity_id)
        # Re-read the receipt after the serialization lock, including its reversal.
        current_row = db.get(PaymentORM, payment_id, populate_existing=True)
        if current_row is None:
            raise NotFoundError("Zahlungsbeleg nicht gefunden")
        payment = _read(db, current_row)
        if payment.reversal:
            raise ValidationError("Dieser Zahlungsbeleg wurde bereits storniert.")
        paid, status = reversed_balance(entity_type, target, payment)
        if payment.booking_id:
            booking = _booking(db, payment.booking_id)
            allocated = Decimal(str(booking.allocated_amount)) - payment.amount
            if allocated < 0:
                raise ValidationError("Die Bankzuordnung ist inkonsistent. Bitte prüfen.")
            _update_booking(db, booking, allocated)
        _update_target(db, cls, target, paid, status)
        reversal = PaymentReversalORM(id=str(uuid4()), payment_id=payment.id, amount=payment.amount, **payload.model_dump())
        db.add(reversal)
        db.flush()
        result = _read_reversal(reversal)
        if commit:
            db.commit()
            db.expire_all()
        return result
    except (IntegrityError, ValidationError):
        if not commit:
            raise
        db.rollback()
        existing = db.scalar(select(PaymentReversalORM).where(PaymentReversalORM.idempotency_key == payload.idempotency_key))
        if existing:
            return validate_reversal_replay(_read_reversal(existing), payment_id, payload)
        if db.scalar(select(PaymentReversalORM).where(PaymentReversalORM.payment_id == payment_id)):
            raise ValidationError("Dieser Zahlungsbeleg wurde bereits storniert.") from None
        raise
    except Exception:
        if commit:
            db.rollback()
        raise


def import_payment(db: Session, payment: Payment) -> Payment:
    if payment.credit_receipt_id:
        from ..services.payments import FinancialConsistencyError
        raise FinancialConsistencyError("Guthabenverrechnungen benötigen das vollständige Serverbackup.")
    _, target = _target(db, payment.entity_type, payment.entity_id)
    existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payment.idempotency_key))
    if existing:
        restored = validate_replay(_read(db, existing), payment.entity_type, payment.entity_id, payment)
        if restored.reversal != payment.reversal:
            raise ValidationError("Der Zahlungsbeleg enthält abweichende Stornodaten.")
        return restored
    try:
        if payment.reversal and (payment.reversal.payment_id != payment.id or payment.reversal.amount != payment.amount):
            raise ValidationError("Stornobeleg und Zahlungsbeleg passen nicht zusammen.")
        if payment.booking_id:
            booking = _booking(db, payment.booking_id)
            # Restored bank counters derive from active receipts, never the snapshot field.
            from ..db.credit_models import CreditReceiptORM, CreditReversalORM
            from ..services.credit_ledger import money
            active = sum((Decimal(str(amount)) for amount in db.scalars(select(PaymentORM.amount).outerjoin(PaymentReversalORM,
                PaymentReversalORM.payment_id == PaymentORM.id).where(PaymentORM.booking_id == payment.booking_id,
                    PaymentReversalORM.id.is_(None)))), Decimal("0"))
            active += sum((money(int(amount)) for amount in db.scalars(select(CreditReceiptORM.amount_cents)
                .outerjoin(CreditReversalORM, CreditReversalORM.receipt_id == CreditReceiptORM.id)
                .where(CreditReceiptORM.booking_id == payment.booking_id, CreditReversalORM.id.is_(None)))), Decimal("0"))
            from .sql_store import SQLAlchemyStore
            allocated = validate_payment_booking(SQLAlchemyStore(db), payment.entity_type, target, booking,
                Decimal("0") if payment.reversal else payment.amount, allocated=active)
            _update_booking(db, booking, allocated)
        db.add(PaymentORM(**payment.model_dump(exclude={"entity_type", "entity_id", "reversal", "credit_receipt_id"}),
                          **{f"{payment.entity_type}_id": payment.entity_id}))
        db.flush()
        if payment.reversal:
            db.add(PaymentReversalORM(**payment.reversal.model_dump()))
            db.flush()
        db.commit()
        db.expire_all()
        return payment
    except Exception:
        db.rollback()
        raise
