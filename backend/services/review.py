"""Review list: rents and payments that need a person's decision.

- A unit's rent differs from what its running contract owes: someone changed the
  unit expecting the tenant's rent to change. Since the rent lives on the contract
  that needs a rent adjustment (or a manual rent period).
- A contract's history was taken over from today's unit rent although the unit
  was edited during the tenancy (written by the rent history migration).
- A rent adjustment is due but not applied.
- A tenant payment is not (fully) credited to a contract.
- An incoming payment has no tenant (e.g. from a bank statement import).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from ..domain.lease_engine import OCCUPYING_CONTRACT_STATUSES
from .payment_allocations import _credited, _money
from .rent_history import charge_for


def _eur(value: Any) -> str:
    return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def review_items(store: Any, today: date) -> list[dict]:
    items: list[dict] = []
    units = {u.id: u for u in store.list_units()}
    contracts = store.list_contracts()
    tenants = {t.id: t.full_name for t in store.list_tenants()}

    for contract in contracts:
        running = (contract.status in OCCUPYING_CONTRACT_STATUSES and contract.start_date <= today
                   and (contract.end_date is None or contract.end_date >= today))
        unit = units.get(contract.unit_id)
        periods = store.list_contract_rent_periods(contract.id)
        charge = charge_for(store, contract, today)
        if not (running and unit and charge and periods):
            continue
        unit_rent = _money(unit.cold_rent)
        # Raised by applied adjustments only: the unit still holds the starting rent.
        if unit_rent != charge.cold_rent and unit_rent != _money(periods[0].cold_rent):
            items.append({
                "kind": "unit_rent_differs", "severity": "warning",
                "title": f"Miete der Einheit {unit.label} weicht vom Vertrag {contract.contract_number} ab",
                "detail": f"Einheit {_eur(unit.cold_rent or 0)}, Vertrag {_eur(charge.cold_rent)} Kaltmiete. "
                          "Gilt die neue Miete auch für den laufenden Vertrag, bitte als Mietanpassung anwenden.",
                "entity_type": "contract", "entity_id": contract.id, "link": "/rent-adjustments"})
        first = periods[0]
        taken_over = (first.source == "contract_start" and len(periods) == 1
                      and (first.created_at - contract.created_at).days >= 1  # written by the migration
                      and unit.updated_at.date() > contract.start_date)
        if taken_over:
            items.append({
                "kind": "history_taken_over", "severity": "info",
                "title": f"Mietverlauf von {contract.contract_number} aus der heutigen Einheitsmiete übernommen",
                "detail": f"Ab Vertragsbeginn {_day(contract.start_date)} gilt {_eur(first.cold_rent)} Kaltmiete. "
                          "Die Einheit wurde nach Vertragsbeginn geändert; war die Miete anfangs anders, bitte "
                          "den Verlauf mit einer Mietanpassung oder einem manuellen Mietstand korrigieren.",
                "entity_type": "contract", "entity_id": contract.id, "link": "/contracts"})

    numbers = {c.id: c.contract_number for c in contracts}
    for adjustment in store.list_rent_adjustments():
        if adjustment.status == "pending" and adjustment.effective_date <= today:
            items.append({
                "kind": "adjustment_not_applied", "severity": "warning",
                "title": f"Mietanpassung für {numbers.get(adjustment.contract_id, '—')} ist fällig, aber nicht angewendet",
                "detail": f"Wirksam seit {_day(adjustment.effective_date)}: {_eur(adjustment.previous_rent)} → "
                          f"{_eur(adjustment.new_rent)}.",
                "entity_type": "rent_adjustment", "entity_id": adjustment.id, "link": "/rent-adjustments"})

    tenant_ids = {b.tenant_id for b in store.list_bookings() if b.tenant_id}
    for tenant_id in sorted(tenant_ids):
        credited: dict[str, Decimal] = {}
        for booking, _, amount in _credited(store, tenant_id):
            credited[booking.id] = credited.get(booking.id, Decimal("0")) + amount
        for booking in store.list_bookings():
            if booking.tenant_id != tenant_id or booking.booking_date > today:
                continue
            rest = _money(booking.amount) - credited.get(booking.id, Decimal("0"))
            if rest:
                items.append({
                    "kind": "unassigned_payment", "severity": "info",
                    "title": f"Zahlung von {tenants.get(tenant_id, '—')} nicht (ganz) zugeordnet",
                    "detail": f"{_day(booking.booking_date)}: {_eur(booking.amount)}, davon {_eur(rest)} ohne Vertrag"
                              + (f" – „{booking.payment_text}“" if booking.payment_text else ""),
                    "entity_type": "booking", "entity_id": booking.id, "link": f"/tenants/{tenant_id}/account"})

    for booking in store.list_bookings():
        if booking.amount > 0 and not booking.tenant_id and not booking.category_id and booking.booking_date <= today:
            items.append({
                "kind": "payment_without_tenant", "severity": "info",
                "title": "Zahlungseingang ohne Mieter und Kategorie",
                "detail": f"{_day(booking.booking_date)}: {_eur(booking.amount)}"
                          + (f" – „{booking.payment_text}“" if booking.payment_text else ""),
                "entity_type": "booking", "entity_id": booking.id, "link": "/bookings"})
    return items
