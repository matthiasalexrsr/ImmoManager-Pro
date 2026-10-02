"""Bounded reads from the existing immutable receipt/reversal ledger."""
import heapq
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from time import time
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, case, cast, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.credit_models import CreditReceiptORM
from ..db.orm_models import PaymentORM, PaymentReversalORM
from .bank_matching import LIFETIME, MatchError, _read, _scope_key, _sign, digest
from .booking_query import maximum_page_size
from .payments import Payment, PaymentCreate, PaymentReversal, _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scope_context, scoped_clause


class PaymentHistoryQuery(BaseModel):
    page_size: int = Field(25, ge=1, le=5000)
    cursor: str | None = Field(None, min_length=1, max_length=4096)


class PaymentHistoryPage(BaseModel):
    items: list[Payment]
    next_cursor: str | None
    has_more: bool


def _stamp(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def payment_history(store, kind, identifier, query, *, scope=None):
    scope = scope if scope is not None else current_scope()
    refresh_scope(scope)
    if query.page_size > maximum_page_size():
        raise MatchError("MATCH_PAGE_SIZE", "Eine kleinere Belegseite wählen; weitere Seiten bleiben verfügbar.", 400)
    with scope_context(scope), (_memory_lock if not hasattr(store, "db") else nullcontext()):
        getattr(store, f"get_{kind}")(identifier)
        binding = digest([kind, identifier, _scope_key(scope)])
        after = None
        if query.cursor:
            cursor = _read(query.cursor, "payment-history-v1")
            if cursor.get("binding") != binding:
                raise MatchError("MATCH_SOURCE_CHANGED", "Die Belegauswahl oder Zugriffsrechte wurden geändert. Neu laden.")
            try:
                after = (_stamp(datetime.fromisoformat(cursor["after"][0])), cursor["after"][1])
                if not isinstance(after[1], str) or not after[1]:
                    raise ValueError("Invalid receipt identity")
            except (KeyError, TypeError, ValueError, IndexError):
                raise MatchError("MATCH_REVIEW_INVALID", "Die Belegposition ist ungültig. Neu laden.", 400) from None
        if hasattr(store, "db"):
            field = getattr(PaymentORM, f"{kind}_id")
            predicate = scoped_clause(PaymentORM, scope=scope)
            if predicate is not None:
                # A moved parent must not make a partial ledger look complete.
                # The explicit predicate is captured before entering the raw read.
                with scope_context(None):
                    hidden = store.db.scalar(select(PaymentORM.__table__.c.id).where(field == identifier, ~predicate).limit(1))
                if hidden:
                    raise HTTPException(403, "payment_history_scope_incomplete: Die Konto- und Objektbezüge durch die Verwaltung prüfen lassen.")
            statement = select(PaymentORM, PaymentReversalORM, CreditReceiptORM.id).outerjoin(PaymentReversalORM,
                PaymentReversalORM.payment_id == PaymentORM.id).outerjoin(CreditReceiptORM,
                CreditReceiptORM.payment_id == PaymentORM.id).where(field == identifier)
            chronology: Any = PaymentORM.created_at
            position = after[0] if after else None
            if store.db.get_bind().dialect.name == "sqlite":
                # CURRENT_TIMESTAMP stores whole seconds; ORM inserts append
                # six decimals. Normalize both spellings before keyset compare.
                raw_time = cast(PaymentORM.created_at, String)
                chronology = case((func.instr(raw_time, ".") > 0, raw_time), else_=raw_time + ".000000")
                position = after[0].isoformat(sep=" ", timespec="microseconds") if after else None
            if after:
                statement = statement.where(or_(chronology > position, and_(chronology == position,
                    bytewise_id(PaymentORM.id) > after[1])))
            with store.db.no_autoflush:
                rows = store.db.execute(statement.order_by(chronology, bytewise_id(PaymentORM.id))
                    .limit(query.page_size + 1).execution_options(populate_existing=True)).all()
            items = [Payment.model_validate({"id": receipt.id, "entity_type": "receivable" if receipt.receivable_id else "rent_charge" if receipt.rent_charge_id else "invoice",
                "entity_id": receipt.receivable_id or receipt.rent_charge_id or receipt.invoice_id,
                **{key: Decimal(str(getattr(receipt, key))) if key == "amount" else getattr(receipt, key) for key in PaymentCreate.model_fields},
                "created_at": receipt.created_at, "reversal": PaymentReversal.model_validate(reversal, from_attributes=True) if reversal else None,
                "credit_receipt_id": credit_id}) for receipt, reversal, credit_id in rows]
        else:
            def receipts():
                for item in object.__getattribute__(store, "__dict__")["payments"].values():
                    matches = item.booking_id == identifier if kind == "booking" else item.entity_type == kind and item.entity_id == identifier
                    if matches and not memory_visible(store, "payments", item, scope=scope):
                        raise HTTPException(403, "payment_history_scope_incomplete: Die Konto- und Objektbezüge durch die Verwaltung prüfen lassen.")
                    if matches and (after is None or (_stamp(item.created_at), item.id.encode()) > (after[0], after[1].encode())):
                        yield item
            items = heapq.nsmallest(query.page_size + 1, receipts(), key=lambda item: (_stamp(item.created_at), item.id.encode()))
        has_more = len(items) > query.page_size
        visible = items[:query.page_size]
        cursor = _sign({"v": "payment-history-v1", "binding": binding, "expires": int(time()) + LIFETIME,
            "after": [_stamp(visible[-1].created_at).isoformat(), visible[-1].id]}) if has_more else None
        refresh_scope(scope)
        return {"items": visible, "next_cursor": cursor, "has_more": has_more}
