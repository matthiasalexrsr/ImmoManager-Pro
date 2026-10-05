"""Credit payments to contracts: automatic suggestion, manual split, accounts per contract."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from ..domain.lease_engine import LeaseEngine, PaymentLine
from ..domain.occupancy import NON_BILLABLE_STATUSES
from ..domain.payment_allocation import ContractCandidate, suggest_allocation
from ..models import PaymentAllocationCreate
from ..storage import ValidationError
from .rent_history import charge_for, rent_steps


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


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


def auto_allocate(store: Any, booking: Any) -> list[Any]:
    """(Re)place the automatic allocations of a booking; manual ones are left as they are."""
    current = store.list_payment_allocations(booking_id=booking.id)
    if any(a.source == "manual" for a in current):
        return current
    for allocation in current:
        store.delete_payment_allocation(allocation.id)
    if not booking.tenant_id:
        return []
    pairs = suggest_allocation(_money(booking.amount), booking.booking_date, booking.unit_id,
                               _candidates(store, booking.tenant_id, booking.booking_date))
    return [store.create_payment_allocation(PaymentAllocationCreate(
        booking_id=booking.id, contract_id=contract_id, amount=float(amount), source="auto"))
        for contract_id, amount in pairs]


def set_allocations(store: Any, booking_id: str, items: Iterable[tuple[str, float]]) -> list[Any]:
    """Replace a booking's allocations by hand; an empty list leaves it unassigned."""
    booking = store.get_booking(booking_id)
    wanted = [(contract_id, _money(amount)) for contract_id, amount in items if amount]
    tenant_contracts = {c.id for c in store.list_contracts() if c.tenant_id and c.tenant_id == booking.tenant_id}
    for contract_id, amount in wanted:
        if contract_id not in tenant_contracts:
            raise ValidationError("Zuordnen lässt sich nur an Verträge des Mieters der Buchung")
        if (amount > 0) != (booking.amount > 0):
            raise ValidationError("Zuordnungen haben dasselbe Vorzeichen wie die Buchung")
    if abs(sum((amount for _, amount in wanted), Decimal("0"))) > abs(_money(booking.amount)):
        raise ValidationError("Die Zuordnungen übersteigen den Buchungsbetrag")
    for allocation in store.list_payment_allocations(booking_id=booking_id):
        store.delete_payment_allocation(allocation.id)
    return [store.create_payment_allocation(PaymentAllocationCreate(
        booking_id=booking_id, contract_id=contract_id, amount=float(amount), source="manual"))
        for contract_id, amount in wanted]


def allocate_unassigned(store: Any) -> dict:
    """Allocate tenant bookings that have no allocation yet (existing data, imports)."""
    allocated_ids = {a.booking_id for a in store.list_payment_allocations()}
    done, unclear = 0, []
    for booking in store.list_bookings():
        if not booking.tenant_id or booking.id in allocated_ids:
            continue
        if auto_allocate(store, booking):
            done += 1
        else:
            unclear.append(booking.id)
    return {"allocated": done, "unassigned": unclear}


def _credited(store: Any, tenant_id: str) -> list[tuple[Any, str, Decimal]]:
    """(booking, contract id, amount) for a tenant's payments.

    Stored allocations count as they are; a booking without any (imported, or
    created before allocations existed) is credited by the same rules on the fly.
    """
    bookings = [b for b in store.list_bookings() if b.tenant_id == tenant_id]
    stored: dict[str, list[Any]] = defaultdict(list)
    for allocation in store.list_payment_allocations():
        stored[allocation.booking_id].append(allocation)
    credited = []
    for booking in bookings:
        if stored[booking.id]:
            credited += [(booking, a.contract_id, _money(a.amount)) for a in stored[booking.id]]
        else:
            pairs = suggest_allocation(_money(booking.amount), booking.booking_date, booking.unit_id,
                                       _candidates(store, tenant_id, booking.booking_date))
            credited += [(booking, contract_id, amount) for contract_id, amount in pairs]
    return credited


def contract_payments(store: Any, contract: Any) -> list[PaymentLine]:
    """Payments credited to a contract; returns reduce the latest earlier payments."""
    entries = sorted(((booking.booking_date, amount) for booking, contract_id, amount
                      in _credited(store, contract.tenant_id) if contract_id == contract.id),
                     key=lambda entry: entry[0])
    lines: list[list[Any]] = []
    for day, amount in entries:
        if amount > 0:
            lines.append([day, amount])
            continue
        owed = -amount
        for line in reversed(lines):
            taken = min(owed, line[1])
            line[1] -= taken
            owed -= taken
            if not owed:
                break
    return [PaymentLine(booking_date=day, amount=amount) for day, amount in lines if amount > 0]


def tenant_account(store: Any, tenant_id: str, as_of: date) -> dict:
    """Per contract what was due, what was paid and the balance; plus unassigned payments."""
    contracts = [c for c in store.list_contracts() if c.tenant_id == tenant_id]
    rows = []
    for contract in contracts:
        receivables = LeaseEngine.build_monthly_receivables(
            contract_start=contract.start_date, contract_end=contract.end_date,
            rent_steps=rent_steps(store, contract), until_including=as_of)
        balance = LeaseEngine.calculate_balance(receivables, contract_payments(store, contract))
        rows.append({"contract_id": contract.id, "contract_number": contract.contract_number,
                     "expected": float(balance.expected_total), "paid": float(balance.paid_total),
                     "outstanding": float(balance.outstanding_total), "overpaid": float(balance.overpaid_total)})
    allocated: dict[str, Decimal] = defaultdict(Decimal)
    for booking, _, amount in _credited(store, tenant_id):
        allocated[booking.id] += amount
    unassigned = []
    for booking in store.list_bookings():
        if booking.tenant_id != tenant_id or booking.booking_date > as_of:
            continue
        rest = _money(booking.amount) - allocated[booking.id]
        if rest:
            unassigned.append({"booking_id": booking.id, "booking_date": booking.booking_date.isoformat(),
                               "amount": float(booking.amount), "unassigned": float(rest),
                               "payment_text": booking.payment_text})
    return {"tenant_id": tenant_id, "as_of": as_of.isoformat(), "contracts": rows,
            "paid_total": float(sum((_money(b.amount) for b in store.list_bookings()
                                     if b.tenant_id == tenant_id and b.booking_date <= as_of), Decimal("0"))),
            "unassigned": unassigned}
