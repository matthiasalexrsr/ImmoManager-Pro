"""Real, immutable credit receipts, serialized with billing revision posting.

A positive revision reserves only credit in its own root-statement chain.
Offsets consume that reservation through a real payment, in the same transaction.
"""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from ..db.credit_models import CreditReceiptORM, CreditReversalORM
from ..db.orm_models import BillingSettlementORM, ContractORM, ReceivableORM
from ..storage import NotFoundError, ValidationError
from .credit_types import CreditOffsetCreate, CreditPayoutCreate, CreditReceipt, CreditReversal, CreditReversalCreate
from .payments import FinancialConsistencyError, PaymentCreate, PaymentReversalCreate, _memory_lock


def cents(value) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise FinancialConsistencyError("Ungültiger Geldbetrag im Guthabenjournal.")
    with localcontext() as ctx:
        ctx.prec = max(28, len(amount.as_tuple().digits) + 3)
        scaled = amount * 100
        if scaled != scaled.to_integral_value():
            raise FinancialConsistencyError("Das Guthabenjournal enthält Bruchteile eines Cents.")
        return int(scaled)


def money(value: int) -> Decimal:
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value), 100)
    return Decimal(f"{sign}{whole}.{remainder:02d}")


def lock_contract(db, contract_id):
    """A DML lock works across PG sessions and SQLite, without invalidating ETags."""
    if db.get_bind().dialect.name == "sqlite" and not db.connection().connection.driver_connection.in_transaction:
        db.execute(text("BEGIN IMMEDIATE"))
    result = db.execute(update(ContractORM).where(ContractORM.id == contract_id)
        .values(updated_at=ContractORM.updated_at).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise NotFoundError("Vertrag nicht gefunden")
    db.expire_all()


@contextmanager
def atomic_credit(store, contract_id):
    if hasattr(store, "db"):
        try:
            lock_contract(store.db, contract_id)
            yield
            store.db.commit()
            store.db.expire_all()
        except Exception:
            store.db.rollback()
            raise
    else:
        with _memory_lock:
            names = ("payments", "credit_receipts", "credit_reversals", "bookings", "receivables", "rent_charges")
            before = {name: deepcopy(getattr(store, name)) for name in names}
            try:
                store.get_contract(contract_id)
                yield
            except Exception:
                for name, values in before.items():
                    setattr(store, name, values)
                raise


def _read_reversal(row):
    values = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    values["amount"] = money(int(values.pop("amount_cents")))
    if values["created_at"].tzinfo is None:
        values["created_at"] = values["created_at"].replace(tzinfo=timezone.utc)
    return CreditReversal(**values)


def _read_with_reversal(row, reversal):
    values = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    values["amount"] = money(int(values.pop("amount_cents")))
    if values["created_at"].tzinfo is None:
        values["created_at"] = values["created_at"].replace(tzinfo=timezone.utc)
    return CreditReceipt(**values, reversal=_read_reversal(reversal) if reversal else None)


def _read(store, row):
    if not hasattr(store, "db"):
        reversal = next((r for r in store.credit_reversals.values() if r.receipt_id == row.id), None)
        return row.model_copy(update={"reversal": reversal})
    reversal = store.db.scalar(select(CreditReversalORM).where(CreditReversalORM.receipt_id == row.id))
    return _read_with_reversal(row, reversal)


def _receipts(store, contract_id=None):
    if hasattr(store, "db"):
        query = select(CreditReceiptORM, CreditReversalORM).outerjoin(
            CreditReversalORM, CreditReversalORM.receipt_id == CreditReceiptORM.id
        ).order_by(CreditReceiptORM.transaction_date, CreditReceiptORM.created_at, CreditReceiptORM.id)
        if contract_id:
            query = query.where(CreditReceiptORM.contract_id == contract_id)
        return [_read_with_reversal(row, reversal) for row, reversal in store.db.execute(query)]
    return sorted((_read(store, row) for row in store.credit_receipts.values()
        if contract_id is None or row.contract_id == contract_id), key=lambda r: (r.transaction_date, r.created_at, r.id))


def _source(store, source_id):
    if hasattr(store, "db"):
        source = store.db.get(BillingSettlementORM, source_id, populate_existing=True)
    else:
        source = store.billing_settlements.get(source_id)
    if source is None:
        raise NotFoundError("Guthabenquelle nicht gefunden")
    if source.kind != "credit" or source.status != "credit_available" or cents(source.signed_amount) >= 0:
        raise FinancialConsistencyError("Nur gebuchte Abrechnungsguthaben können verwendet werden.")
    return source


def _settlements(store, contract_id):
    if hasattr(store, "db"):
        return list(store.db.scalars(select(BillingSettlementORM).where(BillingSettlementORM.contract_id == contract_id)))
    return [row for row in store.billing_settlements.values() if row.contract_id == contract_id]


def summary(store, contract_id, *, locked=False):
    if not locked:
        with atomic_credit(store, contract_id):
            return summary(store, contract_id, locked=True)
    store.get_contract(contract_id)
    with nullcontext() if hasattr(store, "db") else _memory_lock:
        spent: dict[str, int] = {}
        if hasattr(store, "db"):
            query = (select(CreditReceiptORM.source_settlement_id, CreditReceiptORM.amount_cents)
                .outerjoin(CreditReversalORM, CreditReversalORM.receipt_id == CreditReceiptORM.id)
                .where(CreditReceiptORM.contract_id == contract_id, CreditReversalORM.id.is_(None)))
            for source_id, amount_cents in store.db.execute(query):
                spent[source_id] = spent.get(source_id, 0) + int(amount_cents)
            claim_rows = {r.id: r for r in store.db.scalars(select(ReceivableORM).join(BillingSettlementORM,
                BillingSettlementORM.receivable_id == ReceivableORM.id).where(BillingSettlementORM.contract_id == contract_id))}
        else:
            claim_rows = store.receivables
            for receipt in _receipts(store, contract_id):
                if receipt.reversal is None:
                    spent[receipt.source_settlement_id] = spent.get(receipt.source_settlement_id, 0) + cents(receipt.amount)
        roots: dict[str, dict[str, Any]] = {}
        sources = []
        for row in _settlements(store, contract_id):
            root = roots.setdefault(row.root_statement_id, {"remaining": 0, "reserved": 0, "claims": []})
            signed = cents(row.signed_amount)
            if signed < 0 and row.kind == "credit" and row.status == "credit_available":
                consumed = spent.get(row.id, 0)
                remaining = -signed - consumed
                if remaining < 0:
                    raise FinancialConsistencyError("Guthabenbelege überschreiten die gebuchte Guthabenquelle.")
                sources.append({"id": row.id, "root_statement_id": row.root_statement_id,
                    "original_amount": str(money(-signed)), "remaining_amount": str(money(remaining))})
                root["remaining"] += remaining
            elif signed > 0 and row.receivable_id:
                target = claim_rows.get(row.receivable_id)
                if target is None:
                    raise FinancialConsistencyError("Die gebuchte Korrekturforderung fehlt.")
                if target.status not in {"cancelled", "void"}:
                    outstanding = max(0, cents(target.amount_due) - cents(target.amount_paid))
                    root["reserved"] += outstanding
                    if outstanding:
                        root["claims"].append({"target_type": "receivable", "target_id": target.id,
                            "amount": str(money(outstanding))})
        for source in sources:
            root = roots[source["root_statement_id"]]
            source["available_amount"] = str(money(min(cents(source["remaining_amount"]), max(0, root["remaining"] - root["reserved"]))))
            source["reserved_claims"] = root["claims"]
        return {"contract_id": contract_id, "sources": sorted(sources, key=lambda row: row["id"]),
            "remaining_amount": str(money(sum(r["remaining"] for r in roots.values()))),
            "reserved_amount": str(money(sum(min(r["remaining"], r["reserved"]) for r in roots.values()))),
            "available_amount": str(money(sum(max(0, r["remaining"] - r["reserved"]) for r in roots.values())))}


def journal(store, contract_id, *, offset=0, limit=50):
    store.get_contract(contract_id)
    if hasattr(store, "db"):
        total = store.db.scalar(select(func.count()).select_from(CreditReceiptORM)
            .where(CreditReceiptORM.contract_id == contract_id))
        query = (select(CreditReceiptORM, CreditReversalORM).outerjoin(
                CreditReversalORM, CreditReversalORM.receipt_id == CreditReceiptORM.id)
            .where(CreditReceiptORM.contract_id == contract_id)
            .order_by(CreditReceiptORM.transaction_date, CreditReceiptORM.created_at, CreditReceiptORM.id)
            .offset(offset).limit(limit))
        return {"contract_id": contract_id, "total": total,
            "receipts": [_read_with_reversal(row, reversal) for row, reversal in store.db.execute(query)]}
    rows = _receipts(store, contract_id)
    return {"contract_id": contract_id, "total": len(rows), "receipts": rows[offset:offset + limit]}


def _by_key(store, key):
    if hasattr(store, "db"):
        row = store.db.scalar(select(CreditReceiptORM).where(CreditReceiptORM.idempotency_key == key))
    else:
        row = store.credit_receipts.get(key)
    return _read(store, row) if row else None


def _replay(receipt, payload):
    fields = ("source_settlement_id", "amount", "transaction_date", "note")
    mismatch = any(getattr(receipt, field) != getattr(payload, field) for field in fields)
    if isinstance(payload, CreditPayoutCreate):
        mismatch |= receipt.method != payload.method or receipt.booking_id != payload.booking_id
    else:
        mismatch |= receipt.method != "offset" or receipt.target_type != payload.target_type or receipt.target_id != payload.target_id
    if mismatch:
        raise FinancialConsistencyError("Diese Belegreferenz wurde bereits für einen anderen Vorgang verwendet.")
    return receipt


def _booking_allocation(store, contract_id, booking_id, amount, *, release=False, transaction_date=None):
    if hasattr(store, "db"):
        from .credit_schema import require_negative_allocation_schema
        require_negative_allocation_schema(store.db.connection())
    from ..repositories.payment_repo import _booking, _update_booking
    booking = _booking(store.db, booking_id) if hasattr(store, "db") else store.get_booking(booking_id)
    contract = store.get_contract(contract_id)
    if booking.amount >= 0:
        raise FinancialConsistencyError("Eine Auszahlung benötigt eine negative Bankbuchung.")
    if transaction_date is not None and transaction_date != booking.booking_date:
        raise FinancialConsistencyError("Auszahlungsdatum und Bankbuchungsdatum müssen übereinstimmen.")
    # Undo restores the original allocation even if descriptive contract/account
    # assignments subsequently changed. The booking's own identity is guarded.
    if not release:
        if store.get_account(booking.account_id).portfolio_id != store.get_property(contract.property_id).portfolio_id:
            raise FinancialConsistencyError("Bankkonto und Vertrag gehören nicht zum selben Portfolio.")
        for field in ("tenant_id", "property_id", "unit_id"):
            if getattr(booking, field) and getattr(booking, field) != getattr(contract, field):
                raise FinancialConsistencyError("Die Bankbuchung gehört nicht zum gewählten Vertrag.")
    allocated = cents(booking.allocated_amount) + (-1 if release else 1) * amount
    if not 0 <= allocated <= -cents(booking.amount):
        raise FinancialConsistencyError("Das verfügbare Bankbuchungsbudget reicht nicht aus.")
    if hasattr(store, "db"):
        _update_booking(store.db, booking, money(allocated))
    else:
        booking.allocated_amount = float(money(allocated))
        booking.updated_at = datetime.now(timezone.utc)


def create_receipt(store, payload, actor_id=None):
    source = _source(store, payload.source_settlement_id)
    contract_id = source.contract_id
    try:
        with atomic_credit(store, contract_id):
            existing = _by_key(store, payload.idempotency_key)
            if existing:
                return _replay(existing, payload)
            data = summary(store, contract_id, locked=True)
            available = next(s for s in data["sources"] if s["id"] == source.id)
            allowed = Decimal(available["available_amount"])
            if isinstance(payload, CreditOffsetCreate):
                target = getattr(store, f"get_{payload.target_type}")(payload.target_id)
                if target.contract_id != contract_id:
                    raise FinancialConsistencyError("Eine Verrechnung muss zum Vertrag der Guthabenquelle gehören.")
                reserved = sum(cents(r["amount"]) for r in available["reserved_claims"]
                    if r["target_type"] == payload.target_type and r["target_id"] == payload.target_id)
                allowed = money(min(cents(available["remaining_amount"]), cents(allowed) + reserved))
            # Compare before expanding an input exponent: arbitrary amounts cannot allocate memory.
            if payload.amount > allowed:
                raise FinancialConsistencyError("Der Betrag überschreitet das aktuell verfügbare Guthaben.")
            receipt_id = str(uuid4())
            values = payload.model_dump(exclude={"confirmed_payment"})
            values.update(id=receipt_id, contract_id=contract_id, actor_id=actor_id, amount=money(cents(payload.amount)))
            if isinstance(payload, CreditOffsetCreate):
                from ..repositories.payment_repo import record_payment
                payment_command = PaymentCreate(idempotency_key=f"credit-offset:{receipt_id}", amount=payload.amount,
                    payment_date=payload.transaction_date, note=payload.note)
                payment = (record_payment(store.db, payload.target_type, payload.target_id, payment_command, commit=False,
                    expected_contract_id=contract_id)
                    if hasattr(store, "db") else store.record_payment(payload.target_type, payload.target_id, payment_command))
                values.update(method="offset", payment_id=payment.id)
                if not hasattr(store, "db"):
                    store.payments[payment.idempotency_key] = payment.model_copy(update={"credit_receipt_id": receipt_id})
            elif payload.booking_id:
                _booking_allocation(store, contract_id, payload.booking_id, cents(payload.amount), transaction_date=payload.transaction_date)
            receipt = CreditReceipt(**values)
            if hasattr(store, "db"):
                values.pop("amount")
                values["created_at"] = receipt.created_at.replace(tzinfo=None)
                store.db.add(CreditReceiptORM(**values, amount_cents=str(cents(payload.amount))))
                store.db.flush()
            else:
                store.credit_receipts[payload.idempotency_key] = receipt
            return receipt
    except IntegrityError as error:
        existing = _by_key(store, payload.idempotency_key)
        if existing:
            return _replay(existing, payload)
        raise FinancialConsistencyError("Der Vorgang wurde gleichzeitig geändert. Bitte neu laden.") from error
    except ValidationError as error:
        raise FinancialConsistencyError(str(error)) from error


def receipt_by_id(store, receipt_id):
    row = (store.db.get(CreditReceiptORM, receipt_id, populate_existing=True) if hasattr(store, "db")
        else next((r for r in store.credit_receipts.values() if r.id == receipt_id), None))
    if row is None:
        raise NotFoundError("Guthabenbeleg nicht gefunden")
    return _read(store, row)


def reverse_receipt(store, receipt_id, payload, actor_id=None):
    receipt = receipt_by_id(store, receipt_id)
    try:
        with atomic_credit(store, receipt.contract_id):
            receipt = receipt_by_id(store, receipt_id)
            row = (store.db.scalar(select(CreditReversalORM).where(CreditReversalORM.idempotency_key == payload.idempotency_key))
                if hasattr(store, "db") else store.credit_reversals.get(payload.idempotency_key))
            existing = _read_reversal(row) if row is not None and hasattr(store, "db") else row
            if existing:
                if existing.receipt_id != receipt_id or any(getattr(existing, key) != getattr(payload, key)
                        for key in CreditReversalCreate.model_fields):
                    raise FinancialConsistencyError("Diese Stornoreferenz gehört zu einem anderen Vorgang.")
                return existing
            if receipt.reversal:
                raise FinancialConsistencyError("Dieser Guthabenbeleg wurde bereits storniert.")
            payment_reversal_id = None
            if receipt.payment_id:
                from ..repositories.payment_repo import reverse_payment
                from .payments import reverse_memory_payment
                command = PaymentReversalCreate(**payload.model_dump())
                result = (reverse_payment(store.db, receipt.target_type, receipt.target_id, receipt.payment_id, command,
                    commit=False, credit_internal=True) if hasattr(store, "db") else
                    reverse_memory_payment(store, receipt.target_type, receipt.target_id, receipt.payment_id, command, credit_internal=True))
                payment_reversal_id = result.id
            if receipt.booking_id:
                _booking_allocation(store, receipt.contract_id, receipt.booking_id, cents(receipt.amount), release=True)
            reversal = CreditReversal(id=str(uuid4()), receipt_id=receipt_id, amount=receipt.amount,
                actor_id=actor_id, payment_reversal_id=payment_reversal_id, **payload.model_dump())
            if hasattr(store, "db"):
                values = reversal.model_dump(exclude={"amount"})
                values["created_at"] = reversal.created_at.replace(tzinfo=None)
                store.db.add(CreditReversalORM(**values, amount_cents=str(cents(receipt.amount))))
                store.db.flush()
            else:
                store.credit_reversals[payload.idempotency_key] = reversal
            return reversal
    except IntegrityError as error:
        raise FinancialConsistencyError("Der Stornovorgang wurde gleichzeitig geändert. Bitte neu laden.") from error
    except ValidationError as error:
        raise FinancialConsistencyError(str(error)) from error


def reverse_linked_payment(store, payment, payload):
    receipt_id = payment.credit_receipt_id
    reversal = reverse_receipt(store, receipt_id, CreditReversalCreate(**payload.model_dump()))
    # Return the existing payment endpoint's documented response shape.
    if hasattr(store, "db"):
        from ..db.orm_models import PaymentReversalORM
        from ..repositories.payment_repo import _read_reversal
        return _read_reversal(store.db.get(PaymentReversalORM, reversal.payment_reversal_id))
    return next(p.reversal for p in store.payments.values() if p.id == payment.id)


def guard_partial_restore(store, data):
    """The business subset has no complete credit graph: reject before any mutation."""
    existing = (store.db.scalar(select(CreditReceiptORM.id).limit(1)) if hasattr(store, "db") else bool(store.credit_receipts))
    incoming = data.get("credit_receipts") or data.get("credit_reversals") or any(
        isinstance(row, dict) and row.get("credit_receipt_id") for row in data.get("payments", []))
    if existing or incoming:
        raise FinancialConsistencyError("Dieser JSON-Teilimport enthält kein vollständiges Guthabenjournal. Bitte das vollständige Serverbackup verwenden.")
