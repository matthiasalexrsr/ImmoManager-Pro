"""Atomically record a payment receipt and update its allocated balance."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.orm_models import PaymentORM, ReceivableORM, RentChargeORM
from ..services.payments import EntityType, Payment, PaymentCreate, next_balance, validate_replay
from ..storage import NotFoundError, ValidationError


def _read(row: PaymentORM) -> Payment:
    return Payment(
        id=row.id, idempotency_key=row.idempotency_key, amount=Decimal(str(row.amount)),
        payment_date=row.payment_date, note=row.note, created_at=row.created_at,
        entity_type="receivable" if row.receivable_id else "rent_charge",
        entity_id=row.receivable_id or row.rent_charge_id or "",
    )


def list_payments(db: Session, entity_type=None, entity_id=None) -> list[Payment]:
    query = select(PaymentORM).order_by(PaymentORM.payment_date, PaymentORM.created_at, PaymentORM.id)
    if entity_type:
        column = PaymentORM.receivable_id if entity_type == "receivable" else PaymentORM.rent_charge_id
        query = query.where(column == entity_id) if entity_id else query.where(column.is_not(None))
    return [_read(row) for row in db.scalars(query)]


def record_payment(db: Session, entity_type: EntityType, entity_id: str, payload: PaymentCreate) -> Payment:
    target_class = ReceivableORM if entity_type == "receivable" else RentChargeORM
    target = cast(ReceivableORM | RentChargeORM | None, db.get(target_class, entity_id, populate_existing=True))
    if target is None:
        raise NotFoundError("Zahlungsposten nicht gefunden")
    existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payload.idempotency_key))
    if existing:
        return validate_replay(_read(existing), entity_type, entity_id, payload)
    paid, status = next_balance(entity_type, target, payload)
    # Compare-and-swap prevents simultaneous requests from losing a payment.
    predicates = [target_class.id == entity_id, getattr(target_class, "amount_paid") == target.amount_paid,
                  getattr(target_class, "status") == target.status]
    for field in ("amount_due",) if entity_type == "receivable" else (
        "cold_rent", "service_charge", "heating_charge", "other_charges"
    ):
        predicates.append(getattr(target_class, field) == getattr(target, field))
    try:
        result = db.execute(update(target_class).where(*predicates).values(
            amount_paid=float(paid), status=status, updated_at=datetime.now(timezone.utc)
        ).execution_options(synchronize_session=False))
        if cast(CursorResult, result).rowcount != 1:
            db.rollback()
            existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payload.idempotency_key))
            if existing:
                return validate_replay(_read(existing), entity_type, entity_id, payload)
            raise ValidationError("Der Posten wurde zwischenzeitlich geändert. Bitte neu laden.")
        row = PaymentORM(id=str(uuid4()), **payload.model_dump(), **{f"{entity_type}_id": entity_id})
        db.add(row)
        db.flush()
        payment = _read(row)
        db.commit()
        db.expire_all()
        return payment
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == payload.idempotency_key))
        if existing:
            return validate_replay(_read(existing), entity_type, entity_id, payload)
        raise
    except Exception:
        db.rollback()
        raise
