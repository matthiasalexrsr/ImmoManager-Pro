"""Deposit file (Kautionsakte): from the agreement to the settlement, linked to receipt, payment and result.

* Agreement (`deposits`): amount (cap three net cold rents, § 551 I BGB: above it only
  with an explicit reason), form, up to three instalments, where the money is held.
* Receipt: the instalments are expectations; payments are bookings of the tenant, of
  which the deposit file names a share (`deposit_payments`). That share is no rent: the
  rent allocation of the booking is recomputed without it, so every amount counts once.
* Interest of a cash deposit: rate periods, exact arithmetic (domain/deposit_rules.py).
* Move-out: a settlement draft offers the defects the finalized move-out protocol puts
  on the tenant (amounts entered by hand), the contract's open receivables and rent
  arrears to offset, and a retention for an open utility statement period. Finalizing
  archives the PDF as an immutable original and, once per command key, creates the
  payout booking (or the remaining-claim receivable), the offset bookings and settles
  the offset receivables. Releasing a retention later is its own settlement with its
  own original.
* Guarantee / pledged savings book: no booking; provided and released with date and proof.
* Takeover: a deposit paid before this app's bookings begin has no booking to link. The
  file takes the day from which the app keeps it, the deposit received and the interest
  credited until then; that amount counts as received on that day (instalments,
  interest, settlement), and bookings before that day are part of it. The plain records
  of earlier versions (status "held" with a receipt date) can be taken over in one step.

All database work runs in document_versions.work() units (SQL session, or memory with
undo) called from synchronous endpoints in the thread pool. Writes re-check the
actor's rights under the account lock up to the commit; reads follow the portfolio
boundary of the contract (a foreign deposit is "not found").
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..db.deposit_models import (
    DepositInstalmentORM,
    DepositInterestRateORM,
    DepositPaymentORM,
    DepositSettlementItemORM,
    DepositSettlementORM,
)
from ..db.orm_models import (
    BookingORM,
    ContractORM,
    DepositORM,
    DocumentORM,
    PaymentAllocationORM,
    PropertyORM,
    ReceivableORM,
    TenantORM,
    UnitORM,
)
from ..domain import deposit_rules as rules
from ..domain.clock import local_today
from ..domain.lease_engine import LeaseEngine
from ..domain.money import ZERO, as_number, money
from ..models import Booking, Deposit, Document, DocumentCreate, PaymentAllocation, Receivable
from ..models_deposits import (
    AgreementRequest,
    DepositInstalment,
    DepositInterestRate,
    DepositPayment,
    DepositSettlement,
    DepositSettlementItem,
    FinalizeRequest,
    LegacyTakeoverRequest,
    RatesRequest,
    ReceiptRequest,
    SecurityRequest,
    SettlementContent,
    SettlementCreate,
    TakeoverRequest,
)
from ..storage import NotFoundError
from . import document_versions as archive
from . import letterhead as letterheads
from .deposit_render import render_pdf
from .deposit_validation import (
    DOC_TYPE,
    LETTERHEAD_FORMAT_VERSION,
    SCHEMA_VERSION,
    VIRTUAL_PREFIX,
    DepositValidationError,
    document_id_for,
    finalize_request_hash,
    validate_deposit_snapshot,
)
from .final_statements import FINAL_STATUSES
from .housing_confirmation import etag
from .housing_confirmation_validation import digest
from .payment_allocations import contract_ledger, non_rent_shares, planned_pairs, rent_amount
from .rent_history import charge_for

logger = logging.getLogger(__name__)

EDIT_AREAS = ("/deposits",)
FINALIZE_AREAS = ("/deposits", "/documents", "/bookings", "/receivables")
SETTLED_MESSAGE = ("Die Kaution ist abgerechnet; die Abrechnung bleibt unverändert. Weitere Schritte nur über die "
                   "Freigabe eines Einbehalts.")
OPEN_RECEIVABLE = frozenset({"open", "overdue", "partial"})
FORM_LABELS = {"cash": "Barkaution", "transfer": "Überweisung", "deposit_account": "Kautionskonto",
               "guarantee": "Bürgschaft", "pledged_savings": "Verpfändetes Sparbuch"}

_ORM = {
    "deposits": DepositORM, "deposit_instalments": DepositInstalmentORM,
    "deposit_interest_rates": DepositInterestRateORM, "deposit_payments": DepositPaymentORM,
    "deposit_settlements": DepositSettlementORM, "deposit_settlement_items": DepositSettlementItemORM,
    "bookings": BookingORM, "receivables": ReceivableORM, "payment_allocations": PaymentAllocationORM,
}


def now() -> datetime:
    """Naive UTC, as stored (a session time zone of PostgreSQL never shifts it)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid4())


def _num(value: Decimal) -> float:
    return as_number(value)


def _text(value: Decimal) -> str:
    return str(money(value))


def _not_found(what: str = "Kaution") -> HTTPException:
    return HTTPException(404, f"{what} nicht vorhanden.")


def _conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


# ─── Writing through one unit (SQL session or memory store) ──────────────────

def _put(unit: archive.Unit, collection: str, item: Any, *, insert_only: bool = False) -> None:
    """Insert or update a record of a store collection inside the unit."""
    if unit.db is None:
        # Match SQL's primary-key check even if an existing ID is outside the actor's scope.
        if insert_only and item.id in object.__getattribute__(unit.store, "__dict__")[collection]:
            raise _conflict("Die Positionskennung ist bereits vergeben. Bitte die Abrechnung neu laden.")
        unit.insert(getattr(unit.store, collection), item.id, item)
        return
    orm = _ORM[collection]
    columns = {column.key for column in orm.__table__.columns}
    values = {key: value for key, value in item.model_dump().items() if key in columns}
    if insert_only:
        unit.db.add(orm(**values))
        return
    row = unit.db.get(orm, item.id)
    if row is None:
        unit.db.add(orm(**values))
        return
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)


def _remove(unit: archive.Unit, collection: str, item_id: str) -> None:
    if unit.db is None:
        unit.remove(getattr(unit.store, collection), item_id)
        return
    row = unit.db.get(_ORM[collection], item_id)
    if row is not None:
        unit.db.delete(row)


def _flush(unit: archive.Unit) -> None:
    if unit.db is not None:
        unit.db.flush()


# ─── Reading ─────────────────────────────────────────────────────────────────

def _deposit(unit: archive.Unit, deposit_id: str) -> Deposit:
    try:
        return unit.store.get_deposit(deposit_id)
    except NotFoundError:
        raise _not_found() from None


def _parents(unit: archive.Unit, contract_id: str, *, lock: bool = False, deposit_id: str | None = None):
    """The contract and its subject; with `lock` (SQL) locked in the archive's order and read again."""
    store = unit.store
    try:
        contract = store.get_contract(contract_id)
    except NotFoundError:
        raise _not_found("Vertrag") from None
    if lock and unit.db is not None:
        before = (contract.property_id, contract.unit_id, contract.tenant_id)
        rows: list[tuple[Any, str]] = [(TenantORM, contract.tenant_id), (PropertyORM, contract.property_id),
                                       (UnitORM, contract.unit_id), (ContractORM, contract.id)]
        if deposit_id is not None:
            rows.append((DepositORM, deposit_id))
        for model, key in rows:
            if unit.db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                raise HTTPException(404, "Vertrag, Kaution oder Zuordnung nicht mehr vorhanden.")
        unit.db.expire_all()
        contract = store.get_contract(contract_id)
        if before != (contract.property_id, contract.unit_id, contract.tenant_id):
            raise _conflict("Die Vertragszuordnung wurde während der Prüfung geändert.")
    try:
        prop = store.get_property(contract.property_id)
        location = store.get_unit(contract.unit_id)
        tenant = store.get_tenant(contract.tenant_id)
        portfolio = store.get_portfolio(prop.portfolio_id)
    except NotFoundError:
        raise _not_found("Vertrag") from None
    if location.property_id != prop.id:
        raise HTTPException(503, "Einheit und Objekt des Vertrags passen nicht zusammen. Bestand prüfen.")
    return contract, prop, location, tenant, portfolio


def _postal(row) -> str:
    """A postal address in lines (street, postcode and town), or "" if it is incomplete."""
    line = (row.address_line or "").strip()
    city = " ".join(part.strip() for part in (row.postal_code, row.city) if part and part.strip())
    return f"{line}\n{city}" if line and city else ""


def _source(contract, prop, location, tenant, portfolio) -> dict[str, Any]:
    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name, "owner_name": portfolio.owner_name},
        "property": {"id": prop.id, "portfolio_id": prop.portfolio_id, "name": prop.name,
                     "address_line": prop.address_line, "postal_code": prop.postal_code, "city": prop.city},
        "unit": {"id": location.id, "property_id": location.property_id, "label": location.label},
        "contract": {"id": contract.id, "contract_number": contract.contract_number,
                     "property_id": contract.property_id, "unit_id": contract.unit_id,
                     "tenant_id": contract.tenant_id, "status": contract.status,
                     "start_date": contract.start_date.isoformat(),
                     "end_date": contract.end_date.isoformat() if contract.end_date else None,
                     "deposit_amount": contract.deposit_amount},
        "tenant": {"id": tenant.id, "full_name": tenant.full_name},
        "etags": {"portfolio": etag("portfolios", portfolio.id, portfolio.updated_at),
                  "property": etag("properties", prop.id, prop.updated_at),
                  "unit": etag("units", location.id, location.updated_at),
                  "contract": etag("contracts", contract.id, contract.updated_at),
                  "tenant": etag("tenants", tenant.id, tenant.updated_at)},
    }


def revision(item: Deposit | DepositSettlement) -> str:
    collection = "deposits" if isinstance(item, Deposit) else "deposit_settlements"
    return etag(collection, item.id, item.updated_at)


def _check_revision(item: Deposit | DepositSettlement, base_revision: str | None) -> None:
    if base_revision is not None and base_revision != revision(item):
        raise _conflict("Die Kautionsakte wurde inzwischen geändert. Bitte neu laden; die Eingaben bleiben erhalten.")


def _settlements(unit: archive.Unit, deposit_id: str) -> list[DepositSettlement]:
    return unit.store.list_deposit_settlements(deposit_id)


def _final(settlements: list[DepositSettlement], kind: str = "final") -> DepositSettlement | None:
    return next((s for s in settlements if s.kind == kind), None)


def _is_settled(settlements: list[DepositSettlement]) -> bool:
    return any(s.finalized_at is not None for s in settlements)


def _require_open(unit: archive.Unit, deposit: Deposit) -> None:
    if _is_settled(_settlements(unit, deposit.id)):
        raise _conflict(SETTLED_MESSAGE)


def _cold_rent_at_start(unit: archive.Unit, contract) -> Decimal | None:
    charge = charge_for(unit.store, contract, contract.start_date)
    return charge.cold_rent if charge is not None else None


def _advances_at(unit: archive.Unit, contract, day: date) -> Decimal:
    charge = charge_for(unit.store, contract, day)
    return money(charge.service_charge_advance + charge.heating_advance) if charge else ZERO


def _cap(unit: archive.Unit, contract, amount: Decimal) -> dict[str, Any]:
    check = rules.check_cap(amount, _cold_rent_at_start(unit, contract))
    return {"cold_rent": _num(check.cold_rent) if check.cold_rent is not None else None,
            "cap": _num(check.cap) if check.cap is not None else None,
            "exceeds": check.exceeds, "excess": _num(check.excess), "known": check.cap is not None}


def _receipts(unit: archive.Unit, deposit_id: str) -> list[tuple[DepositPayment, Booking | None]]:
    links = [link for link in unit.store.list_deposit_payments(deposit_id) if link.kind == "receipt"]
    result = []
    for link in links:
        try:
            booking = unit.store.get_booking(link.booking_id)
        except NotFoundError:
            booking = None        # not visible to this account (another portfolio's account)
        result.append((link, booking))
    return sorted(result, key=lambda pair: (pair[1].booking_date if pair[1] else date.min, pair[0].id))


def _carried(deposit: Deposit) -> tuple[date, Decimal, Decimal] | None:
    """The takeover of a deposit paid before the app's bookings: day, amount received, interest credited."""
    if deposit.carried_on is None or not deposit.carried_amount:
        return None
    return deposit.carried_on, money(deposit.carried_amount), money(deposit.carried_interest or 0)


def _received(deposit: Deposit, links: Iterable[DepositPayment]) -> Decimal:
    """The deposit received: the takeover plus the linked receipts (corrections negative)."""
    carried = _carried(deposit)
    return (carried[1] if carried else ZERO) + sum((money(link.amount) for link in links if link.kind == "receipt"),
                                                    ZERO)


def _events(deposit: Deposit, pairs: Iterable[tuple[DepositPayment, Booking | None]]) -> list[tuple[date, Decimal]]:
    """The balance changes that bear interest: the takeover (with the interest credited until then) and the
    visible receipts."""
    carried = _carried(deposit)
    events = [(carried[0], carried[1] + carried[2])] if carried else []
    return events + [(booking.booking_date, money(link.amount)) for link, booking in pairs if booking is not None]


def _rates(unit: archive.Unit, deposit_id: str) -> list[rules.RatePeriod]:
    return [rules.RatePeriod(rate.valid_from, rules.parse_rate(rate.rate_percent))
            for rate in unit.store.list_deposit_interest_rates(deposit_id)]


def _interest(unit: archive.Unit, deposit: Deposit, until: date,
              events: Iterable[tuple[date, Decimal]] | None = None) -> rules.InterestResult:
    if deposit.form not in rules.MONEY_FORMS:
        return rules.InterestResult(ZERO)
    if events is None:
        events = _events(deposit, _receipts(unit, deposit.id))
    return rules.interest(events, _rates(unit, deposit.id), until)


def _interest_json(result: rules.InterestResult) -> list[dict[str, Any]]:
    from datetime import timedelta

    return [{"year": y.year, "start": y.start.isoformat(), "end_inclusive": (y.end - timedelta(days=1)).isoformat(),
             "principal_start": _text(y.principal_start), "interest": _text(y.interest)} for y in result.years]


def _instalments(unit: archive.Unit, deposit_id: str) -> list[rules.Instalment]:
    return [rules.Instalment(row.number, row.due_date, money(row.amount))
            for row in unit.store.list_deposit_instalments(deposit_id)]


def _stage(deposit: Deposit, received: Decimal, settlements: list[DepositSettlement], retention: Decimal) -> str:
    """Where the file stands; `retention` is what a finalized final settlement kept back."""
    if deposit.form in rules.SECURITY_FORMS:
        if deposit.released_on:
            return "released"
        return "provided" if deposit.provided_on else "agreed"
    final, release = _final(settlements), _final(settlements, "retention_release")
    if release is not None and release.finalized_at is not None:
        return "closed"
    if final is not None and final.finalized_at is not None:
        return "retained" if retention > 0 and release is None else (
            "settlement_draft" if release is not None else "settled")
    if final is not None:
        return "settlement_draft"
    if deposit.status in ("returned", "partially_returned"):
        return "settled"        # returned with an earlier version's plain record, before the deposit file
    if received <= 0:
        return "agreed"
    return "received" if received >= money(deposit.amount) else "partially_received"


def _retention(items: Iterable[DepositSettlementItem]) -> Decimal:
    return sum((money(i.amount) for i in items if i.kind == "retention"), ZERO)


def _accounts(unit: archive.Unit, portfolio_id: str) -> list[dict[str, Any]]:
    return [{"id": a.id, "name": a.name, "account_type": a.account_type, "bank_name": a.bank_name, "iban": a.iban}
            for a in unit.store.list_accounts() if a.portfolio_id == portfolio_id]


def _account(unit: archive.Unit, account_id: str, prop) -> Any:
    try:
        account = unit.store.get_account(account_id)
    except NotFoundError:
        raise HTTPException(400, "Das gewählte Konto ist nicht vorhanden.") from None
    if account.portfolio_id != prop.portfolio_id:
        raise HTTPException(400, "Das Konto gehört zu einem anderen Portfolio als das Mietobjekt.")
    return account


# ─── Agreement ───────────────────────────────────────────────────────────────

def source(store, contract_id: str, actor_id: str) -> dict[str, Any]:
    """What a new agreement of the contract starts from: cold rent, cap, schedule, accounts, existing files."""
    with archive.work(store, actor_id) as unit:
        contract, prop, location, tenant, portfolio = _parents(unit, contract_id)
        cold = _cold_rent_at_start(unit, contract)
        suggested = money(contract.deposit_amount) if contract.deposit_amount else (
            money(cold) * rules.CAP_MONTHS if cold else ZERO)
        schedules = {}
        if suggested > 0:
            for count in range(1, rules.MAX_INSTALMENTS + 1):
                schedules[str(count)] = [{"number": i.number, "due_date": i.due_date.isoformat(),
                                          "amount": _num(i.amount)}
                                         for i in rules.schedule(suggested, contract.start_date, count=count,
                                                                 federal_state=getattr(prop, "federal_state", None))]
        return {
            "contract_id": contract.id,
            "source": _source(contract, prop, location, tenant, portfolio),
            "suggested_amount": _num(suggested) if suggested else None,
            "cap": _cap(unit, contract, suggested),
            "schedules": schedules,
            "accounts": _accounts(unit, prop.portfolio_id),
            "deposits": [_brief(unit, d) for d in unit.store.list_deposits() if d.contract_id == contract.id],
        }


def _checked_agreement(unit: archive.Unit, payload: AgreementRequest, contract, prop
                       ) -> tuple[Decimal, list[rules.Instalment]]:
    amount = money(payload.amount)
    check = rules.check_cap(amount, _cold_rent_at_start(unit, contract))
    if check.exceeds and not payload.cap_reason:
        raise HTTPException(400, f"Die Kaution übersteigt drei Nettokaltmieten ({check.cap} €). Bitte den Betrag "
                                 "senken oder ausdrücklich begründen (§ 551 Abs. 1 BGB).")
    if payload.form in rules.SECURITY_FORMS:
        if payload.instalment_amounts is not None or payload.instalment_count != 1:
            raise HTTPException(400, "Bürgschaft und verpfändetes Sparbuch werden nicht in Raten gezahlt.")
        if payload.account_id:
            raise HTTPException(400, "Für Bürgschaft und Sparbuch wird keine Zahlung gebucht; bitte kein Konto wählen.")
        return amount, []
    if payload.account_id:
        _account(unit, payload.account_id, prop)
    try:
        amounts = ([money(value) for value in payload.instalment_amounts]
                   if payload.instalment_amounts is not None else None)
        schedule = rules.schedule(amount, contract.start_date, amounts, count=payload.instalment_count,
                                  federal_state=getattr(prop, "federal_state", None))
    except rules.DepositRuleError as error:
        raise HTTPException(400, str(error)) from None
    return amount, schedule


def _agreement_fields(payload: AgreementRequest, amount: Decimal) -> dict[str, Any]:
    money_form = payload.form in rules.MONEY_FORMS
    return {"contract_id": payload.contract_id, "amount": float(amount), "form": payload.form,
            "cap_reason": payload.cap_reason, "account_id": payload.account_id if money_form else None,
            "institution": payload.institution, "account_reference": payload.account_reference,
            "account_holder": payload.account_holder, "held_date": payload.held_date, "notes": payload.notes}


def _write_instalments(unit: archive.Unit, deposit_id: str, schedule: list[rules.Instalment]) -> None:
    for row in unit.store.list_deposit_instalments(deposit_id):
        _remove(unit, "deposit_instalments", row.id)
    _flush(unit)
    stamp = now()
    for instalment in schedule:
        _put(unit, "deposit_instalments", DepositInstalment(
            id=new_id(), deposit_id=deposit_id, number=instalment.number, due_date=instalment.due_date,
            amount=float(instalment.amount), created_at=stamp, updated_at=stamp))
    _flush(unit)


def create(store, payload: AgreementRequest, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        contract, prop, *_ = _parents(unit, payload.contract_id, lock=True)
        amount, schedule = _checked_agreement(unit, payload, contract, prop)
        stamp = now()
        deposit = Deposit(id=new_id(), status="held", created_at=stamp, updated_at=stamp,
                          **_agreement_fields(payload, amount))
        _put(unit, "deposits", deposit)
        _flush(unit)
        _write_instalments(unit, deposit.id, schedule)
        return _detail(unit, deposit)


def update_agreement(store, deposit_id: str, payload: AgreementRequest, actor_id: str) -> dict[str, Any]:
    if payload.base_revision is None:
        raise HTTPException(422, "Bitte den Stand der Kautionsakte mitsenden (base_revision).")
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _check_revision(deposit, payload.base_revision)
        _require_open(unit, deposit)
        links = unit.store.list_deposit_payments(deposit.id)
        if payload.contract_id != deposit.contract_id and (links or _settlements(unit, deposit.id)):
            raise _conflict("Eine Kaution mit Zahlungen oder Abrechnung bleibt bei ihrem Vertrag.")
        if links and payload.form in rules.SECURITY_FORMS:
            raise _conflict("Für diese Kaution sind Zahlungen erfasst; Bürgschaft oder Sparbuch passen nicht dazu. "
                            "Bitte zuerst die Zahlungen lösen.")
        if deposit.carried_on is not None and payload.form in rules.SECURITY_FORMS:
            raise _conflict("Für diese Kaution ist ein übernommener Bestand erfasst; Bürgschaft oder Sparbuch passen "
                            "nicht dazu. Bitte zuerst die Übernahme entfernen.")
        if deposit.form in rules.SECURITY_FORMS and deposit.released_on:
            raise _conflict("Die Sicherheit ist freigegeben; die Vereinbarung bleibt unverändert.")
        contract, prop, *_ = _parents(unit, payload.contract_id, lock=payload.contract_id != deposit.contract_id)
        amount, schedule = _checked_agreement(unit, payload, contract, prop)
        updated = deposit.model_copy(update={**_agreement_fields(payload, amount), "updated_at": now()})
        _put(unit, "deposits", updated)
        _flush(unit)
        _write_instalments(unit, deposit.id, schedule)
        if payload.form in rules.SECURITY_FORMS:
            for rate in unit.store.list_deposit_interest_rates(deposit.id):
                _remove(unit, "deposit_interest_rates", rate.id)
        _flush(unit)
        return _detail(unit, updated)


def _touch(unit: archive.Unit, deposit: Deposit) -> Deposit:
    updated = deposit.model_copy(update={"updated_at": now()})
    _put(unit, "deposits", updated)
    _flush(unit)
    return updated


def delete(store, deposit_id: str, actor_id: str) -> None:
    """Delete an agreement without payments or settlements (with its instalments and rates)."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        if unit.store.list_deposit_payments(deposit.id) or _settlements(unit, deposit.id):
            raise _conflict("Die Kaution hat Zahlungen oder eine Abrechnung und bleibt deshalb erhalten.")
        for row in unit.store.list_deposit_instalments(deposit.id):
            _remove(unit, "deposit_instalments", row.id)
        for row in unit.store.list_deposit_interest_rates(deposit.id):
            _remove(unit, "deposit_interest_rates", row.id)
        _flush(unit)
        _remove(unit, "deposits", deposit.id)
        _flush(unit)


def ensure_plain_record_editable(store, deposit_id: str) -> None:
    """The older record endpoints (PUT/PATCH /deposits/{id}) do not touch a settled file."""
    if any(s.finalized_at is not None for s in store.list_deposit_settlements(deposit_id)):
        raise _conflict(SETTLED_MESSAGE)


# ─── Receipts (allocated bookings) ───────────────────────────────────────────

def _reallocate(unit: archive.Unit, booking: Booking) -> None:
    """Credit the booking to rent again without its deposit share (and its reversals likewise)."""
    for item in [booking, *unit.store.list_booking_reversals(booking.id)]:
        allocations = unit.store.list_payment_allocations(booking_id=item.id)
        available = rent_amount(item, non_rent_shares(unit.store, [item.id]))
        manual = [a for a in allocations if a.source == "manual"]
        if manual:
            allocated = sum((money(a.amount) for a in manual), ZERO)
            if abs(allocated) > abs(available) or (allocated and (allocated > 0) != (available > 0)):
                raise _conflict("Die Buchung ist von Hand Mietverträgen zugeordnet; zusammen mit der Kaution wäre "
                                "sie mehr als einmal gezählt. Bitte zuerst die Zuordnung zur Miete verringern.")
            continue
        for allocation in allocations:
            _remove(unit, "payment_allocations", allocation.id)
        _flush(unit)
        stamp = now()
        for contract_id, amount in planned_pairs(unit.store, item):
            _put(unit, "payment_allocations", PaymentAllocation(
                id=new_id(), booking_id=item.id, contract_id=contract_id, amount=float(amount), source="auto",
                created_at=stamp, updated_at=stamp))
        _flush(unit)


def _free_amount(unit: archive.Unit, booking: Booking, deposit: Deposit) -> Decimal:
    """What of the booking is neither a deposit share nor allocated to rent by hand."""
    manual = sum((money(a.amount) for a in unit.store.list_payment_allocations(booking_id=booking.id)
                  if a.source == "manual"), ZERO)
    free = rent_amount(booking, non_rent_shares(unit.store, [booking.id])) - manual
    if booking.reverses_booking_id and money(booking.amount) < 0:
        # A return can only undo this file's share of its own original. Other
        # receipts (or a carried balance) must never subsidise that correction.
        links = unit.store.list_deposit_payments(deposit.id)
        original = sum((money(link.amount) for link in links
                        if link.kind == "receipt" and link.booking_id == booking.reverses_booking_id), ZERO)
        other_returns = {row.id for row in unit.store.list_booking_reversals(booking.reverses_booking_id)
                         if row.id != booking.id}
        corrected = sum((money(link.amount) for link in links
                         if link.kind == "receipt" and link.booking_id in other_returns), ZERO)
        free = max(free, -max(original + corrected, ZERO))
    return free


def _unresolved_returns(unit: archive.Unit, deposit: Deposit) -> list[dict[str, Any]]:
    """Do not pay out deposit money that its cash source has already returned."""
    links = unit.store.list_deposit_payments(deposit.id)
    found = []
    for link, booking in _receipts(unit, deposit.id):
        if booking is None or money(link.amount) <= 0 or booking.reverses_booking_id:
            continue
        returns = unit.store.list_booking_reversals(booking.id)
        if not returns:
            continue
        ids = {row.id for row in returns}
        own = money(link.amount) + sum((money(row.amount) for row in links
                                        if row.kind == 'receipt' and row.booking_id in ids), ZERO)
        cash = money(booking.amount) + sum((money(row.amount) for row in returns), ZERO)
        reserved = sum(non_rent_shares(unit.store, [booking.id, *ids]).values(), ZERO)
        if own > ZERO and reserved > max(cash, ZERO):
            found.append({'code': 'unassigned_return', 'blocking': True, 'booking_id': returns[0].id,
                'message': 'Eine Rückbuchung dieser Kautionszahlung ist noch nicht vollständig zugeordnet. '
                           'Bitte den Kautionsanteil unter „Zahlung zuordnen“ korrigieren, bevor Sie abrechnen.'})
    return found


def payment_candidates(store, deposit_id: str, actor_id: str, *, skip: int = 0, limit: int = 200,
                       query: str = "") -> dict[str, Any]:
    if skip < 0 or not 1 <= limit <= 250:
        raise HTTPException(422, "Ungültiger Abschnitt der Zahlungszuordnung.")
    with archive.work(store, actor_id) as unit:
        deposit = _deposit(unit, deposit_id)
        contract, prop, *_ = _parents(unit, deposit.contract_id)
        accounts = {a.id for a in unit.store.list_accounts() if a.portfolio_id == prop.portfolio_id}
        receipts = {link.booking_id: link for link, _ in _receipts(unit, deposit.id)}
        linked = {link.booking_id for link in unit.store.list_deposit_payments(deposit.id)}
        carried = _carried(deposit)
        found = []
        if deposit.form in rules.MONEY_FORMS:
            for booking in unit.store.list_bookings(tenant_id=contract.tenant_id):
                if (booking.id in linked or booking.account_id not in accounts
                        or (deposit.account_id and booking.account_id != deposit.account_id)):
                    continue
                if carried and booking.booking_date < carried[0]:
                    continue
                if money(booking.amount) < 0 and booking.reverses_booking_id not in receipts:
                    continue
                free = _free_amount(unit, booking, deposit)
                if not free or (free > 0) != (money(booking.amount) > 0):
                    continue
                found.append({"booking_id": booking.id, "booking_date": booking.booking_date.isoformat(),
                              "amount": _num(money(booking.amount)), "free": _num(free),
                              "account_id": booking.account_id, "payment_text": booking.payment_text,
                              "reverses_booking_id": booking.reverses_booking_id})
        found.sort(key=lambda row: (row["booking_date"], row["booking_id"]), reverse=True)
        if query.strip():
            needle = query.strip().casefold()
            found = [row for row in found if any(needle in str(row.get(key) or "").casefold()
                     for key in ("payment_text", "booking_date", "amount"))]
        return {"deposit_id": deposit.id, "items": found[skip:skip + limit], "total": len(found),
                "skip": skip, "limit": limit, "more": skip + limit < len(found)}


def add_receipt(store, deposit_id: str, payload: ReceiptRequest, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        contract, prop, *_ = _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _require_open(unit, deposit)
        if deposit.form not in rules.MONEY_FORMS:
            raise _conflict("Bürgschaft und verpfändetes Sparbuch werden nicht gebucht; bitte Nachweis und Datum "
                            "erfassen.")
        try:
            booking = unit.store.get_booking(payload.booking_id)
        except NotFoundError:
            raise _not_found("Buchung") from None
        if booking.tenant_id != contract.tenant_id:
            raise HTTPException(400, "Als Kautionszahlung zählen nur Buchungen des Mieters dieses Vertrags.")
        _account(unit, booking.account_id, prop)
        if deposit.account_id and booking.account_id != deposit.account_id:
            raise HTTPException(400, "Die Buchung liegt nicht auf dem Konto, auf dem die Kaution geführt wird.")
        if any(link.booking_id == booking.id for link in unit.store.list_deposit_payments(deposit.id)):
            raise _conflict("Diese Buchung ist der Kaution bereits zugeordnet.")
        carried = _carried(deposit)
        if carried and booking.booking_date < carried[0]:
            raise HTTPException(400, f"Die Buchung vom {booking.booking_date:%d.%m.%Y} liegt vor dem Übernahmetag "
                                     f"{carried[0]:%d.%m.%Y}; sie ist im übernommenen Bestand enthalten.")
        receipts = {link.booking_id: link for link, _ in _receipts(unit, deposit.id)}
        if money(booking.amount) < 0 and booking.reverses_booking_id not in receipts:
            raise HTTPException(400, "Eine Rückbuchung zählt nur als Korrektur einer zugeordneten Kautionszahlung.")
        free = _free_amount(unit, booking, deposit)
        amount = money(payload.amount) if payload.amount is not None else free
        if (not amount or (amount > 0) != (money(booking.amount) > 0) or abs(amount) > abs(free)
                or (free and (free > 0) != (amount > 0))):
            raise HTTPException(400, f"Von dieser Buchung sind noch {free} € frei (nicht der Miete von Hand oder "
                                     "einer Kaution zugeordnet); jeder Betrag zählt nur einmal.")
        received = sum((money(link.amount) for link in receipts.values()), ZERO)
        if received + amount < 0:
            raise HTTPException(400, "Die Korrektur ist höher als die erfassten Eingänge.")
        stamp = now()
        _put(unit, "deposit_payments", DepositPayment(
            id=new_id(), deposit_id=deposit.id, booking_id=booking.id, kind="receipt", amount=float(amount),
            notes=payload.notes, created_at=stamp, updated_at=stamp))
        _flush(unit)
        _reallocate(unit, booking)
        return _detail(unit, _touch(unit, deposit))


def remove_receipt(store, deposit_id: str, payment_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _require_open(unit, deposit)
        links = unit.store.list_deposit_payments(deposit.id)
        link = next((row for row in links if row.id == payment_id and row.kind == "receipt"), None)
        if link is None:
            raise _not_found("Zahlungszuordnung")
        try:
            booking = unit.store.get_booking(link.booking_id)
        except NotFoundError:
            raise _not_found("Buchung") from None
        reversals = {b.id for b in unit.store.list_booking_reversals(booking.id)}
        if any(row.booking_id in reversals for row in links):
            raise _conflict("Zu dieser Zahlung ist eine Rückbuchung zugeordnet; bitte zuerst diese lösen.")
        _remove(unit, "deposit_payments", link.id)
        _flush(unit)
        _reallocate(unit, booking)
        return _detail(unit, _touch(unit, deposit))


# ─── Interest rates ──────────────────────────────────────────────────────────

def set_rates(store, deposit_id: str, payload: RatesRequest, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _check_revision(deposit, payload.base_revision)
        _require_open(unit, deposit)
        if deposit.form not in rules.MONEY_FORMS and payload.rates:
            raise HTTPException(400, "Zinsen gelten für Barkautionen; Bürgschaft und Sparbuch verzinst die Bank selbst.")
        if len({rate.valid_from for rate in payload.rates}) != len(payload.rates):
            raise HTTPException(400, "Je Tag gibt es nur einen Zinssatz.")
        parsed = []
        for rate in payload.rates:
            try:
                parsed.append((rate, rules.parse_rate(rate.rate_percent)))
            except rules.DepositRuleError as error:
                raise HTTPException(400, str(error)) from None
        for row in unit.store.list_deposit_interest_rates(deposit.id):
            _remove(unit, "deposit_interest_rates", row.id)
        _flush(unit)
        stamp = now()
        for rate, percent in sorted(parsed, key=lambda pair: pair[0].valid_from):
            _put(unit, "deposit_interest_rates", DepositInterestRate(
                id=new_id(), deposit_id=deposit.id, valid_from=rate.valid_from, rate_percent=str(percent),
                note=rate.note, created_at=stamp, updated_at=stamp))
        _flush(unit)
        return _detail(unit, _touch(unit, deposit))


# ─── Takeover (deposit paid before this app's bookings) ─────────────────────

TAKEOVER_FIELDS = ("carried_on", "carried_amount", "carried_interest", "carried_note")


def _cents(value: float | None, label: str) -> Decimal | None:
    if value is None:
        return None
    amount = money(value)
    if amount != Decimal(str(value)):
        raise HTTPException(400, f"{label} hat höchstens zwei Nachkommastellen.")
    return amount


def _takeover_changes(unit: archive.Unit, deposit: Deposit, payload: TakeoverRequest) -> dict[str, Any]:
    amount = _cents(payload.carried_amount, "Der übernommene Betrag")
    interest = _cents(payload.carried_interest, "Die übernommenen Zinsen")
    if amount is None and payload.carried_on is None:
        if interest or payload.carried_note:
            raise HTTPException(400, "Zinsen und Vermerk gehören zu einem übernommenen Betrag mit Übernahmetag.")
        return dict.fromkeys(TAKEOVER_FIELDS)
    if deposit.form not in rules.MONEY_FORMS:
        raise _conflict("Bürgschaft und verpfändetes Sparbuch werden mit Datum und Nachweis erfasst, nicht übernommen.")
    if amount is None or payload.carried_on is None:
        raise HTTPException(400, "Für die Übernahme bitte den Übernahmetag und den bis dahin eingegangenen Betrag "
                                 "angeben.")
    if payload.carried_on > local_today():
        raise HTTPException(400, "Der Übernahmetag liegt in der Zukunft.")
    earlier = [booking for link, booking in _receipts(unit, deposit.id)
               if booking is not None and booking.booking_date < payload.carried_on]
    if earlier:
        raise _conflict(f"{len(earlier)} zugeordnete Zahlung(en) liegen vor dem Übernahmetag und wären doppelt "
                        "gezählt. Bitte sie zuerst lösen oder einen früheren Übernahmetag wählen.")
    return {"carried_on": payload.carried_on, "carried_amount": float(amount),
            "carried_interest": float(interest) if interest else None, "carried_note": payload.carried_note}


def set_takeover(store, deposit_id: str, payload: TakeoverRequest, actor_id: str) -> dict[str, Any]:
    """Record (or remove) what was received and credited before the app's bookings begin."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _check_revision(deposit, payload.base_revision)
        _require_open(unit, deposit)
        if deposit.status in ("returned", "partially_returned"):
            raise _conflict("Die Kaution wurde bereits zurückgezahlt; sie darf nicht erneut als Eingang übernommen werden.")
        updated = deposit.model_copy(update={**_takeover_changes(unit, deposit, payload), "updated_at": now()})
        _put(unit, "deposits", updated)
        _flush(unit)
        return _detail(unit, updated)


def _legacy_candidate(unit: archive.Unit, deposit: Deposit, used: set[str] | None = None) -> bool:
    """A plain record of an earlier version: held since its receipt date, nothing of the file recorded yet.

    `used` names the deposits with payments, settlements or instalments (read once for a list)."""
    if not (deposit.form in rules.MONEY_FORMS and deposit.status == "held" and deposit.held_date is not None
            and deposit.held_date <= local_today() and money(deposit.amount) > 0 and deposit.carried_on is None):
        return False
    if used is not None:
        return deposit.id not in used
    return not (unit.store.list_deposit_payments(deposit.id) or _settlements(unit, deposit.id)
                or unit.store.list_deposit_instalments(deposit.id))


def legacy_candidates(store, actor_id: str) -> dict[str, Any]:
    """The earlier plain records the takeover in one step would take over as received."""
    with archive.work(store, actor_id) as unit:
        contracts = {c.id: c for c in unit.store.list_contracts()}
        tenants = {t.id: t for t in unit.store.list_tenants()}
        used = ({row.deposit_id for row in unit.store.list_deposit_payments()}
                | {row.deposit_id for row in unit.store.list_deposit_settlements()}
                | {row.deposit_id for row in unit.store.list_deposit_instalments()})
        items = []
        for deposit in unit.store.list_deposits():
            contract = contracts.get(deposit.contract_id)
            if contract is None or not _legacy_candidate(unit, deposit, used):
                continue
            tenant = tenants.get(contract.tenant_id)
            items.append({"id": deposit.id, "contract_id": contract.id, "contract_number": contract.contract_number,
                          "tenant_name": tenant.full_name if tenant else None,
                          "amount": _num(money(deposit.amount)), "held_date": deposit.held_date.isoformat()})
        items.sort(key=lambda row: ((row["tenant_name"] or "").casefold(), row["contract_number"] or "", row["id"]))
        return {"items": items, "count": len(items),
                "amount": _num(sum((Decimal(str(row["amount"])) for row in items), ZERO))}


def take_over_legacy(store, payload: LegacyTakeoverRequest, actor_id: str) -> dict[str, Any]:
    """Take over the named plain records as received on their receipt date, all or none."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        stamp = now()
        refused = []
        for deposit_id in sorted(payload.deposit_ids):         # one lock order for parallel requests
            deposit = _deposit(unit, deposit_id)
            _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
            deposit = _deposit(unit, deposit_id)
            if not _legacy_candidate(unit, deposit):
                refused.append(deposit_id)
                continue
            assert deposit.held_date is not None
            _put(unit, "deposits", deposit.model_copy(update={
                "carried_on": deposit.held_date, "carried_amount": float(money(deposit.amount)),
                "carried_interest": None,
                "carried_note": f"Aus dem bisherigen Kautionsdatensatz übernommen (Eingang {deposit.held_date:%d.%m.%Y}).",
                "updated_at": stamp}))
            _flush(unit)       # before the next lock: reading again (expire_all) would drop unflushed changes
        if refused:
            raise _conflict(f"{len(refused)} der Kautionen sind inzwischen keine Altbestände mehr (Zahlungen, "
                            "Raten oder Abrechnung erfasst). Bitte die Liste neu laden; nichts wurde übernommen.")
        return {"taken_over": len(payload.deposit_ids)}


# ─── Guarantee and pledged savings book ──────────────────────────────────────

def _proof(unit: archive.Unit, document_id: str | None, contract) -> str | None:
    if document_id is None:
        return None
    try:
        document = unit.store.get_document(document_id)
    except NotFoundError:
        raise HTTPException(400, "Der Nachweis ist nicht als Dokument vorhanden.") from None
    if document.contract_id != contract.id and getattr(document, "tenant_id", None) != contract.tenant_id:
        raise HTTPException(400, "Der Nachweis gehört nicht zu diesem Vertrag oder Mieter.")
    return document.id


def set_security(store, deposit_id: str, payload: SecurityRequest, actor_id: str) -> dict[str, Any]:
    """A guarantee or pledged savings book: provided (date, proof) and released (date and proof)."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        contract, *_ = _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        _check_revision(deposit, payload.base_revision)
        if deposit.form not in rules.SECURITY_FORMS:
            raise _conflict("Eine Barkaution wird über Buchungen und die Kautionsabrechnung erledigt.")
        if deposit.released_on is not None:
            raise _conflict("Die Sicherheit ist bereits freigegeben; die Freigabe bleibt unverändert.")
        if payload.released_on is not None:
            if payload.provided_on is None:
                raise HTTPException(400, "Freigegeben werden kann nur eine erhaltene Sicherheit.")
            if payload.released_on < payload.provided_on:
                raise HTTPException(400, "Die Freigabe liegt vor dem Erhalt der Sicherheit.")
            if not payload.release_document_id and not payload.release_note:
                raise HTTPException(400, "Für die Freigabe bitte einen Nachweis (Dokument oder Vermerk) angeben.")
        changes: dict[str, Any] = {
            "provided_on": payload.provided_on, "held_date": payload.provided_on,
            "proof_document_id": _proof(unit, payload.proof_document_id, contract),
            "released_on": payload.released_on,
            "release_document_id": _proof(unit, payload.release_document_id, contract),
            "release_note": payload.release_note, "updated_at": now()}
        if payload.released_on is not None:
            changes.update({"status": "returned", "return_date": payload.released_on})
        updated = deposit.model_copy(update=changes)
        _put(unit, "deposits", updated)
        _flush(unit)
        return _detail(unit, updated)


# ─── Settlement: sources ─────────────────────────────────────────────────────

def _move_out_protocol(unit: archive.Unit, contract_id: str):
    """The finalized move-out protocol in force (a corrected one never)."""
    protocols = [p for p in unit.store.list_handover_protocols() if p.contract_id == contract_id]
    superseded = {p.correction_of_id for p in protocols if p.correction_of_id and p.finalized_at is not None}
    current = [p for p in protocols if p.protocol_type == "move_out" and p.finalized_at is not None
               and p.id not in superseded]
    return max(current, key=lambda p: (p.protocol_date, p.id), default=None)


def _tenant_defects(unit: archive.Unit, protocol_id: str | None) -> list[Any]:
    if protocol_id is None:
        return []
    from .handover_protocol import parts_of

    parts = parts_of(unit.store, {protocol_id})
    rooms = {room.id: room.name for room in parts["handover_rooms"]}
    return [(defect, rooms.get(defect.room_id or "")) for defect in parts["handover_defects"]
            if defect.responsible == "tenant"]


def _rent_outstanding(unit: archive.Unit, contract, day: date) -> Decimal:
    receivables, payments = contract_ledger(unit.store, contract, day)
    balance = LeaseEngine.calculate_balance(receivables, payments)
    return money(balance.outstanding_total)


def _offset_before(unit: archive.Unit, receivable_id: str, settlement_id: str) -> Decimal:
    """What finalized settlements already offset against the receivable."""
    total = ZERO
    for other in unit.store.list_deposit_settlements():
        if other.id == settlement_id or other.finalized_at is None:
            continue
        total += sum((money(i.amount) for i in unit.store.list_deposit_settlement_items(other.id)
                      if i.receivable_id == receivable_id and i.kind == "receivable"), ZERO)
    return total


def _open_receivables(unit: archive.Unit, contract_id: str, settlement_id: str) -> list[tuple[Receivable, Decimal]]:
    found = []
    for receivable in unit.store.list_receivables():
        if receivable.contract_id != contract_id or receivable.status not in OPEN_RECEIVABLE:
            continue
        from .receivable_residuals import residual
        state = residual(unit.store, receivable, date.max)
        if state["unresolved_legacy"]:
            continue
        open_amount = money(state["residual"])
        if open_amount > 0:
            found.append((receivable, open_amount))
    return sorted(found, key=lambda pair: (pair[0].due_date, pair[0].id))


def _utility_period_open(unit: archive.Unit, contract, day: date) -> bool:
    """Whether no issued utility statement period of the property covers the tenancy's last day."""
    last = min(contract.end_date or day, day)
    return not any(p.property_id == contract.property_id and p.status in FINAL_STATUSES
                   and p.start_date <= last <= p.end_date for p in unit.store.list_billing_periods())


def _settlement(unit: archive.Unit, deposit: Deposit, settlement_id: str) -> DepositSettlement:
    found = next((s for s in _settlements(unit, deposit.id) if s.id == settlement_id), None)
    if found is None:
        raise _not_found("Kautionsabrechnung")
    return found


def _require_draft(settlement: DepositSettlement) -> None:
    if settlement.finalized_at is not None:
        raise _conflict("Die Abrechnung ist abgeschlossen und bleibt unverändert.")


def create_settlement(store, deposit_id: str, payload: SettlementCreate, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        contract, *_ = _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        if deposit.form not in rules.MONEY_FORMS:
            raise _conflict("Bürgschaft und verpfändetes Sparbuch werden mit Datum und Nachweis freigegeben, "
                            "nicht abgerechnet.")
        settlements = _settlements(unit, deposit.id)
        existing = _final(settlements, payload.kind)
        if existing is not None:
            return {"created": False, **_detail(unit, deposit)}
        protocol_id = None
        if payload.kind == "final":
            day = payload.settlement_date or contract.end_date or local_today()
            protocol = _move_out_protocol(unit, contract.id)
            protocol_id = protocol.id if protocol is not None else None
        else:
            final = _final(settlements)
            if final is None or final.finalized_at is None:
                raise _conflict("Ein Einbehalt wird erst nach der abgeschlossenen Kautionsabrechnung freigegeben.")
            if _retention(unit.store.list_deposit_settlement_items(final.id)) <= 0:
                raise _conflict("Die Kautionsabrechnung hat nichts einbehalten.")
            day = payload.settlement_date or max(local_today(), final.settlement_date)
        stamp = now()
        settlement = DepositSettlement(id=new_id(), deposit_id=deposit.id, kind=payload.kind, settlement_date=day,
                                       handover_protocol_id=protocol_id, status="draft", created_at=stamp,
                                       updated_at=stamp)
        _put(unit, "deposit_settlements", settlement)
        _flush(unit)
        return {"created": True, **_detail(unit, _touch(unit, deposit))}


def save_settlement(store, deposit_id: str, settlement_id: str, payload: SettlementContent,
                    actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        settlement = _settlement(unit, deposit, settlement_id)
        _check_revision(settlement, payload.base_revision)
        _require_draft(settlement)
        item_ids = [item.id for item in payload.items if item.id is not None]
        if len(item_ids) != len(set(item_ids)):
            raise HTTPException(400, "Jede Position braucht eine eigene Kennung.")
        if settlement.kind == "retention_release" and any(item.kind == "retention" for item in payload.items):
            raise HTTPException(400, "Die Freigabe eines Einbehalts behält nichts weiter ein.")
        if sum(1 for item in payload.items if item.kind in ("retention", "rent_arrears")) > len(
                {item.kind for item in payload.items if item.kind in ("retention", "rent_arrears")}):
            raise HTTPException(400, "Einbehalt und Mietrückstand stehen je höchstens einmal in einer Abrechnung.")
        receivables = [item.receivable_id for item in payload.items if item.receivable_id]
        if len(receivables) != len(set(receivables)):
            raise HTTPException(400, "Jede Forderung wird nur einmal verrechnet.")
        for item in payload.items:
            if (item.kind == "receivable") != (item.receivable_id is not None):
                raise HTTPException(400, "Eine Verrechnung nennt genau die offene Forderung, die sie begleicht.")
            if item.handover_defect_id is not None and item.kind != "defect":
                raise HTTPException(400, "Nur ein Mangel verweist auf das Übergabeprotokoll.")
        for row in unit.store.list_deposit_settlement_items(settlement.id):
            _remove(unit, "deposit_settlement_items", row.id)
        _flush(unit)
        stamp = now()
        for position, item in enumerate(payload.items):
            # Our previous items were deleted above; an occupied ID belongs to another file.
            _put(unit, "deposit_settlement_items", DepositSettlementItem(
                id=item.id or new_id(), settlement_id=settlement.id, position=position, kind=item.kind,
                description=item.description, amount=float(money(item.amount)), reason=item.reason,
                handover_defect_id=item.handover_defect_id, receivable_id=item.receivable_id,
                created_at=stamp, updated_at=stamp), insert_only=True)
        _flush(unit)
        updated = settlement.model_copy(update={
            "settlement_date": payload.settlement_date,
            "interest_amount": float(money(payload.interest_amount)) if payload.interest_amount is not None else None,
            "interest_reason": payload.interest_reason, "notes": payload.notes, "updated_at": now()})
        _put(unit, "deposit_settlements", updated)
        _flush(unit)
        return _detail(unit, deposit)


def delete_settlement(store, deposit_id: str, settlement_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        settlement = _settlement(unit, deposit, settlement_id)
        _require_draft(settlement)
        for row in unit.store.list_deposit_settlement_items(settlement.id):
            _remove(unit, "deposit_settlement_items", row.id)
        _flush(unit)
        _remove(unit, "deposit_settlements", settlement.id)
        _flush(unit)
        return _detail(unit, _touch(unit, deposit))


# ─── Settlement: evaluation and review ───────────────────────────────────────

def _problem(code: str, message: str, *, blocking: bool = True) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": blocking}


def _evaluate(unit: archive.Unit, deposit: Deposit, settlement: DepositSettlement, contract) -> dict[str, Any]:
    """Figures, problems and the facts of the review of a settlement draft (or what it was at finalization)."""
    items = unit.store.list_deposit_settlement_items(settlement.id)
    day = settlement.settlement_date
    problems: list[dict[str, Any]] = []
    previous = None
    receipts: list[dict[str, Any]] = []
    carried_interest: Decimal | None = None      # credited before the takeover (final settlement only)
    if settlement.kind == "final":
        problems.extend(_unresolved_returns(unit, deposit))
        pairs = _receipts(unit, deposit.id)
        if any(booking is None for _, booking in pairs):
            problems.append(_problem("hidden_receipt", "Nicht alle Kautionszahlungen sind für dieses Konto sichtbar."))
        visible = [(link, booking) for link, booking in pairs if booking is not None]
        principal = _received(deposit, [link for link, _ in pairs])
        carried = _carried(deposit)
        if carried:
            carried_interest = carried[2]
            receipts.append({"booking_id": None, "booking_date": carried[0].isoformat(), "amount": _text(carried[1]),
                             "label": "Übernommener Bestand (vor Beginn der Buchungen in der App)"})
        receipts += [{"booking_id": booking.id, "booking_date": booking.booking_date.isoformat(),
                      "amount": _text(money(link.amount)),
                      "label": booking.payment_text or ("Korrektur" if money(link.amount) < 0 else "Zahlungseingang")}
                     for link, booking in visible]
        events = _events(deposit, visible)
        if principal <= 0:
            problems.append(_problem("no_receipt", "Es ist kein Eingang der Kaution erfasst; eine Abrechnung ohne "
                                                   "Kaution ist nicht nötig."))
        if any(booking.booking_date > day for _, booking in visible) or (carried and carried[0] > day):
            problems.append(_problem("receipt_after_date", "Ein Eingang liegt nach dem Abrechnungstag; bitte den "
                                     "Abrechnungstag berichtigen, bevor die Kaution ausgezahlt wird."))
        if principal < money(deposit.amount):
            problems.append(_problem("not_fully_received", f"Eingegangen sind {_text(principal)} € von "
                                                           f"{_text(money(deposit.amount))} € vereinbart.",
                                     blocking=False))
        if day < contract.start_date:
            problems.append(_problem("date_before_start", "Der Abrechnungstag liegt vor dem Mietbeginn."))
        if contract.end_date is None or contract.end_date > day:
            problems.append(_problem("tenancy_running", "Das Mietverhältnis ist zum Abrechnungstag nicht beendet.",
                                     blocking=False))
    else:
        final = _final(_settlements(unit, deposit.id))
        if final is None or final.finalized_at is None:
            raise _conflict("Ein Einbehalt wird erst nach der abgeschlossenen Kautionsabrechnung freigegeben.")
        principal = _retention(unit.store.list_deposit_settlement_items(final.id))
        events = [(final.settlement_date, principal)]
        receipts = [{"booking_id": None, "booking_date": final.settlement_date.isoformat(), "amount": _text(principal),
                     "label": "Einbehalt aus der Kautionsabrechnung"}]
        row = archive.head(unit, final.document_id) if final.document_id else None
        previous = {"settlement_id": final.id, "document_id": final.document_id or "",
                    "version_id": row.id if row is not None else "", "pdf_sha256": row.sha256 if row is not None else "",
                    "settlement_date": final.settlement_date.isoformat(), "retention": _text(principal)}
        if day < final.settlement_date:
            problems.append(_problem("date_before_final", "Die Freigabe liegt vor der Kautionsabrechnung."))
    computed = (rules.interest(events, _rates(unit, deposit.id), day) if deposit.form in rules.MONEY_FORMS
                else rules.InterestResult(ZERO))
    computed_total = computed.total + (carried_interest or ZERO)
    interest_amount = computed_total
    if settlement.interest_amount is not None:
        interest_amount = money(settlement.interest_amount)
        if interest_amount != computed_total and not settlement.interest_reason:
            problems.append(_problem("interest_reason", "Abweichende Zinsen brauchen eine Begründung (z. B. "
                                                        "Gutschrift laut Kontoauszug)."))

    protocol_defects = {defect.id: (defect, room) for defect, room in
                        _tenant_defects(unit, settlement.handover_protocol_id)}
    open_receivables = {r.id: (r, amount) for r, amount in _open_receivables(unit, contract.id, settlement.id)}
    for item in items:
        if item.kind == "defect" and item.handover_defect_id and item.handover_defect_id not in protocol_defects:
            problems.append(_problem("defect_unknown", f"„{item.description}“ ist kein Mangel des Auszugsprotokolls, "
                                                       "für den der Mieter verantwortlich ist."))
        if item.kind == "other" and not item.reason:
            problems.append(_problem("claim_reason", f"Für „{item.description}“ fehlt die Begründung."))
        if item.kind == "receivable":
            found = open_receivables.get(item.receivable_id or "")
            if found is None:
                problems.append(_problem("receivable_not_open", f"„{item.description}“: die Forderung ist nicht mehr "
                                                                "offen oder gehört nicht zu diesem Vertrag."))
            elif money(item.amount) > found[1]:
                problems.append(_problem("receivable_exceeded", f"„{item.description}“: offen sind nur "
                                                                f"{_text(found[1])} €."))
        if item.kind == "rent_arrears":
            outstanding = _rent_outstanding(unit, contract, day)
            if money(item.amount) > outstanding:
                problems.append(_problem("arrears_exceeded", f"Der Mietrückstand zum {day:%d.%m.%Y} beträgt "
                                                             f"{_text(outstanding)} €."))
        if item.kind == "retention":
            if not item.reason:
                problems.append(_problem("retention_reason", "Der Einbehalt braucht eine Begründung."))
            if not _utility_period_open(unit, contract, day):
                problems.append(_problem("retention_not_open", "Für das Ende des Mietverhältnisses ist die "
                                                               "Nebenkostenabrechnung bereits erteilt; ein Einbehalt "
                                                               "ist nicht begründet."))
    included = {item.handover_defect_id for item in items if item.handover_defect_id}
    for defect_id, (defect, room) in protocol_defects.items():
        if defect_id not in included:
            problems.append(_problem("defect_open", f"Mangel „{defect.description}“ ist dem Mieter zugeordnet, aber "
                                                    "nicht abgerechnet.", blocking=False))
    if settlement.kind == "final" and settlement.handover_protocol_id is None:
        problems.append(_problem("no_protocol", "Kein abgeschlossenes Auszugsprotokoll: Mängel bitte von Hand "
                                                "begründen.", blocking=False))
    outcome = None
    try:
        outcome = rules.settle(principal, interest_amount, [rules.Item(i.kind, money(i.amount)) for i in items],
                               allow_retention=settlement.kind == "final")
    except rules.DepositRuleError as error:
        problems.append(_problem("arithmetic", str(error)))
    arrears = sum((money(i.amount) for i in items if i.kind == "rent_arrears"), ZERO)
    if outcome is not None and (outcome.payout > 0 or arrears > 0) and not deposit.account_id:
        problems.append(_problem("account_needed", "Für Auszahlung und Verrechnung beim Abschluss ein Konto wählen.",
                                 blocking=False))
    return {"items": items, "principal": principal, "computed": computed, "computed_total": computed_total,
            "carried_interest": carried_interest, "interest": interest_amount,
            "outcome": outcome, "problems": problems, "receipts": receipts, "previous": previous, "arrears": arrears}


def _outcome_json(outcome: rules.Outcome | None) -> dict[str, str] | None:
    if outcome is None:
        return None
    return {name: _text(getattr(outcome, name)) for name in (
        "principal", "interest", "credit", "new_claims", "offsets", "retention", "claims", "result", "payout",
        "remaining_claim", "covered")}


def _review(unit: archive.Unit, deposit: Deposit, settlement: DepositSettlement):
    contract, prop, location, tenant, portfolio = _parents(unit, deposit.contract_id)
    evaluation = _evaluate(unit, deposit, settlement, contract)
    computed = evaluation["computed"]
    source = _source(contract, prop, location, tenant, portfolio)
    source["letter"] = {"letterhead": letterheads.source(unit, prop.id, fallback_sender=portfolio.owner_name or portfolio.name),
                        "recipient_name": tenant.full_name,
                        "recipient_address": _postal(tenant) or _postal(prop)}
    review = {
        "format_version": LETTERHEAD_FORMAT_VERSION,
        "deposit": {"id": deposit.id, "contract_id": deposit.contract_id, "amount": _text(money(deposit.amount)),
                    "form": deposit.form, "institution": deposit.institution,
                    "account_reference": deposit.account_reference, "account_holder": deposit.account_holder,
                    "cap_reason": deposit.cap_reason,
                    "instalments": [{"number": i.number, "due_date": i.due_date.isoformat(), "amount": _text(i.amount)}
                                    for i in _instalments(unit, deposit.id)]},
        "settlement": {"id": settlement.id, "deposit_id": deposit.id, "kind": settlement.kind,
                       "settlement_date": settlement.settlement_date.isoformat(),
                       "handover_protocol_id": settlement.handover_protocol_id, "notes": settlement.notes},
        "items": [{"id": i.id, "position": i.position, "kind": i.kind, "description": i.description,
                   "amount": _text(money(i.amount)), "reason": i.reason, "handover_defect_id": i.handover_defect_id,
                   "receivable_id": i.receivable_id} for i in evaluation["items"]],
        "receipts": evaluation["receipts"],
        "interest": {"computed": _text(evaluation["computed_total"]),
                     "override": _text(money(settlement.interest_amount))
                     if settlement.interest_amount is not None else None,
                     "reason": settlement.interest_reason,
                     "rates": [{"valid_from": r.valid_from.isoformat(), "rate_percent": str(r.percent)}
                               for r in _rates(unit, deposit.id)],
                     "years": _interest_json(computed)},
        "outcome": _outcome_json(evaluation["outcome"]),
        "previous": evaluation["previous"],
        "source": source,
    }
    if evaluation["carried_interest"] is not None:     # only with a takeover: other reviews keep their shape
        review["interest"]["carried"] = _text(evaluation["carried_interest"])
    pdf = render_pdf(review, letterheads.logo_bytes(unit, prop.id)) if review["outcome"] is not None else b""
    review["pdf_sha256"] = hashlib.sha256(pdf).hexdigest()
    return review, digest(review), pdf, evaluation, (contract, prop, location, tenant, portfolio)


def preview(store, deposit_id: str, settlement_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        deposit = _deposit(unit, deposit_id)
        settlement = _settlement(unit, deposit, settlement_id)
        _require_draft(settlement)
        review, review_hash, pdf, evaluation, _ = _review(unit, deposit, settlement)
        problems = evaluation["problems"]
        return {"review_hash": review_hash, "pdf_sha256": review["pdf_sha256"], "size_bytes": len(pdf),
                "revision": revision(settlement), "problems": problems, "outcome": review["outcome"],
                "ready": review["outcome"] is not None and not any(p["blocking"] for p in problems)}


def preview_pdf(store, deposit_id: str, settlement_id: str, actor_id: str) -> tuple[bytes, str, str]:
    with archive.work(store, actor_id) as unit:
        deposit = _deposit(unit, deposit_id)
        settlement = _settlement(unit, deposit, settlement_id)
        _require_draft(settlement)
        review, review_hash, pdf, _, _ = _review(unit, deposit, settlement)
        if not pdf:
            raise _conflict("Die Abrechnung geht so nicht auf; bitte die Hinweise der Prüfung beachten.")
        return pdf, review["pdf_sha256"], review_hash


# ─── Settlement: finalization ────────────────────────────────────────────────

def _validated_evidence(row) -> dict[str, Any]:
    archive.validate_manifest(row)
    try:
        evidence = validate_deposit_snapshot(row, row.metadata_snapshot)
    except DepositValidationError:
        raise HTTPException(503, "Die archivierte Kautionsabrechnung ist beschädigt.") from None
    if not evidence:
        raise _not_found("Kautionsabrechnung")
    return evidence


def _replay(unit: archive.Unit, deposit: Deposit, settlement: DepositSettlement, document: Document,
            request_hash: str) -> dict[str, Any]:
    """The same command again (e.g. after a lost answer): the stored original, checked; never a second one."""
    if (document.contract_id != deposit.contract_id or document.document_type != DOC_TYPE
            or document.file_url != f"/uploads/{VIRTUAL_PREFIX}{document.id}.pdf"):
        raise _conflict("Die Vorgangsreferenz gehört bereits zu einem anderen Dokument.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Die gespeicherte Abrechnung hat kein archiviertes Original.")
    evidence = _validated_evidence(row)
    if (row.request_sha256 != request_hash or row.actor_id != unit.actor_id
            or evidence["settlement_id"] != settlement.id or settlement.document_id != document.id):
        raise _conflict("Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
    _, binding = archive.bind_document(unit, document.id)
    archive.authorized_version(unit, document.id, row.id, binding)
    for _ in archive.verified_blocks(unit, row):
        pass
    return _detail(unit, _deposit(unit, deposit.id))


def _new_booking(contract, account_id: str, amount: Decimal, day: date, text: str) -> Booking:
    stamp = now()
    return Booking(id=new_id(), account_id=account_id, property_id=contract.property_id, unit_id=contract.unit_id,
                   tenant_id=contract.tenant_id, booking_date=day, amount=float(amount), status="open",
                   payment_text=text[:500], created_at=stamp, updated_at=stamp)


def finalize(store, deposit_id: str, settlement_id: str, payload: FinalizeRequest, actor_id: str) -> dict[str, Any]:
    if payload.confirmed is not True:
        raise HTTPException(422, "Bitte bestätigen, dass die Abrechnung geprüft ist.")
    request_hash = finalize_request_hash(settlement_id, payload.model_dump(mode="json"))
    document_id = document_id_for(actor_id, payload.idempotency_key)
    with archive.work(store, actor_id, write_areas=FINALIZE_AREAS) as unit:
        deposit = _deposit(unit, deposit_id)
        # locks first: a parallel request (same key or not) then finds this one's result
        _parents(unit, deposit.contract_id, lock=True, deposit_id=deposit.id)
        deposit = _deposit(unit, deposit_id)
        settlement = _settlement(unit, deposit, settlement_id)
        try:
            existing = unit.store.get_document(document_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return _replay(unit, deposit, settlement, existing, request_hash)
        _require_draft(settlement)
        review, review_hash, pdf, evaluation, parents = _review(unit, deposit, settlement)
        contract, prop, location, tenant, portfolio = parents
        blocking = [p["message"] for p in evaluation["problems"] if p["blocking"]]
        if blocking or evaluation["outcome"] is None:
            raise _conflict("Die Abrechnung ist noch nicht abschließbar: " + " ".join(blocking))
        if review_hash != payload.review_hash:
            raise _conflict("Die Abrechnung stimmt nicht mehr mit der geprüften Vorschau überein. Bitte neu prüfen.")
        outcome: rules.Outcome = evaluation["outcome"]
        arrears: Decimal = evaluation["arrears"]
        account_id = payload.payout_account_id or deposit.account_id
        if (outcome.payout > 0 or arrears > 0) and not account_id:
            raise HTTPException(422, "Für Auszahlung bzw. Verrechnung bitte das Konto wählen, auf dem die Kaution "
                                     "geführt wird.")
        if account_id and (outcome.payout > 0 or arrears > 0):
            _account(unit, account_id, prop)
        day = settlement.settlement_date
        label = "Kautionsabrechnung" if settlement.kind == "final" else "Freigabe Kautionseinbehalt"
        stamp = archive.now()
        changes: dict[str, Any] = {}

        # 1. money moves are bookings, linked to the deposit file with their share
        def link(booking: Booking, kind: str) -> None:
            _put(unit, "bookings", booking)
            _flush(unit)
            _put(unit, "deposit_payments", DepositPayment(
                id=new_id(), deposit_id=deposit.id, booking_id=booking.id, kind=kind, amount=booking.amount,
                settlement_id=settlement.id, created_at=stamp, updated_at=stamp))
            _flush(unit)

        if outcome.payout > 0:
            assert account_id is not None
            payout = _new_booking(contract, account_id, -outcome.payout, day,
                                  f"{label}: Auszahlung an {tenant.full_name} ({contract.contract_number})")
            link(payout, "payout")
            changes["payout_booking_id"] = payout.id
        if arrears > 0:
            assert account_id is not None
            # Verrechnung: the deposit releases the amount and it pays the rent arrears (net zero on the account)
            released = _new_booking(contract, account_id, -arrears, day,
                                    f"{label}: Verrechnung mit Mietrückstand ({contract.contract_number})")
            link(released, "offset")
            credit = _new_booking(contract, account_id, arrears, day,
                                  f"{label}: Mietrückstand aus Kaution beglichen ({contract.contract_number})")
            _put(unit, "bookings", credit)
            _flush(unit)
            _put(unit, "payment_allocations", PaymentAllocation(
                id=new_id(), booking_id=credit.id, contract_id=contract.id, amount=float(arrears), source="manual",
                created_at=stamp, updated_at=stamp))
            changes.update({"offset_booking_id": released.id, "offset_credit_booking_id": credit.id})
        # 2. offset receivables are settled by the deposit
        for item in evaluation["items"]:
            if item.kind != "receivable" or item.receivable_id is None:
                continue
            receivable = unit.store.get_receivable(item.receivable_id)
            from .receivable_residuals import residual
            settled = money(receivable.amount_due) - money(residual(unit.store, receivable, date.max)["residual"]) + money(item.amount)
            status = "paid" if settled >= money(receivable.amount_due) else "partial"
            _put(unit, "receivables", receivable.model_copy(update={"status": status, "updated_at": stamp}))
        # 3. a remaining claim becomes a receivable of the contract
        if outcome.remaining_claim > 0:
            claim = Receivable(id=new_id(), contract_id=contract.id, due_date=day,
                               amount_due=float(outcome.remaining_claim), status="open",
                               description=f"Restforderung aus der {label} vom {day:%d.%m.%Y}",
                               created_at=stamp, updated_at=stamp)
            _put(unit, "receivables", claim)
            changes["claim_receivable_id"] = claim.id
        _flush(unit)

        # 4. the document and its immutable original, in this transaction
        values = {
            "id": document_id,
            **DocumentCreate(
                property_id=prop.id, unit_id=location.id, contract_id=contract.id,
                title=f"{label} – {contract.contract_number} – {day:%d.%m.%Y}",
                document_type=DOC_TYPE, document_date=day, tags="kaution",
                description=f"Abgeschlossene {label} (Kaution {_text(money(deposit.amount))} €)",
                file_url=f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf",
            ).model_dump(),
            "ai_document_type": None, "ai_summary": None, "ai_entities_json": None, "ai_confidence": None,
            "ai_model": None, "ai_analyzed_at": None, "created_at": stamp, "updated_at": stamp,
        }
        document = Document.model_validate(values)
        if unit.db is not None:
            from sqlalchemy import insert

            unit.db.execute(insert(DocumentORM), values)
        else:
            unit.insert(object.__getattribute__(unit.store, "__dict__")["documents"], document.id, document)
        binding = {"portfolio_id": prop.portfolio_id, "property_id": prop.id, "unit_id": location.id,
                   "contract_id": contract.id, "tenant_id": tenant.id}
        extension = {
            "schema_version": SCHEMA_VERSION, "review": review, "review_hash": review_hash,
            "request_sha256": request_hash, "actor_id": actor_id, "idempotency_key": payload.idempotency_key,
            "deposit_id": deposit.id, "settlement_id": settlement.id, "confirmed": True,
            "payout_account_id": payload.payout_account_id,
        }
        row = archive.publish_generated_original(unit, document, binding, pdf, request_hash,
                                                 version_id=new_id(), metadata_extra={"deposit_settlement": extension})
        _validated_evidence(row)

        # 5. the deposit's state, then the settlement finalized last (from here on the triggers keep it)
        if settlement.kind == "final":
            deposit_changes = {"status": "partially_returned" if outcome.retention > 0 else "returned",
                               "return_date": day, "deductions": float(min(outcome.claims, money(deposit.amount))),
                               "deduction_reason": f"Kautionsabrechnung vom {day:%d.%m.%Y}"}
        else:
            deposit_changes = {"status": "returned", "return_date": day}
        deposit = deposit.model_copy(update={**deposit_changes, "updated_at": stamp})
        _put(unit, "deposits", deposit)
        _flush(unit)
        final = now()
        settlement = settlement.model_copy(update={
            **changes, "status": "finalized", "result_amount": float(outcome.result), "document_id": document_id,
            "finalized_at": final, "finalized_by": actor_id, "updated_at": final})
        _put(unit, "deposit_settlements", settlement)
        _flush(unit)
        return _detail(unit, deposit)


# ─── Reading the archived original ───────────────────────────────────────────

def _verified(unit: archive.Unit, document: Document) -> tuple[bytes, Any]:
    row = archive.head(unit, document.id)
    if row is None:
        raise _not_found("Archiviertes Original")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    _validated_evidence(row)
    return archive.original_bytes(unit, row), row


def read_original(store, deposit_id: str, settlement_id: str, actor_id: str) -> tuple[bytes, Any]:
    with archive.work(store, actor_id) as unit:
        deposit = _deposit(unit, deposit_id)
        settlement = _settlement(unit, deposit, settlement_id)
        if settlement.document_id is None:
            raise _not_found("Abgeschlossene Abrechnung")
        try:
            document = unit.store.get_document(settlement.document_id)
        except NotFoundError:
            raise _not_found("Dokument") from None
        return _verified(unit, document)


def read_pdf_for_key(store, key: str, actor_id: str) -> bytes | None:
    """/uploads/deposit-settlements/<id>.pdf: always the verified original, never a file on disk."""
    if not key.startswith(VIRTUAL_PREFIX) or not key.endswith(".pdf"):
        return None
    from uuid import UUID

    identifier = key[len(VIRTUAL_PREFIX):-4]
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError
    except ValueError:
        raise _not_found("Kautionsabrechnung") from None
    with archive.work(store, actor_id) as unit:
        try:
            document = unit.store.get_document(identifier)
        except NotFoundError:
            raise _not_found("Kautionsabrechnung") from None
        if document.file_url != f"/uploads/{key}" or document.document_type != DOC_TYPE:
            raise _not_found("Kautionsabrechnung")
        return _verified(unit, document)[0]


# ─── The file ────────────────────────────────────────────────────────────────

def _settlement_json(unit: archive.Unit, deposit: Deposit, settlement: DepositSettlement, contract
                     ) -> dict[str, Any]:
    items = unit.store.list_deposit_settlement_items(settlement.id)
    result: dict[str, Any] = {
        **settlement.model_dump(mode="json"), "revision": revision(settlement),
        "items": [item.model_dump(mode="json") for item in items], "finalized": settlement.finalized_at is not None}
    if settlement.finalized_at is not None:
        original = None
        if settlement.document_id:
            row = archive.head(unit, settlement.document_id)
            if row is not None:
                evidence = _validated_evidence(row)
                original = {"document_id": row.document_id, "version_id": row.id, "pdf_sha256": row.sha256,
                            "size_bytes": row.size_bytes,
                            "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
                            "file_url": row.metadata_snapshot["file_url"],
                            "download_url": f"/deposits/{deposit.id}/settlements/{settlement.id}/document",
                            "outcome": evidence["review"]["outcome"], "interest": evidence["review"]["interest"]}
        result["original"] = original
        result["outcome"] = original["outcome"] if original else None
        return result
    evaluation = _evaluate(unit, deposit, settlement, contract)
    day = settlement.settlement_date
    included = {item.handover_defect_id for item in items if item.handover_defect_id}
    taken = {item.receivable_id for item in items if item.receivable_id}
    result.update({
        "outcome": _outcome_json(evaluation["outcome"]),
        "interest": {"computed": _num(evaluation["computed_total"]),
                     "carried": _num(evaluation["carried_interest"])
                     if evaluation["carried_interest"] is not None else None,
                     "years": _interest_json(evaluation["computed"])},
        "problems": evaluation["problems"],
        "suggestions": {
            "defects": [{"id": defect.id, "room": room, "description": defect.description, "remedy": defect.remedy,
                         "included": defect.id in included}
                        for defect, room in _tenant_defects(unit, settlement.handover_protocol_id)],
            "receivables": [{"id": r.id, "due_date": r.due_date.isoformat(), "amount_due": _num(money(r.amount_due)),
                             "open": _num(amount), "description": getattr(r, "description", None),
                             "statement_id": r.statement_id, "included": r.id in taken}
                            for r, amount in _open_receivables(unit, contract.id, settlement.id)],
            "rent_arrears": _num(_rent_outstanding(unit, contract, day)),
            "retention_allowed": settlement.kind == "final" and _utility_period_open(unit, contract, day),
            "monthly_advances": _num(_advances_at(unit, contract, min(contract.end_date or day, day))),
        },
    })
    return result


def _brief(unit: archive.Unit, deposit: Deposit) -> dict[str, Any]:
    settlements = _settlements(unit, deposit.id)
    received = _received(deposit, unit.store.list_deposit_payments(deposit.id))
    final = _final(settlements)
    retention = (_retention(unit.store.list_deposit_settlement_items(final.id))
                 if final is not None and final.finalized_at is not None else ZERO)
    return {"id": deposit.id, "contract_id": deposit.contract_id, "amount": _num(money(deposit.amount)),
            "form": deposit.form, "received": _num(received), "retention": _num(retention),
            "stage": _stage(deposit, received, settlements, retention), "status": deposit.status}


def _detail(unit: archive.Unit, deposit: Deposit) -> dict[str, Any]:
    contract, prop, location, tenant, portfolio = _parents(unit, deposit.contract_id)
    settlements = _settlements(unit, deposit.id)
    links = unit.store.list_deposit_payments(deposit.id)
    receipts = _receipts(unit, deposit.id)
    received = _received(deposit, [link for link, _ in receipts])
    carried = _carried(deposit)
    states, _ = rules.apply_receipts(
        _instalments(unit, deposit.id),
        ([(carried[0], carried[1])] if carried else [])
        + [(booking.booking_date if booking else date.min, money(link.amount)) for link, booking in receipts])
    # beyond the agreed amount (the plain records of earlier versions have no instalments to compare with)
    surplus = max(received - money(deposit.amount), ZERO)
    final = _final(settlements)
    retention = (_retention(unit.store.list_deposit_settlement_items(final.id))
                 if final is not None and final.finalized_at is not None else ZERO)
    today = local_today()
    until = final.settlement_date if final is not None and final.finalized_at is not None else today
    interest = _interest(unit, deposit, until)
    bookings: dict[str, Any] = {}
    for row in links:
        try:
            bookings[row.booking_id] = unit.store.get_booking(row.booking_id)
        except NotFoundError:
            bookings[row.booking_id] = None
    account = None
    if deposit.account_id:
        try:
            found = unit.store.get_account(deposit.account_id)
            account = {"id": found.id, "name": found.name, "bank_name": found.bank_name, "iban": found.iban}
        except NotFoundError:
            account = {"id": deposit.account_id, "missing": True}
    order = {"final": 0, "retention_release": 1}
    return {
        "deposit": {**deposit.model_dump(mode="json"), "revision": revision(deposit)},
        "stage": _stage(deposit, received, settlements, retention),
        "settled": _is_settled(settlements),
        "money_form": deposit.form in rules.MONEY_FORMS,
        "source": _source(contract, prop, location, tenant, portfolio),
        "cap": _cap(unit, contract, money(deposit.amount)),
        "account": account,
        "accounts": _accounts(unit, prop.portfolio_id),
        "instalments": [{"number": s.number, "due_date": s.due_date.isoformat(), "amount": _num(s.amount),
                         "paid": _num(s.paid), "open": _num(s.open), "status": s.status(today)} for s in states],
        "received": _num(received), "outstanding": _num(max(money(deposit.amount) - received, ZERO)),
        "surplus": _num(surplus),
        "payments": [{**row.model_dump(mode="json"),
                      "booking": ({"id": b.id, "booking_date": b.booking_date.isoformat(), "amount": _num(money(b.amount)),
                                   "account_id": b.account_id, "payment_text": b.payment_text, "status": b.status}
                                  if (b := bookings.get(row.booking_id)) is not None else None)}
                     for row in sorted(links, key=lambda r: (
                         bookings[r.booking_id].booking_date if bookings.get(r.booking_id) else date.min, r.id))],
        "warnings": _unresolved_returns(unit, deposit),
        "interest_rates": [r.model_dump(mode="json") for r in unit.store.list_deposit_interest_rates(deposit.id)],
        "interest": {"until": until.isoformat(), "total": _num(interest.total + (carried[2] if carried else ZERO)),
                     "carried": _num(carried[2]) if carried else None, "years": _interest_json(interest),
                     "balance": _num(interest.balance)},
        "legacy_candidate": _legacy_candidate(unit, deposit),
        "retention": _num(retention),
        "settlements": [_settlement_json(unit, deposit, s, contract)
                        for s in sorted(settlements, key=lambda s: order.get(s.kind, 9))],
    }


def detail(store, deposit_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        return _detail(unit, _deposit(unit, deposit_id))


STAGES = ("agreed", "partially_received", "received", "settlement_draft", "retained", "settled", "closed",
          "provided", "released")


def files(store, actor_id: str, *, contract_id: str | None = None, stage: str | None = None,
          query: str | None = None, skip: int = 0, limit: int = 50) -> dict[str, Any]:
    """The deposit files the account may see, with figures; every one counted, a page of them returned."""
    with archive.work(store, actor_id) as unit:
        contracts = {c.id: c for c in unit.store.list_contracts()}
        tenants = {t.id: t for t in unit.store.list_tenants()}
        properties = {p.id: p for p in unit.store.list_properties()}
        units = {u.id: u for u in unit.store.list_units()}
        links: dict[str, list[DepositPayment]] = defaultdict(list)
        for link in unit.store.list_deposit_payments():
            links[link.deposit_id].append(link)
        settlements: dict[str, list[DepositSettlement]] = defaultdict(list)
        for settlement in unit.store.list_deposit_settlements():
            settlements[settlement.deposit_id].append(settlement)
        rows = []
        for deposit in unit.store.list_deposits():
            contract = contracts.get(deposit.contract_id)
            if contract is None or (contract_id and deposit.contract_id != contract_id):
                continue
            received = _received(deposit, links[deposit.id])
            final = _final(settlements[deposit.id])
            retention = (_retention(unit.store.list_deposit_settlement_items(final.id))
                         if final is not None and final.finalized_at is not None else ZERO)
            tenant = tenants.get(contract.tenant_id)
            prop = properties.get(contract.property_id)
            location = units.get(contract.unit_id)
            rows.append({
                "id": deposit.id, "contract_id": contract.id, "contract_number": contract.contract_number,
                "contract_status": contract.status, "contract_end": contract.end_date.isoformat()
                if contract.end_date else None,
                "tenant_id": contract.tenant_id, "tenant_name": tenant.full_name if tenant else None,
                "property_name": prop.name if prop else None, "unit_label": location.label if location else None,
                "form": deposit.form, "amount": _num(money(deposit.amount)), "received": _num(received),
                "outstanding": _num(max(money(deposit.amount) - received, ZERO)) if deposit.form in rules.MONEY_FORMS
                else 0.0,
                "retention": _num(retention), "stage": _stage(deposit, received, settlements[deposit.id], retention),
                "settled_on": final.settlement_date.isoformat() if final and final.finalized_at else None,
            })
        if query:
            needle = query.casefold()
            rows = [row for row in rows if any(needle in str(row.get(name) or "").casefold() for name in (
                "contract_number", "tenant_name", "property_name", "unit_label"))]
        counts = {name: sum(1 for row in rows if row["stage"] == name) for name in STAGES}
        if stage:
            rows = [row for row in rows if row["stage"] == stage]
        rows.sort(key=lambda row: ((row["tenant_name"] or "").casefold(), row["contract_number"] or "", row["id"]))
        totals = {"count": len(rows), "amount": _num(sum((Decimal(str(r["amount"])) for r in rows), ZERO)),
                  "received": _num(sum((Decimal(str(r["received"])) for r in rows), ZERO)),
                  "retention": _num(sum((Decimal(str(r["retention"])) for r in rows), ZERO))}
        return {"items": rows[skip:skip + limit], "total": len(rows), "skip": skip, "limit": limit,
                "totals": totals, "stages": counts}


def records_of(store, deposit_ids: set[str]) -> dict[str, list]:
    """The deposit file rows of these deposits (data subject access export)."""
    settlements = [s for s in store.list_deposit_settlements() if s.deposit_id in deposit_ids]
    settlement_ids = {s.id for s in settlements}
    return {
        "deposit_instalments": [r for r in store.list_deposit_instalments() if r.deposit_id in deposit_ids],
        "deposit_interest_rates": [r for r in store.list_deposit_interest_rates() if r.deposit_id in deposit_ids],
        "deposit_payments": [r for r in store.list_deposit_payments() if r.deposit_id in deposit_ids],
        "deposit_settlements": settlements,
        "deposit_settlement_items": [r for r in store.list_deposit_settlement_items()
                                     if r.settlement_id in settlement_ids],
    }


# ─── Guards for bookings and receivables the deposit file names ──────────────

def _booking_linked(store, booking_id: str) -> bool:
    lister = getattr(store, "list_deposit_payments", None)
    if lister is None:
        return False
    return bool(lister(booking_ids=[booking_id])) or any(
        s.offset_credit_booking_id == booking_id for s in store.list_deposit_settlements())


def ensure_booking_unchanged(store, booking_id: str, changes: dict[str, Any]) -> None:
    """A booking the deposit file names keeps amount, date, account and tenant (unlink it there first)."""
    from .receivable_residuals import cash_reserved
    deposit_linked = _booking_linked(store, booking_id)
    if not deposit_linked and not cash_reserved(store, [booking_id]):
        return
    current = store.get_booking(booking_id)
    guarded = ("amount", "booking_date", "account_id", "tenant_id", "reverses_booking_id")
    if any(name in changes and changes[name] != getattr(current, name) for name in guarded):
        if not deposit_linked:
            raise _conflict("Die Buchung gehört zu einem belegten Forderungsausgleich. Betrag, Datum, Konto und Mieter bleiben erhalten; Korrekturen erfolgen durch Storno oder Rücknahme.")
        raise _conflict("Die Buchung gehört zu einer Kautionsakte. Betrag, Datum, Konto und Mieter lassen sich nur "
                        "ändern, nachdem sie dort gelöst wurde (eine abgerechnete Kaution bleibt unverändert).")
