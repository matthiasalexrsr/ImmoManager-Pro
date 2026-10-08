"""Credit payments to contracts: automatic suggestion, manual split, accounts per contract.

A reversal (Storno) is credited to the contracts of the booking it cancels, in that booking's
proportions, and reduces exactly that payment; it is never allocated by the rules on its own.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from ..domain.billing_engine import allocate_cents
from ..domain.lease_engine import LeaseEngine, PaymentLine
from ..domain.money import ZERO, as_number, cents, money
from ..domain.occupancy import NON_BILLABLE_STATUSES
from ..domain.payment_allocation import ContractCandidate, suggest_allocation
from ..models import PaymentAllocationCreate
from ..storage import NotFoundError, ValidationError
from .read_cache import CachedReads
from .rent_history import charge_for, rent_steps

Pairs = list[tuple[str, Decimal]]


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


def _stored_pairs(store: Any, booking_id: str) -> Pairs:
    return [(a.contract_id, money(a.amount)) for a in store.list_payment_allocations(booking_id=booking_id)]


def auto_allocate(store: Any, booking: Any) -> list[Any]:
    """(Re)place the automatic allocations of a booking; manual ones are left as they are."""
    current = store.list_payment_allocations(booking_id=booking.id)
    if any(a.source == "manual" for a in current):
        return current
    for allocation in current:
        store.delete_payment_allocation(allocation.id)
    if not booking.tenant_id:
        return []
    if booking.reverses_booking_id:
        try:
            original = store.get_booking(booking.reverses_booking_id)
        except NotFoundError:
            return []
        pairs = mirror_allocation(money(original.amount), _stored_pairs(store, original.id), money(booking.amount))
    else:
        pairs = suggest_allocation(money(booking.amount), booking.booking_date, booking.unit_id,
                                   _candidates(store, booking.tenant_id, booking.booking_date))
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
    wanted = [(contract_id, money(amount)) for contract_id, amount in items if amount]
    tenant_contracts = {c.id for c in store.list_contracts() if c.tenant_id and c.tenant_id == booking.tenant_id}
    for contract_id, amount in wanted:
        if contract_id not in tenant_contracts:
            raise ValidationError("Zuordnen lässt sich nur an Verträge des Mieters der Buchung")
        if (amount > 0) != (money(booking.amount) > 0):
            raise ValidationError("Zuordnungen haben dasselbe Vorzeichen wie die Buchung")
    if abs(sum((amount for _, amount in wanted), ZERO)) > abs(money(booking.amount)):
        raise ValidationError("Die Zuordnungen übersteigen den Buchungsbetrag")
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
    done, unclear = 0, []
    # originals first: a reversal follows the allocation of the booking it cancels
    for booking in sorted(store.list_bookings(), key=lambda b: bool(b.reverses_booking_id)):
        if not booking.tenant_id or booking.id in allocated_ids:
            continue
        if auto_allocate(store, booking):
            done += 1
        else:
            unclear.append(booking.id)
    return {"allocated": done, "unassigned": unclear}


def credited_by_tenant(store: Any, tenant_ids: Iterable[str] | None = None,
                       bookings: list[Any] | None = None) -> dict[str, list[tuple[Any, str, Decimal]]]:
    """(booking, contract id, amount) per tenant, reading bookings and allocations once.

    Stored allocations count as they are; a booking without any (imported, or
    created before allocations existed) is credited by the same rules on the fly.
    `bookings` are all bookings when the caller has read them already.
    """
    wanted = set(tenant_ids) if tenant_ids is not None else None
    if wanted is not None and len(wanted) == 1:
        # one tenant (account page, settlement): read only their bookings and allocations
        bookings = store.list_bookings(tenant_id=next(iter(wanted)))
        booking_ids = {b.id for b in bookings}
        allocations = store.list_payment_allocations(booking_ids=booking_ids) if booking_ids else []
    else:
        bookings = [b for b in (store.list_bookings() if bookings is None else bookings)
                    if b.tenant_id and (wanted is None or b.tenant_id in wanted)]
        booking_ids = {b.id for b in bookings}
        allocations = store.list_payment_allocations()
    stored: dict[str, list[Any]] = defaultdict(list)
    for allocation in allocations:
        if allocation.booking_id in booking_ids:
            stored[allocation.booking_id].append(allocation)
    by_id = {b.id: b for b in bookings}
    pairs_of: dict[str, Pairs] = {}
    credited: dict[str, list[tuple[Any, str, Decimal]]] = defaultdict(list)
    candidates: dict[tuple[str, date], list[ContractCandidate]] = {}
    # originals first: a reversal without stored allocations mirrors its original
    for booking in sorted(bookings, key=lambda b: bool(b.reverses_booking_id)):
        if stored[booking.id]:
            pairs = [(a.contract_id, money(a.amount)) for a in stored[booking.id]]
        elif booking.reverses_booking_id:
            original = by_id.get(booking.reverses_booking_id)
            pairs = mirror_allocation(money(original.amount), pairs_of.get(original.id, []),
                                      money(booking.amount)) if original is not None else []
        else:
            key = (booking.tenant_id, booking.booking_date)
            if key not in candidates:
                candidates[key] = _candidates(store, booking.tenant_id, booking.booking_date)
            pairs = suggest_allocation(money(booking.amount), booking.booking_date, booking.unit_id, candidates[key])
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
    cancels, any other return the latest earlier payments."""
    if credited is None:
        credited = _credited(store, contract.tenant_id)
    entries = sorted(((booking.booking_date, booking.id, booking.reverses_booking_id, amount)
                      for booking, contract_id, amount in credited
                      if contract_id == contract.id and (until is None or booking.booking_date <= until)),
                     key=lambda entry: entry[0])
    lines: list[list[Any]] = []    # [day, remaining amount, booking id]
    for day, booking_id, reverses, amount in entries:
        if amount > 0:
            lines.append([day, amount, booking_id])
            continue
        owed = -amount
        for line in [line for line in lines if line[2] == reverses] + lines[::-1]:
            taken = min(owed, line[1])
            line[1] -= taken
            owed -= taken
            if not owed:
                break
    return [PaymentLine(booking_date=day, amount=amount) for day, amount, _ in lines if amount > 0]


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
        receivables = LeaseEngine.build_monthly_receivables(
            contract_start=contract.start_date, contract_end=contract.end_date,
            rent_steps=rent_steps(store, contract), until_including=as_of)
        balance = LeaseEngine.calculate_balance(receivables, contract_payments(store, contract, credited))
        values = {"expected": balance.expected_total, "paid": balance.paid_total,
                  "outstanding": balance.outstanding_total, "overpaid": balance.overpaid_total}
        for name, value in values.items():
            sums[name] += value
        rows.append({"contract_id": contract.id, "contract_number": contract.contract_number,
                     **{name: as_number(value) for name, value in values.items()}})
    allocated: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for booking, _, amount in credited:
        allocated[booking.id] += amount
    own_bookings = [b for b in store.list_bookings(tenant_id=tenant_id) if b.booking_date <= as_of]
    unassigned, unassigned_total = [], ZERO
    for booking in own_bookings:
        rest = money(booking.amount) - allocated[booking.id]
        if rest:
            unassigned_total += rest
            unassigned.append({"booking_id": booking.id, "booking_date": booking.booking_date.isoformat(),
                               "amount": as_number(money(booking.amount)), "unassigned": as_number(rest),
                               "payment_text": booking.payment_text})
    totals = {name: as_number(value) for name, value in sums.items()}
    totals["balance"] = as_number(sums["outstanding"] - sums["overpaid"])
    totals["unassigned"] = as_number(unassigned_total)
    return {"tenant_id": tenant_id, "as_of": as_of.isoformat(), "contracts": rows, "totals": totals,
            "paid_total": as_number(sum((money(b.amount) for b in own_bookings), ZERO)),
            "unassigned": unassigned}
