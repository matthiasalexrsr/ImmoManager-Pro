"""Dunning (Mahnwesen) from the open claim to letter, payment and result.

Flow: preview (stateless: which claims, stage, fee, interest) → run (creates the
case, its claims and one draft letter per contract, each queued in the outbox) →
finalize a draft (fee and interest become receivables, the PDF becomes an immutable
archived original, the outbox entry is ready to print or to hand to a mail program)
→ sent by hand → replies, payments → result (paid, partially paid, written off,
handed over). The escalation job proposes due next stages; it never creates letters.

Claims of a contract: its rent months (rent history), stored receivables from the
utility statement, and the fees and interest earlier letters of the contract charged.
Manual receivables are listed but not dunned (they may duplicate a rent month).
Excluded while pending: claims with an open objection against their utility
statement (billing_objections), claims the tenant disputes (dunning_disputes), and
claims of a case closed as written off, partially paid or handed over. Payments are
applied to the remaining claims (domain/dunning_process.py), so a payment received
or allocated after a run reduces the claim and stops the next stage.

Everything runs synchronously in a unit of document_versions.work(): a SQL session
of its own (or the memory store with undo), the actor's rights checked under the
account lock until the commit, the portfolio boundary of every table applied.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, insert, select, update

from ..db.dunning_models import (
    DunningBaseRateORM,
    DunningBlockORM,
    DunningCaseItemORM,
    DunningCaseORM,
    DunningDisputeORM,
    DunningEventORM,
    DunningLetterORM,
    DunningOutboxORM,
    DunningReplyORM,
    DunningRunORM,
    DunningStageSettingORM,
)
from ..db.orm_models import ContractORM, DocumentORM, ReceivableORM
from ..domain import dunning_process as rules_
from ..domain.dunning_process import (
    STAGE_LABELS,
    Claim,
    OpenItem,
    Payment,
    RatePeriod,
    StageRule,
    default_interest,
    digest,
    next_stage,
)
from ..domain.money import ZERO, as_number, money
from ..domain.receivables import is_unpaid_debt
from ..models import Document, DocumentCreate, NotificationCreate
from ..models_dunning import (
    AssignRequest,
    BaseRateRequest,
    BlockRequest,
    CancelLetterRequest,
    DisputeDecision,
    DisputeRequest,
    DunningBaseRate,
    DunningBlock,
    DunningCase,
    DunningCaseItem,
    DunningDispute,
    DunningEvent,
    DunningLetter,
    DunningOutbox,
    DunningReply,
    DunningRun,
    DunningStageSetting,
    FinalizeRequest,
    LiftBlockRequest,
    MarkSentRequest,
    NoteRequest,
    ReplyRequest,
    ResultRequest,
    RunRequest,
    RunScope,
    StageSettingsRequest,
)
from ..store_errors import NotFoundError
from . import document_versions as archive
from .dunning_letter_validation import (
    DOC_TYPE,
    PDF_FORMAT_VERSION,
    SCHEMA_VERSION,
    VIRTUAL_PREFIX,
    DunningLetterValidationError,
    document_id_for,
    finalize_request_hash,
    validate_dunning_letter_snapshot,
)
from .dunning_render import plain_text, render_pdf, subject
from .payment_allocations import contract_ledger

WRITE_AREAS = ("/dunning",)
FINALIZE_AREAS = ("/dunning", "/documents")
SETTINGS_AREAS = ("/dunning/settings",)
OPEN_OBJECTION_STATUSES = frozenset({"open", "correction"})
CLOSED_EXCLUDING = frozenset({"partially_paid", "written_off", "handed_over"})
REFERENCE = re.compile(r"\bM-\d{4}-[0-9A-F]{8}\b", re.IGNORECASE)
MAX_PAGE = 500
RESULT_LABELS = {"paid": "bezahlt", "partially_paid": "teilweise bezahlt", "written_off": "abgeschrieben",
                 "handed_over": "abgegeben (Inkasso/Gericht)"}
EXCLUSION_LABELS = {
    "objection": "Widerspruch gegen die Nebenkostenabrechnung noch nicht entschieden",
    "dispute": "vom Mieter bestritten, noch nicht entschieden",
    "dispute_upheld": "Einwand des Mieters berechtigt",
    "closed_case": "in einem abgeschlossenen Mahnfall erledigt",
    "manual": "manuelle Forderung: nicht eindeutig von der Miete getrennt, wird nicht automatisch gemahnt",
}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return date.today()


class _Part:
    def __init__(self, orm: Any, model: Any):
        self.orm, self.model = orm, model


PARTS = {
    "dunning_stage_settings": _Part(DunningStageSettingORM, DunningStageSetting),
    "dunning_base_rates": _Part(DunningBaseRateORM, DunningBaseRate),
    "dunning_blocks": _Part(DunningBlockORM, DunningBlock),
    "dunning_disputes": _Part(DunningDisputeORM, DunningDispute),
    "dunning_runs": _Part(DunningRunORM, DunningRun),
    "dunning_cases": _Part(DunningCaseORM, DunningCase),
    "dunning_case_items": _Part(DunningCaseItemORM, DunningCaseItem),
    "dunning_letters": _Part(DunningLetterORM, DunningLetter),
    "dunning_outbox": _Part(DunningOutboxORM, DunningOutbox),
    "dunning_replies": _Part(DunningReplyORM, DunningReply),
    "dunning_events": _Part(DunningEventORM, DunningEvent),
}


# ─── Reading and writing through one unit (SQL session or memory store) ──────

class JobContext:
    """What the escalation job gives: its store (and SQL session); writes are its chunk's."""

    def __init__(self, store: Any):
        self.store = store
        self.db = store.db if hasattr(store, "db") and hasattr(store, "communication") else None

    def insert(self, collection: Any, key: Any, value: Any) -> None:
        collection[key] = value


def _row(orm_obj: Any) -> dict:
    return {column.key: getattr(orm_obj, column.key) for column in orm_obj.__table__.columns}


def _rows(ctx: Any, name: str, **criteria: Any) -> list:
    part = PARTS[name]
    if ctx.db is not None:
        query = select(part.orm)
        for key, value in criteria.items():
            column = getattr(part.orm, key)
            query = query.where(column.in_(list(value)) if isinstance(value, (set, frozenset, list, tuple))
                                else column.is_(None) if value is None else column == value)
        return [part.model.model_validate(_row(row)) for row in ctx.db.scalars(query)]

    def matches(item: Any) -> bool:
        for key, value in criteria.items():
            current = getattr(item, key)
            if isinstance(value, (set, frozenset, list, tuple)):
                if current not in value:
                    return False
            elif current != value:
                return False
        return True

    return [item for item in getattr(ctx.store, name).values() if matches(item)]


def _one(ctx: Any, name: str, item_id: str) -> Any | None:
    part = PARTS[name]
    if ctx.db is not None:
        row = ctx.db.get(part.orm, item_id)
        return part.model.model_validate(_row(row)) if row is not None else None
    collection = getattr(ctx.store, name)
    return collection[item_id] if item_id in collection else None


def _need(ctx: Any, name: str, item_id: str, what: str) -> Any:
    item = _one(ctx, name, item_id)
    if item is None:
        raise HTTPException(404, f"{what} nicht vorhanden.")
    return item


def _save(ctx: Any, name: str, item: Any) -> Any:
    part = PARTS[name]
    item = item.model_copy(update={"updated_at": now()})
    if ctx.db is None:
        ctx.insert(getattr(ctx.store, name), item.id, item)
        return item
    row = ctx.db.get(part.orm, item.id)
    values = item.model_dump()
    if row is None:
        ctx.db.add(part.orm(**values))
    else:
        for key, value in values.items():
            if getattr(row, key) != value:
                setattr(row, key, value)
    ctx.db.flush()
    return item


def _new(model: Any, **values: Any) -> Any:
    stamp = now()
    return model(id=str(uuid4()), created_at=stamp, updated_at=stamp, **values)


def _event(ctx: Any, case: DunningCase, kind: str, summary: str, actor_id: str | None,
           data: dict | None = None, at: datetime | None = None) -> DunningEvent:
    if at is None:
        _lock_contract(ctx, case.contract_id)
        if ctx.db is not None:
            last = ctx.db.scalar(select(func.max(DunningEventORM.at)).where(DunningEventORM.case_id == case.id))
        else:
            last = max((event.at for event in _rows(ctx, "dunning_events", case_id=case.id)), default=None)
        at = now()
        if last is not None and at <= last:
            at = last + timedelta(microseconds=1)
    return _save(ctx, "dunning_events", _new(DunningEvent, case_id=case.id, contract_id=case.contract_id, kind=kind,
                                             at=at, actor_id=actor_id, summary=summary, data=data))


def _lock_contract(ctx: Any, contract_id: str) -> None:
    if ctx.db is not None and ctx.db.scalar(
            select(ContractORM.id).where(ContractORM.id == contract_id).with_for_update()) is None:
        raise HTTPException(404, "Vertrag nicht vorhanden.")


def _contract(ctx: Any, contract_id: str) -> Any:
    try:
        return ctx.store.get_contract(contract_id)
    except NotFoundError:
        raise HTTPException(404, "Vertrag nicht vorhanden.") from None


# ─── Settings: stages and base rates ─────────────────────────────────────────

def stage_rules(ctx: Any) -> list[StageRule]:
    stored = {row.stage: row for row in _rows(ctx, "dunning_stage_settings")}
    if len(stored) != 4:
        return list(rules_.DEFAULT_RULES)
    return [StageRule(row.stage, row.label, row.days_after, money(row.fee), row.payment_deadline_days,
                      row.charge_interest) for row in sorted(stored.values(), key=lambda r: r.stage)]


def base_rates(ctx: Any) -> list[RatePeriod]:
    return sorted((RatePeriod(row.valid_from, Decimal(str(row.rate_percent)))
                   for row in _rows(ctx, "dunning_base_rates")), key=lambda r: r.valid_from)


def _rule_dict(rule: StageRule) -> dict:
    return {"stage": rule.stage, "label": rule.label, "days_after": rule.days_after, "fee": as_number(rule.fee),
            "payment_deadline_days": rule.payment_deadline_days, "charge_interest": rule.charge_interest}


def settings(store: Any, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit:
        stored = len(_rows(unit, "dunning_stage_settings")) == 4
        return {"stages": [_rule_dict(rule) for rule in stage_rules(unit)], "stages_stored": stored,
                "base_rates": [{"id": row.id, "valid_from": row.valid_from.isoformat(),
                                "rate_percent": row.rate_percent, "source_note": row.source_note,
                                "consumer_rate_percent": float(Decimal(str(row.rate_percent))
                                                               + rules_.CONSUMER_SURCHARGE)}
                               for row in sorted(_rows(unit, "dunning_base_rates"), key=lambda r: r.valid_from)],
                "consumer_surcharge_points": float(rules_.CONSUMER_SURCHARGE)}


def save_stages(store: Any, payload: StageSettingsRequest, actor_id: str) -> dict:
    try:
        rules_.check_rules([StageRule(s.stage, s.label, s.days_after, money(s.fee), s.payment_deadline_days,
                                      s.charge_interest) for s in payload.stages])
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    with archive.work(store, actor_id, write_areas=SETTINGS_AREAS) as unit:
        existing = {row.stage: row for row in _rows(unit, "dunning_stage_settings")}
        for stage in payload.stages:
            current = existing.get(stage.stage)
            values = stage.model_dump()
            item = (current.model_copy(update=values) if current is not None
                    else _new(DunningStageSetting, **values))
            _save(unit, "dunning_stage_settings", item)
    return settings(store, actor_id)


def add_base_rate(store: Any, payload: BaseRateRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=SETTINGS_AREAS) as unit:
        if _rows(unit, "dunning_base_rates", valid_from=payload.valid_from):
            raise HTTPException(409, "Für dieses Datum ist bereits ein Basiszinssatz erfasst.")
        _save(unit, "dunning_base_rates", _new(DunningBaseRate, valid_from=payload.valid_from,
                                               rate_percent=float(Decimal(str(payload.rate_percent))
                                                                  .quantize(Decimal("0.001"))),
                                               source_note=payload.source_note))
    return settings(store, actor_id)


def delete_base_rate(store: Any, rate_id: str, actor_id: str) -> None:
    with archive.work(store, actor_id, write_areas=SETTINGS_AREAS) as unit:
        _need(unit, "dunning_base_rates", rate_id, "Basiszinssatz")
        if unit.db is not None:
            unit.db.delete(unit.db.get(DunningBaseRateORM, rate_id))
        else:
            unit.remove(unit.store.dunning_base_rates, rate_id)


# ─── The state of one contract ───────────────────────────────────────────────

@dataclass
class State:
    contract: Any
    as_of: date
    items: list[OpenItem]
    excluded: list[dict]
    unapplied: Decimal
    case: DunningCase | None
    case_items: dict[str, DunningCaseItem]
    letters: list[DunningLetter]
    blocks: list[DunningBlock]
    disputes: list[DunningDispute]
    manual: list[dict] = field(default_factory=list)

    @property
    def draft(self) -> DunningLetter | None:
        return next((letter for letter in self.letters if letter.status == "draft"), None)

    @property
    def last_final(self) -> DunningLetter | None:
        finals = [letter for letter in self.letters if letter.status == "final"]
        return max(finals, key=lambda letter: letter.stage) if finals else None

    def active_block(self, day: date) -> DunningBlock | None:
        return next((b for b in sorted(self.blocks, key=lambda b: b.blocked_until, reverse=True)
                     if b.lifted_at is None and b.blocked_until >= day), None)

    def overdue_principal(self) -> list[OpenItem]:
        return [item for item in self.items
                if item.claim.principal and item.outstanding > 0 and item.claim.due_date < self.as_of]

    def open_charges(self) -> list[OpenItem]:
        return [item for item in self.items if not item.claim.principal and item.outstanding > 0]


def _receivables_of(ctx: Any, contract_id: str) -> list:
    if ctx.db is not None:
        from ..models import Receivable
        return [Receivable.model_validate({**_row(row), "description": None})
                for row in ctx.db.scalars(select(ReceivableORM).where(ReceivableORM.contract_id == contract_id))]
    return [r for r in ctx.store.list_receivables() if r.contract_id == contract_id]


def _objected_statements(ctx: Any, statement_ids: set[str]) -> set[str]:
    """Statements with an objection not yet decided (one against a statement, or against its whole period)."""
    if not statement_ids:
        return set()
    statements = {s.id: s for s in ctx.store.list_utility_statements() if s.id in statement_ids}
    periods = {s.billing_period_id for s in statements.values()}
    pending = [o for o in ctx.store.list_billing_objections() if o.status in OPEN_OBJECTION_STATUSES
               and o.billing_period_id in periods]
    found = set()
    for statement in statements.values():
        for objection in pending:
            if objection.billing_period_id == statement.billing_period_id and objection.statement_id in (
                    None, statement.id):
                found.add(statement.id)
    return found


def _deposit_offsets(ctx: Any, contract_id: str) -> dict[str, list[tuple[date, Decimal]]]:
    """Dated, claim-specific payments from finalized deposit settlements only."""
    offsets: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    if ctx.db is not None:
        from ..db.deposit_models import DepositSettlementItemORM, DepositSettlementORM
        from ..db.orm_models import DepositORM

        query = (select(DepositSettlementItemORM.receivable_id, DepositSettlementORM.settlement_date,
                        DepositSettlementItemORM.amount)
                 .join(DepositSettlementORM, DepositSettlementItemORM.settlement_id == DepositSettlementORM.id)
                 .join(DepositORM, DepositSettlementORM.deposit_id == DepositORM.id)
                 .where(DepositORM.contract_id == contract_id, DepositSettlementORM.finalized_at.is_not(None),
                        DepositSettlementItemORM.kind == "receivable",
                        DepositSettlementItemORM.receivable_id.is_not(None)))
        for receivable_id, day, amount in ctx.db.execute(query):
            offsets[receivable_id].append((day, money(amount)))
        return offsets
    deposit_ids = {d.id for d in ctx.store.list_deposits() if d.contract_id == contract_id}
    for settlement in ctx.store.list_deposit_settlements():
        if settlement.deposit_id not in deposit_ids or settlement.finalized_at is None:
            continue
        for item in ctx.store.list_deposit_settlement_items(settlement.id):
            if item.kind == "receivable" and item.receivable_id:
                offsets[item.receivable_id].append((settlement.settlement_date, money(item.amount)))
    return offsets


def evaluate(ctx: Any, contract: Any, as_of: date, *, payments_until: date | None = None) -> State:
    contract_id = contract.id
    cases = _rows(ctx, "dunning_cases", contract_id=contract_id)
    all_items = _rows(ctx, "dunning_case_items", case_id={c.id for c in cases}) if cases else []
    open_case = next((c for c in cases if c.status == "open"), None)
    closed_keys = {item.claim_key: case.result for case in cases if case.status == "closed"
                   and case.result in CLOSED_EXCLUDING for item in all_items if item.case_id == case.id}
    disputes = _rows(ctx, "dunning_disputes", contract_id=contract_id)
    disputed = {d.claim_key: d.status for d in disputes if d.status in ("open", "upheld")}

    claims: list[Claim] = []
    receivable_lines, payment_lines = contract_ledger(ctx.store, contract, as_of, payments_until=payments_until)
    # the tenant account's claims: from the takeover on for a tenancy taken over, arrears carried over first
    for line in receivable_lines:
        if line.total_amount <= 0:
            continue
        if line.label:
            claims.append(Claim(line.claim_key or "rent:carried", "rent", line.due_date,
                                money(line.total_amount), line.label))
        else:
            claims.append(Claim(f"rent:{line.period_start:%Y-%m}", "rent", line.due_date, money(line.total_amount),
                                f"Miete {line.period_start:%m/%Y}"))
    receivables = _receivables_of(ctx, contract_id)
    offsets = _deposit_offsets(ctx, contract_id)
    payment_date = payments_until or as_of
    charge_items = {item.receivable_id: item for item in all_items if item.kind in ("fee", "interest")
                    and item.receivable_id}
    objected = _objected_statements(ctx, {r.statement_id for r in receivables if r.statement_id})
    manual: list[dict] = []
    for receivable in receivables:
        # A fully offset claim remains reconstructable before its settlement date.
        offset_total = sum((amount for _, amount in offsets.get(receivable.id, [])), ZERO)
        if not is_unpaid_debt(receivable) and not (receivable.status == "paid" and offset_total
                                                   >= money(receivable.amount_due) > 0):
            continue
        charge = charge_items.get(receivable.id)
        if charge is not None:
            claims.append(Claim(charge.claim_key, charge.kind, receivable.due_date, money(receivable.amount_due),
                                charge.description, receivable.id))
        elif receivable.statement_id:
            key = f"receivable:{receivable.id}"
            claim = Claim(key, "receivable", receivable.due_date, money(receivable.amount_due),
                          receivable.description or "Nachzahlung aus der Nebenkostenabrechnung", receivable.id)
            claims.append(claim)
            if receivable.statement_id in objected:
                disputed.setdefault(key, "objection")
        else:
            manual.append({"key": f"receivable:{receivable.id}", "receivable_id": receivable.id,
                           "description": receivable.description or "Forderung",
                           "due_date": receivable.due_date.isoformat(), "amount": as_number(money(receivable.amount_due)),
                           "reason": "manual", "reason_label": EXCLUSION_LABELS["manual"]})
    dunnable, excluded = [], []
    for claim in claims:
        reason = None
        if claim.key in closed_keys:
            reason = "closed_case"
        elif claim.key in disputed:
            reason = {"open": "dispute", "upheld": "dispute_upheld", "objection": "objection"}[disputed[claim.key]]
        if reason:
            excluded.append({"key": claim.key, "kind": claim.kind, "description": claim.description,
                             "due_date": claim.due_date.isoformat(), "amount": as_number(claim.amount),
                             "receivable_id": claim.receivable_id, "reason": reason,
                             "reason_label": EXCLUSION_LABELS[reason]})
        else:
            dunnable.append(claim)
    payments = [Payment(line.booking_date, money(line.amount)) for line in payment_lines]
    payments.extend(Payment(day, amount, claim.key) for claim in dunnable if claim.receivable_id
                    for day, amount in offsets.get(claim.receivable_id, []) if day <= payment_date)
    items, unapplied = rules_.apply_payments(dunnable, payments)
    letters = sorted(_rows(ctx, "dunning_letters", case_id=open_case.id), key=lambda x: (x.stage, x.created_at)) \
        if open_case else []
    return State(contract, as_of, items, excluded, unapplied, open_case,
                 {item.claim_key: item for item in all_items if open_case and item.case_id == open_case.id},
                 letters, _rows(ctx, "dunning_blocks", contract_id=contract_id), disputes, manual)


# ─── Letter figures ──────────────────────────────────────────────────────────

def _address(*parts: Any) -> str | None:
    city = " ".join(p for p in parts[1:3] if p)
    return "\n".join(p for p in (parts[0], city) if p) or None


def _parties(ctx: Any, contract: Any) -> dict:
    prop = ctx.store.get_property(contract.property_id)
    unit_obj = ctx.store.get_unit(contract.unit_id)
    tenant = ctx.store.get_tenant(contract.tenant_id)
    portfolio = ctx.store.get_portfolio(prop.portfolio_id)
    tenant_address = _address(tenant.address_line, tenant.postal_code, tenant.city)
    property_address = _address(prop.address_line, prop.postal_code, prop.city)
    return {
        "portfolio_id": portfolio.id,
        "sender": {"name": portfolio.owner_name or portfolio.name},
        "recipient": {"name": tenant.full_name, "address": tenant_address or property_address,
                      "email": tenant.email},
        "contract": {"id": contract.id, "number": contract.contract_number, "property": prop.name,
                     "unit": unit_obj.label, "tenant_id": tenant.id},
    }


def _s(value: Decimal) -> str:
    return str(money(value))


def letter_content(ctx: Any, state: State, stage: int, letter_date: date, reference: str,
                   rules: list[StageRule], rates: list[RatePeriod], parties: dict) -> tuple[dict, dict[str, date]]:
    """The reviewed content of a letter and, per principal claim, the day interest is charged up to afterwards."""
    rule = {r.stage: r for r in rules}[stage]
    deadline = letter_date + timedelta(days=rule.payment_deadline_days)
    lines, interest_until, missing = [], {}, None
    total_interest = ZERO
    for item in state.overdue_principal():
        claim = item.claim
        case_item = state.case_items.get(claim.key)
        charged = case_item.interest_until if case_item else (claim.due_date if claim.kind == "rent" else None)
        interest = ZERO
        segments: list = []
        if rule.charge_interest and charged is not None and charged < letter_date:
            result = default_interest(item, charged_until=charged, until=letter_date, rates=rates)
            if result.missing_from is not None:
                missing = min(missing, result.missing_from) if missing else result.missing_from
            else:
                interest = result.amount
                segments = result.as_dict()["segments"]
                interest_until[claim.key] = letter_date
        total_interest += interest
        lines.append({"key": claim.key, "kind": claim.kind, "description": claim.description,
                      "receivable_id": claim.receivable_id, "due_date": claim.due_date.isoformat(),
                      "amount": _s(claim.amount), "paid": _s(item.paid), "outstanding": _s(item.outstanding),
                      "interest": _s(interest),
                      "interest_from": (charged + timedelta(days=1)).isoformat() if interest and charged else None,
                      "interest_segments": segments})
    charges = [{"key": item.claim.key, "kind": item.claim.kind, "description": item.claim.description,
                "receivable_id": item.claim.receivable_id, "due_date": item.claim.due_date.isoformat(),
                "amount": _s(item.claim.amount), "paid": _s(item.paid), "outstanding": _s(item.outstanding)}
               for item in state.open_charges()]
    principal = sum((money(line["outstanding"]) for line in lines), ZERO)
    earlier = sum((money(line["outstanding"]) for line in charges), ZERO)
    fee = money(rule.fee)
    notes = []
    if total_interest:
        notes.append("Verzugszinsen nach § 288 Abs. 1 BGB: Basiszinssatz zuzüglich fünf Prozentpunkten jährlich "
                     "auf die offene Hauptforderung, taggenau (Tage/365), je Forderung auf den Cent gerundet.")
    if missing:
        notes.append(f"Für Tage ab {missing.strftime('%d.%m.%Y')} ist kein Basiszinssatz erfasst; Zinsen für die "
                     "betroffenen Forderungen werden in diesem Schreiben nicht berechnet.")
    content = {
        "format_version": PDF_FORMAT_VERSION, "reference": reference, "stage": stage, "stage_label": rule.label,
        "as_of": state.as_of.isoformat(), "letter_date": letter_date.isoformat(),
        "payment_deadline": deadline.isoformat(),
        "sender": parties["sender"], "recipient": {k: parties["recipient"][k] for k in ("name", "address")},
        "contract": {k: parties["contract"][k] for k in ("id", "number", "property", "unit")},
        "lines": lines, "earlier_charges": charges, "principal": _s(principal), "earlier_charges_total": _s(earlier),
        "fee": _s(fee), "interest": _s(total_interest), "total": _s(principal + earlier + fee + total_interest),
        "interest_missing_from": missing.isoformat() if missing else None, "interest_note": " ".join(notes) or None,
    }
    return content, interest_until


def _numbers(content: dict) -> dict:
    return {key: float(content[key]) for key in ("principal", "earlier_charges_total", "fee", "interest", "total")}


# ─── Proposals (preview, job) ────────────────────────────────────────────────

def proposal(ctx: Any, state: State, letter_date: date, rules: list[StageRule], rates: list[RatePeriod],
             parties: dict | None = None) -> dict:
    """What the next step for the contract is, with the figures of the letter it would be."""
    case = state.case
    current = case.stage if case else 0
    principal = state.overdue_principal()
    charges = state.open_charges()
    oldest = min((item.claim.due_date for item in principal), default=None)
    last = state.last_final
    due = next_stage(current, rules=rules, as_of=state.as_of, oldest_overdue=oldest,
                     last_letter_date=last.letter_date if last else None,
                     last_deadline=last.payment_deadline if last else None)
    result: dict[str, Any] = {"contract_id": state.contract.id, "contract_number": state.contract.contract_number,
                              "case_id": case.id if case else None, "case_reference": case.reference if case else None,
                              "current_stage": current, "next_stage": due.stage,
                              "next_stage_label": STAGE_LABELS.get(due.stage or 0),
                              "due_on": due.due_on.isoformat() if due.due_on else None,
                              "excluded": state.excluded + state.manual, "letter": None}
    block = state.active_block(state.as_of)
    if block is not None:
        result.update(status="blocked", reason=f"Mahnsperre bis {block.blocked_until:%d.%m.%Y}: {block.reason}")
    elif state.draft is not None:
        result.update(status="draft_pending", reason="Ein Entwurf dieser Akte ist noch nicht abgeschlossen.")
    elif due.stage is None:
        result.update(status="final_stage", reason="Letzte Mahnstufe erreicht: Ergebnis festhalten "
                                                   "(bezahlt, abgeschrieben oder abgegeben).")
    elif not principal and not (charges and current > 0):
        result.update(status="nothing_due", reason="Keine überfällige Forderung offen.")
    elif not due.due:
        result.update(status="not_yet", reason=f"Nächste Stufe frühestens am {due.due_on:%d.%m.%Y}."
                      if due.due_on else "Noch nicht fällig.")
    else:
        parties = parties or _parties(ctx, state.contract)
        content, _ = letter_content(ctx, state, due.stage, letter_date, case.reference if case else "(neu)", rules,
                                    rates, parties)
        result.update(status="due", reason=None, letter={**_numbers(content), "lines": content["lines"],
                                                          "earlier_charges": content["earlier_charges"],
                                                          "payment_deadline": content["payment_deadline"],
                                                          "interest_missing_from": content["interest_missing_from"],
                                                          "interest_note": content["interest_note"]})
    return result


def _preview_digest(entries: list[dict], as_of: date, letter_date: date) -> str:
    return digest({"as_of": as_of.isoformat(), "letter_date": letter_date.isoformat(),
                   "due": [{k: entry[k] for k in ("contract_id", "case_id", "next_stage", "letter")}
                           for entry in entries if entry["status"] == "due"]})


def _scope_contracts(ctx: Any, scope: RunScope) -> tuple[list, str]:
    if bool(scope.contract_id) == bool(scope.portfolio_id):
        raise HTTPException(422, "Bitte genau einen Vertrag oder ein Portfolio wählen.")
    if scope.contract_id:
        contract = _contract(ctx, scope.contract_id)
        return [contract], ctx.store.get_property(contract.property_id).portfolio_id
    try:
        ctx.store.get_portfolio(scope.portfolio_id)
    except NotFoundError:
        raise HTTPException(404, "Portfolio nicht vorhanden.") from None
    properties = {p.id for p in ctx.store.list_properties() if p.portfolio_id == scope.portfolio_id}
    contracts = sorted((c for c in ctx.store.list_contracts() if c.property_id in properties),
                       key=lambda c: (c.contract_number, c.id))
    return contracts, scope.portfolio_id  # type: ignore[return-value]


def _dates(scope: RunScope) -> tuple[date, date]:
    as_of = scope.as_of or today()
    letter_date = scope.letter_date or as_of
    if letter_date < as_of:
        raise HTTPException(422, "Das Briefdatum darf nicht vor dem Stichtag liegen.")
    return as_of, letter_date


def _preview(ctx: Any, scope: RunScope) -> dict:
    as_of, letter_date = _dates(scope)
    contracts, portfolio_id = _scope_contracts(ctx, scope)
    rules, rates = stage_rules(ctx), base_rates(ctx)
    entries = [proposal(ctx, evaluate(ctx, contract, as_of), letter_date, rules, rates) for contract in contracts]
    due = [entry for entry in entries if entry["status"] == "due"]
    totals = {key: as_number(sum((money(entry["letter"][key]) for entry in due), ZERO))
              for key in ("principal", "earlier_charges_total", "fee", "interest", "total")}
    return {"as_of": as_of.isoformat(), "letter_date": letter_date.isoformat(), "portfolio_id": portfolio_id,
            "contract_id": scope.contract_id, "entries": entries, "due_count": len(due), "totals": totals,
            "preview_hash": _preview_digest(entries, as_of, letter_date)}


def preview(store: Any, scope: RunScope, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit:
        return _preview(unit, scope)


# ─── Runs: cases, claims and draft letters ───────────────────────────────────

def _reference(opened_on: date) -> str:
    return f"M-{opened_on.year}-{uuid4().hex[:8].upper()}"


def _run_public(ctx: Any, run: DunningRun) -> dict:
    letters = _rows(ctx, "dunning_letters", run_id=run.id)
    return {"id": run.id, "portfolio_id": run.portfolio_id, "contract_id": run.contract_id,
            "as_of": run.as_of.isoformat(), "letter_date": run.letter_date.isoformat(), "summary": run.summary,
            "letters": [_letter_brief(ctx, letter) for letter in sorted(letters, key=lambda x: x.contract_id)],
            "created_at": run.created_at.isoformat()}


def create_run(store: Any, payload: RunRequest, actor_id: str) -> dict:
    request_hash = digest({"operation": "dunning_run", "payload": payload.model_dump(mode="json")})
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        existing = _rows(unit, "dunning_runs", created_by=actor_id, command_key=payload.command_key)
        if existing:
            if existing[0].request_sha256 != request_hash:
                raise HTTPException(409, "Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
            return _run_public(unit, existing[0])
        scope = RunScope(**payload.model_dump(include=set(RunScope.model_fields)))
        if scope.contract_id:
            _lock_contract(unit, scope.contract_id)
        result = _preview(unit, scope)
        if result["preview_hash"] != payload.preview_hash:
            raise HTTPException(409, "Seit der Vorschau haben sich Forderungen, Zahlungen oder Sperren geändert. "
                                     "Bitte die Vorschau neu laden.")
        as_of, letter_date = date.fromisoformat(result["as_of"]), date.fromisoformat(result["letter_date"])
        run = _save(unit, "dunning_runs", _new(
            DunningRun, portfolio_id=result["portfolio_id"], contract_id=scope.contract_id, as_of=as_of,
            letter_date=letter_date, preview_hash=payload.preview_hash, request_sha256=request_hash,
            command_key=payload.command_key, created_by=actor_id, summary=None))
        rules, rates = stage_rules(unit), base_rates(unit)
        drafted = 0
        for entry in result["entries"]:
            if entry["status"] != "due":
                continue
            _lock_contract(unit, entry["contract_id"])
            contract = _contract(unit, entry["contract_id"])
            state = evaluate(unit, contract, as_of)
            _draft_letter(unit, state, entry["next_stage"], letter_date, rules, rates, actor_id, run.id)
            drafted += 1
        summary = {"contracts": len(result["entries"]), "letters": drafted,
                   "skipped": {status: sum(1 for e in result["entries"] if e["status"] == status)
                               for status in {e["status"] for e in result["entries"]} if status != "due"},
                   "totals": result["totals"]}
        run = _save(unit, "dunning_runs", run.model_copy(update={"summary": summary}))
        return _run_public(unit, run)


def _draft_letter(ctx: Any, state: State, stage: int, letter_date: date, rules: list[StageRule],
                  rates: list[RatePeriod], actor_id: str, run_id: str | None) -> DunningLetter:
    case = state.case
    if case is None:
        case = _save(ctx, "dunning_cases", _new(DunningCase, contract_id=state.contract.id,
                                                reference=_reference(state.as_of), status="open", stage=0,
                                                opened_on=state.as_of, created_by=actor_id))
        _event(ctx, case, "case_opened", f"Mahnakte {case.reference} angelegt", actor_id)
        state.case = case
    for item in [*state.overdue_principal(), *state.open_charges()]:
        claim = item.claim
        if claim.key in state.case_items:
            continue
        state.case_items[claim.key] = _save(ctx, "dunning_case_items", _new(
            DunningCaseItem, case_id=case.id, claim_key=claim.key, kind=claim.kind, receivable_id=claim.receivable_id,
            due_date=claim.due_date, description=claim.description, amount=as_number(claim.amount),
            first_stage=stage, interest_until=claim.due_date if claim.kind == "rent" else None))
    parties = _parties(ctx, state.contract)
    content, _ = letter_content(ctx, state, stage, letter_date, case.reference, rules, rates, parties)
    numbers = _numbers(content)
    letter = _save(ctx, "dunning_letters", _new(
        DunningLetter, case_id=case.id, contract_id=state.contract.id, run_id=run_id, stage=stage, status="draft",
        letter_date=letter_date, payment_deadline=date.fromisoformat(content["payment_deadline"]),
        principal=numbers["principal"], earlier_charges=numbers["earlier_charges_total"], fee=numbers["fee"],
        interest=numbers["interest"], total=numbers["total"], content=content, draft_hash=digest(content),
        created_by=actor_id))
    _save(ctx, "dunning_outbox", _new(
        DunningOutbox, letter_id=letter.id, contract_id=state.contract.id, channel="letter", status="queued",
        recipient_name=parties["recipient"]["name"], recipient_address=parties["recipient"]["address"],
        recipient_email=parties["recipient"]["email"], subject=subject(content), body=plain_text(content)))
    _event(ctx, case, "letter_drafted", f"Entwurf {content['stage_label']} über {content['total']} €", actor_id,
           {"letter_id": letter.id, "stage": stage})
    state.letters.append(letter)
    return letter


def refresh_letter(store: Any, letter_id: str, actor_id: str) -> dict:
    """Recompute a draft with today's payments and claims (after a 409 at finalization)."""
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        letter = _need(unit, "dunning_letters", letter_id, "Schreiben")
        if letter.status != "draft":
            raise HTTPException(409, "Nur ein Entwurf lässt sich neu berechnen.")
        _lock_contract(unit, letter.contract_id)
        contract = _contract(unit, letter.contract_id)
        as_of = date.fromisoformat(letter.content["as_of"])
        state = evaluate(unit, contract, as_of, payments_until=max(as_of, today()))
        if not state.overdue_principal() and not state.open_charges():
            raise HTTPException(409, "Es ist keine Forderung mehr offen. Bitte den Entwurf verwerfen.")
        content, _ = letter_content(unit, state, letter.stage, letter.letter_date, letter.content["reference"],
                                    stage_rules(unit), base_rates(unit), _parties(unit, contract))
        numbers = _numbers(content)
        letter = _save(unit, "dunning_letters", letter.model_copy(update={
            "content": content, "draft_hash": digest(content), "principal": numbers["principal"],
            "earlier_charges": numbers["earlier_charges_total"], "fee": numbers["fee"],
            "interest": numbers["interest"], "total": numbers["total"],
            "payment_deadline": date.fromisoformat(content["payment_deadline"])}))
        outbox = _rows(unit, "dunning_outbox", letter_id=letter.id)
        if outbox:
            _save(unit, "dunning_outbox", outbox[0].model_copy(update={"subject": subject(content),
                                                                       "body": plain_text(content)}))
        case = _need(unit, "dunning_cases", letter.case_id, "Mahnakte")
        _event(unit, case, "letter_refreshed", f"Entwurf neu berechnet: {content['total']} €", actor_id,
               {"letter_id": letter.id})
        return _letter_public(unit, letter)


def cancel_letter(store: Any, letter_id: str, payload: CancelLetterRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        letter = _need(unit, "dunning_letters", letter_id, "Schreiben")
        if letter.status != "draft":
            raise HTTPException(409, "Ein abgeschlossenes Schreiben bleibt unverändert; nur Entwürfe lassen sich "
                                     "verwerfen.")
        letter = _save(unit, "dunning_letters", letter.model_copy(update={
            "status": "cancelled", "cancelled_at": now(), "cancel_reason": payload.reason}))
        for entry in _rows(unit, "dunning_outbox", letter_id=letter.id):
            _save(unit, "dunning_outbox", entry.model_copy(update={"status": "cancelled"}))
        case = _need(unit, "dunning_cases", letter.case_id, "Mahnakte")
        _event(unit, case, "letter_cancelled", f"Entwurf verworfen: {payload.reason}", actor_id,
               {"letter_id": letter.id})
        return _letter_public(unit, letter)


# ─── Finalizing a letter: charges, original, outbox ──────────────────────────

def _validated_evidence(row: Any) -> dict:
    archive.validate_manifest(row)
    try:
        evidence = validate_dunning_letter_snapshot(row, row.metadata_snapshot)
    except DunningLetterValidationError:
        raise HTTPException(503, "Das archivierte Mahnschreiben ist beschädigt.") from None
    if not evidence:
        raise HTTPException(404, "Kein Mahnschreiben.")
    return evidence


def _replay(unit: archive.Unit, letter: DunningLetter, document: Document, request_hash: str) -> dict:
    if letter.document_id != document.id:
        raise HTTPException(409, "Die Vorgangsreferenz gehört bereits zu einem anderen Schreiben.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Das Schreiben hat kein archiviertes Original.")
    if row.request_sha256 != request_hash or row.actor_id != unit.actor_id:
        raise HTTPException(409, "Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
    _verified(unit, document)
    return _letter_public(unit, letter)


def _add_receivable(unit: archive.Unit, contract_id: str, due: date, amount: Decimal, description: str) -> str:
    stamp, receivable_id = now(), str(uuid4())
    values = {"id": receivable_id, "contract_id": contract_id, "due_date": due, "amount_due": as_number(amount),
              "dunning_level": None, "status": "open", "statement_id": None, "created_at": stamp,
              "updated_at": stamp}
    if unit.db is not None:
        unit.db.execute(insert(ReceivableORM), values)
    else:
        from ..models import Receivable
        unit.insert(unit.store.receivables, receivable_id, Receivable.model_validate({**values,
                                                                                     "description": description}))
    return receivable_id


def _mark_level(unit: archive.Unit, receivable_ids: list[str], stage: int) -> None:
    if not receivable_ids:
        return
    if unit.db is not None:
        unit.db.execute(update(ReceivableORM).where(ReceivableORM.id.in_(receivable_ids))
                        .values(dunning_level=str(stage), updated_at=now()))
        return
    collection = unit.store.receivables
    for receivable_id in receivable_ids:
        if receivable_id in collection:
            unit.insert(collection, receivable_id, collection[receivable_id].model_copy(
                update={"dunning_level": str(stage), "updated_at": now()}))


def _set_receivable_status(unit: Any, receivable_ids: list[str], status: str) -> None:
    if not receivable_ids:
        return
    if unit.db is not None:
        unit.db.execute(update(ReceivableORM).where(ReceivableORM.id.in_(receivable_ids))
                        .values(status=status, updated_at=now()))
        return
    collection = unit.store.receivables
    for receivable_id in receivable_ids:
        if receivable_id in collection:
            unit.insert(collection, receivable_id, collection[receivable_id].model_copy(
                update={"status": status, "updated_at": now()}))


def finalize_letter(store: Any, letter_id: str, payload: FinalizeRequest, actor_id: str) -> dict:
    if not payload.confirmed:
        raise HTTPException(422, "Bitte bestätigen, dass das Schreiben so abgeschlossen werden soll.")
    request_hash = finalize_request_hash(letter_id, payload.model_dump(mode="json"))
    document_id = document_id_for(actor_id, payload.command_key)
    with archive.work(store, actor_id, write_areas=FINALIZE_AREAS) as unit:
        letter = _need(unit, "dunning_letters", letter_id, "Schreiben")
        _lock_contract(unit, letter.contract_id)
        if unit.db is not None:
            unit.db.expire_all()
        letter = _need(unit, "dunning_letters", letter_id, "Schreiben")
        try:
            existing = unit.store.get_document(document_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return _replay(unit, letter, existing, request_hash)
        if letter.status != "draft":
            raise HTTPException(409, "Das Schreiben ist bereits abgeschlossen oder verworfen.")
        if payload.draft_hash != letter.draft_hash:
            raise HTTPException(409, "Der Entwurf wurde inzwischen geändert. Bitte neu laden.")
        contract = _contract(unit, letter.contract_id)
        case = _need(unit, "dunning_cases", letter.case_id, "Mahnakte")
        if case.status != "open":
            raise HTTPException(409, "Die Mahnakte ist abgeschlossen.")
        if any(other.stage < letter.stage and other.status == "draft"
               for other in _rows(unit, "dunning_letters", case_id=case.id)):
            raise HTTPException(409, "Ein früherer Entwurf ist noch offen.")
        if case.stage >= letter.stage:
            raise HTTPException(409, "Diese Mahnstufe ist bereits abgeschlossen.")
        as_of = date.fromisoformat(letter.content["as_of"])
        state = evaluate(unit, contract, as_of, payments_until=max(as_of, today()))
        for day in (letter.letter_date, today()):
            block = state.active_block(day)
            if block is not None:
                raise HTTPException(409, f"Für den Vertrag besteht eine Mahnsperre bis "
                                         f"{block.blocked_until:%d.%m.%Y}: {block.reason}")
        rules, rates = stage_rules(unit), base_rates(unit)
        content, interest_until = letter_content(unit, state, letter.stage, letter.letter_date, case.reference,
                                                 rules, rates, _parties(unit, contract))
        if not content["lines"] and not content["earlier_charges"]:
            raise HTTPException(409, "Es ist keine Forderung mehr offen (z. B. Zahlung eingegangen). "
                                     "Bitte den Entwurf verwerfen und das Ergebnis festhalten.")
        if digest(content) != letter.draft_hash:
            raise HTTPException(409, "Seit dem Entwurf haben sich Forderungen oder Zahlungen geändert (z. B. "
                                     "Zahlungseingang oder Widerspruch). Bitte den Entwurf neu berechnen.")

        deadline = letter.payment_deadline
        charge_ids: list[str] = []
        for kind, amount, label in (("fee", money(content["fee"]), f"Mahngebühr {content['stage_label']}"),
                                    ("interest", money(content["interest"]),
                                     f"Verzugszinsen bis {letter.letter_date:%d.%m.%Y}")):
            if amount <= 0:
                continue
            description = f"{label} ({case.reference})"
            receivable_id = _add_receivable(unit, contract.id, deadline, amount, description)
            charge_ids.append(receivable_id)
            _save(unit, "dunning_case_items", _new(
                DunningCaseItem, case_id=case.id, claim_key=f"{kind}:{letter.id}", kind=kind,
                receivable_id=receivable_id, due_date=deadline, description=description, amount=as_number(amount),
                first_stage=letter.stage))
        for line in content["lines"]:
            item = state.case_items.get(line["key"])
            if item is None:
                continue
            until = interest_until.get(line["key"], item.interest_until)
            if item.kind == "receivable" and until is None:
                until = deadline           # in default after the deadline of the first letter (§ 286 I BGB)
            if until != item.interest_until:
                _save(unit, "dunning_case_items", item.model_copy(update={"interest_until": until}))
        claim_receivables = [line["receivable_id"] for line in [*content["lines"], *content["earlier_charges"]]
                             if line.get("receivable_id")]
        _mark_level(unit, [rid for rid in claim_receivables if rid not in charge_ids], letter.stage)

        pdf = render_pdf(content)
        stamp = now()
        prop = unit.store.get_property(contract.property_id)
        values = {
            "id": document_id,
            **DocumentCreate(
                property_id=prop.id, unit_id=contract.unit_id, contract_id=contract.id,
                title=f"{content['stage_label']} {case.reference} – {contract.contract_number}", document_type=DOC_TYPE,
                document_date=letter.letter_date, tags="mahnung",
                description=f"{content['stage_label']} über {content['total']} €, Zahlungsziel "
                            f"{deadline:%d.%m.%Y}",
                file_url=f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf",
            ).model_dump(),
            "ai_document_type": None, "ai_summary": None, "ai_entities_json": None, "ai_confidence": None,
            "ai_model": None, "ai_analyzed_at": None, "created_at": stamp, "updated_at": stamp,
        }
        document = Document.model_validate(values)
        if unit.db is not None:
            unit.db.execute(insert(DocumentORM), values)
        else:
            unit.insert(object.__getattribute__(unit.store, "__dict__")["documents"], document.id, document)
        binding = {"portfolio_id": prop.portfolio_id, "property_id": prop.id, "unit_id": contract.unit_id,
                   "contract_id": contract.id, "tenant_id": contract.tenant_id}
        extension = {
            "schema_version": SCHEMA_VERSION, "content": content, "draft_hash": letter.draft_hash,
            "request_sha256": request_hash, "actor_id": actor_id, "command_key": payload.command_key,
            "letter_id": letter.id, "case_id": case.id, "reference": case.reference, "stage": letter.stage,
            "claim_keys": [line["key"] for line in [*content["lines"], *content["earlier_charges"]]],
            "receivable_ids": claim_receivables, "charge_receivable_ids": charge_ids, "confirmed": True,
        }
        row = archive.publish_generated_original(unit, document, binding, pdf, request_hash, version_id=str(uuid4()),
                                                 metadata_extra={"dunning_letter": extension})
        _validated_evidence(row)
        letter = _save(unit, "dunning_letters", letter.model_copy(update={
            "status": "final", "document_id": document_id, "version_id": row.id, "finalized_at": stamp,
            "finalized_by": actor_id}))
        _save(unit, "dunning_cases", case.model_copy(update={"stage": letter.stage}))
        for entry in _rows(unit, "dunning_outbox", letter_id=letter.id):
            email = entry.recipient_email if payload.channel == "email" else None
            if payload.channel == "email" and not email:
                raise HTTPException(409, "Für den Mieter ist keine E-Mail-Adresse hinterlegt. Bitte per Brief "
                                         "abschließen oder die Adresse ergänzen.")
            _save(unit, "dunning_outbox", entry.model_copy(update={
                "channel": payload.channel, "status": "ready", "prepared_at": stamp, "subject": subject(content),
                "body": plain_text(content)}))
        _event(unit, case, "letter_finalized", f"{content['stage_label']} abgeschlossen: {content['total']} €, "
                                               f"Zahlungsziel {deadline:%d.%m.%Y}", actor_id,
               {"letter_id": letter.id, "document_id": document_id, "pdf_sha256": row.sha256})
        return _letter_public(unit, letter)


def _verified(unit: archive.Unit, document: Document) -> tuple[bytes, Any]:
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(404, "Das Schreiben hat kein archiviertes Original.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    _validated_evidence(row)
    return archive.original_bytes(unit, row), row


def letter_pdf(store: Any, letter_id: str, actor_id: str) -> tuple[bytes, str, bool]:
    """(PDF, file name, is the archived original): a draft is rendered, a final letter is the verified original."""
    with archive.work(store, actor_id) as unit:
        letter = _need(unit, "dunning_letters", letter_id, "Schreiben")
        name = f"{letter.content['stage_label']} {letter.content['reference']}.pdf".replace(" ", "_")
        if letter.status != "final":
            return render_pdf(letter.content), name, False
        try:
            document = unit.store.get_document(letter.document_id)
        except NotFoundError:
            raise HTTPException(404, "Schreiben nicht vorhanden.") from None
        content, _ = _verified(unit, document)
        return content, name, True


def read_pdf_for_key(store: Any, key: str, actor_id: str) -> bytes | None:
    """/uploads/dunning-letters/<id>.pdf: always the verified original, never a file on disk."""
    if not key.startswith(VIRTUAL_PREFIX) or not key.endswith(".pdf"):
        return None
    identifier = key[len(VIRTUAL_PREFIX):-4]
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError
    except ValueError:
        raise HTTPException(404, "Schreiben nicht vorhanden.") from None
    with archive.work(store, actor_id) as unit:
        try:
            document = unit.store.get_document(identifier)
        except NotFoundError:
            raise HTTPException(404, "Schreiben nicht vorhanden.") from None
        if document.file_url != f"/uploads/{key}":
            raise HTTPException(404, "Schreiben nicht vorhanden.")
        return _verified(unit, document)[0]


# ─── Public shapes ───────────────────────────────────────────────────────────

def _letter_brief(ctx: Any, letter: DunningLetter) -> dict:
    return {"id": letter.id, "case_id": letter.case_id, "contract_id": letter.contract_id, "stage": letter.stage,
            "stage_label": letter.content.get("stage_label"), "status": letter.status,
            "reference": letter.content.get("reference"), "letter_date": letter.letter_date.isoformat(),
            "payment_deadline": letter.payment_deadline.isoformat(), "principal": letter.principal,
            "earlier_charges": letter.earlier_charges, "fee": letter.fee, "interest": letter.interest,
            "total": letter.total, "document_id": letter.document_id,
            "finalized_at": letter.finalized_at.isoformat() if letter.finalized_at else None,
            "cancel_reason": letter.cancel_reason}


def _letter_public(ctx: Any, letter: DunningLetter) -> dict:
    outbox = _rows(ctx, "dunning_outbox", letter_id=letter.id)
    return {**_letter_brief(ctx, letter), "content": letter.content, "draft_hash": letter.draft_hash,
            "outbox": _outbox_public(outbox[0]) if outbox else None,
            "pdf_url": f"/dunning/letters/{letter.id}/pdf",
            "original_url": f"/uploads/{VIRTUAL_PREFIX}{letter.document_id}.pdf" if letter.document_id else None}


def letter_detail(store: Any, letter_id: str, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit:
        return _letter_public(unit, _need(unit, "dunning_letters", letter_id, "Schreiben"))


def _outbox_public(entry: DunningOutbox, extra: dict | None = None) -> dict:
    return {**entry.model_dump(mode="json", exclude={"body"}), "body": entry.body, **(extra or {})}


def _case_public(case: DunningCase) -> dict:
    return {**case.model_dump(mode="json"), "stage_label": STAGE_LABELS.get(case.stage, "Noch kein Schreiben"),
            "result_label": RESULT_LABELS.get(case.result or "")}


def _item_public(item: OpenItem) -> dict:
    claim = item.claim
    return {"key": claim.key, "kind": claim.kind, "description": claim.description,
            "due_date": claim.due_date.isoformat(), "amount": as_number(claim.amount), "paid": as_number(item.paid),
            "outstanding": as_number(item.outstanding), "receivable_id": claim.receivable_id}


# ─── The case file of a contract ─────────────────────────────────────────────

def contract_file(store: Any, contract_id: str, actor_id: str, as_of: date | None = None) -> dict:
    with archive.work(store, actor_id) as unit:
        contract = _contract(unit, contract_id)
        day = as_of or today()
        state = evaluate(unit, contract, day)
        rules, rates = stage_rules(unit), base_rates(unit)
        parties = _parties(unit, contract)
        cases = sorted(_rows(unit, "dunning_cases", contract_id=contract.id), key=lambda c: (c.opened_on, c.id),
                       reverse=True)
        letters = _rows(unit, "dunning_letters", contract_id=contract.id)
        outbox = {entry.letter_id: entry for entry in _rows(unit, "dunning_outbox", contract_id=contract.id)}
        case_keys = {case.id: {i.claim_key for i in _rows(unit, "dunning_case_items", case_id=case.id)}
                     for case in cases}
        items = [i for i in state.items if i.outstanding > 0 or i.claim.key in case_keys.get(
            state.case.id if state.case else "", set())]
        return {
            "contract": {**parties["contract"], "tenant_name": parties["recipient"]["name"],
                         "tenant_email": parties["recipient"]["email"], "status": contract.status,
                         "portfolio_id": parties["portfolio_id"]},
            "as_of": day.isoformat(),
            "claims": [_item_public(i) for i in items],
            "excluded": state.excluded, "manual": state.manual,
            "totals": {"overdue_principal": as_number(sum((i.outstanding for i in state.overdue_principal()), ZERO)),
                       "open_charges": as_number(sum((i.outstanding for i in state.open_charges()), ZERO)),
                       "unapplied_payments": as_number(state.unapplied)},
            "blocks": [b.model_dump(mode="json") | {"active": b.lifted_at is None and b.blocked_until >= day}
                       for b in sorted(state.blocks, key=lambda b: b.created_at, reverse=True)],
            "disputes": [d.model_dump(mode="json") for d in sorted(state.disputes, key=lambda d: d.raised_on,
                                                                   reverse=True)],
            "cases": [{**_case_public(case), "outstanding": as_number(_case_outstanding(state, case_keys[case.id]))
                       if case.status == "open" else case.result_outstanding,
                       "letters": [{**_letter_brief(unit, letter),
                                    "outbox": _outbox_public(outbox[letter.id]) if letter.id in outbox else None}
                                   for letter in sorted(letters, key=lambda x: (x.stage, x.created_at))
                                   if letter.case_id == case.id]}
                      for case in cases],
            "next": proposal(unit, state, day, rules, rates, parties),
        }


def _case_outstanding(state: State, keys: set[str]) -> Decimal:
    open_items = sum((item.outstanding for item in state.items if item.claim.key in keys), ZERO)
    pending = sum((money(entry["amount"]) for entry in state.excluded
                   if entry["key"] in keys and entry["reason"] in ("dispute", "objection")), ZERO)
    return open_items + pending


def overview(store: Any, actor_id: str, *, status: str = "open", portfolio_id: str | None = None,
             offset: int = 0, limit: int = 50, as_of: date | None = None) -> dict:
    if not 1 <= limit <= MAX_PAGE or offset < 0:
        raise HTTPException(422, f"Bitte eine Seitengröße zwischen 1 und {MAX_PAGE} wählen.")
    if status not in ("open", "closed", "all"):
        raise HTTPException(422, "Unbekannter Status.")
    day = as_of or today()
    with archive.work(store, actor_id) as unit:
        cases = _rows(unit, "dunning_cases") if status == "all" else _rows(unit, "dunning_cases", status=status)
        contracts = {c.id: c for c in unit.store.list_contracts()}
        properties = {p.id: p for p in unit.store.list_properties()}
        tenants = {t.id: t for t in unit.store.list_tenants()}
        if portfolio_id:
            cases = [c for c in cases if c.contract_id in contracts
                     and properties.get(contracts[c.contract_id].property_id) is not None
                     and properties[contracts[c.contract_id].property_id].portfolio_id == portfolio_id]
        cases.sort(key=lambda c: (c.status != "open", -c.stage, c.opened_on, c.id))
        page = cases[offset:offset + limit]
        rows = []
        for case in page:
            contract = contracts.get(case.contract_id)
            if contract is None:
                continue
            letters = _rows(unit, "dunning_letters", case_id=case.id)
            entry = {**_case_public(case), "contract_number": contract.contract_number,
                     "tenant_name": tenants[contract.tenant_id].full_name if contract.tenant_id in tenants else None,
                     "property_name": properties[contract.property_id].name
                     if contract.property_id in properties else None,
                     "drafts": sum(1 for letter in letters if letter.status == "draft"),
                     "last_letter": _letter_brief(unit, max((x for x in letters if x.status == "final"),
                                                            key=lambda x: x.stage))
                     if any(x.status == "final" for x in letters) else None}
            if case.status == "open":
                state = evaluate(unit, contract, day)
                keys = {i.claim_key for i in _rows(unit, "dunning_case_items", case_id=case.id)}
                entry["outstanding"] = as_number(_case_outstanding(state, keys))
                block = state.active_block(day)
                entry["blocked_until"] = block.blocked_until.isoformat() if block else None
                nxt = proposal(unit, state, day, stage_rules(unit), base_rates(unit))
                entry["next_status"], entry["next_stage"], entry["due_on"] = (nxt["status"], nxt["next_stage"],
                                                                              nxt["due_on"])
            else:
                entry["outstanding"] = case.result_outstanding
            rows.append(entry)
        counts = {
            "open_cases": len(_rows(unit, "dunning_cases", status="open")),
            "drafts": len(_rows(unit, "dunning_letters", status="draft")),
            "outbox_ready": len(_rows(unit, "dunning_outbox", status="ready")),
            "replies_review": len(_rows(unit, "dunning_replies", status="review")),
            "active_blocks": sum(1 for b in _rows(unit, "dunning_blocks") if b.lifted_at is None
                                 and b.blocked_until >= day),
        }
        return {"counts": counts, "total": len(cases), "offset": offset, "limit": limit, "items": rows,
                "as_of": day.isoformat()}


# ─── Timeline (case thread), paged ───────────────────────────────────────────

def _encode_cursor(at: datetime, event_id: str) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{event_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, event_id = text.split("|", 1)
        return datetime.fromisoformat(stamp), event_id
    except (ValueError, binascii.Error, UnicodeError):
        raise HTTPException(422, "Ungültige Seite. Bitte die erste Seite neu laden.") from None


def timeline(store: Any, case_id: str, actor_id: str, *, after: str | None = None, limit: int = 50) -> dict:
    if not 1 <= limit <= MAX_PAGE:
        raise HTTPException(422, f"Bitte eine Seitengröße zwischen 1 und {MAX_PAGE} wählen.")
    with archive.work(store, actor_id) as unit:
        case = _need(unit, "dunning_cases", case_id, "Mahnakte")
        point = _decode_cursor(after) if after else None
        if unit.db is not None:
            model = DunningEventORM
            query = select(model).where(model.case_id == case.id)
            if point is not None:
                query = query.where((model.at > point[0]) | ((model.at == point[0]) & (model.id > point[1])))
            found = [DunningEvent.model_validate(_row(row)) for row in
                     unit.db.scalars(query.order_by(model.at, model.id).limit(limit + 1))]
            total = unit.db.scalar(select(func.count()).select_from(model).where(model.case_id == case.id))
        else:
            events = sorted((e for e in unit.store.dunning_events.values() if e.case_id == case.id),
                            key=lambda e: (e.at, e.id))
            total = len(events)
            found = [e for e in events if point is None or (e.at, e.id) > point][:limit + 1]
        page = found[:limit]
        replies = {r.id: r for r in _rows(unit, "dunning_replies", id={e.data["reply_id"] for e in page
                                                                         if e.data and e.data.get("reply_id")})} \
            if any(e.data and e.data.get("reply_id") for e in page) else {}
        items = []
        for event in page:
            entry = event.model_dump(mode="json")
            reply_id = (event.data or {}).get("reply_id")
            if reply_id and reply_id in replies:
                entry["reply"] = replies[reply_id].model_dump(mode="json")
            items.append(entry)
        more = len(found) > limit
        return {"case": _case_public(case), "items": items, "total": total, "has_more": more,
                "next_after": _encode_cursor(page[-1].at, page[-1].id) if more and page else None}


def add_note(store: Any, case_id: str, payload: NoteRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        case = _need(unit, "dunning_cases", case_id, "Mahnakte")
        return _event(unit, case, "note", payload.text, actor_id).model_dump(mode="json")


# ─── Blocks and disputes ─────────────────────────────────────────────────────

def add_block(store: Any, contract_id: str, payload: BlockRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        contract = _contract(unit, contract_id)
        if payload.blocked_until < today():
            raise HTTPException(422, "Eine Mahnsperre muss bis heute oder später gelten.")
        block = _save(unit, "dunning_blocks", _new(DunningBlock, contract_id=contract.id, reason=payload.reason,
                                                   blocked_until=payload.blocked_until, created_by=actor_id))
        for case in _rows(unit, "dunning_cases", contract_id=contract.id, status="open"):
            _event(unit, case, "block_set", f"Mahnsperre bis {payload.blocked_until:%d.%m.%Y}: {payload.reason}",
                   actor_id, {"block_id": block.id})
        return block.model_dump(mode="json")


def lift_block(store: Any, block_id: str, payload: LiftBlockRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        block = _need(unit, "dunning_blocks", block_id, "Mahnsperre")
        if block.lifted_at is not None:
            raise HTTPException(409, "Die Mahnsperre ist bereits aufgehoben.")
        block = _save(unit, "dunning_blocks", block.model_copy(update={"lifted_at": now(), "lifted_by": actor_id,
                                                                       "lift_note": payload.note}))
        for case in _rows(unit, "dunning_cases", contract_id=block.contract_id, status="open"):
            _event(unit, case, "block_lifted", "Mahnsperre aufgehoben" + (f": {payload.note}" if payload.note else ""),
                   actor_id, {"block_id": block.id})
        return block.model_dump(mode="json")


def add_dispute(store: Any, contract_id: str, payload: DisputeRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        contract = _contract(unit, contract_id)
        state = evaluate(unit, contract, payload.raised_on or today())
        known = {i.claim.key for i in state.items} | {e["key"] for e in state.excluded}
        if payload.claim_key not in known:
            raise HTTPException(422, "Diese Forderung gehört nicht zum Vertrag.")
        if any(d.claim_key == payload.claim_key and d.status == "open" for d in state.disputes):
            raise HTTPException(409, "Für diese Forderung ist bereits ein Einwand offen.")
        dispute = _save(unit, "dunning_disputes", _new(
            DunningDispute, contract_id=contract.id, claim_key=payload.claim_key, reason=payload.reason,
            raised_on=payload.raised_on or today(), status="open", created_by=actor_id))
        for case in _rows(unit, "dunning_cases", contract_id=contract.id, status="open"):
            _event(unit, case, "dispute_raised", f"Einwand gegen {payload.claim_key}: {payload.reason}", actor_id,
                   {"dispute_id": dispute.id})
        return dispute.model_dump(mode="json")


def decide_dispute(store: Any, dispute_id: str, payload: DisputeDecision, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        dispute = _need(unit, "dunning_disputes", dispute_id, "Einwand")
        if dispute.status != "open":
            raise HTTPException(409, "Der Einwand ist bereits entschieden.")
        dispute = _save(unit, "dunning_disputes", dispute.model_copy(update={
            "status": payload.decision, "decided_on": payload.decided_on or today(), "decision_note": payload.note}))
        label = "berechtigt" if payload.decision == "upheld" else "zurückgewiesen"
        for case in _rows(unit, "dunning_cases", contract_id=dispute.contract_id, status="open"):
            _event(unit, case, "dispute_decided", f"Einwand gegen {dispute.claim_key} {label}", actor_id,
                   {"dispute_id": dispute.id})
        return dispute.model_dump(mode="json")


# ─── Results ─────────────────────────────────────────────────────────────────

def set_result(store: Any, case_id: str, payload: ResultRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        case = _need(unit, "dunning_cases", case_id, "Mahnakte")
        _lock_contract(unit, case.contract_id)
        if case.status != "open":
            raise HTTPException(409, "Die Mahnakte ist bereits abgeschlossen.")
        letters = _rows(unit, "dunning_letters", case_id=case.id)
        if any(letter.status == "draft" for letter in letters):
            raise HTTPException(409, "Bitte zuerst den offenen Entwurf abschließen oder verwerfen.")
        contract = _contract(unit, case.contract_id)
        state = evaluate(unit, contract, payload.result_date)
        items = _rows(unit, "dunning_case_items", case_id=case.id)
        keys = {item.claim_key for item in items}
        outstanding = _case_outstanding(state, keys)
        paid = sum((item.paid for item in state.items if item.claim.key in keys), ZERO)
        if payload.result == "paid" and outstanding > 0:
            raise HTTPException(409, f"Es sind noch {as_number(outstanding):.2f} € offen. Bitte „teilweise bezahlt“, "
                                     "„abgeschrieben“ oder „abgegeben“ wählen.")
        if payload.result == "partially_paid" and (outstanding <= 0 or paid <= 0):
            raise HTTPException(409, "„Teilweise bezahlt“ setzt einen Zahlungseingang und einen offenen Rest voraus.")
        case = _save(unit, "dunning_cases", case.model_copy(update={
            "status": "closed", "closed_on": payload.result_date, "result": payload.result,
            "result_date": payload.result_date, "result_reference": payload.reference, "result_note": payload.note,
            "result_outstanding": as_number(outstanding)}))
        charges = [item.receivable_id for item in items if item.kind in ("fee", "interest") and item.receivable_id]
        open_charges = {i.claim.receivable_id for i in state.items if i.claim.receivable_id
                        and i.claim.receivable_id in charges and i.outstanding > 0}
        if payload.result == "written_off":
            _set_receivable_status(unit, sorted(open_charges), "cancelled")
        elif payload.result == "paid":
            _set_receivable_status(unit, sorted(set(charges) - open_charges), "paid")
        _event(unit, case, "result", f"Ergebnis: {RESULT_LABELS[payload.result]} am {payload.result_date:%d.%m.%Y}, "
                                     f"Referenz {payload.reference}; offen {as_number(outstanding):.2f} €",
               actor_id, {"result": payload.result, "outstanding": str(outstanding)})
        return _case_public(case)


# ─── Outbox ──────────────────────────────────────────────────────────────────

def outbox(store: Any, actor_id: str, *, status: str | None = None, contract_id: str | None = None,
           offset: int = 0, limit: int = 50) -> dict:
    if not 1 <= limit <= MAX_PAGE or offset < 0:
        raise HTTPException(422, f"Bitte eine Seitengröße zwischen 1 und {MAX_PAGE} wählen.")
    with archive.work(store, actor_id) as unit:
        criteria: dict[str, Any] = {}
        if status:
            criteria["status"] = status
        if contract_id:
            criteria["contract_id"] = contract_id
        entries = sorted(_rows(unit, "dunning_outbox", **criteria), key=lambda e: (e.created_at, e.id), reverse=True)
        page = entries[offset:offset + limit]
        letters = {letter.id: letter for letter in _rows(unit, "dunning_letters", id={e.letter_id for e in page})} \
            if page else {}
        return {"total": len(entries), "offset": offset, "limit": limit,
                "items": [_outbox_public(entry, {"letter": _letter_brief(unit, letters[entry.letter_id])
                                                 if entry.letter_id in letters else None}) for entry in page]}


def mark_sent(store: Any, entry_id: str, payload: MarkSentRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        entry = _need(unit, "dunning_outbox", entry_id, "Postausgangseintrag")
        if entry.status != "ready":
            raise HTTPException(409, "Nur ein abgeschlossenes, noch nicht versendetes Schreiben lässt sich als "
                                     "versendet vermerken.")
        letter = _need(unit, "dunning_letters", entry.letter_id, "Schreiben")
        if payload.sent_on < letter.letter_date:
            raise HTTPException(422, "Das Versanddatum liegt vor dem Briefdatum.")
        entry = _save(unit, "dunning_outbox", entry.model_copy(update={
            "status": "sent", "sent_on": payload.sent_on, "sent_via": payload.via, "sent_note": payload.note,
            "sent_by": actor_id}))
        case = _need(unit, "dunning_cases", letter.case_id, "Mahnakte")
        _event(unit, case, "sent", f"{letter.content['stage_label']} versendet am {payload.sent_on:%d.%m.%Y} "
                                   f"({payload.via})", actor_id, {"letter_id": letter.id, "outbox_id": entry.id})
        return _outbox_public(entry)


def email_draft(store: Any, entry_id: str, actor_id: str) -> tuple[bytes, str]:
    """An unsent e-mail (.eml) with the archived original attached, to open in a mail program."""
    with archive.work(store, actor_id) as unit:
        entry = _need(unit, "dunning_outbox", entry_id, "Postausgangseintrag")
        if entry.status not in ("ready", "sent") or entry.channel != "email" or not entry.recipient_email:
            raise HTTPException(409, "Ein E-Mail-Entwurf gibt es nur für abgeschlossene Schreiben per E-Mail.")
        letter = _need(unit, "dunning_letters", entry.letter_id, "Schreiben")
        document = unit.store.get_document(letter.document_id)
        pdf, row = _verified(unit, document)
        message = EmailMessage()
        message["To"] = entry.recipient_email
        message["Subject"] = entry.subject
        message["Date"] = format_datetime(datetime.combine(letter.letter_date, datetime.min.time(), timezone.utc))
        message["X-Unsent"] = "1"
        message.set_content(entry.body)
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=row.filename)
        return message.as_bytes(), f"{letter.content['reference']}.eml"


# ─── Replies ─────────────────────────────────────────────────────────────────

def _references(*texts: str | None) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in REFERENCE.findall(text or ""):
            value = match.upper()
            if value not in found:
                found.append(value)
    return found


def _reply_public(ctx: Any, reply: DunningReply) -> dict:
    case = _one(ctx, "dunning_cases", reply.case_id) if reply.case_id else None
    return {**reply.model_dump(mode="json"), "case_reference": case.reference if case else None}


def record_reply(store: Any, payload: ReplyRequest, actor_id: str) -> dict:
    """Attach only on one explicit, known reference; anything else goes to the review list."""
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        references = _references(payload.reference, payload.body)
        cases = {ref: _rows(unit, "dunning_cases", reference=ref) for ref in references}
        known = {ref: found[0] for ref, found in cases.items() if found}
        case, reason = None, None
        if not references:
            reason = "no_reference"
        elif len(references) > 1:
            reason = "ambiguous"
        elif not known:
            reason = "unknown_reference"
        else:
            case = known[references[0]]
        reply = _save(unit, "dunning_replies", _new(
            DunningReply, case_id=case.id if case else None, contract_id=case.contract_id if case else None,
            reference=payload.reference, received_on=payload.received_on or today(), channel=payload.channel,
            sender=payload.sender, body=payload.body, status="assigned" if case else "review", review_reason=reason,
            assigned_by=actor_id if case else None, assigned_at=now() if case else None, created_by=actor_id))
        if case is not None:
            _event(unit, case, "reply", f"Eingang ({payload.channel}) vom {reply.received_on:%d.%m.%Y}", actor_id,
                   {"reply_id": reply.id})
        return _reply_public(unit, reply)


def replies(store: Any, actor_id: str, *, status: str | None = "review", offset: int = 0, limit: int = 50) -> dict:
    if not 1 <= limit <= MAX_PAGE or offset < 0:
        raise HTTPException(422, f"Bitte eine Seitengröße zwischen 1 und {MAX_PAGE} wählen.")
    with archive.work(store, actor_id) as unit:
        found = _rows(unit, "dunning_replies", status=status) if status else _rows(unit, "dunning_replies")
        found.sort(key=lambda r: (r.received_on, r.created_at, r.id), reverse=True)
        return {"total": len(found), "offset": offset, "limit": limit,
                "items": [_reply_public(unit, r) for r in found[offset:offset + limit]]}


def assign_reply(store: Any, reply_id: str, payload: AssignRequest, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        reply = _need(unit, "dunning_replies", reply_id, "Eingang")
        if reply.status != "review":
            raise HTTPException(409, "Nur Eingänge der Prüfliste lassen sich zuordnen.")
        if bool(payload.case_id) == bool(payload.reference):
            raise HTTPException(422, "Bitte genau eine Mahnakte oder ein Aktenzeichen angeben.")
        if payload.case_id:
            case = _need(unit, "dunning_cases", payload.case_id, "Mahnakte")
        else:
            found = _rows(unit, "dunning_cases", reference=(payload.reference or "").strip().upper())
            if not found:
                raise HTTPException(404, "Mahnakte nicht vorhanden.")
            case = found[0]
        reply = _save(unit, "dunning_replies", reply.model_copy(update={
            "case_id": case.id, "contract_id": case.contract_id, "status": "assigned", "assigned_by": actor_id,
            "assigned_at": now()}))
        _event(unit, case, "reply", f"Eingang ({reply.channel}) vom {reply.received_on:%d.%m.%Y} von Hand zugeordnet",
               actor_id, {"reply_id": reply.id, "manual": True})
        return _reply_public(unit, reply)


def unassign_reply(store: Any, reply_id: str, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        reply = _need(unit, "dunning_replies", reply_id, "Eingang")
        if reply.status != "assigned" or reply.case_id is None:
            raise HTTPException(409, "Der Eingang ist keiner Mahnakte zugeordnet.")
        case = _need(unit, "dunning_cases", reply.case_id, "Mahnakte")
        reply = _save(unit, "dunning_replies", reply.model_copy(update={
            "case_id": None, "contract_id": None, "status": "review", "review_reason": "unassigned",
            "assigned_by": None, "assigned_at": None}))
        _event(unit, case, "reply_unassigned", "Eingang von der Akte gelöst (falsche Zuordnung)", actor_id,
               {"reply_id": reply.id})
        return _reply_public(unit, reply)


def dismiss_reply(store: Any, reply_id: str, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=WRITE_AREAS) as unit:
        reply = _need(unit, "dunning_replies", reply_id, "Eingang")
        if reply.status != "review":
            raise HTTPException(409, "Nur Eingänge der Prüfliste lassen sich ablegen.")
        return _reply_public(unit, _save(unit, "dunning_replies", reply.model_copy(update={"status": "dismissed"})))


# ─── The escalation job: proposals, never letters ────────────────────────────

PROPOSAL_RULE_VERSION = "v1"


def proposal_key(contract_id: str) -> str:
    return f"dunning:{contract_id}"


def propose(store: Any, ledger: Any, run_id: str | None, as_of: date, contracts: Iterable[Any]) -> int:
    """Notify once per contract and due next stage; returns how many proposals were new."""
    ctx = JobContext(store)
    rules, rates = stage_rules(ctx), base_rates(ctx)
    created = 0
    for contract in contracts:
        state = evaluate(ctx, contract, as_of)
        entry = proposal(ctx, state, as_of, rules, rates)
        if entry["status"] != "due":
            continue
        last = state.last_final
        basis = last.id if last else min(i.claim.key for i in state.overdue_principal())
        occurrence = f"{state.case.id if state.case else 'new'}:{entry['next_stage']}:{basis}"
        if not ledger.record(proposal_key(contract.id), PROPOSAL_RULE_VERSION, occurrence, "proposed", run_id):
            continue
        title = f"Mahnvorschlag: {entry['next_stage_label']} – Vertrag {contract.contract_number}"
        content = (f"Fällig seit {date.fromisoformat(entry['due_on']):%d.%m.%Y}: {entry['next_stage_label']} über "
                   f"{entry['letter']['total']:.2f} € (Hauptforderung {entry['letter']['principal']:.2f} €). "
                   "Bitte in der Mahnübersicht prüfen und den Lauf bestätigen; es wurde nichts versendet.")
        notification = NotificationCreate(notification_type="dunning_proposal", title=title, content=content,
                                          severity="warning", entity_type="contract", entity_id=contract.id)
        if ctx.db is not None:
            store.communication._notifications.create(notification)
        else:
            store.create_notification(notification)
        created += 1
    return created


# ─── DSGVO ───────────────────────────────────────────────────────────────────

def records_of_contracts(store: Any, contract_ids: set[str]) -> dict[str, list]:
    """Dunning records of the tenant's contracts for the DSGVO export (Art. 15)."""
    ctx = JobContext(store)
    if not contract_ids:
        return {name: [] for name in ("dunning_cases", "dunning_case_items", "dunning_letters", "dunning_outbox",
                                      "dunning_blocks", "dunning_disputes", "dunning_replies", "dunning_events")}
    cases = _rows(ctx, "dunning_cases", contract_id=contract_ids)
    case_ids = {c.id for c in cases}
    return {
        "dunning_cases": cases,
        "dunning_case_items": _rows(ctx, "dunning_case_items", case_id=case_ids) if case_ids else [],
        "dunning_letters": _rows(ctx, "dunning_letters", contract_id=contract_ids),
        "dunning_outbox": _rows(ctx, "dunning_outbox", contract_id=contract_ids),
        "dunning_blocks": _rows(ctx, "dunning_blocks", contract_id=contract_ids),
        "dunning_disputes": _rows(ctx, "dunning_disputes", contract_id=contract_ids),
        "dunning_replies": _rows(ctx, "dunning_replies", contract_id=contract_ids),
        "dunning_events": _rows(ctx, "dunning_events", contract_id=contract_ids),
    }


def contract_ids_after(store: Any, after: str, limit: int) -> list[Any]:
    """Contracts in id order, a chunk at a time (the job)."""
    if hasattr(store, "db") and hasattr(store, "communication"):
        from ..models import Contract
        rows = store.db.scalars(select(ContractORM).where(ContractORM.id > after).order_by(ContractORM.id)
                                .limit(limit))
        return [Contract.model_validate(_row(row)) for row in rows]
    return sorted((c for c in store.list_contracts() if c.id > after), key=lambda c: c.id)[:limit]

