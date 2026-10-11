"""Invoice review (Rechnungsprüfung): receipt → factual and arithmetic check → decision →
payment → dispute → result, on top of the existing invoices (docs/INVOICE_REVIEW_20261011.md).

* Receipt: a review row beside the existing invoice, with receipt date, original document
  (SHA-256 at receipt), Skonto and due date. Supplier and invoice number are the duplicate
  key: a receipt with the same key is refused unless acknowledged with a reason; same
  supplier, same amount and a near date is a warning.
* Factual check (sachlich): the order is the existing maintenance order link, the contract
  the existing service-contract bill; otherwise a free cost assignment. Deviations (over the
  order or change order, tariff vs. bill, overlapping periods) are findings.
* Arithmetic check (rechnerisch): net + VAT = gross per rate, the § 14 UStG checklist.
* Decision: approve, approve partially, reject, query the supplier, each recorded. Above the
  configured four-eyes limit only owner or manager approve, and never the person who checked.
* Payment: the existing invoice_payments; status paid/partially paid/overpaid and Skonto are
  derived. Only approved invoices are proposed for payment; nothing leaves the system.
* Dispute: the part not approved stays open until a credit note, an agreed partial payment
  or a write-off settles it.
* Result: approved amounts feed project figures and service contracts (flows()); a rejected
  invoice flows nowhere; a recoverable approved invoice enters the utility billing once.

Every write runs in one unit of work (maintenance_projects.work): the actor's account is
held and its rights checked against backend.permissions up to the commit, the invoice row is
locked, the portfolio boundary applies to every row read or written, and the step is
appended to the immutable history in the same transaction. Legacy invoices (no review row)
are never changed by reading them.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from .. import auth
from ..domain import invoice_review as rules
from ..domain.money import ZERO, as_number, cents, money
from ..invoice_review_models import (
    CheckRequest,
    CostTransferRequest,
    DecisionRequest,
    DisputeResolution,
    InvoiceCostTransfer,
    InvoiceReview,
    InvoiceReviewEvent,
    InvoiceReviewSettings,
    ReceiptPatch,
    ReceiptRequest,
    SettingsUpdate,
)
from ..permissions import may_write
from ..storage import NotFoundError
from .maintenance_projects import work
from .maintenance_rows import Rows, stamp

INVOICE_MISSING = "Rechnung nicht gefunden"
REVIEW_MISSING = "Für diese Rechnung wurde noch kein Rechnungseingang erfasst."
SETTINGS_ID = "default"
DECIDERS_ABOVE_LIMIT = ("eigentuemer", "verwalter")
PENDING = ("received", "query")
DECIDED = ("approved", "partially_approved", "rejected")
STATUS_LABELS = {"legacy": "nicht geprüft (Bestand)", "received": "Eingang erfasst", "query": "Rückfrage",
                 "approved": "freigegeben", "partially_approved": "teilweise freigegeben", "rejected": "abgelehnt"}
# invoice fields a decided review fixes (the old API may still change status, notes, category …)
FIXED_AFTER_DECISION = ("supplier", "invoice_number", "invoice_date", "net_amount", "vat_amount", "gross_amount",
                        "vat_rate", "property_id")


def conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def forbidden(message: str) -> HTTPException:
    return HTTPException(403, message)


def _amount_label(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _dump(record: Any) -> dict | None:
    return None if record is None else record.model_dump(mode="json")


# ─── Settings ────────────────────────────────────────────────────────────────

def _settings(rows: Rows) -> InvoiceReviewSettings:
    return rows.get("invoice_review_settings", SETTINGS_ID) or InvoiceReviewSettings(id=SETTINGS_ID)


def read_settings(store: Any) -> dict:
    return _settings(Rows.reading(store)).model_dump(mode="json")


def update_settings(store: Any, payload: SettingsUpdate, actor_id: str | None) -> dict:
    with work(store, actor_id, ("/invoice-review/settings",)) as unit:
        rows = Rows.of(unit)
        values = payload.model_dump()
        current = rows.get("invoice_review_settings", SETTINGS_ID)
        if current is None:
            record = InvoiceReviewSettings(id=SETTINGS_ID, updated_by=unit.user.get("id"), **values)
            rows.add("invoice_review_settings", record)
        else:
            record = rows.update("invoice_review_settings", SETTINGS_ID, updated_by=unit.user.get("id"), **values)
        return record.model_dump(mode="json")


# ─── History ─────────────────────────────────────────────────────────────────

def _event(rows: Rows, user: dict, invoice_id: str, action: str, *, status_after: str | None = None,
           amount: Decimal | None = None, reason: str | None = None, details: dict | None = None) -> None:
    """Append one step to the invoice's history (the invoice row is locked by the unit)."""
    seq = max((event.seq for event in rows.find("invoice_review_events", invoice_id=invoice_id)), default=0) + 1
    rows.add("invoice_review_events", InvoiceReviewEvent(
        id=str(uuid4()), invoice_id=invoice_id, seq=seq, action=action, status_after=status_after,
        amount=None if amount is None else float(amount), reason=reason, details=details or {},
        actor_id=user.get("id"), actor_name=user.get("full_name") or user.get("username"),
        actor_role=user.get("role"), created_at=stamp("invoice_review_events")))


# ─── Reading the surroundings of an invoice ──────────────────────────────────

@dataclass
class Links:
    order_link: Any = None
    order: Any = None
    contract_link: Any = None
    contract: Any = None


def _links(rows: Rows, invoice_id: str) -> Links:
    found = Links()
    order_links = rows.find("maintenance_order_invoices", invoice_id=invoice_id)
    if order_links:
        found.order_link = order_links[0]
        found.order = rows.get("maintenance_orders", found.order_link.order_id)
    contract_links = rows.find("service_contract_invoices", invoice_id=invoice_id)
    if contract_links:
        found.contract_link = contract_links[0]
        found.contract = rows.get("service_contracts", found.contract_link.service_contract_id)
    return found


def _effective_payments(rows: Rows, invoice_ids: list[str]) -> dict[str, list[rules.Payment]]:
    """Payments of the invoices: allocations of outgoing bookings, minus what reversals took back.

    A booking pays at most its amount less its reversals; its allocations (to any invoice)
    use that up in the order they were made, like the project figures (domain.project_costs).
    """
    allocations = rows.find("invoice_payments", invoice_id=invoice_ids)
    booking_ids = {a.booking_id for a in allocations}
    if not booking_ids:
        return {}
    bookings = {b.id: b for b in rows.find("bookings", id=booking_ids)}
    reversed_by: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for reversal in rows.find("bookings", reverses_booking_id=booking_ids):
        reversed_by[reversal.reverses_booking_id] += money(reversal.amount)
    left = {key: max(-(money(b.amount) + reversed_by[key]), ZERO) for key, b in bookings.items()}
    wanted = set(invoice_ids)
    found: dict[str, list[rules.Payment]] = defaultdict(list)
    every = rows.find("invoice_payments", booking_id=booking_ids)
    for allocation in sorted(every, key=lambda a: (str(a.created_at), a.id)):
        booking = bookings.get(allocation.booking_id)
        if booking is None:
            continue
        effective = min(money(allocation.amount), left[booking.id])
        left[booking.id] -= effective
        if allocation.invoice_id in wanted and effective > 0:
            found[allocation.invoice_id].append(rules.Payment(booking.booking_date, effective))
    return found


def _credit_totals(rows: Rows, invoice_ids: list[str]) -> dict[str, Decimal]:
    """Approved credit notes per invoice they reduce."""
    notes = [r for r in rows.find("invoice_reviews", credit_for_invoice_id=invoice_ids)
             if r.kind == "credit_note" and r.status == "approved"]
    invoices = {i.id: i for i in rows.find("invoices", id=[r.invoice_id for r in notes])}
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for note in notes:
        invoice = invoices.get(note.invoice_id)
        if invoice is not None:
            totals[note.credit_for_invoice_id] += abs(money(note.approved_amount if note.approved_amount is not None
                                                            else invoice.gross_amount))
    return totals


def _due_on(invoice: Any, review: Any) -> date | None:
    return invoice.due_date or (review.due_on if review is not None else None)


def _settle(invoice: Any, review: Any, payments: list[rules.Payment], credits: Decimal,
            today: date) -> rules.Settlement:
    if review is None:
        return rules.settle(gross=invoice.gross_amount, status="legacy", payments=payments,
                            due_on=invoice.due_date, today=today)
    return rules.settle(
        gross=invoice.gross_amount, status=review.status, approved=review.approved_amount, credits=credits,
        dispute_status=review.dispute_status, dispute_outcome=review.dispute_outcome,
        dispute_settled=review.dispute_settled_amount, payments=payments, skonto_percent=review.skonto_percent,
        skonto_until=review.skonto_until, due_on=_due_on(invoice, review), today=today,
        credit_note=review.kind == "credit_note")


def settlements(rows: Rows, invoices: Iterable[Any], today: date | None = None) -> dict[str, rules.Settlement]:
    invoices = list(invoices)
    ids = [i.id for i in invoices]
    reviews = {r.invoice_id: r for r in rows.find("invoice_reviews", invoice_id=ids)}
    payments = _effective_payments(rows, ids)
    credits = _credit_totals(rows, ids)
    today = today or date.today()
    return {i.id: _settle(i, reviews.get(i.id), payments.get(i.id, []), credits.get(i.id, ZERO), today)
            for i in invoices}


def flows(rows: Rows, invoices: Iterable[Any]) -> dict[str, tuple[str, Decimal]]:
    """What reviewed invoices contribute to other modules: {invoice id: (review status, amount)}.

    Legacy invoices are absent (callers keep using the gross amount). A rejected invoice and
    a credit note contribute nothing themselves; a credit note reduces its invoice instead.
    """
    invoices = list(invoices)
    reviews = {r.invoice_id: r for r in rows.find("invoice_reviews", invoice_id=[i.id for i in invoices])}
    reviewed = [i for i in invoices if i.id in reviews]
    if not reviewed:
        return {}
    found = {}
    for invoice_id, settlement in settlements(rows, reviewed).items():
        review = reviews[invoice_id]
        if review.kind == "credit_note":
            found[invoice_id] = ("credit_note", ZERO)
        else:
            amount = settlement.flow_amount()
            found[invoice_id] = (review.status, settlement.gross if amount is None else amount)
    return found


def flows_for(store: Any, invoices: Iterable[Any]) -> dict[str, tuple[str, Decimal]]:
    return flows(Rows.reading(store), invoices)


# ─── Duplicates ──────────────────────────────────────────────────────────────

def _invoice_facts(invoice: Any) -> rules.InvoiceFacts:
    return rules.InvoiceFacts(invoice.id, invoice.supplier, getattr(invoice, "invoice_number", None),
                              invoice.invoice_date, money(invoice.gross_amount))


def _duplicate_candidates(rows: Rows, store: Any, candidate: rules.InvoiceFacts, window: int) -> list[Any]:
    """Visible invoices that could be duplicates: same number, or same gross near the date."""
    number = rules.number_key(candidate.invoice_number)
    db = rows.db if rows.db is not None else getattr(store, "db", None)
    if db is not None:
        from sqlalchemy import and_, or_, select

        from ..db.orm_models import InvoiceORM

        number_column = InvoiceORM.__table__.c.invoice_number
        near = and_(InvoiceORM.gross_amount == float(candidate.gross),
                    InvoiceORM.invoice_date >= candidate.invoice_date - timedelta(days=window),
                    InvoiceORM.invoice_date <= candidate.invoice_date + timedelta(days=window))
        clauses = [near]
        if number:
            # the key compares loosely ("RE-0042" = "re 42"); the database narrows by the digits
            digits = "".join(ch for ch in number if ch.isdigit()).lstrip("0")
            clauses.append(number_column.ilike(f"%{digits or number}%"))
        query = select(InvoiceORM).where(or_(*clauses)).where(InvoiceORM.id != candidate.id).limit(500)
        return [rows._model("invoices", obj) for obj in db.scalars(query)]
    return [i for i in rows._collection("invoices").values() if i.id != candidate.id]


def find_duplicates(rows: Rows, store: Any, candidate: rules.InvoiceFacts, window: int) -> list[dict]:
    others = _duplicate_candidates(rows, store, candidate, window)
    return rules.duplicates(candidate, (_invoice_facts(i) for i in others), window)


def duplicate_check(store: Any, *, supplier: str, invoice_number: str | None, gross_amount: float,
                    invoice_date: date, exclude_invoice_id: str | None = None) -> dict:
    rows = Rows.reading(store)
    window = _settings(rows).duplicate_window_days
    candidate = rules.InvoiceFacts(exclude_invoice_id or "", supplier, invoice_number, invoice_date,
                                   money(gross_amount))
    return {"duplicates": find_duplicates(rows, store, candidate, window), "window_days": window}


# ─── The original document ───────────────────────────────────────────────────

def _file_digest(document: Any) -> str | None:
    from .file_storage import get_file_storage

    url = getattr(document, "file_url", None) or ""
    if not url.startswith("/uploads/"):
        return None
    try:
        content = get_file_storage().get(url.removeprefix("/uploads/"))
    except Exception:  # noqa: BLE001  (an unreadable file is reported, not fatal)
        return None
    return hashlib.sha256(content).hexdigest() if content is not None else None


# ─── Receipt ─────────────────────────────────────────────────────────────────

def _validate_place(unit: Any, values: dict) -> None:
    """Property and unit of the free assignment exist, are visible and belong together."""
    store = unit.store
    prop_id, unit_id = values.get("property_id"), values.get("unit_id")
    if prop_id:
        try:
            store.get_property(prop_id)
        except NotFoundError:
            raise NotFoundError("Objekt nicht gefunden") from None
    if unit_id:
        try:
            found = store.get_unit(unit_id)
        except NotFoundError:
            raise NotFoundError("Einheit nicht gefunden") from None
        if prop_id and found.property_id != prop_id:
            raise conflict("Die Einheit gehört nicht zu diesem Objekt.")
        if not prop_id:
            values["property_id"] = found.property_id


def _change_order_check(rows: Rows, invoice_id: str, change_order_id: str | None) -> None:
    if not change_order_id:
        return
    change = rows.get("maintenance_change_orders", change_order_id)
    if change is None:
        raise NotFoundError("Nachtrag nicht gefunden")
    link = _links(rows, invoice_id).order_link
    if link is None or link.order_id != change.order_id:
        raise conflict("Ein Nachtrag wird nur einer Rechnung zugeordnet, die seinem Auftrag zugeordnet ist.")
    if change.status != "approved":
        raise conflict("Der Nachtrag ist nicht genehmigt.")


def _terms(invoice: Any, values: dict, current: Any = None) -> dict:
    """Skonto deadline and due date from the invoice date (fixed now, refreshed when they change)."""
    percent = values.get("skonto_percent", getattr(current, "skonto_percent", None))
    days = values.get("skonto_days", getattr(current, "skonto_days", None))
    result = {"skonto_until": rules.skonto_terms(invoice.invoice_date, percent, days)}
    payment_days = values.pop("payment_days", None)
    if payment_days is not None:
        result["due_on"] = invoice.invoice_date + timedelta(days=payment_days)
    elif current is None:
        result["due_on"] = invoice.due_date
    return result


def start_review(store: Any, invoice_id: str | None, payload: ReceiptRequest, actor_id: str | None) -> dict:
    """Record the receipt of an invoice: of an existing one, or (payload.invoice) a new one."""
    from ..models import Invoice

    areas: tuple[str, ...]
    if invoice_id is None:
        if payload.invoice is None:
            raise conflict("Bitte die Rechnungsdaten angeben.")
        areas = ("/invoice-review/receipts", "/invoices")
    else:
        if payload.invoice is not None:
            raise conflict("Eine vorhandene Rechnung wird nicht neu erfasst.")
        areas = (f"/invoices/{invoice_id}/review",)
    with work(store, actor_id, areas) as unit:
        rows = Rows.of(unit)
        user = unit.user
        if payload.invoice is not None:
            draft = payload.invoice
            now = stamp("invoices")
            invoice = Invoice.model_validate({   # the UI contract fields come in at import time
                **draft.model_dump(), "id": str(uuid4()), "status": "open",
                "vat_amount": draft.vat_amount or float(money(draft.gross_amount) - money(draft.net_amount)),
                "source_document_id": payload.document_id, "created_at": now, "updated_at": now})
            rows.add("invoices", invoice)
        else:
            if not rows.lock("invoices", invoice_id or ""):
                raise NotFoundError(INVOICE_MISSING)
            invoice = rows.require("invoices", invoice_id, INVOICE_MISSING)
        if rows.find("invoice_reviews", invoice_id=invoice.id):
            raise conflict("Der Eingang dieser Rechnung ist bereits erfasst.")
        if invoice.status == "cancelled":
            raise conflict("Eine stornierte Rechnung wird nicht geprüft.")
        settings = _settings(rows)
        duplicates = find_duplicates(rows, unit.store, _invoice_facts(invoice), settings.duplicate_window_days)
        same_key = [d for d in duplicates if d["reason"] == "same_number"]
        if same_key and not payload.accept_duplicate:
            first = same_key[0]
            raise conflict(f"Rechnungsnummer und Lieferant sind bereits erfasst (Dublette: Rechnung "
                           f"{first['invoice_number']} vom {date.fromisoformat(first['invoice_date']):%d.%m.%Y}). "
                           "Nur mit Begründung trotzdem erfassen.")
        links = _links(rows, invoice.id)
        if payload.kind == "credit_note":
            target_id = payload.credit_for_invoice_id or ""
            target = rows.get("invoices", target_id)
            if target is None:
                raise NotFoundError("Die geminderte Rechnung wurde nicht gefunden")
            if target.id == invoice.id:
                raise conflict("Eine Gutschrift mindert eine andere Rechnung.")
            target_review = (rows.find("invoice_reviews", invoice_id=target.id) or [None])[0]
            if target_review is not None and target_review.kind == "credit_note":
                raise conflict("Eine Gutschrift mindert eine Rechnung, keine andere Gutschrift.")
            if links.order_link is not None or links.contract_link is not None:
                raise conflict("Eine Gutschrift wird keinem Auftrag und keinem Objektvertrag zugeordnet; sie mindert "
                               "die genannte Rechnung.")
        values = payload.model_dump(exclude={"invoice", "accept_duplicate", "duplicate_reason", "note", "kind",
                                             "credit_for_invoice_id"}, exclude_none=True)
        _validate_place(unit, values)
        if values.get("property_id") and invoice.property_id and values["property_id"] != invoice.property_id:
            raise conflict("Die Rechnung gehört bereits zu einem anderen Objekt; die Kostenstelle muss dazu passen.")
        _change_order_check(rows, invoice.id, values.get("change_order_id"))
        terms = _terms(invoice, values)
        document_id = payload.document_id or invoice.source_document_id
        digest = None
        if document_id:
            document = rows.get("documents", document_id)
            if document is None:
                raise NotFoundError("Beleg (Dokument) nicht gefunden")
            digest = _file_digest(document)
            if not invoice.source_document_id:
                rows.update("invoices", invoice.id, source_document_id=document_id)
        now = stamp("invoice_reviews")
        review = InvoiceReview(
            id=str(uuid4()), invoice_id=invoice.id, kind=payload.kind,
            credit_for_invoice_id=payload.credit_for_invoice_id, received_on=payload.received_on or date.today(),
            document_id=document_id, document_sha256=digest, status="received",
            vat_lines=[line.model_dump() for line in payload.vat_lines or []],
            skonto_percent=payload.skonto_percent, skonto_days=payload.skonto_days,
            property_id=values.get("property_id"), unit_id=values.get("unit_id"),
            cost_category=payload.cost_category, recoverable=bool(payload.recoverable),
            change_order_id=payload.change_order_id,
            duplicate_of_invoice_id=duplicates[0]["invoice_id"] if duplicates and payload.accept_duplicate else None,
            created_by=user.get("id"), created_at=now, updated_at=now, **terms)
        rows.add("invoice_reviews", review)
        _event(rows, user, invoice.id, "received", status_after="received", amount=money(invoice.gross_amount),
               reason=payload.note, details={
                   "kind": payload.kind, "received_on": review.received_on.isoformat(), "document_id": document_id,
                   "document_sha256": digest, "credit_for_invoice_id": payload.credit_for_invoice_id,
                   "supplier": invoice.supplier, "invoice_number": getattr(invoice, "invoice_number", None),
                   "created_invoice": payload.invoice is not None})
        if same_key or (duplicates and payload.accept_duplicate):
            _event(rows, user, invoice.id, "duplicate_acknowledged", status_after="received",
                   reason=payload.duplicate_reason, details={"duplicates": duplicates})
        return {"invoice": _dump(invoice), "review": _dump(review), "duplicates": duplicates}


class Reviewed:
    """The locked invoice of a write unit and its review."""

    def __init__(self, unit: Any, invoice_id: str):
        self.unit, self.rows = unit, Rows.of(unit)
        if not self.rows.lock("invoices", invoice_id):
            raise NotFoundError(INVOICE_MISSING)
        self.invoice = self.rows.require("invoices", invoice_id, INVOICE_MISSING)
        found = self.rows.find("invoice_reviews", invoice_id=invoice_id)
        if not found:
            raise conflict(REVIEW_MISSING)
        self.review = found[0]
        self.user: dict = unit.user

    @property
    def role(self) -> str | None:
        return self.user.get("role")

    def event(self, action: str, **kwargs: Any) -> None:
        _event(self.rows, self.user, self.invoice.id, action, **kwargs)

    def update(self, **changes: Any) -> Any:
        self.review = self.rows.update("invoice_reviews", self.review.id, **changes)
        return self.review

    def require_pending(self) -> None:
        if self.review.status not in PENDING:
            raise conflict(f"Über die Rechnung ist bereits entschieden ({STATUS_LABELS[self.review.status]}); "
                           "der Prüfverlauf bleibt unverändert.")


def _reviewed(store: Any, actor_id: str | None, invoice_id: str, *areas: str):
    from contextlib import contextmanager

    @contextmanager
    def unit_of_work():
        with work(store, actor_id, tuple(areas)) as unit:
            yield Reviewed(unit, invoice_id)

    return unit_of_work()


def patch_review(store: Any, invoice_id: str, payload: ReceiptPatch, actor_id: str | None) -> dict:
    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review") as r:
        r.require_pending()
        values = payload.model_dump(exclude_unset=True, exclude={"reason", "note"})
        if "vat_lines" in values:
            values["vat_lines"] = [line.model_dump() for line in payload.vat_lines or []]
        if not values:
            return _dump(r.review) or {}
        place = {key: values.get(key, getattr(r.review, key)) for key in ("property_id", "unit_id")}
        if "unit_id" in values and "property_id" not in values and values["unit_id"]:
            place["property_id"] = None
        _validate_place(r.unit, place)
        if place["property_id"] and r.invoice.property_id and place["property_id"] != r.invoice.property_id:
            raise conflict("Die Rechnung gehört bereits zu einem anderen Objekt; die Kostenstelle muss dazu passen.")
        values.update({k: v for k, v in place.items() if k in values or (k == "property_id" and "unit_id" in values)})
        if "change_order_id" in values:
            _change_order_check(r.rows, r.invoice.id, values["change_order_id"])
        if "document_id" in values:
            if values["document_id"]:
                document = r.rows.get("documents", values["document_id"])
                if document is None:
                    raise NotFoundError("Beleg (Dokument) nicht gefunden")
                values["document_sha256"] = _file_digest(document)
                if not r.invoice.source_document_id:
                    r.rows.update("invoices", r.invoice.id, source_document_id=document.id)
            else:
                values["document_sha256"] = None
        if {"skonto_percent", "skonto_days", "payment_days"} & set(values):
            values.update(_terms(r.invoice, values, r.review))
        values.pop("payment_days", None)
        if "recoverable" in values:
            values["recoverable"] = bool(values["recoverable"])
        before = {key: getattr(r.review, key) for key in values}
        r.update(**values)
        changed = {key: {"from": _plain(before[key]), "to": _plain(getattr(r.review, key))} for key in values
                   if before[key] != getattr(r.review, key)}
        if changed:
            r.event("receipt_changed", status_after=r.review.status, reason=payload.reason or payload.note,
                    details={"changes": changed})
        return _dump(r.review) or {}


def _plain(value: Any) -> Any:
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return as_number(value)
    return value


# ─── Checks ──────────────────────────────────────────────────────────────────

def _arithmetic(invoice: Any, review: Any) -> list[dict]:
    return rules.arithmetic_findings(invoice.net_amount, invoice.vat_amount, invoice.gross_amount,
                                     invoice.vat_rate, review.vat_lines if review is not None else None)


def _checklist(invoice: Any, review: Any, settings: InvoiceReviewSettings, has_period: bool) -> dict:
    errors = [f for f in _arithmetic(invoice, review) if f["severity"] == "error"]
    return rules.checklist(gross=invoice.gross_amount, invoice_date=invoice.invoice_date,
                           invoice_number=getattr(invoice, "invoice_number", None),
                           has_skonto=bool(review is not None and review.skonto_percent), arithmetic_ok=not errors,
                           has_service_period=has_period, small_limit=settings.small_invoice_limit,
                           manual=review.checklist if review is not None else None)


def factual_check(store: Any, invoice_id: str, payload: CheckRequest, actor_id: str | None) -> dict:
    if payload.checklist:
        raise conflict("Die Pflichtangaben nach § 14 UStG gehören zur rechnerischen Prüfung.")
    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review/factual-check") as r:
        r.require_pending()
        if r.review.kind == "credit_note":
            raise conflict("Eine Gutschrift braucht keine sachliche Prüfung.")
        links = _links(r.rows, invoice_id)
        if r.role == "techniker" and links.order_link is None:
            raise forbidden("Die Technik bestätigt die sachliche Prüfung nur für Rechnungen zu einem "
                            "Instandhaltungsauftrag.")
        findings = _factual_findings(r.rows, r.invoice, r.review, links)
        r.update(factual_result=payload.result, factual_note=payload.note, factual_by=r.user.get("id"),
                 factual_at=stamp("invoice_reviews"))
        r.event("factual_check", status_after=r.review.status, reason=payload.note, details={
            "result": payload.result, "assignment": _assignment(r.rows, r.invoice, r.review, links)["kind"],
            "findings": [f["code"] for f in findings]})
        return _dump(r.review) or {}


def arithmetic_check(store: Any, invoice_id: str, payload: CheckRequest, actor_id: str | None) -> dict:
    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review/arithmetic-check") as r:
        r.require_pending()
        keys = {key for key, _label, _small in rules.CHECKLIST} - rules.AUTOMATIC | {"invoice_number"}
        manual = dict(r.review.checklist or {})
        for key, value in (payload.checklist or {}).items():
            if key not in keys:
                raise conflict(f"Unbekannte Pflichtangabe: {key}")
            manual[key] = value
        r.update(checklist=manual)
        links = _links(r.rows, invoice_id)
        listing = _checklist(r.invoice, r.review, _settings(r.rows), links.contract_link is not None)
        findings = _arithmetic(r.invoice, r.review)
        r.update(arithmetic_result=payload.result, arithmetic_note=payload.note, arithmetic_by=r.user.get("id"),
                 arithmetic_at=stamp("invoice_reviews"))
        r.event("arithmetic_check", status_after=r.review.status, reason=payload.note, details={
            "result": payload.result, "findings": [f["code"] for f in findings], "missing": listing["missing"],
            "checked": {"net": as_number(money(r.invoice.net_amount)), "vat": as_number(money(r.invoice.vat_amount)),
                        "gross": as_number(money(r.invoice.gross_amount))}})
        return _dump(r.review) or {}


# ─── Decision ────────────────────────────────────────────────────────────────

def _four_eyes(r: Reviewed, settings: InvoiceReviewSettings) -> bool:
    limit = settings.four_eyes_limit
    return limit is not None and money(r.invoice.gross_amount) > money(limit) and r.review.kind == "invoice"


def _check_approver(r: Reviewed, settings: InvoiceReviewSettings) -> None:
    """Above the limit: owner or manager, and not one of the people who checked."""
    if not _four_eyes(r, settings) or not r.user:
        return
    limit = _amount_label(money(settings.four_eyes_limit))
    if r.role not in DECIDERS_ABOVE_LIMIT:
        raise forbidden(f"Rechnungen über {limit} geben Eigentümer oder Verwaltung frei (Vier-Augen-Prinzip).")
    checkers = {r.review.factual_by, r.review.arithmetic_by} - {None}
    if r.user.get("id") in checkers:
        raise conflict(f"Vier-Augen-Prinzip: Über {limit} gibt nicht frei, wer die Rechnung geprüft hat.")


def decide(store: Any, invoice_id: str, payload: DecisionRequest, actor_id: str | None) -> dict:
    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review/decision") as r:
        r.require_pending()
        gross = money(r.invoice.gross_amount)
        settings = _settings(r.rows)
        now = stamp("invoice_reviews")
        if payload.decision in ("approve", "partial"):
            credit = r.review.kind == "credit_note"
            missing = []
            if not credit and r.review.factual_result is None:
                missing.append("sachliche Prüfung")
            if r.review.arithmetic_result is None:
                missing.append("rechnerische Prüfung")
            if missing:
                raise conflict(f"Vor der Freigabe fehlt: {', '.join(missing)}.")
            objected = "objected" in (r.review.factual_result, r.review.arithmetic_result)
            if payload.decision == "approve" and objected:
                raise conflict("Eine Prüfung hat Beanstandungen; freigeben lässt sich nur ein Teilbetrag (mit "
                               "Begründung), oder die Rechnung wird abgelehnt bzw. zurückgefragt.")
            if credit and payload.decision == "partial":
                raise conflict("Eine Gutschrift wird ganz übernommen oder abgelehnt.")
            if credit:
                target = r.rows.get("invoices", r.review.credit_for_invoice_id)
                if target is None:
                    raise NotFoundError("Die geminderte Rechnung wurde nicht gefunden")
            _check_approver(r, settings)
            amount = gross if payload.decision == "approve" else money(payload.amount)
            if amount > gross:
                raise conflict(f"Freigegeben wird höchstens der Rechnungsbetrag ({_amount_label(gross)}).")
            if payload.decision == "partial" and amount == gross:
                raise conflict("Der Teilbetrag entspricht dem Rechnungsbetrag; bitte ganz freigeben.")
            status = "approved" if payload.decision == "approve" else "partially_approved"
            r.update(status=status, approved_amount=float(amount), decision_reason=payload.reason,
                     decided_by=r.user.get("id"), decided_at=now,
                     dispute_status="open" if status == "partially_approved" else None)
            r.event("approved" if status == "approved" else "partially_approved", status_after=status, amount=amount,
                    reason=payload.reason, details={
                        "gross": as_number(gross), "four_eyes": _four_eyes(r, settings),
                        "disputed": as_number(gross - amount)})
            if status == "partially_approved":
                r.event("dispute_opened", status_after=status, amount=gross - amount, reason=payload.reason)
        elif payload.decision == "reject":
            r.update(status="rejected", approved_amount=None, decision_reason=payload.reason,
                     decided_by=r.user.get("id"), decided_at=now)
            r.event("rejected", status_after="rejected", amount=gross, reason=payload.reason)
        else:
            r.update(status="query", decision_reason=payload.reason)
            r.event("query", status_after="query", reason=payload.reason)
        return _dump(r.review) or {}


def resolve_dispute(store: Any, invoice_id: str, payload: DisputeResolution, actor_id: str | None) -> dict:
    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review/dispute") as r:
        if r.review.dispute_status != "open":
            raise conflict("Zu dieser Rechnung ist kein Widerspruch offen.")
        credits = _credit_totals(r.rows, [invoice_id]).get(invoice_id, ZERO)
        settlement = _settle(r.invoice, r.review, [], credits, date.today())
        remaining = settlement.dispute_open
        settled = ZERO
        if payload.outcome == "credit" and credits == 0:
            raise conflict("Es ist keine freigegebene Gutschrift zu dieser Rechnung erfasst.")
        if payload.outcome == "partial_payment":
            settled = money(payload.amount)
            if settled > remaining:
                raise conflict(f"Offen im Widerspruch sind nur {_amount_label(remaining)}.")
            if money(r.review.approved_amount) + settled > money(r.invoice.gross_amount):
                raise conflict("Freigegeben wird höchstens der Rechnungsbetrag.")
            settings = _settings(r.rows)
            _check_approver(r, settings)
        written_off = remaining - settled
        r.update(dispute_status="resolved", dispute_outcome=payload.outcome,
                 dispute_settled_amount=float(settled) if payload.outcome == "partial_payment" else None,
                 dispute_written_off=float(written_off), dispute_reason=payload.reason,
                 dispute_resolved_by=r.user.get("id"), dispute_resolved_at=stamp("invoice_reviews"))
        r.event("dispute_resolved", status_after=r.review.status, amount=settled or None, reason=payload.reason,
                details={"outcome": payload.outcome, "credits": as_number(credits),
                         "settled": as_number(settled), "written_off": as_number(written_off)})
        return _dump(r.review) or {}


# ─── Result: utility billing ─────────────────────────────────────────────────

def transfer_cost(store: Any, invoice_id: str, payload: CostTransferRequest, actor_id: str | None) -> dict:
    from ..models import CostItem
    from .final_statements import EDITABLE_STATUSES

    with _reviewed(store, actor_id, invoice_id, f"/invoices/{invoice_id}/review/cost-transfer",
                   "/billing/cost-items") as r:
        review, invoice = r.review, r.invoice
        if review.kind != "invoice" or review.status not in rules.APPROVED:
            raise conflict("Nur eine freigegebene Rechnung geht in die Nebenkostenabrechnung; eine abgelehnte "
                           "nie.")
        if not review.recoverable:
            raise conflict("Die Rechnung ist nicht als umlagefähig markiert.")
        if review.dispute_status == "open":
            raise conflict("Erst nach Klärung des Widerspruchs übernehmen; dann steht der Betrag fest.")
        links = _links(r.rows, invoice_id)
        if links.contract_link is not None:
            raise conflict("Die Rechnung gehört zu einem Objektvertrag; sie wird dort in die Abrechnung übernommen "
                           "(zeitanteilig und nach Standorten).")
        if r.rows.find("invoice_cost_transfers", invoice_id=invoice_id):
            raise conflict("Die Rechnung ist bereits in eine Nebenkostenabrechnung übernommen und zählt nur einmal.")
        period = r.rows.get("billing_periods", payload.billing_period_id)
        if period is None:
            raise NotFoundError("Abrechnungsperiode nicht gefunden")
        if period.status not in EDITABLE_STATUSES:
            raise conflict(f"Die Abrechnungsperiode ist '{period.status}' und nimmt keine Kosten mehr auf.")
        place = invoice.property_id or review.property_id
        if place != period.property_id:
            raise conflict("Die Abrechnungsperiode gehört nicht zum Objekt der Rechnung.")
        key = r.rows.get("allocation_keys", payload.allocation_key_id)
        if key is None or key.property_id != period.property_id:
            raise conflict("Der Verteilerschlüssel gehört nicht zum Objekt der Abrechnungsperiode.")
        settlement = settlements(r.rows, [invoice])[invoice.id]
        amount = settlement.flow_amount() or ZERO
        if amount <= 0:
            raise conflict("Nach Freigabe, Gutschriften und Skonto bleibt kein Betrag zu übernehmen.")
        gross = money(invoice.gross_amount)
        net = cents(amount * money(invoice.net_amount) / gross) if gross else amount
        number = getattr(invoice, "invoice_number", None)
        description = payload.description or (f"{invoice.supplier}: Rechnung {number}" if number
                                              else f"{invoice.supplier}: Rechnung vom "
                                                   f"{invoice.invoice_date.strftime('%d.%m.%Y')}")
        now = stamp("cost_items")
        item = CostItem(id=str(uuid4()), billing_period_id=period.id, description=description, amount=float(amount),
                        allocation_key_id=key.id, is_recoverable=True, cost_category=review.cost_category,
                        source_document_id=review.document_id or invoice.source_document_id,
                        vat_rate=invoice.vat_rate, net_amount=float(net), gross_amount=float(amount),
                        created_at=now, updated_at=now)
        r.rows.add("cost_items", item)
        transfer = InvoiceCostTransfer(id=str(uuid4()), invoice_id=invoice_id, cost_item_id=item.id,
                                       billing_period_id=period.id, amount=float(amount),
                                       created_by=r.user.get("id"), created_at=stamp("invoice_cost_transfers"))
        r.rows.add("invoice_cost_transfers", transfer)
        r.event("cost_transferred", status_after=review.status, amount=amount,
                details={"billing_period_id": period.id, "billing_period_label": period.label,
                         "cost_item_id": item.id})
        return {"transfer": _dump(transfer), "cost_item": _dump(item)}


# ─── Guards for the other modules ────────────────────────────────────────────

def review_of(rows: Rows, invoice_id: str) -> Any:
    found = rows.find("invoice_reviews", invoice_id=invoice_id)
    return found[0] if found else None


def ensure_payable(rows: Rows, invoice_id: str) -> None:
    """A rejected invoice and a credit note are not paid (payments of the others are allowed)."""
    review = review_of(rows, invoice_id)
    if review is None:
        return
    if review.kind == "credit_note":
        raise conflict("Eine Gutschrift wird nicht bezahlt; sie mindert ihre Rechnung.")
    if review.status == "rejected":
        raise conflict("Die Rechnung ist abgelehnt und wird nicht bezahlt.")


def ensure_linkable(rows: Rows, invoice_id: str) -> None:
    """A rejected invoice and a credit note are not billed against an order or a contract."""
    review = review_of(rows, invoice_id)
    if review is None:
        return
    if review.kind == "credit_note":
        raise conflict("Eine Gutschrift wird keinem Auftrag und keinem Objektvertrag zugeordnet.")
    if review.status == "rejected":
        raise conflict("Eine abgelehnte Rechnung fließt in keine Auswertung.")


def ensure_invoice_deletable(store: Any, invoice_id: str) -> None:
    rows = Rows.reading(store)
    if rows.find("invoice_review_events", invoice_id=invoice_id) or rows.find("invoice_reviews",
                                                                              invoice_id=invoice_id):
        raise conflict("Die Rechnung hat einen Prüfverlauf; dieser bleibt als Nachweis erhalten. Statt zu löschen "
                       "die Rechnung ablehnen.")
    if rows.find("invoice_reviews", credit_for_invoice_id=invoice_id):
        raise conflict("Eine Gutschrift mindert diese Rechnung; zuerst die Gutschrift klären.")


def ensure_invoice_change_allowed(store: Any, invoice_id: str, changes: dict) -> None:
    """After the decision the reviewed facts of the invoice stay as they were checked."""
    rows = Rows.reading(store)
    review = review_of(rows, invoice_id)
    if review is None or review.status not in DECIDED:
        return
    invoice = rows.get("invoices", invoice_id)
    if invoice is None:
        return
    changed = [key for key in FIXED_AFTER_DECISION if key in changes and _same(getattr(invoice, key, None),
                                                                                changes[key]) is False]
    if changed:
        raise conflict("Über die Rechnung ist entschieden; Lieferant, Nummer, Datum, Objekt und Beträge bleiben wie "
                       f"geprüft (geändert werden sollte: {', '.join(changed)}).")


def _same(current: Any, new: Any) -> bool:
    if isinstance(current, (int, float, Decimal)) or isinstance(new, (int, float, Decimal)):
        try:
            return money(current) == money(new)
        except Exception:  # noqa: BLE001
            return current == new
    return current == new


# ─── Views ───────────────────────────────────────────────────────────────────

def _assignment(rows: Rows, invoice: Any, review: Any, links: Links) -> dict:
    if links.order_link is not None:
        order = links.order
        change = rows.get("maintenance_change_orders", review.change_order_id) if review is not None else None
        return {"kind": "maintenance_order", "case_id": links.order_link.case_id,
                "order": _dump(order), "change_order": _dump(change)}
    if links.contract_link is not None:
        return {"kind": "service_contract", "service_contract_id": links.contract_link.service_contract_id,
                "contract_title": getattr(links.contract, "title", None),
                "recoverable": getattr(links.contract, "recoverable", None), "bill": _dump(links.contract_link)}
    if review is not None and (review.property_id or invoice.property_id):
        return {"kind": "free", "property_id": review.property_id or invoice.property_id,
                "unit_id": review.unit_id, "cost_category": review.cost_category, "recoverable": review.recoverable}
    return {"kind": None}


def _factual_findings(rows: Rows, invoice: Any, review: Any, links: Links) -> list[dict]:
    gross = money(invoice.gross_amount)
    if links.order_link is not None and links.order is not None:
        order = links.order
        changes = rows.find("maintenance_change_orders", order_id=order.id)
        ordered = money(order.gross_amount) + sum((money(c.gross_amount) for c in changes if c.status == "approved"),
                                                  ZERO)
        others = [link.invoice_id for link in rows.find("maintenance_order_invoices", order_id=order.id)
                  if link.invoice_id != invoice.id]
        other_invoices = [i for i in rows.find("invoices", id=others) if i.status != "cancelled"]
        flow = flows(rows, other_invoices)
        billed = sum((flow[i.id][1] if i.id in flow else money(i.gross_amount) for i in other_invoices), ZERO)
        change = None
        if review is not None and review.change_order_id:
            found = rows.get("maintenance_change_orders", review.change_order_id)
            if found is not None:
                change = (found.title, money(found.gross_amount))
        return rules.order_findings(gross=gross, ordered=ordered, billed_elsewhere=billed,
                                    order_label=f"„{order.order_number or order.supplier_name}“", change_order=change)
    if links.contract_link is not None and links.contract is not None:
        from ..domain.service_contract_finance import planned_instalments
        from ..domain.service_contract_terms import Terms

        bill, contract = links.contract_link, links.contract
        tariffs = rows.find("service_contract_tariffs", service_contract_id=contract.id)
        planned = sum((i.amount for i in planned_instalments(tariffs, contract.start_date, Terms.of(contract).effective_end,
                                                             bill.period_start, bill.period_end)), ZERO)
        others = [b for b in rows.find("service_contract_invoices", service_contract_id=contract.id)
                  if b.id != bill.id and b.kind == bill.kind
                  and rules.periods_overlap(b.period_start, b.period_end, bill.period_start, bill.period_end)]
        reviewed = {x.invoice_id: x for x in rows.find("invoice_reviews", invoice_id=[b.invoice_id for b in others])}
        numbers = {i.id: getattr(i, "invoice_number", None) for i in rows.find("invoices", id=[b.invoice_id for b in others])}
        overlaps = [{"invoice_id": b.invoice_id, "invoice_number": numbers.get(b.invoice_id),
                     "period_start": b.period_start.isoformat(), "period_end": b.period_end.isoformat()}
                    for b in others if b.invoice_id in reviewed and reviewed[b.invoice_id].status in rules.APPROVED]
        return rules.contract_findings(gross=gross, kind=bill.kind, planned=planned,
                                       credited=money(bill.advances_credited), overlaps=overlaps,
                                       has_tariff=any(t.advance_amount for t in tariffs))
    if review is not None and review.kind == "invoice" and not (review.property_id or invoice.property_id):
        return [rules.finding("no_assignment", "warning",
                              "Die Rechnung ist weder einem Auftrag noch einem Objektvertrag noch einer Kostenstelle "
                              "(Objekt) zugeordnet.")]
    return []


def abilities(role: str | None, invoice_id: str, review: Any, links: Links | None = None) -> dict[str, bool]:
    base = f"/invoices/{invoice_id}/review"
    pending = review is not None and review.status in PENDING
    factual = may_write(role, f"{base}/factual-check")
    if role == "techniker":
        factual = factual and links is not None and links.order_link is not None
    return {
        "receive": review is None and may_write(role, base),
        "edit_receipt": pending and may_write(role, base),
        "factual_check": pending and review.kind == "invoice" and factual,
        "arithmetic_check": pending and may_write(role, f"{base}/arithmetic-check"),
        "decide": pending and may_write(role, f"{base}/decision"),
        "decide_above_limit": role in DECIDERS_ABOVE_LIMIT,
        "resolve_dispute": review is not None and review.dispute_status == "open"
        and may_write(role, f"{base}/dispute"),
        "transfer_cost": review is not None and review.status in rules.APPROVED
        and may_write(role, f"{base}/cost-transfer") and may_write(role, "/billing/cost-items"),
        "pay": may_write(role, f"/invoices/{invoice_id}/payments"),
        "settings": may_write(role, "/invoice-review/settings"),
    }


def _user_names(ids: Iterable[str | None]) -> dict[str, str | None]:
    names: dict[str, str | None] = {}
    for user_id in {i for i in ids if i}:
        found = auth.get_user_by_id(user_id)
        names[user_id] = (found.get("full_name") or found.get("username")) if found else None
    return names


def review_view(store: Any, invoice_id: str, actor: dict | None, today: date | None = None) -> dict:
    rows = Rows.reading(store)
    invoice = rows.require("invoices", invoice_id, INVOICE_MISSING)
    review = review_of(rows, invoice_id)
    settings = _settings(rows)
    today = today or date.today()
    links = _links(rows, invoice_id)
    settlement = settlements(rows, [invoice], today)[invoice_id]
    arithmetic = _arithmetic(invoice, review)
    listing = _checklist(invoice, review, settings, links.contract_link is not None)
    factual = _factual_findings(rows, invoice, review, links)
    duplicates = find_duplicates(rows, store, _invoice_facts(invoice), settings.duplicate_window_days)
    events = sorted(rows.find("invoice_review_events", invoice_id=invoice_id), key=lambda e: e.seq)
    checked = next((e.details.get("checked") for e in reversed(events) if e.action == "arithmetic_check"), None)
    changed_after_check = bool(checked) and (
        money(checked["gross"]) != money(invoice.gross_amount) or money(checked["net"]) != money(invoice.net_amount))
    findings = [*arithmetic, *rules.checklist_findings(listing), *factual, *settlement.findings]
    if duplicates:
        findings.append(rules.finding("possible_duplicate", "warning",
                                      f"{len(duplicates)} mögliche Dublette(n) desselben Lieferanten.",
                                      count=len(duplicates)))
    if changed_after_check:
        findings.append(rules.finding("changed_after_check", "error",
                                      "Die Beträge der Rechnung wurden nach der rechnerischen Prüfung geändert."))
    document = None
    document_id = review.document_id if review is not None else invoice.source_document_id
    if document_id:
        found = rows.get("documents", document_id)
        if found is not None:
            current = _file_digest(found)
            recorded = review.document_sha256 if review is not None else None
            integrity = ("unverified" if not recorded else "unavailable" if current is None
                         else "unchanged" if current == recorded else "changed")
            if integrity == "changed":
                findings.append(rules.finding("document_changed", "error",
                                              "Die Belegdatei weicht von der beim Eingang erfassten Fassung ab."))
            document = {**(_dump(found) or {}), "sha256_at_receipt": recorded, "integrity": integrity}
    payments = rows.find("invoice_payments", invoice_id=invoice_id)
    bookings = {b.id: b for b in rows.find("bookings", id=[p.booking_id for p in payments])}
    credit_reviews = [r for r in rows.find("invoice_reviews", credit_for_invoice_id=invoice_id)]
    credit_invoices = {i.id: i for i in rows.find("invoices", id=[r.invoice_id for r in credit_reviews])}
    target = None
    if review is not None and review.credit_for_invoice_id:
        found_target = rows.get("invoices", review.credit_for_invoice_id)
        target = _dump(found_target)
    transfer = (rows.find("invoice_cost_transfers", invoice_id=invoice_id) or [None])[0]
    names = _user_names([*(e.actor_id for e in events), *(getattr(review, k, None) for k in
                                                          ("factual_by", "arithmetic_by", "decided_by",
                                                           "dispute_resolved_by", "created_by"))])
    role = (actor or {}).get("role")
    return {
        "invoice": _dump(invoice),
        "review": None if review is None else {
            **(_dump(review) or {}), "factual_by_name": names.get(review.factual_by or ""),
            "arithmetic_by_name": names.get(review.arithmetic_by or ""),
            "decided_by_name": names.get(review.decided_by or ""),
            "dispute_resolved_by_name": names.get(review.dispute_resolved_by or "")},
        "status": review.status if review is not None else "legacy",
        "kind": review.kind if review is not None else "invoice",
        "document": document,
        "assignment": _assignment(rows, invoice, review, links),
        "arithmetic": {"lines": [{"rate": float(line.rate), "net": as_number(line.net), "vat": as_number(line.vat)}
                                 for line in rules.invoice_lines(invoice.net_amount, invoice.vat_amount,
                                                                 invoice.gross_amount, invoice.vat_rate,
                                                                 review.vat_lines if review is not None else None)],
                       "findings": arithmetic},
        "checklist": listing,
        "factual_findings": factual,
        "duplicates": duplicates,
        "findings": findings,
        "settlement": settlement.as_json(),
        "payments": [{**(_dump(p) or {}), "booking": _dump(bookings.get(p.booking_id))} for p in payments],
        "credit_notes": [{"invoice": _dump(credit_invoices.get(r.invoice_id)), "status": r.status}
                         for r in credit_reviews if r.invoice_id in credit_invoices],
        "credit_for": target,
        "transfer": _dump(transfer),
        "history": [{**(_dump(e) or {}), "actor_name": e.actor_name or names.get(e.actor_id or "")} for e in events],
        "four_eyes": {"limit": settings.four_eyes_limit,
                      "required": settings.four_eyes_limit is not None
                      and money(invoice.gross_amount) > money(settings.four_eyes_limit)
                      and (review is None or review.kind == "invoice")},
        "settings": settings.model_dump(mode="json"),
        "abilities": abilities(role, invoice_id, review, links),
    }


# ─── Inbox and payment proposals ─────────────────────────────────────────────

INBOX_STATUSES = ("legacy", "received", "query", "approved", "partially_approved", "rejected", "pending", "dispute")


def _row(invoice: Any, review: Any, settlement: rules.Settlement, names: dict[str, str]) -> dict:
    return {
        "invoice_id": invoice.id, "supplier": invoice.supplier,
        "invoice_number": getattr(invoice, "invoice_number", None),
        "invoice_date": invoice.invoice_date.isoformat(),
        "property_id": invoice.property_id or (review.property_id if review is not None else None),
        "property_name": names.get(invoice.property_id or (review.property_id if review is not None else "") or ""),
        "gross_amount": as_number(money(invoice.gross_amount)),
        "status": review.status if review is not None else "legacy",
        "kind": review.kind if review is not None else "invoice",
        "received_on": review.received_on.isoformat() if review is not None else None,
        "factual_result": review.factual_result if review is not None else None,
        "arithmetic_result": review.arithmetic_result if review is not None else None,
        "dispute_status": review.dispute_status if review is not None else None,
        "document_id": (review.document_id if review is not None else None) or invoice.source_document_id,
        "settlement": settlement.as_json(),
    }


def _unpaid_sql(review_table: Any, invoice_table: Any, payments_table: Any) -> Any:
    from sqlalchemy import func, literal, select

    paid = (select(func.coalesce(func.sum(payments_table.c.amount), 0))
            .where(payments_table.c.invoice_id == invoice_table.c.id).scalar_subquery())
    base = func.coalesce(review_table.c.approved_amount, invoice_table.c.gross_amount)
    least = base * (literal(100) - func.coalesce(review_table.c.skonto_percent, 0)) / literal(100)
    return paid < least - literal(0.005)


def inbox(store: Any, *, status: str | None = None, due: str | None = None, skonto: bool = False,
          property_id: str | None = None, q: str | None = None, skip: int = 0, limit: int = 50,
          today: date | None = None) -> dict:
    """Invoices with their review state, one page, newest first; filters run before paging.

    "unpaid" (for due and Skonto) compares the allocated payments with the approved (or gross)
    amount less Skonto; credit notes are not part of that filter, the row shows the exact state.
    """
    today = today or date.today()
    q = (q or "").strip() or None
    rows = Rows.reading(store)
    horizon = {"overdue": None, "week": today + timedelta(days=7), "month": today + timedelta(days=30)}
    db = getattr(store, "db", None)
    if db is not None:
        from sqlalchemy import and_, func, not_, or_, select

        from ..db.invoice_review_models import InvoiceReviewORM
        from ..db.maintenance_project_models import InvoicePaymentORM
        from ..db.orm_models import InvoiceORM

        inv, rev, pay = InvoiceORM.__table__, InvoiceReviewORM.__table__, InvoicePaymentORM.__table__
        query = select(InvoiceORM).outerjoin(InvoiceReviewORM, InvoiceReviewORM.invoice_id == InvoiceORM.id)
        conditions = []
        if status == "legacy":
            conditions.append(rev.c.id.is_(None))
        elif status == "pending":
            conditions.append(rev.c.status.in_(PENDING))
        elif status == "dispute":
            conditions.append(rev.c.dispute_status == "open")
        elif status:
            conditions.append(rev.c.status == status)
        if property_id:
            conditions.append(or_(inv.c.property_id == property_id, rev.c.property_id == property_id))
        if q:
            pattern = f"%{q}%"
            conditions.append(or_(inv.c.supplier.ilike(pattern), inv.c.invoice_number.ilike(pattern)))
        unpaid = and_(or_(rev.c.status.is_(None), rev.c.status.notin_(("rejected",))),
                      or_(rev.c.kind.is_(None), rev.c.kind == "invoice"), _unpaid_sql(rev, inv, pay))
        if due in horizon:
            due_on = func.coalesce(inv.c.due_date, rev.c.due_on)
            window = due_on < today if due == "overdue" else and_(due_on >= today, due_on <= horizon[due])
            conditions.extend([due_on.is_not(None), window, unpaid])
        if skonto:
            conditions.extend([rev.c.skonto_until.is_not(None), rev.c.skonto_until >= today, unpaid,
                               not_(rev.c.status == "rejected")])
        if conditions:
            query = query.where(and_(*conditions))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        order = ([func.coalesce(inv.c.due_date, rev.c.due_on).asc()] if due else
                 [rev.c.skonto_until.asc()] if skonto else [inv.c.invoice_date.desc()])
        page = [rows._model("invoices", obj) for obj in
                db.scalars(query.order_by(*order, inv.c.id).offset(skip).limit(limit))]
        reviews = {r.invoice_id: r for r in rows.find("invoice_reviews", invoice_id=[i.id for i in page])}
    else:
        every = list(store.invoices.values())
        reviews_all = {r.invoice_id: r for r in store.invoice_reviews.values()}
        settled_all = settlements(rows, every, today) if (due or skonto) else {}

        def keep(invoice: Any) -> bool:
            review = reviews_all.get(invoice.id)
            current = review.status if review is not None else "legacy"
            if status == "pending" and current not in PENDING:
                return False
            if status == "dispute" and (review is None or review.dispute_status != "open"):
                return False
            if status and status not in ("pending", "dispute") and current != status:
                return False
            if property_id and property_id not in (invoice.property_id, getattr(review, "property_id", None)):
                return False
            if q and not any(q.casefold() in (value or "").casefold()
                             for value in (invoice.supplier, getattr(invoice, "invoice_number", None))):
                return False
            if due or skonto:
                if current == "rejected" or (review is not None and review.kind == "credit_note"):
                    return False
                base = money(review.approved_amount if review is not None and review.approved_amount is not None
                             else invoice.gross_amount)
                percent = Decimal(str(review.skonto_percent or 0)) if review is not None else Decimal(0)
                if settled_all[invoice.id].paid >= base * (100 - percent) / 100 - Decimal("0.005"):
                    return False
            if due in horizon:
                due_on = _due_on(invoice, review)
                if due_on is None or (due_on >= today if due == "overdue" else not today <= due_on <= horizon[due]):
                    return False
            if skonto and (review is None or review.skonto_until is None or review.skonto_until < today):
                return False
            return True

        found = [i for i in every if keep(i)]
        if due:
            found.sort(key=lambda i: (_due_on(i, reviews_all.get(i.id)) or date.max, i.id))
        elif skonto:
            found.sort(key=lambda i: (reviews_all[i.id].skonto_until, i.id))
        else:
            found.sort(key=lambda i: i.id)
            found.sort(key=lambda i: i.invoice_date, reverse=True)
        total = len(found)
        page = found[skip:skip + limit]
        reviews = {i.id: reviews_all[i.id] for i in page if i.id in reviews_all}
    settled = settlements(rows, page, today)
    property_ids = {i.property_id or getattr(reviews.get(i.id), "property_id", None) for i in page} - {None}
    names = {p.id: p.name for p in rows_properties(store, property_ids)}
    return {"items": [_row(i, reviews.get(i.id), settled[i.id], names) for i in page], "total": total,
            "skip": skip, "limit": limit, "has_more": skip + len(page) < total}


def rows_properties(store: Any, ids: set[str]) -> list[Any]:
    found = []
    for key in ids:
        try:
            found.append(store.get_property(key))
        except NotFoundError:
            continue
    return found


def payment_proposals(store: Any, *, until: date | None = None, today: date | None = None, skip: int = 0,
                      limit: int = 100) -> dict:
    """Approved invoices with an open amount: what to pay, by when, with which Skonto. Nothing is sent."""
    today = today or date.today()
    rows = Rows.reading(store)
    approved = [r for r in rows.find("invoice_reviews", status=list(rules.APPROVED)) if r.kind == "invoice"]
    invoices = {i.id: i for i in rows.find("invoices", id=[r.invoice_id for r in approved])}
    reviews = {r.invoice_id: r for r in approved if r.invoice_id in invoices}
    settled = settlements(rows, invoices.values(), today)
    items = []
    for invoice_id, settlement in settled.items():
        if settlement.open <= 0:
            continue
        review, invoice = reviews[invoice_id], invoices[invoice_id]
        pay_by = settlement.skonto_until if settlement.skonto_available else settlement.due_on
        if until is not None and pay_by is not None and pay_by > until:
            continue
        amount = settlement.open - (settlement.skonto_amount if settlement.skonto_available and not settlement.paid
                                    else ZERO)
        items.append({
            "invoice_id": invoice_id, "supplier": invoice.supplier,
            "invoice_number": getattr(invoice, "invoice_number", None),
            "payment_reference": getattr(invoice, "payment_reference", None) or getattr(invoice, "invoice_number", None),
            "property_id": invoice.property_id or review.property_id, "status": review.status,
            "open": as_number(settlement.open), "proposed_amount": as_number(amount),
            "skonto_amount": as_number(settlement.skonto_amount) if settlement.skonto_available else 0.0,
            "skonto_until": settlement.skonto_until.isoformat() if settlement.skonto_available and settlement.skonto_until
            else None,
            "due_on": settlement.due_on.isoformat() if settlement.due_on else None,
            "pay_by": pay_by.isoformat() if pay_by else None, "overdue": settlement.overdue,
            "dispute_open": as_number(settlement.dispute_open)})
    items.sort(key=lambda item: (item["pay_by"] or "9999-12-31", item["invoice_id"]))
    total_amount = sum((money(item["proposed_amount"]) for item in items), ZERO)
    return {"items": items[skip:skip + limit], "total": len(items), "skip": skip, "limit": limit,
            "has_more": skip + limit < len(items), "total_amount": as_number(total_amount),
            "note": "Vorschlag; es wird keine Zahlungsdatei erzeugt und nichts an eine Bank übermittelt."}


# ─── DSGVO (Art. 15) ─────────────────────────────────────────────────────────

def records_for_documents(store: Any, document_ids: set[str]) -> dict[str, list]:
    """Reviews (with history) whose original document is one of the given documents."""
    rows = Rows.reading(store)
    reviews = rows.find("invoice_reviews", document_id=document_ids) if document_ids else []
    events = rows.find("invoice_review_events", invoice_id=[r.invoice_id for r in reviews])
    return {"invoice_reviews": reviews, "invoice_review_events": events}
