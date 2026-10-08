"""Budget, ordered, invoiced and paid of a project, derived; nothing is booked twice.

* ordered  = gross of every order that is not cancelled + its approved change orders
* invoiced = gross of the existing invoices linked to the project's orders, each invoice
             once (the link is unique per invoice), cancelled invoices not counted
* paid     = outgoing bookings allocated to those invoices (invoice_payments). A booking
             pays at most what is left of it after its reversals (Stornos), its allocations
             in the order they were made; an invoice is paid at most up to its gross amount.

All amounts are exact cents (domain.money); `as_number` only at the API boundary.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .money import ZERO, as_number, money


@dataclass(frozen=True)
class OrderFacts:
    id: str
    status: str
    gross: Decimal


@dataclass(frozen=True)
class ChangeFacts:
    order_id: str
    status: str
    gross: Decimal


@dataclass(frozen=True)
class InvoiceFacts:
    id: str
    order_id: str
    status: str
    gross: Decimal


@dataclass(frozen=True)
class AllocationFacts:
    id: str
    invoice_id: str
    booking_id: str
    amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class BookingFacts:
    id: str
    amount: Decimal              # an outgoing payment is negative
    reversed_amount: Decimal     # sum of its reversals (they carry the opposite sign)

    @property
    def available(self) -> Decimal:
        """What the booking can pay: its outflow minus what its reversals took back."""
        return max(-(self.amount + self.reversed_amount), ZERO)


@dataclass
class OrderCosts:
    order_id: str
    status: str
    order_gross: Decimal = ZERO
    approved_changes: Decimal = ZERO
    proposed_changes: Decimal = ZERO
    invoiced: Decimal = ZERO
    paid: Decimal = ZERO

    @property
    def ordered(self) -> Decimal:
        return ZERO if self.status == "cancelled" else self.order_gross + self.approved_changes


@dataclass
class ProjectCosts:
    budget: Decimal | None
    orders: dict[str, OrderCosts] = field(default_factory=dict)
    invoice_paid: dict[str, Decimal] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)

    @property
    def ordered(self) -> Decimal:
        return sum((o.ordered for o in self.orders.values()), ZERO)

    @property
    def proposed_changes(self) -> Decimal:
        return sum((o.proposed_changes for o in self.orders.values() if o.status != "cancelled"), ZERO)

    @property
    def invoiced(self) -> Decimal:
        return sum((o.invoiced for o in self.orders.values()), ZERO)

    @property
    def paid(self) -> Decimal:
        return sum((o.paid for o in self.orders.values()), ZERO)

    def as_json(self) -> dict:
        budget = self.budget
        return {
            "budget": None if budget is None else as_number(budget),
            "ordered": as_number(self.ordered),
            "pending_change_orders": as_number(self.proposed_changes),
            "invoiced": as_number(self.invoiced),
            "paid": as_number(self.paid),
            "open_to_invoice": as_number(self.ordered - self.invoiced),
            "open_to_pay": as_number(self.invoiced - self.paid),
            "remaining_budget": None if budget is None else as_number(budget - self.ordered),
            "orders": [{
                "order_id": o.order_id, "status": o.status, "order_gross": as_number(o.order_gross),
                "approved_change_orders": as_number(o.approved_changes),
                "pending_change_orders": as_number(o.proposed_changes), "ordered": as_number(o.ordered),
                "invoiced": as_number(o.invoiced), "paid": as_number(o.paid),
            } for o in self.orders.values()],
            "invoice_paid": {key: as_number(value) for key, value in self.invoice_paid.items()},
            "warnings": self.warnings,
        }


def effective_allocations(allocations: Iterable[AllocationFacts],
                          bookings: dict[str, BookingFacts]) -> dict[str, Decimal]:
    """How much of each allocation its booking really pays (in the order the allocations were made)."""
    left = {key: booking.available for key, booking in bookings.items()}
    result: dict[str, Decimal] = {}
    for allocation in sorted(allocations, key=lambda a: (a.created_at, a.id)):
        available = left.get(allocation.booking_id, ZERO)
        used = min(money(allocation.amount), available)
        result[allocation.id] = used
        left[allocation.booking_id] = available - used
    return result


def roll_up(budget: float | None, orders: Iterable[OrderFacts], changes: Iterable[ChangeFacts],
            invoices: Iterable[InvoiceFacts], allocations: Iterable[AllocationFacts],
            bookings: dict[str, BookingFacts], invoice_status: dict[str, str] | None = None) -> ProjectCosts:
    """The project's figures. `allocations` holds every allocation of the bookings involved,
    also to invoices of other projects: they decide how much of a booking is left."""
    costs = ProjectCosts(budget=None if budget is None else money(budget))
    for order in orders:
        costs.orders[order.id] = OrderCosts(order.id, order.status, order_gross=money(order.gross))
    for change in changes:
        target = costs.orders.get(change.order_id)
        if target is None:
            continue
        if change.status == "approved":
            target.approved_changes += money(change.gross)
        elif change.status == "proposed":
            target.proposed_changes += money(change.gross)

    allocations = list(allocations)
    effective = effective_allocations(allocations, bookings)
    allocated: dict[str, Decimal] = defaultdict(lambda: ZERO)
    requested: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for allocation in allocations:
        allocated[allocation.invoice_id] += effective[allocation.id]
        requested[allocation.invoice_id] += money(allocation.amount)

    for invoice in invoices:
        target = costs.orders.get(invoice.order_id)
        if target is None:
            continue
        gross = money(invoice.gross)
        paid = min(allocated[invoice.id], max(gross, ZERO))
        costs.invoice_paid[invoice.id] = paid
        target.paid += paid
        if invoice.status != "cancelled":
            target.invoiced += gross
        elif paid > 0:
            costs.warnings.append({"code": "payment_on_cancelled_invoice", "invoice_id": invoice.id,
                                   "message": "Auf eine stornierte Rechnung wurde gezahlt; Erstattung prüfen."})
        if allocated[invoice.id] < requested[invoice.id]:
            costs.warnings.append({"code": "payment_reversed", "invoice_id": invoice.id,
                                   "message": "Eine zugeordnete Zahlung wurde (teilweise) storniert."})
        if allocated[invoice.id] > gross:
            costs.warnings.append({"code": "overpaid_invoice", "invoice_id": invoice.id,
                                   "message": "Der Rechnung ist mehr Zahlung zugeordnet als ihr Bruttobetrag."})
        if (invoice_status or {}).get(invoice.id) == "paid" and paid < gross:
            costs.warnings.append({"code": "marked_paid_without_payment", "invoice_id": invoice.id,
                                   "message": "Die Rechnung ist als bezahlt markiert, aber nicht vollständig "
                                              "durch Buchungen belegt."})

    for entry in costs.orders.values():
        if entry.status != "cancelled" and entry.invoiced > entry.ordered:
            costs.warnings.append({"code": "invoiced_over_ordered", "order_id": entry.order_id,
                                   "message": "Abgerechnet ist mehr als beauftragt (inkl. genehmigter Nachträge)."})
    if costs.budget is not None:
        if costs.ordered > costs.budget:
            costs.warnings.append({"code": "ordered_over_budget",
                                   "message": "Die Beauftragung übersteigt das Budget."})
        if costs.invoiced > costs.budget:
            costs.warnings.append({"code": "invoiced_over_budget",
                                   "message": "Die Rechnungen übersteigen das Budget."})
    return costs
