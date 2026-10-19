"""Canonical dated residuals of stored receivables, using existing financial sources.

Settlement edges reserve existing money, they are not postings. Cash reversals reduce
the original edges proportionally at their booking date. Deposit offsets are read
directly from finalized immutable settlements, never copied to a second ledger.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import HTTPException

from ..domain.billing_engine import allocate_cents
from ..domain.money import ZERO, money
from ..finance_models import ReverseSettlement, Settlement, SettlementCommand
from .maintenance_projects import work
from .maintenance_rows import Rows


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def settlement_rows(store):
    return Rows.reading(store).find("receivable_settlements")


def ensure_evidence_visible(store, claim_ids, visible_edges):
    """An unreadable financial source must produce an error, never a fictitious full debt."""
    from .portfolio_scope import current_scope, scope_context
    scope = current_scope()
    if scope is None or scope.unrestricted or not claim_ids:
        return
    rows = Rows.reading(store)
    with scope_context(None):
        complete = rows.find("receivable_settlements", receivable_id=claim_ids)
        complete += rows.find("receivable_settlements", credit_id=claim_ids)
    if {e.id for e in complete} - {e.id for e in visible_edges}:
        raise HTTPException(403, "Für einen belegbaren Forderungsrest fehlen Rechte auf verknüpfte Zahlungsquellen. Bitte den gemeinsamen Belegzugriff klären.")


def ensure_claim_unchanged(store, identifier, changes):
    """A source used by a settlement keeps its financial identity; corrections use new evidence."""
    current = store.get_receivable(identifier)
    linked = any(identifier in (e.receivable_id, e.credit_id) for e in settlement_rows(store))
    linked = linked or any(e[0] == identifier for e in deposit_evidence(store, current.contract_id))
    if not linked:
        return
    guarded = ("contract_id", "amount_due", "due_date", "status", "statement_id")
    if any(k in changes and changes[k] != getattr(current, k) for k in guarded):
        raise HTTPException(409, "Diese Forderung gehört zu einem belegten Ausgleich. Quelle und Betrag bleiben erhalten.")


def cash_events(store, booking, edges, reversals=None):
    """Dated allocation/return timeline, including allocations after partial returns.

    `reversals` are the booking's reversals when the caller already read them (a report reads all at once).
    """
    originals = {e.id: e for e in edges if not e.reverses_id}
    remaining = {key: ZERO for key in originals}
    events = [(e.effective_date, 1 if e.reverses_id else 0, e.id, e) for e in edges]
    events += [(b.booking_date, 2, b.id, b)
               for b in (store.list_booking_reversals(booking.id) if reversals is None else reversals)]
    balance = money(booking.amount)
    result = []
    for day, phase, _, item in sorted(events, key=lambda event: event[:3]):
        if phase == 0:
            remaining[item.id] = money(item.amount)
            result.append((item.receivable_id, day, money(item.amount), "booking", item.id))
        elif phase == 1:
            amount = remaining.get(item.reverses_id, ZERO)
            remaining[item.reverses_id] = ZERO
            result.append((item.receivable_id, day, -amount, "allocation_reversal", item.id))
        else:
            returned = min(abs(money(item.amount)), balance)
            active = sorted(key for key, value in remaining.items() if value > 0)
            total = sum((remaining[key] for key in active), ZERO)
            reduction = min(total, money(total * returned / balance)) if balance else ZERO
            portions = allocate_cents(reduction, [remaining[key] for key in active]) if active else []
            for key, amount in zip(active, portions):
                remaining[key] -= amount
                result.append((originals[key].receivable_id, day, -amount, "reversal", item.id))
            balance -= returned
    return result


def cash_reserved(store, booking_ids=None):
    """Shares reserved from each original AND reversal; rent gets exactly the complement."""
    wanted = set(booking_ids) if booking_ids is not None else {b.id for b in store.list_bookings()}
    rows = Rows.reading(store)
    source_ids = set(wanted)
    if hasattr(store, 'db'):
        from sqlalchemy import select

        from ..db.orm_models import BookingORM
        from ..storage import NotFoundError
        from .portfolio_scope import BOUNDED, scoped_clause

        # Validate every requested source under the current portfolio boundary,
        # without a separate SQL round trip for each cash row in a report.
        parents: dict[str, str | None] = {}
        keys = sorted(wanted)
        # Built once and marked as bounded: the session would otherwise bound every select inside
        # this boundary again (several seconds for a restricted account's review list).
        boundary = scoped_clause(BookingORM)
        for start in range(0, len(keys), 500):
            query = select(BookingORM.id, BookingORM.reverses_booking_id).where(BookingORM.id.in_(keys[start:start + 500]))
            if boundary is not None:
                query = query.where(boundary).execution_options(**{BOUNDED: True})
            parents.update(dict(store.db.execute(query).all()))
        if wanted - parents.keys():
            raise NotFoundError('Buchung nicht gefunden')
        source_ids.update(parent for parent in parents.values() if parent)
    else:
        for key in wanted:
            booking = store.get_booking(key)
            if booking.reverses_booking_id:
                source_ids.add(booking.reverses_booking_id)
    from .portfolio_scope import scope_context
    # Only authorized source IDs cross this boundary, and only their amounts return.
    with scope_context(None):
        edges = rows.find("receivable_settlements", booking_id=source_ids)
    by_booking = defaultdict(list)
    for edge in edges:
        if edge.booking_id:
            by_booking[edge.booking_id].append(edge)
    found: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_id = {e.id: e for e in edges}
    for booking_id, selected in by_booking.items():
        for _, _, amount, kind, source in cash_events(store, store.get_booking(booking_id), selected):
            key = source if kind == "reversal" else by_id[source].booking_id
            if key in wanted:
                found[key] += amount
    return dict(found)


def dated_evidence(store, contract_id, *, known_claims=None, known_edges=None, booking_edges=None,
                   bookings=None, reversals=None, deposits=None):
    """(claim id, date, amount, source type, source id), stable and decimal exact.

    `bookings` and `reversals` (by booking id) and the contract's `deposits` evidence spare queries per
    contract and booking when a report reads many contracts; a booking missing from them is read as before.
    """
    result = list(deposits) if deposits is not None else deposit_evidence(store, contract_id)
    receivables = {r.id: r for r in (known_claims if known_claims is not None else Rows.reading(store).find("receivables", contract_id=contract_id))}
    if known_edges is None:
        rows = Rows.reading(store)
        linked = rows.find("receivable_settlements", receivable_id=set(receivables))
        linked += rows.find("receivable_settlements", credit_id=set(receivables))
        edges = list({edge.id: edge for edge in linked}.values())
        ensure_evidence_visible(store, set(receivables), edges)
    else:
        edges = known_edges
    by_booking = defaultdict(list)
    for edge in edges:
        if edge.receivable_id not in receivables and edge.credit_id not in receivables:
            continue
        if edge.booking_id:
            by_booking[edge.booking_id].append(edge)
        else:
            result.append((edge.receivable_id, edge.effective_date, money(edge.amount), "credit", edge.id))
            result.append((edge.credit_id, edge.effective_date, -money(edge.amount), "credit", edge.id))
    for booking_id, selected in by_booking.items():
        known = bookings is not None and booking_id in bookings
        booking = bookings[booking_id] if known else store.get_booking(booking_id)
        # Include every edge sharing this booking for a deterministic global cent split.
        if booking_edges is not None:
            all_edges = booking_edges.get(booking_id, [])
        else:
            from .portfolio_scope import scope_context
            with scope_context(None):
                all_edges = Rows.reading(store).find("receivable_settlements", booking_id=booking_id)
        all_edges = sorted(all_edges, key=lambda e: e.id)
        selected_ids = {e.receivable_id for e in selected}
        returned = reversals.get(booking_id, []) if known and reversals is not None else None
        result.extend(event for event in cash_events(store, booking, all_edges, returned) if event[0] in selected_ids)
    return sorted(result, key=lambda row: (row[1], row[0], row[3], row[4]))


def deposit_evidence(store, contract_id):
    """Public read hook: finalized deposit sources, never drafts or inferred payments."""
    return deposit_evidence_by_contract(store, {contract_id}).get(contract_id, [])


def deposit_evidence_by_contract(store, contract_ids):
    """The finalized deposit sources of several contracts at once, grouped by contract."""
    result: dict[str, list[tuple[str, date, Decimal, str, str]]] = defaultdict(list)
    if hasattr(store, "db"):
        from sqlalchemy import select

        from ..db.deposit_models import DepositSettlementItemORM, DepositSettlementORM
        from ..db.orm_models import DepositORM
        keys = sorted(contract_ids)
        for start in range(0, len(keys), 500):
            query = (select(DepositORM.contract_id, DepositSettlementItemORM.receivable_id, DepositSettlementORM.settlement_date,
                            DepositSettlementItemORM.amount, DepositORM.id)
                     .join(DepositSettlementORM, DepositSettlementItemORM.settlement_id == DepositSettlementORM.id)
                     .join(DepositORM, DepositORM.id == DepositSettlementORM.deposit_id)
                     .where(DepositORM.contract_id.in_(keys[start:start + 500]), DepositSettlementORM.finalized_at.is_not(None),
                            DepositSettlementItemORM.kind == "receivable", DepositSettlementItemORM.receivable_id.is_not(None))
                     .order_by(DepositSettlementItemORM.id))
            for contract_id, key, day, amount, source in store.db.execute(query):
                result[contract_id].append((key, day, money(amount), "deposit", source))
        return dict(result)
    contract_of = {d.id: d.contract_id for d in store.list_deposits() if d.contract_id in contract_ids}
    for settlement in store.list_deposit_settlements():
        if settlement.deposit_id in contract_of and settlement.finalized_at is not None:
            result[contract_of[settlement.deposit_id]].extend(
                (item.receivable_id, settlement.settlement_date, money(item.amount), "deposit", settlement.deposit_id)
                for item in store.list_deposit_settlement_items(settlement.id) if item.kind == "receivable" and item.receivable_id)
    return dict(result)


class ResidualReader:
    """One report's source graph, grouped once; no cross-request or cross-user cache."""
    def __init__(self, store):
        self.store = store
        self.claims: dict[str, list] = defaultdict(list)
        self.edges: dict[str, list] = defaultdict(list)
        self.booking_edges: dict[str, list] = defaultdict(list)
        claims = {r.id: r for r in store.list_receivables()}
        for claim in claims.values():
            self.claims[claim.contract_id].append(claim)
        edges = settlement_rows(store)
        ensure_evidence_visible(store, set(claims), edges)
        for edge in edges:
            target = claims.get(edge.receivable_id)
            if target:
                self.edges[target.contract_id].append(edge)
        # Retain hidden shares for a visible source's proportional reversal budget.
        from .portfolio_scope import scope_context
        with scope_context(None):
            for edge in Rows.reading(store).find("receivable_settlements", booking_id={e.booking_id for e in edges if e.booking_id}):
                self.booking_edges[edge.booking_id].append(edge)
        # The paying bookings and their reversals, read once for the whole report instead of per booking
        # (thousands of queries on a few years of rent); visibility is the store's, as for single reads.
        rows = Rows.reading(store)
        paid_by = {edge.booking_id for edge in edges if edge.booking_id}
        self.bookings = {booking.id: booking for booking in rows.find("bookings", id=paid_by)}
        self.reversals: dict[str, list] = defaultdict(list)
        for reversal in rows.find("bookings", reverses_booking_id=set(self.bookings)):
            self.reversals[reversal.reverses_booking_id].append(reversal)
        self.deposits = deposit_evidence_by_contract(store, set(self.claims))
        # The parent chain behind each claim's currency, read once; a record missing here is read singly,
        # so an unreadable contract, property or portfolio still fails exactly as a detailed read.
        self.contracts = {c.id: c for c in rows.find("contracts", id=set(self.claims))}
        self.properties = {p.id: p for p in rows.find("properties", id={c.property_id for c in self.contracts.values()})}
        self.portfolios = {p.id: p for p in store.list_portfolios()}
        self.evidence: dict[str, list] = {}
        self.currencies: dict[str, str] = {}

    def contract_evidence(self, contract_id):
        if contract_id not in self.evidence:
            self.evidence[contract_id] = dated_evidence(self.store, contract_id, known_claims=self.claims[contract_id],
                known_edges=self.edges[contract_id], booking_edges=self.booking_edges,
                bookings=self.bookings, reversals=self.reversals, deposits=self.deposits.get(contract_id, []))
        return self.evidence[contract_id]

    def balance(self, receivable, as_of=None):
        """Aggregate callers need exact amounts, not per-row serialized proof.

        The same source/permission validation runs for the report's graph; no
        historical balance is inferred from an undated partial-payment status.
        """
        self.currency(receivable.contract_id)  # preserve the same authorized parent chain as a detailed read
        own = [event for event in self.contract_evidence(receivable.contract_id) if event[0] == receivable.id]
        return _balance(receivable, own, as_of or date.today())[1]

    def currency(self, contract_id):
        if contract_id not in self.currencies:
            contract = self.contracts.get(contract_id) or self.store.get_contract(contract_id)
            prop = self.properties.get(contract.property_id) or self.store.get_property(contract.property_id)
            portfolio = self.portfolios.get(prop.portfolio_id) or self.store.get_portfolio(prop.portfolio_id)
            self.currencies[contract_id] = portfolio.currency
        return self.currencies[contract_id]

    def read(self, receivable, as_of=None):
        contract_id = receivable.contract_id
        return residual(self.store, receivable, as_of, evidence=self.contract_evidence(contract_id),
                        edges=self.edges[contract_id], currency=self.currency(contract_id))


def _balance(receivable, own, as_of):
    applied = sum((event[2] for event in own if event[1] <= as_of), ZERO)
    original = money(receivable.amount_due)
    # An opaque legacy status cannot supply a payment date or a paid amount.
    unresolved = receivable.status == "partial" and not own
    from ..domain.receivables import UNPAID_RECEIVABLE_STATUSES
    legacy_closed = receivable.status not in UNPAID_RECEIVABLE_STATUSES and not own
    balance = ZERO if legacy_closed else original - applied
    return applied, balance, unresolved, legacy_closed


def residual(store, receivable, as_of=None, *, evidence=None, edges=None, currency=None):
    as_of = as_of or date.today()
    evidence = dated_evidence(store, receivable.contract_id) if evidence is None else evidence
    own = [e for e in evidence if e[0] == receivable.id]
    applied, balance, unresolved, legacy_closed = _balance(receivable, own, as_of)
    original = money(receivable.amount_due)
    edges = Rows.reading(store).find("receivable_settlements", receivable_id=receivable.id) if edges is None else edges
    edge_by_id = {e.id: e for e in edges}
    def source_url(e):
        if e[3] == "deposit":
            return "/deposits?deposit_id=" + e[4]
        if e[3] == "reversal":
            return "/bookings?booking_id=" + e[4]
        edge = edge_by_id.get(e[4])
        if edge and edge.booking_id:
            return "/bookings?booking_id=" + edge.booking_id
        return "/receivables?contract_id=" + receivable.contract_id
    return {"receivable_id": receivable.id, "as_of": as_of.isoformat(),
            "original": str(original), "settled": str(applied), "residual": str(balance),
            "unresolved_legacy": unresolved, "undated_legacy_closed": legacy_closed,
            "revision": digest([receivable.model_dump(mode="json"), evidence]),
            "evidence": [{"date": e[1].isoformat(), "amount": str(e[2]), "kind": e[3], "source_id": e[4], "url": source_url(e)}
                         for e in own if e[1] <= as_of],
            "allocations": [e.model_dump(mode="json") for e in edges if e.receivable_id == receivable.id],
            "currency": currency if currency is not None else store.get_portfolio(store.get_property(
                store.get_contract(receivable.contract_id).property_id).portfolio_id).currency}


def allocate(store, receivable_id, payload: SettlementCommand, actor_id=None):
    if bool(payload.booking_id) == bool(payload.credit_id):
        raise HTTPException(422, "Genau eine Buchung oder Gutschrift auswählen.")
    key = digest([actor_id, "receivable-settlement", payload.idempotency_key])
    request_hash = digest([receivable_id, payload.model_dump(mode="json")])
    with work(store, actor_id, ("/receivables", "/bookings")) as unit:
        rows = Rows.of(unit)
        # Consistent parent order serializes all consumers of a contract's cash and credits.
        initial = unit.store.get_receivable(receivable_id)
        from .deposits import _parents
        _parents(unit, initial.contract_id, lock=True)
        rows.lock("receivables", receivable_id)
        claim = unit.store.get_receivable(receivable_id)
        unit.store.get_contract(claim.contract_id)
        existing = rows.get("receivable_settlements", key)
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Dieser Wiederholungsschlüssel gehört zu einer anderen Zuordnung.")
            return existing.model_dump(mode="json")
        state = residual(unit.store, claim, date.max)
        if state["revision"] != payload.expected_revision:
            raise HTTPException(409, "Die Forderung wurde geändert. Aktuellen Stand laden; Eingabe bleibt erhalten.")
        if state["unresolved_legacy"] or state["undated_legacy_closed"]:
            raise HTTPException(409, "Ungeklärter Altbestand: zuerst anhand der Originalbelege klären.")
        if money(state["residual"]) < payload.amount or money(claim.amount_due) <= 0:
            raise HTTPException(409, "Der Betrag übersteigt den belegbaren Forderungsrest.")
        if payload.booking_id:
            rows.lock("bookings", payload.booking_id)
            booking = unit.store.get_booking(payload.booking_id)
            contract = unit.store.get_contract(claim.contract_id)
            claim_currency = unit.store.get_portfolio(unit.store.get_property(contract.property_id).portfolio_id).currency
            source_currency = unit.store.get_portfolio(unit.store.get_account(booking.account_id).portfolio_id).currency
            if source_currency != claim_currency:
                raise HTTPException(409, "Zahlung und Forderung haben unterschiedliche Währungen. Eine Umrechnung wird nicht erfunden.")
            if booking.tenant_id != contract.tenant_id or booking.reverses_booking_id or money(booking.amount) <= 0:
                raise HTTPException(409, "Nur ein Zahlungseingang dieses Mieters kann zugeordnet werden.")
            if payload.effective_date < booking.booking_date:
                raise HTTPException(422, "Der Ausgleich darf nicht vor dem Zahlungseingang liegen.")
            from .payment_allocations import non_rent_shares
            shares = non_rent_shares(unit.store, [booking.id])
            # Manual rent splits are a prior reservation; automatic splits may be displaced explicitly.
            manual = sum((money(a.amount) for a in unit.store.list_payment_allocations(booking_id=booking.id)
                          if a.source == "manual"), ZERO)
            reversed_amount = sum((abs(money(b.amount)) for b in unit.store.list_booking_reversals(booking.id)), ZERO)
            reversals = unit.store.list_booking_reversals(booking.id)
            returned_share = sum(cash_reserved(unit.store, [b.id for b in reversals]).values(), ZERO) if reversals else ZERO
            available = money(booking.amount) - reversed_amount - shares.get(booking.id, ZERO) - returned_share - manual
            from .portfolio_scope import scope_context
            with scope_context(None):
                provider_used = sum((abs(money(p.amount)) for table in ("invoice_payments", "service_contract_payments")
                                     for p in rows.find(table, booking_id=booking.id)), ZERO)
            available -= provider_used
            if payload.amount > available:
                raise HTTPException(409, "Die Zahlung ist bereits anderweitig zugeordnet oder storniert.")
        else:
            assert payload.credit_id is not None
            rows.lock("receivables", payload.credit_id)
            credit = unit.store.get_receivable(payload.credit_id)
            if credit.contract_id != claim.contract_id or money(credit.amount_due) >= 0:
                raise HTTPException(409, "Nur ein Guthaben desselben Vertrags kann verrechnet werden.")
            credit_state = residual(unit.store, credit, date.max)
            if credit_state["unresolved_legacy"] or credit_state["undated_legacy_closed"]:
                raise HTTPException(409, "Das Guthaben ist ein ungeklärter Altbestand.")
            if payload.effective_date < credit.due_date or payload.amount > -money(credit_state["residual"]):
                raise HTTPException(409, "Das Guthaben reicht zu diesem Datum nicht aus.")
        edge = Settlement(id=key, receivable_id=claim.id, booking_id=payload.booking_id, credit_id=payload.credit_id,
                          amount=payload.amount, effective_date=payload.effective_date, reason=payload.reason,
                          actor_id=actor_id, request_hash=request_hash)
        rows.add("receivable_settlements", edge)
        if payload.booking_id:
            _refresh_rent(unit, rows, booking)
        return edge.model_dump(mode="json")


def reverse(store, receivable_id, settlement_id, payload: ReverseSettlement, actor_id=None):
    key = digest([actor_id, "receivable-settlement", payload.idempotency_key])
    request_hash = digest([receivable_id, settlement_id, payload.model_dump(mode="json")])
    with work(store, actor_id, ("/receivables", "/bookings")) as unit:
        rows = Rows.of(unit)
        claim = unit.store.get_receivable(receivable_id)
        from .deposits import _parents
        _parents(unit, claim.contract_id, lock=True)
        rows.lock("receivables", claim.id)
        original = rows.require("receivable_settlements", settlement_id, "Ausgleich nicht gefunden")
        if original.receivable_id != claim.id or original.reverses_id:
            raise HTTPException(409, "Nur der ursprüngliche Ausgleich dieser Forderung lässt sich zurücknehmen.")
        existing = rows.get("receivable_settlements", key)
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Wiederholungsschlüssel gehört zu einem anderen Befehl.")
            return existing.model_dump(mode="json")
        if payload.expected_revision != residual(unit.store, claim)["revision"]:
            raise HTTPException(409, "Die Forderung wurde geändert. Bitte den Stand neu laden.")
        if rows.find("receivable_settlements", reverses_id=original.id):
            raise HTTPException(409, "Dieser Ausgleich wurde bereits zurückgenommen.")
        if payload.effective_date < original.effective_date:
            raise HTTPException(422, "Eine Rücknahme darf nicht vor ihrem Ausgleich liegen.")
        if original.booking_id:
            rows.lock("bookings", original.booking_id)
        if original.credit_id:
            rows.lock("receivables", original.credit_id)
        edge = Settlement(id=key, receivable_id=claim.id, booking_id=original.booking_id, credit_id=original.credit_id,
                          reverses_id=original.id, amount=-original.amount, effective_date=payload.effective_date,
                          reason=payload.reason, actor_id=actor_id, request_hash=request_hash)
        rows.add("receivable_settlements", edge)
        if original.booking_id:
            _refresh_rent(unit, rows, unit.store.get_booking(original.booking_id))
        return edge.model_dump(mode="json")


def _refresh_rent(unit, rows, booking):
    from uuid import uuid4

    from ..models import PaymentAllocation
    from .payment_allocations import ensure_allocations_visible, planned_pairs
    for current in [booking, *sorted(unit.store.list_booking_reversals(booking.id), key=lambda b: (b.booking_date, b.id))]:
        existing = ensure_allocations_visible(unit.store, current.id)
        if any(a.source == "manual" for a in existing):
            continue
        for allocation in existing:
            if unit.db is not None:
                from sqlalchemy import delete

                from ..db.orm_models import PaymentAllocationORM
                unit.db.execute(delete(PaymentAllocationORM).where(PaymentAllocationORM.id == allocation.id))
            else:
                unit.remove(object.__getattribute__(unit.store, "__dict__")["payment_allocations"], allocation.id)
        for contract_id, amount in planned_pairs(unit.store, current):
            rows.add("payment_allocations", PaymentAllocation(id=str(uuid4()), booking_id=current.id,
                     contract_id=contract_id, amount=float(amount), source="auto"))


def snapshot_problems(plan, existing):
    """Public import hook: validate budgets and identities against the complete resulting graph."""
    after = {spec.key: {**existing.get(spec.key, {}), **{obj.id: obj for obj in objects}} for spec, objects in plan}
    claims, bookings = after.get("receivables", {}), after.get("bookings", {})
    contracts = after.get("contracts", {})
    edges = after.get("receivable_settlements", {})
    problems = []
    by_claim: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_cash: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_credit: dict[str, Decimal] = defaultdict(lambda: ZERO)
    reversed_ids = set()
    for edge in edges.values():
        claim = claims.get(edge.receivable_id)
        contract = contracts.get(claim.contract_id) if claim else None
        if not claim or not contract:
            continue  # the shared reference validator supplies the missing-parent message
        if not edge.booking_id:
            by_claim[claim.id] += money(edge.amount)
        if money(claim.amount_due) <= 0:
            problems.append("Ein Ausgleich muss eine positive Forderung nennen")
        if edge.booking_id:
            by_cash[edge.booking_id] += money(edge.amount)
            booking = bookings.get(edge.booking_id)
            if booking and (booking.reverses_booking_id or money(booking.amount) <= 0 or
                            booking.tenant_id != contract.tenant_id or edge.effective_date < booking.booking_date):
                problems.append("Ausgleich und Zahlungsquelle gehören nicht zusammen")
        if edge.credit_id:
            by_credit[edge.credit_id] += money(edge.amount)
            credit = claims.get(edge.credit_id)
            if credit and (credit.contract_id != claim.contract_id or money(credit.amount_due) >= 0 or edge.effective_date < credit.due_date):
                problems.append("Ausgleich und Guthaben gehören nicht zusammen")
        if edge.reverses_id:
            original = edges.get(edge.reverses_id)
            if edge.reverses_id in reversed_ids or not original or original.reverses_id or (
                    original.receivable_id, original.booking_id, original.credit_id, -money(original.amount)) != (
                    edge.receivable_id, edge.booking_id, edge.credit_id, money(edge.amount)) or (
                    original and edge.effective_date < original.effective_date):
                problems.append("Ungültige oder doppelte Rücknahme eines Forderungsausgleichs")
            reversed_ids.add(edge.reverses_id)
    from types import SimpleNamespace
    snapshot_store = SimpleNamespace(list_booking_reversals=lambda key: [b for b in bookings.values() if b.reverses_booking_id == key])
    for booking_id in by_cash:
        booking = bookings.get(booking_id)
        if booking and money(booking.amount) > 0:
            own_edges = [e for e in edges.values() if e.booking_id == booking_id]
            for claim_id, _, amount, _, _ in cash_events(snapshot_store, booking, own_edges):
                by_claim[claim_id] += amount
    finalized = {s.id for s in after.get("deposit_settlements", {}).values() if s.finalized_at is not None}
    for item in after.get("deposit_settlement_items", {}).values():
        if item.kind == "receivable" and item.settlement_id in finalized and item.receivable_id in claims:
            by_claim[item.receivable_id] += money(item.amount)
    for identifier, used in by_claim.items():
        if used < 0 or used > money(claims[identifier].amount_due):
            problems.append("Ausgleiche überschreiten den Forderungsbetrag")
    for identifier, used in by_credit.items():
        if identifier in claims and (used < 0 or used > -money(claims[identifier].amount_due)):
            problems.append("Ausgleiche überschreiten das vorhandene Guthaben")
    for identifier, used in by_cash.items():
        if identifier not in bookings:
            continue
        reserved = sum((abs(money(p.amount)) for p in after.get("deposit_payments", {}).values() if p.booking_id == identifier), ZERO)
        reserved += sum((abs(money(p.amount)) for p in after.get("payment_allocations", {}).values()
                         if p.booking_id == identifier and p.source == "manual"), ZERO)
        reserved += sum((abs(money(p.amount)) for table in ("invoice_payments", "service_contract_payments")
                         for p in after.get(table, {}).values() if p.booking_id == identifier), ZERO)
        if used < 0 or used + reserved > money(bookings[identifier].amount):
            problems.append("Ausgleiche überschreiten den verfügbaren Zahlungseingang")
    return problems
