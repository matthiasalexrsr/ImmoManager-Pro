"""Credit payments to contracts: automatic suggestion, manual split, accounts per contract.

A reversal (Storno) is credited to the contracts of the booking it cancels, in that booking's
proportions, and reduces exactly that payment; it is never allocated by the rules on its own.

The share of a booking that a deposit file names (a deposit receipt, payout or offset,
deposit_payments) is no rent: only the rest of the booking is credited to contracts, so
every amount counts once.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional

from ..domain.billing_engine import allocate_cents
from ..domain.lease_engine import LeaseEngine, PaymentLine, ReceivableLine, RentStep
from ..domain.money import ZERO, as_number, cents, money
from ..domain.occupancy import NON_BILLABLE_STATUSES
from ..domain.payment_allocation import ContractCandidate, suggest_allocation
from ..models import PaymentAllocationCreate
from ..storage import NotFoundError, ValidationError
from .read_cache import CachedReads
from .rent_history import charge_for
from .rent_ledger import account_receivables, carried_credit, takeover

Pairs = list[tuple[str, Decimal]]


def _tenant_payment_rows(store: Any, tenant_ids: set[str], until: date | None):
    """Read only these tenants' cash and links. Subqueries avoid huge booking-ID parameter lists."""
    from sqlalchemy import select

    from ..db.deposit_models import DepositPaymentORM
    from ..db.orm_models import BookingORM, PaymentAllocationORM
    from ..models import Booking, PaymentAllocation

    bookings: list[Booking] = []
    allocations: list[PaymentAllocation] = []
    shares: dict[str, Decimal] = {}
    wanted = sorted(tenant_ids)
    for start in range(0, len(wanted), 500):
        selected = select(BookingORM).where(BookingORM.tenant_id.in_(wanted[start:start + 500]))
        ids = select(BookingORM.id).where(BookingORM.tenant_id.in_(wanted[start:start + 500]))
        if until is not None:
            selected = selected.where(BookingORM.booking_date <= until)
            ids = ids.where(BookingORM.booking_date <= until)
        bookings.extend(Booking.model_validate({c.key: getattr(row, c.key) for c in BookingORM.__table__.columns})
                        for row in store.db.scalars(selected))
        from .portfolio_scope import scope_context, scoped_clause
        bounded_ids = ids
        clause = scoped_clause(BookingORM)
        if clause is not None:
            bounded_ids = ids.where(clause)
        # Source cash stays bounded; hidden target shares still consume that cash.
        with scope_context(None):
            allocation_query = select(PaymentAllocationORM).where(PaymentAllocationORM.booking_id.in_(bounded_ids))
            allocations.extend(PaymentAllocation.model_validate(
                {c.key: getattr(row, c.key) for c in PaymentAllocationORM.__table__.columns})
                               for row in store.db.scalars(allocation_query))
            for booking_id, amount in store.db.execute(
                    select(DepositPaymentORM.booking_id, DepositPaymentORM.amount)
                    .where(DepositPaymentORM.booking_id.in_(bounded_ids))):
                shares[booking_id] = shares.get(booking_id, ZERO) + money(amount)
    from .receivable_residuals import cash_reserved
    for key, amount in cash_reserved(store, {b.id for b in bookings}).items():
        shares[key] = shares.get(key, ZERO) + amount
    return bookings, allocations, shares


def _candidates(store: Any, tenant_id: str, day: date) -> list[ContractCandidate]:
    candidates = []
    for contract in store.list_contracts():
        if contract.tenant_id != tenant_id or contract.status in NON_BILLABLE_STATUSES:
            continue
        charge = charge_for(store, contract, day)
        candidates.append(ContractCandidate(
            contract_id=contract.id, unit_id=contract.unit_id, start=contract.start_date, end=contract.end_date,
            monthly_due=charge.warm_rent if charge else Decimal("0")))
    return candidates


def mirror_allocation(original_amount: Decimal, original_pairs: Pairs, amount: Decimal) -> Pairs:
    """What a reversal of *amount* credits: the original's contracts in its proportions.

    A partly unassigned original passes on the same unassigned share.
    """
    allocated = sum((share for _, share in original_pairs), ZERO)
    if not original_pairs or allocated == 0 or original_amount == 0:
        return []
    mirrored = cents(amount * allocated / original_amount)
    if mirrored == 0:
        return []
    shares = allocate_cents(mirrored, [abs(share) for _, share in original_pairs])
    return [(contract_id, share) for (contract_id, _), share in zip(original_pairs, shares) if share]


def deposit_shares(store: Any, booking_ids: Iterable[str] | None = None) -> dict[str, Decimal]:
    """The part of each booking a deposit file names (same sign as the booking)."""
    lister = getattr(store, "list_deposit_payments", None)
    if lister is None:
        return {}
    booking_ids = list(booking_ids) if booking_ids is not None else [b.id for b in store.list_bookings()]
    if not booking_ids:
        return {}
    shares: dict[str, Decimal] = defaultdict(lambda: ZERO)
    from .portfolio_scope import scope_context
    # The caller already authorized these cash sources. Hidden deposit links still
    # consume their budget, without exposing a hidden file's identity or fields.
    with scope_context(None):
        for link in lister(booking_ids=booking_ids):
            shares[link.booking_id] += money(link.amount)
    return dict(shares)


def non_rent_shares(store: Any, booking_ids: Iterable[str] | None = None) -> dict[str, Decimal]:
    """The existing deposit shares plus explicit claim settlements, never labelled as deposits."""
    booking_ids = list(booking_ids) if booking_ids is not None else [b.id for b in store.list_bookings()]
    shares = defaultdict(lambda: ZERO, deposit_shares(store, booking_ids))
    from .receivable_residuals import cash_reserved
    for key, amount in cash_reserved(store, booking_ids).items():
        shares[key] += amount
    return dict(shares)


def rent_amount(booking: Any, shares: dict[str, Decimal]) -> Decimal:
    """What of the booking can pay rent: its amount without the deposit share."""
    return money(booking.amount) - shares.get(booking.id, ZERO)


def ensure_allocations_visible(store: Any, booking_id: str) -> list[Any]:
    """A write must not replace the invisible part of a shared cash source."""
    from fastapi import HTTPException

    from .maintenance_rows import Rows
    from .portfolio_scope import scope_context
    visible = store.list_payment_allocations(booking_id=booking_id)
    with scope_context(None):
        complete = Rows.reading(store).find("payment_allocations", booking_id=booking_id)
    if {a.id for a in visible} != {a.id for a in complete}:
        raise HTTPException(403, "Diese Buchung enthält Zuordnungen außerhalb Ihrer Portfolios. Änderungen benötigen Zugriff auf alle betroffenen Verträge.")
    return visible


def _stored_pairs(store: Any, booking_id: str) -> Pairs:
    return [(a.contract_id, money(a.amount)) for a in store.list_payment_allocations(booking_id=booking_id)]


def planned_pairs(store: Any, booking: Any) -> Pairs:
    """The automatic allocation of a booking by the rules (without its deposit share)."""
    if not booking.tenant_id:
        return []
    amount = rent_amount(booking, non_rent_shares(store, [booking.id]))
    if not amount:
        return []
    if booking.reverses_booking_id:
        try:
            original = store.get_booking(booking.reverses_booking_id)
        except NotFoundError:
            return []
        original_amount = rent_amount(original, non_rent_shares(store, [original.id]))
        return mirror_allocation(original_amount, _stored_pairs(store, original.id), amount)
    return suggest_allocation(amount, booking.booking_date, booking.unit_id,
                              _candidates(store, booking.tenant_id, booking.booking_date))


def auto_allocate(store: Any, booking: Any) -> list[Any]:
    """(Re)place the automatic allocations of a booking; manual ones are left as they are."""
    current = ensure_allocations_visible(store, booking.id)
    if booking.reverses_booking_id:
        ensure_allocations_visible(store, booking.reverses_booking_id)
    if any(a.source == "manual" for a in current):
        return current
    for allocation in current:
        store.delete_payment_allocation(allocation.id)
    pairs = planned_pairs(store, booking)
    return [store.create_payment_allocation(PaymentAllocationCreate(
        booking_id=booking.id, contract_id=contract_id, amount=float(amount), source="auto"))
        for contract_id, amount in pairs]


def reallocate_reversals(store: Any, booking: Any) -> None:
    """After a booking's allocations changed: its reversals follow (unless split by hand)."""
    if not booking.tenant_id or booking.reverses_booking_id:
        return
    for reversal in store.list_booking_reversals(booking.id):
        auto_allocate(store, reversal)


def set_allocations(store: Any, booking_id: str, items: Iterable[tuple[str, float]]) -> list[Any]:
    """Replace a booking's allocations by hand; an empty list leaves it unassigned."""
    booking = store.get_booking(booking_id)
    ensure_allocations_visible(store, booking_id)
    wanted = [(contract_id, money(amount)) for contract_id, amount in items if amount]
    tenant_contracts = {c.id for c in store.list_contracts() if c.tenant_id and c.tenant_id == booking.tenant_id}
    for contract_id, amount in wanted:
        if contract_id not in tenant_contracts:
            raise ValidationError("Zuordnen lässt sich nur an Verträge des Mieters der Buchung")
        if (amount > 0) != (money(booking.amount) > 0):
            raise ValidationError("Zuordnungen haben dasselbe Vorzeichen wie die Buchung")
    available = rent_amount(booking, non_rent_shares(store, [booking.id]))
    if abs(sum((amount for _, amount in wanted), ZERO)) > abs(available):
        raise ValidationError("Die Zuordnungen übersteigen den Buchungsbetrag"
                              + (" ohne den Anteil der Kaution" if available != money(booking.amount) else ""))
    for allocation in store.list_payment_allocations(booking_id=booking_id):
        store.delete_payment_allocation(allocation.id)
    created = [store.create_payment_allocation(PaymentAllocationCreate(
        booking_id=booking_id, contract_id=contract_id, amount=float(amount), source="manual"))
        for contract_id, amount in wanted]
    reallocate_reversals(store, booking)
    return created


def allocate_unassigned(store: Any) -> dict:
    """Allocate tenant bookings that have no allocation yet (existing data, imports)."""
    allocated_ids = {a.booking_id for a in store.list_payment_allocations()}
    bookings = store.list_bookings()
    shares = non_rent_shares(store, [b.id for b in bookings])
    done, unclear = 0, []
    # originals first: a reversal follows the allocation of the booking it cancels
    for booking in sorted(bookings, key=lambda b: bool(b.reverses_booking_id)):
        if not booking.tenant_id or booking.id in allocated_ids or not rent_amount(booking, shares):
            continue         # a booking that is all deposit pays no rent
        if auto_allocate(store, booking):
            done += 1
        else:
            unclear.append(booking.id)
    return {"allocated": done, "unassigned": unclear}


def credited_by_tenant(store: Any, tenant_ids: Iterable[str] | None = None,
                       bookings: list[Any] | None = None,
                       until: date | None = None) -> dict[str, list[tuple[Any, str, Decimal]]]:
    """(booking, contract id, amount) per tenant, reading bookings and allocations once.

    Stored allocations count as they are; a booking without any (imported, or
    created before allocations existed) is credited by the same rules on the fly.
    `bookings` are all bookings when the caller has read them already.
    """
    wanted = set(tenant_ids) if tenant_ids is not None else None
    if wanted is not None and not wanted:
        return {}
    sql_selected = wanted is not None and bookings is None and hasattr(store, "db")
    if sql_selected:
        assert wanted is not None
        bookings, allocations, shares = _tenant_payment_rows(store, wanted, until)
        booking_ids = {b.id for b in bookings}
    elif wanted is not None and len(wanted) == 1 and bookings is None:
        # one tenant (account page, settlement): read only their bookings and allocations
        bookings = store.list_bookings(tenant_id=next(iter(wanted)))
        booking_ids = {b.id for b in bookings}
        allocations = []
    else:
        bookings = [b for b in (store.list_bookings() if bookings is None else bookings)
                    if b.tenant_id and (wanted is None or b.tenant_id in wanted)]
        booking_ids = {b.id for b in bookings}
        allocations = []
    if not sql_selected:
        from .maintenance_rows import Rows
        from .portfolio_scope import scope_context
        with scope_context(None):
            allocations = Rows.reading(store).find("payment_allocations", booking_id=booking_ids)
        shares = non_rent_shares(store, booking_ids)
    stored: dict[str, list[Any]] = defaultdict(list)
    for allocation in allocations:
        if allocation.booking_id in booking_ids:
            stored[allocation.booking_id].append(allocation)
    by_id = {b.id: b for b in bookings}
    pairs_of: dict[str, Pairs] = {}
    credited: dict[str, list[tuple[Any, str, Decimal]]] = defaultdict(list)
    candidates: dict[tuple[str, date], list[ContractCandidate]] = {}
    reads = CachedReads(store)     # contracts and rent histories once, not per unassigned payment
    # originals first: a reversal without stored allocations mirrors its original
    for booking in sorted(bookings, key=lambda b: bool(b.reverses_booking_id)):
        if until is not None and booking.booking_date > until:
            continue
        amount = rent_amount(booking, shares)
        if stored[booking.id]:
            pairs = [(a.contract_id, money(a.amount)) for a in stored[booking.id]]
        elif not amount:
            pairs = []           # all of it is a deposit receipt, payout or offset
        elif booking.reverses_booking_id:
            original = by_id.get(booking.reverses_booking_id)
            pairs = mirror_allocation(rent_amount(original, shares), pairs_of.get(original.id, []),
                                      amount) if original is not None else []
        else:
            key = (booking.tenant_id, booking.booking_date)
            if key not in candidates:
                candidates[key] = _candidates(reads, booking.tenant_id, booking.booking_date)
            pairs = suggest_allocation(amount, booking.booking_date, booking.unit_id, candidates[key])
        pairs_of[booking.id] = pairs
        credited[booking.tenant_id] += [(booking, contract_id, amount) for contract_id, amount in pairs]
    return credited


def _credited(store: Any, tenant_id: str) -> list[tuple[Any, str, Decimal]]:
    """(booking, contract id, amount) for one tenant's payments."""
    return credited_by_tenant(store, [tenant_id]).get(tenant_id, [])


def contract_payments(store: Any, contract: Any,
                      credited: list[tuple[Any, str, Decimal]] | None = None,
                      until: Optional[date] = None) -> list[PaymentLine]:
    """Payments credited to a contract (up to *until*); a reversal reduces the payment it
    cancels, any other return the latest earlier payments.

    An account taken over from a previous system (rent_ledger) counts only what was booked from
    its takeover day on, plus the credit carried over; earlier payments are in the carried balance.
    """
    return _contract_cash(store, contract, credited, until)[0]


def _contract_cash(store: Any, contract: Any, credited: list[tuple[Any, str, Decimal]] | None,
                   until: date | None) -> tuple[list[PaymentLine], list[ReceivableLine]]:
    """Remaining receipts and separately dated debt from returns exceeding receipts.

    A return first undoes its original/earlier cash. Its unmatched share is an
    additional claim, rather than silently disappearing when no receipt remains.
    Later cash pays these claims through the same FIFO ledger as ordinary rent.
    """
    if credited is None:
        credited = _credited(store, contract.tenant_id)
    start, _ = takeover(contract)
    # A manual split may contain several shares for the same booking/contract.
    # They form one cash event and, if needed, one claim identified by that booking.
    amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
    bookings = {}
    for booking, contract_id, amount in credited:
        if (contract_id == contract.id and (until is None or booking.booking_date <= until)
                and (start is None or booking.booking_date >= start)):
            amounts[booking.id] += amount
            bookings[booking.id] = booking
    entries = sorted(((booking.booking_date, booking.id, booking.reverses_booking_id,
                       amounts[booking.id], booking.created_at) for booking in bookings.values()),
                     # Bookings have day precision: apply that day's receipts
                     # before returns, with a stable order independent of SQL rows.
                     key=lambda entry: (entry[0], entry[3] < 0, entry[2] is not None, entry[4], entry[1]))
    # Opening credit participates in returns just like an earlier payment. Adding
    # it after processing cash would leave refunded credit available to pay rent.
    lines: list[list[Any]] = [[line.booking_date, line.amount, None]
                             for line in carried_credit(contract, until)]
    returns = []
    for day, booking_id, reverses, amount, _ in entries:
        if amount > 0:
            lines.append([day, amount, booking_id])
            continue
        owed = -amount
        original = [line for line in lines if reverses is not None and line[2] == reverses]
        for line in original + lines[::-1]:
            taken = min(owed, line[1])
            line[1] -= taken
            owed -= taken
            if not owed:
                break
        if owed:
            returns.append(ReceivableLine(
                period_start=day, period_end=day + timedelta(days=1), due_date=day,
                cold_rent=ZERO, service_charge_advance=ZERO, heating_advance=ZERO,
                total_amount=owed, label="Rückzahlung / Rücklastschrift",
                claim_key=f"rent:return:{booking_id}"))
    return [PaymentLine(booking_date=day, amount=amount) for day, amount, _ in lines if amount > 0], returns


def contract_ledger(store: Any, contract: Any, until: date,
                    credited: list[tuple[Any, str, Decimal]] | None = None,
                    steps: list[RentStep] | None = None, *,
                    payments_until: date | None = None) -> tuple[list[ReceivableLine], list[PaymentLine]]:
    """The complete account: rent, opening balance, returns and remaining receipts."""
    payments, returns = _contract_cash(store, contract, credited, payments_until or until)
    return account_receivables(store, contract, until, steps) + [line for line in returns if line.due_date <= until], payments


def tenant_account(store: Any, tenant_id: str, as_of: date) -> dict:
    """Per contract what was due, what was paid and the balance up to *as_of*; plus unassigned payments.

    Payments booked after *as_of* count neither as paid nor as unassigned. An overpayment is the
    contract's credit (``overpaid``); money not credited to any contract is listed apart and does
    not lower any contract's balance.
    """
    store = CachedReads(store)
    contracts = [c for c in store.list_contracts() if c.tenant_id == tenant_id]
    credited = [entry for entry in _credited(store, tenant_id) if entry[0].booking_date <= as_of]
    rows = []
    sums = {"expected": ZERO, "paid": ZERO, "outstanding": ZERO, "overpaid": ZERO}
    for contract in contracts:
        receivables, payments = contract_ledger(store, contract, as_of, credited)
        balance = LeaseEngine.calculate_balance(receivables, payments)
        values = {"expected": balance.expected_total, "paid": balance.paid_total,
                  "outstanding": balance.outstanding_total, "overpaid": balance.overpaid_total}
        for name, value in values.items():
            sums[name] += value
        start, carried = takeover(contract)
        rows.append({"contract_id": contract.id, "contract_number": contract.contract_number,
                     **{name: as_number(value) for name, value in values.items()},
                     # a tenancy taken over from a previous system: its account starts here
                     "ledger_start": start.isoformat() if start else None,
                     "carried_balance": as_number(carried) if start else None})
    allocated: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for booking, _, amount in credited:
        allocated[booking.id] += amount
    own_bookings = [b for b in store.list_bookings(tenant_id=tenant_id) if b.booking_date <= as_of]
    shares = non_rent_shares(store, [b.id for b in own_bookings])
    unassigned, unassigned_total = [], ZERO
    for booking in own_bookings:
        rest = rent_amount(booking, shares) - allocated[booking.id]
        if rest:
            unassigned_total += rest
            unassigned.append({"booking_id": booking.id, "booking_date": booking.booking_date.isoformat(),
                               "amount": as_number(money(booking.amount)), "unassigned": as_number(rest),
                               "payment_text": booking.payment_text})
    totals = {name: as_number(value) for name, value in sums.items()}
    totals["balance"] = as_number(sums["outstanding"] - sums["overpaid"])
    totals["unassigned"] = as_number(unassigned_total)
    deposit_total = sum(deposit_shares(store, [b.id for b in own_bookings]).values(), ZERO)
    return {"tenant_id": tenant_id, "as_of": as_of.isoformat(), "contracts": rows, "totals": totals,
            "paid_total": as_number(sum((money(b.amount) for b in own_bookings), ZERO)),
            "deposit_total": as_number(deposit_total),
            "receivable_settlement_total": as_number(sum(shares.values(), ZERO) - deposit_total),
            "unassigned": unassigned}
