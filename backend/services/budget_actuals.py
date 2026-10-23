"""The actual amount of a budget, taken from the bookings on request.

A budget names booking categories (``booking_category_ids``). Its actual amount from the bookings is
what the bookings of its property in its calendar year with those categories spent: expenses are
negative amounts, so a refund or a reversal (Storno, which carries the category of the booking it
cancels) lowers it. Rent and other tenant bookings never count. Nothing changes on its own: the user
looks at the amount and its bookings and then takes it over (``apply``) or keeps the manual amount.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from ..domain.money import ZERO, as_number, money
from ..models import Budget, BudgetCreate
from ..storage import NotFoundError
from .finance_ledger import FinanceFilter, booking_sources

# income and the owners' own money (category type "private": withdrawals, contributions) are no spending
NOT_SPENDING = ("income", "private")


def validate_categories(store: Any, data: BudgetCreate) -> None:
    """The chosen categories exist, belong to the property's portfolio and are spending categories."""
    if not data.booking_category_ids:
        return
    try:
        portfolio = store.get_property(data.property_id).portfolio_id
    except NotFoundError:
        return  # the store reports the missing property itself
    categories = {c.id: c for c in store.list_categories()}
    for category_id in dict.fromkeys(data.booking_category_ids):
        category = categories.get(category_id)
        if category is None or category.portfolio_id != portfolio:
            raise HTTPException(400, "Eine gewählte Buchungskategorie gibt es im Portfolio der Immobilie nicht.")
        if category.category_type in NOT_SPENDING:
            raise HTTPException(400, f"„{category.name}“ ist keine Ausgabenkategorie und zählt nicht zum Budget.")


def from_bookings(store: Any, budget: Budget) -> dict:
    """The actual amount the bookings give, with the bookings behind it."""
    if not budget.booking_category_ids:
        raise HTTPException(409, "Für dieses Budget sind keine Buchungskategorien gewählt. Bitte im Budget "
                                 "festlegen, welche Kategorien zum Ist zählen.")
    chosen = set(budget.booking_category_ids)
    names = {c.id: c.name for c in store.list_categories()}
    flt = FinanceFilter(date_from=date(budget.year, 1, 1), date_to=date(budget.year, 12, 31),
                        property_id=budget.property_id)
    rows, total = [], ZERO
    for booking in booking_sources(store, flt):
        if booking.category_id not in chosen or booking.tenant_id:
            continue
        spent = -money(booking.amount)
        total += spent
        rows.append({"id": booking.id, "booking_date": booking.booking_date.isoformat(),
                     "category": names.get(booking.category_id, "—"), "amount": as_number(spent),
                     "payment_text": booking.payment_text, "reverses_booking_id": booking.reverses_booking_id})
    return {"budget_id": budget.id, "year": budget.year, "actual_amount": as_number(money(budget.actual_amount)),
            "from_bookings": as_number(total), "difference": as_number(total - money(budget.actual_amount)),
            "categories": [{"id": c, "name": names.get(c, "—")} for c in budget.booking_category_ids],
            "bookings": rows}


def apply(store: Any, budget: Budget, expected: Decimal | None = None) -> Budget:
    """Take the amount from the bookings as the actual amount.

    ``expected`` is the amount the user saw: when bookings changed in between, nothing is saved.
    """
    amount = Decimal(str(from_bookings(store, budget)["from_bookings"]))
    if expected is not None and money(expected) != amount:
        raise HTTPException(409, "Die Buchungen haben sich inzwischen geändert. Bitte den Betrag erneut ansehen.")
    data = BudgetCreate(**{**budget.model_dump(include=set(BudgetCreate.model_fields)), "actual_amount": float(amount)})
    return store.update_budget(budget.id, data)
