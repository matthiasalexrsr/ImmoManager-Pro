"""Bounded explainable bank suggestions and deliberate central-ledger payments.

Suggestions never mutate balances. Signed review binds current sources, scope
and target; confirmation uses the existing serialized payment/reversal ledger.
"""
import hashlib
import heapq
import hmac
import json
import re
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from time import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, case, func, literal, or_, select

from .. import models as domain
from ..db.booking_order import bytewise_id
from ..db.orm_models import (
    AccountORM,
    ContractORM,
    InvoiceORM,
    PaymentORM,
    PropertyORM,
    ReceivableORM,
    RentChargeORM,
    TenantORM,
)
from ..permissions import may_write_resource
from ..storage import NotFoundError, ValidationError
from .booking_query import _ID, _b64, _signature, _unb64, maximum_page_size
from .credit_ledger import cents
from .payments import PaymentCreate, _memory_lock, payment_total, validate_replay
from .portfolio_scope import current_scope, refresh_scope, scope_context, scoped_clause

Kind = Literal["rent_charge", "receivable", "invoice"]
LIFETIME = 3600
MODELS: dict[Kind, Any] = {"rent_charge": RentChargeORM, "receivable": ReceivableORM, "invoice": InvoiceORM}


class MatchError(ValidationError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


class SuggestionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind = "rent_charge"
    search: str | None = Field(None, max_length=200)
    page_size: int = Field(25, ge=1, le=5000)
    cursor: str | None = Field(None, min_length=1, max_length=4096)

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        if value and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Search must not contain control characters")
        return value.strip() or None if value else None


class MatchConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_token: str = Field(min_length=1, max_length=4096)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    idempotency_key: str = Field(min_length=1, max_length=100)
    note: str | None = Field(None, max_length=2000)


class MatchCandidate(BaseModel):
    kind: Kind
    id: str
    label: str
    reference: str | None
    property_label: str | None
    due_date: date
    open_cents: int = Field(gt=0)
    suggested_cents: int = Field(gt=0)
    score: int = Field(ge=0)
    reasons: list[Literal["reference", "amount_exact", "same_portfolio", "unassigned_property", "assigned_property", "partial_payment"]]
    review_token: str


class SuggestionPage(BaseModel):
    booking_id: str
    available_cents: int = Field(ge=0)
    items: list[MatchCandidate]
    next_cursor: str | None
    has_more: bool
    ambiguous: bool
    source_hash: str


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _scope_key(scope):
    return [scope.user_id, scope.role, scope.unrestricted, list(scope.portfolio_ids)] if scope else None


def _sign(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _b64(body) + "." + _b64(_signature(body))


def _read(token, version):
    try:
        body, signature = token.split(".")
        raw = _unb64(body)
        if not hmac.compare_digest(_unb64(signature), _signature(raw)):
            raise ValueError("Invalid signature")
        value = json.loads(raw)
        if value["v"] != version or type(value["expires"]) is not int:
            raise ValueError("Invalid version")
        if time() >= value["expires"]:
            raise MatchError("MATCH_REVIEW_EXPIRED", "Die Prüfung ist abgelaufen. Vorschläge erneut laden.", 400)
        return value
    except MatchError:
        raise
    except (TypeError, ValueError, KeyError):
        raise MatchError("MATCH_REVIEW_INVALID", "Prüfung konnte nicht verifiziert werden. Vorschläge erneut laden.", 400) from None


def _source(store, booking_id, scope, *, lock=False):
    refresh_scope(scope)
    booking = store.get_booking(booking_id)
    account = store.get_account(booking.account_id)
    if lock and hasattr(store, "db"):
        if store.db.scalar(select(AccountORM.id).where(AccountORM.id == account.id).with_for_update()) is None:
            raise NotFoundError("Bankkonto nicht gefunden")
        account = store.get_account(account.id)
    if booking.status in {"cancelled", "void"}:
        raise MatchError("MATCH_BOOKING_CLOSED", "Die Bankbuchung ist storniert oder abgeschlossen.")
    available = abs(cents(booking.amount)) - cents(booking.allocated_amount)
    fields = ("id", "account_id", "amount", "allocated_amount", "booking_date", "property_id", "tenant_id", "unit_id", "payment_text", "status", "updated_at")
    signature = digest([{field: getattr(booking, field) for field in fields}, account.id, account.portfolio_id,
        digest("".join((account.iban or "").split()).upper()), _scope_key(scope)])
    return booking, account, available, signature


def _target(store, kind, identifier, *, lock=False):
    target = getattr(store, f"get_{kind}")(identifier)
    if kind == "invoice":
        parent = store.get_property(target.property_id) if target.property_id else None
        contract = None
    else:
        contract = store.get_contract(target.contract_id)
        parent = store.get_property(contract.property_id)
    if lock and parent is not None and hasattr(store, "db"):
        if store.db.scalar(select(PropertyORM.id).where(PropertyORM.id == parent.id).with_for_update()) is None:
            raise NotFoundError("Zahlungsobjekt nicht gefunden")
        parent = store.get_property(parent.id)
    return target, parent, _target_hash(target, parent, contract)


def _target_hash(target, parent, contract=None):
    return digest([target.model_dump(), contract.model_dump() if contract else None,
        [parent.id, parent.portfolio_id] if parent else None])


def _domain_row(model, row):
    return model.model_validate({column.key: getattr(row, column.key) for column in row.__table__.columns}) if row else None


def _compatible(store, booking, account, kind, target, parent):
    if (kind == "invoice") != (cents(booking.amount) < 0):
        return False
    if parent and parent.portfolio_id != account.portfolio_id:
        return False
    reference = target if kind == "invoice" else store.get_contract(target.contract_id)
    fields = ("property_id",) if kind == "invoice" else ("property_id", "tenant_id", "unit_id")
    return all(not getattr(booking, field) or getattr(reference, field) == getattr(booking, field) for field in fields)


def _score_sql(booking, kind, model, open_amount):
    text = (booking.payment_text or "").lower()
    references = (model.payment_reference, model.invoice_number) if kind == "invoice" else (ContractORM.contract_number,)
    ref = or_(*(and_(field.is_not(None), field != "", func.instr(literal(text), func.lower(field)) > 0) for field in references))
    exact = func.round(open_amount * 100) == abs(cents(booking.amount)) - cents(booking.allocated_amount)
    score = case((ref, 8), else_=0) + case((exact, 4), else_=0)
    return score, ref, exact


def _sql_rows(store, booking, account, available, query, after, scope):
    model = MODELS[query.kind]
    day: Any
    statement: Any
    if query.kind == "invoice":
        total = model.gross_amount
        day = func.coalesce(model.due_date, model.invoice_date)
        label = model.supplier
        statement = select(model, PropertyORM).outerjoin(PropertyORM, model.property_id == PropertyORM.id)
        parents = or_(PropertyORM.portfolio_id == account.portfolio_id, model.property_id.is_(None))
    else:
        total = model.amount_due if query.kind == "receivable" else model.cold_rent + model.service_charge + model.heating_charge + model.other_charges
        day = model.due_date if query.kind == "receivable" else func.date(model.month + "-01")
        label = TenantORM.full_name
        statement = select(model, ContractORM, PropertyORM).join(ContractORM, model.contract_id == ContractORM.id).join(PropertyORM, ContractORM.property_id == PropertyORM.id).join(TenantORM, ContractORM.tenant_id == TenantORM.id)
        parents = PropertyORM.portfolio_id == account.portfolio_id
    open_amount = total - model.amount_paid
    score, ref, exact = _score_sql(booking, query.kind, model, open_amount)
    if store.db.get_bind().dialect.name == "postgresql":
        text = (booking.payment_text or "").lower()
        fields = (model.payment_reference, model.invoice_number) if query.kind == "invoice" else (ContractORM.contract_number,)
        ref = or_(*(and_(field.is_not(None), field != "", func.strpos(literal(text), func.lower(field)) > 0) for field in fields))
        score = case((ref, 8), else_=0) + case((exact, 4), else_=0)
        if query.kind == "rent_charge":
            from sqlalchemy import Date, cast
            day = cast(model.month + "-01", Date)
    statement = statement.add_columns(score.label("score"), day.label("day"), label.label("label"), ref.label("reference"), exact.label("exact"))
    statement = statement.where(parents, model.status.not_in(["paid", "cancelled", "void"]), open_amount > 0)
    predicate = scoped_clause(model, scope=scope)
    if predicate is not None:
        statement = statement.where(predicate)
    reference = model if query.kind == "invoice" else ContractORM
    for field in (("property_id",) if query.kind == "invoice" else ("property_id", "tenant_id", "unit_id")):
        if getattr(booking, field):
            statement = statement.where(getattr(reference, field) == getattr(booking, field))
    if query.search:
        escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_fields = (model.supplier, model.invoice_number, model.payment_reference, model.id) if query.kind == "invoice" else (TenantORM.full_name, ContractORM.contract_number, model.id)
        statement = statement.where(or_(*(field.ilike(f"%{escaped}%", escape="\\") for field in search_fields)))
    if after:
        rank, last_day, identifier = after
        position_day = date.fromisoformat(last_day) if store.db.get_bind().dialect.name == "postgresql" else last_day
        statement = statement.where(or_(score < rank, and_(score == rank, day > position_day),
            and_(score == rank, day == position_day, bytewise_id(model.id) > identifier)))
    with store.db.no_autoflush:
        rows = store.db.execute(statement.order_by(score.desc(), day, bytewise_id(model.id))
            .limit(query.page_size + 1).execution_options(populate_existing=True)).all()
    result = []
    for row in rows:
        target = row[0]
        day_value = row.day.isoformat() if isinstance(row.day, date) else str(row.day)
        read_model = {"invoice": domain.Invoice, "receivable": domain.Receivable, "rent_charge": domain.RentCharge}[query.kind]
        parsed = _domain_row(read_model, target)
        parent = _domain_row(domain.Property, row[1] if query.kind == "invoice" else row[2])
        contract = None if query.kind == "invoice" else _domain_row(domain.Contract, row[1])
        result.append((target.id, row.score, day_value, row.label, bool(row.reference), bool(row.exact),
            parsed, parent, _target_hash(parsed, parent, contract), parsed.invoice_number if contract is None else contract.contract_number))
    return result


def _memory_rows(store, booking, account, available, query, after, scope):
    def candidates():
        collection = {"invoice": "invoices", "receivable": "receivables", "rent_charge": "rent_charges"}[query.kind]
        for item in getattr(store, collection).values():
            target, parent, target_hash = _target(store, query.kind, item.id)
            if not _compatible(store, booking, account, query.kind, target, parent):
                continue
            outstanding = cents(payment_total(query.kind, target)) - cents(target.amount_paid)
            if target.status in {"paid", "cancelled", "void"} or outstanding <= 0:
                continue
            contract = None if query.kind == "invoice" else store.get_contract(target.contract_id)
            label = target.supplier if contract is None else store.get_tenant(contract.tenant_id).full_name
            references = (target.payment_reference, target.invoice_number) if contract is None else (contract.contract_number,)
            if query.search and query.search.lower() not in " ".join([label, target.id, *(value or "" for value in references)]).lower():
                continue
            reference = any(value and value.lower() in (booking.payment_text or "").lower() for value in references)
            exact = outstanding == available
            rank = 8 * bool(reference) + 4 * exact
            day = (target.due_date or target.invoice_date).isoformat() if contract is None else target.due_date.isoformat() if query.kind == "receivable" else target.month + "-01"
            key = (-rank, day, target.id.encode())
            if after and key <= (-after[0], after[1], after[2].encode()):
                continue
            yield (target.id, rank, day, label, bool(reference), exact, target, parent, target_hash,
                target.invoice_number if contract is None else contract.contract_number)
    return heapq.nsmallest(query.page_size + 1, candidates(), key=lambda row: (-row[1], row[2], row[0].encode()))


def suggestions(store, booking_id, query, *, scope=None):
    scope = scope if scope is not None else current_scope()
    refresh_scope(scope)
    if query.page_size > maximum_page_size():
        raise MatchError("MATCH_PAGE_SIZE", "Eine kleinere Seite wählen; weitere Seiten bleiben verfügbar.", 400)
    with scope_context(scope), (_memory_lock if not hasattr(store, "db") else nullcontext()):
        booking, account, available, source_hash = _source(store, booking_id, scope)
        binding = digest([source_hash, query.model_dump(exclude={"cursor"})])
        after = None
        if query.cursor:
            position = _read(query.cursor, "bank-suggestions-v1")
            if position.get("binding") != binding:
                raise MatchError("MATCH_SOURCE_CHANGED", "Quelle, Filter oder Zugriffsrechte wurden geändert. Neu prüfen.")
            after = position.get("after")
            if not isinstance(after, list) or len(after) != 3 or type(after[0]) is not int or not re.fullmatch(_ID, str(after[2])):
                raise MatchError("MATCH_REVIEW_INVALID", "Fortsetzungsposition ist ungültig.", 400)
            try:
                date.fromisoformat(after[1])
            except (ValueError, TypeError):
                raise MatchError("MATCH_REVIEW_INVALID", "Fortsetzungsdatum ist ungültig.", 400) from None
        rows = [] if available <= 0 or ((query.kind == "invoice") != (cents(booking.amount) < 0)) else (
            _sql_rows(store, booking, account, available, query, after, scope) if hasattr(store, "db") else
            _memory_rows(store, booking, account, available, query, after, scope))
        has_more = len(rows) > query.page_size
        items = []
        for identifier, rank, day, label, reference, exact, target, parent, target_hash, target_reference in rows[:query.page_size]:
            remaining = cents(payment_total(query.kind, target)) - cents(target.amount_paid)
            reasons = ["reference"] if reference else []
            if exact:
                reasons.append("amount_exact")
            if parent:
                reasons.append("same_portfolio")
            else:
                reasons.append("unassigned_property")
            if booking.property_id:
                reasons.append("assigned_property")
            if remaining > available:
                reasons.append("partial_payment")
            review = _sign({"v": "bank-match-v1", "expires": int(time()) + LIFETIME,
                "booking": booking_id, "source": source_hash, "kind": query.kind, "target": identifier, "target_hash": target_hash})
            items.append({"kind": query.kind, "id": identifier, "label": label, "due_date": day,
                "reference": target_reference, "property_label": parent.name if parent else None,
                "open_cents": remaining, "suggested_cents": min(available, remaining), "score": rank,
                "reasons": reasons, "review_token": review})
        cursor = _sign({"v": "bank-suggestions-v1", "binding": binding,
            "after": [rows[query.page_size-1][1], rows[query.page_size-1][2], rows[query.page_size-1][0]],
            "expires": int(time()) + LIFETIME}) if has_more else None
        return {"booking_id": booking_id, "available_cents": available, "items": items,
            "next_cursor": cursor, "has_more": has_more,
            "ambiguous": len(rows) > 1 and rows[0][1] == rows[1][1], "source_hash": source_hash}


def confirm_match(store, booking_id, command, *, scope=None):
    scope = scope if scope is not None else current_scope()
    refresh_scope(scope)
    if scope and not may_write_resource(scope.role, "bookings"):
        raise MatchError("MATCH_WRITE_DENIED", "Keine Berechtigung zur Bankzuordnung.", 403)
    proof = _read(command.review_token, "bank-match-v1")
    if proof.get("booking") != booking_id or proof.get("kind") not in MODELS or not re.fullmatch(_ID, str(proof.get("target"))):
        raise MatchError("MATCH_REVIEW_INVALID", "Die Prüfung gehört nicht zu dieser Bankbuchung.", 400)
    kind, identifier = proof["kind"], proof["target"]
    with scope_context(scope), (_memory_lock if not hasattr(store, "db") else nullcontext()):
        try:
            if hasattr(store, "db"):
                from ..repositories.payment_repo import _booking, _lock_target
                _lock_target(store.db, kind, identifier)
                _booking(store.db, booking_id)
            booking, account, available, source_hash = _source(store, booking_id, scope, lock=True)
            target, parent, target_hash = _target(store, kind, identifier, lock=True)
            payload = PaymentCreate(idempotency_key=command.idempotency_key, amount=command.amount,
                booking_id=booking_id, payment_date=booking.booking_date, note=command.note)
            existing = store.db.scalar(select(PaymentORM).where(PaymentORM.idempotency_key == command.idempotency_key)) if hasattr(store, "db") else store.payments.get(command.idempotency_key)
            if existing:
                if hasattr(store, "db"):
                    from ..repositories.payment_repo import _read as read_receipt
                    existing = read_receipt(store.db, existing)
                return validate_replay(existing, kind, identifier, payload)
            if proof.get("source") != source_hash or proof.get("target_hash") != target_hash:
                raise MatchError("MATCH_SOURCE_CHANGED", "Bankbuchung oder Zahlungsposten wurden geändert. Vorschläge erneut prüfen.")
            if not _compatible(store, booking, account, kind, target, parent):
                raise MatchError("MATCH_TARGET_CHANGED", "Kontozuordnung und Zahlungsposten passen nicht mehr zusammen.")
            if cents(command.amount) > min(available, cents(payment_total(kind, target)) - cents(target.amount_paid)):
                raise MatchError("MATCH_AMOUNT_CHANGED", "Der gewählte Betrag übersteigt den geprüften offenen Betrag.")
            if hasattr(store, "db"):
                from ..repositories.payment_repo import record_payment
                receipt = record_payment(store.db, kind, identifier, payload, commit=False)
                refresh_scope(scope)
                _source(store, booking_id, scope, lock=True)
                store.db.commit()
                store.db.expire_all()
                return receipt
            refresh_scope(scope)
            return store.record_payment(kind, identifier, payload)
        except BaseException:
            if hasattr(store, "db"):
                store.db.rollback()
            raise
