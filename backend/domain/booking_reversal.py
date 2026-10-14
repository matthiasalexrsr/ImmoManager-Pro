"""A reversal (Storno) cancels all or part of one earlier booking.

- It names the booking it reverses (``reverses_booking_id``); that booking is no reversal itself.
- It has the opposite sign and, together with the other reversals of that booking, at most its amount.
- It is on the same account with the same category, property, unit and tenant, and not dated
  before the original: every report attributes it where the original is.
- The link is fixed once booked. A reversed booking keeps its sign, its assignment, a date not
  after its reversals and at least the reversed amount.

Reports net a reversal with its original: it counts on the original's side (income or expense) in
the period of its own date, never as an income or expense of its own (services.finance_ledger).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from .money import money, money_sum

LINKED_FIELDS = ("account_id", "category_id", "property_id", "unit_id", "tenant_id")


def _same_assignment(a: Any, b: Any) -> bool:
    return all((getattr(a, field, None) or None) == (getattr(b, field, None) or None) for field in LINKED_FIELDS)


def reversal_problem(
    booking: Any,
    *,
    existing: Optional[Any],
    original: Optional[Any],
    siblings: Sequence[Any],
    reversals: Sequence[Any],
) -> Optional[str]:
    """Why a booking (new or changed) breaks the reversal rules, or None.

    ``booking`` is the booking as it would be stored, ``existing`` as it is stored now (None
    for a new one), ``original`` the booking it reverses, ``siblings`` the other reversals of
    that original and ``reversals`` the reversals of this booking.
    """
    link = getattr(booking, "reverses_booking_id", None) or None
    if existing is not None and (getattr(existing, "reverses_booking_id", None) or None) != link:
        return "Der Stornobezug einer Buchung lässt sich nicht ändern"
    amount = money(booking.amount)
    if link:
        if original is None:
            return "Die stornierte Buchung existiert nicht"
        if getattr(original, "reverses_booking_id", None):
            return "Eine Stornobuchung lässt sich nicht stornieren"
        if amount * money(original.amount) >= 0:
            return "Ein Storno hat das umgekehrte Vorzeichen der stornierten Buchung"
        if not _same_assignment(booking, original):
            return "Ein Storno gehört zu Konto, Kategorie, Objekt, Einheit und Mieter der stornierten Buchung"
        if booking.booking_date < original.booking_date:
            return "Ein Storno kann nicht vor der stornierten Buchung liegen"
        if abs(amount + money_sum(s.amount for s in siblings)) > abs(money(original.amount)):
            return "Die Stornos übersteigen den Betrag der stornierten Buchung"
    if reversals:
        reversed_total = money_sum(r.amount for r in reversals)
        if amount * reversed_total >= 0 or abs(reversed_total) > abs(amount):
            return (f"Die Buchung ist bereits um {abs(reversed_total):.2f} € storniert; "
                    "Vorzeichen und Betrag müssen das zulassen")
        if not all(_same_assignment(booking, r) for r in reversals):
            return "Eine stornierte Buchung lässt sich nicht umbuchen; bitte Storno löschen oder neu buchen"
        if booking.booking_date > min(r.booking_date for r in reversals):
            return "Eine stornierte Buchung kann nicht nach ihrem Storno liegen"
    return None
