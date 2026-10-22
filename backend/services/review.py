"""Review list: rents and payments that need a person's decision.

- A unit's rent differs from what its running contract owes: someone changed the
  unit expecting the tenant's rent to change. Since the rent lives on the contract
  that needs a rent adjustment (or a manual rent period).
- A contract's history was taken over from today's unit rent although the unit
  was edited during the tenancy (written by the rent history migration).
- A rent adjustment is due but not applied.
- A tenant payment is not (fully) credited to a contract.
- An incoming payment has no tenant (e.g. from a bank statement import).
- Entries that are allowed but implausible: a deposit above three cold rents (§ 551 BGB),
  a comparative rent increase above the 20 % cap within three years (§ 558 Abs. 3 BGB),
  an adjustment not taking effect on the 1st, a statement period over twelve months
  (§ 556 Abs. 3 BGB), an invoice due before its date, an adjustment lowering the rent,
  an open invoice with a negative amount.
- A running contract without a rent history, or whose history begins after the contract (R12-17, R12-03).
- A tenant's payment in the last days of December without a tax year (§ 11 EStG, R12-14).
- Bank accounts sharing an IBAN (entered before that was refused): their balances count twice.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from ..domain.clock import local_date
from ..domain.lease_engine import OCCUPYING_CONTRACT_STATUSES, charge_on
from ..domain.money import money as _money
from .payment_allocations import credited_by_tenant, non_rent_shares
from .read_cache import CachedReads
from .rent_history import charge_for, rent_change_kinds, rent_steps
from .sepa_rules import compact, mask_iban


def _eur(value: Any) -> str:
    return f"{_money(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _percent(value: Decimal) -> str:
    text = f"{value.quantize(Decimal('0.01'))}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " %"


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def review_items(store: Any, today: date) -> list[dict]:
    store = CachedReads(store)
    items: list[dict] = []
    units = {u.id: u for u in store.list_units()}
    contracts = store.list_contracts()
    tenants = {t.id: t.full_name for t in store.list_tenants()}

    for contract in contracts:
        running = (contract.status in OCCUPYING_CONTRACT_STATUSES and contract.start_date <= today
                   and (contract.end_date is None or contract.end_date >= today))
        unit = units.get(contract.unit_id)
        periods = store.list_contract_rent_periods(contract.id)
        if contract.status in OCCUPYING_CONTRACT_STATUSES and not periods:
            # R12-17: without a history the rent is taken from today's unit rent, also for past months
            items.append({
                "kind": "contract_without_history", "severity": "warning",
                "title": f"Vertrag {contract.contract_number} hat keinen Mietverlauf",
                "detail": "Das Mietsoll wird rückwirkend aus der heutigen Miete der Einheit berechnet. Bitte den "
                          "Mietstand ab Vertragsbeginn erfassen.",
                "entity_type": "contract", "entity_id": contract.id, "link": "/contracts"})
        elif (contract.status in OCCUPYING_CONTRACT_STATUSES
              and periods[0].valid_from > (contract.ledger_start or contract.start_date)):
            # R12-03: the days before the first rent state owe nothing (a takeover owes from its ledger start)
            begins = contract.ledger_start or contract.start_date
            items.append({
                "kind": "history_starts_late", "severity": "warning",
                "title": f"Mietverlauf von {contract.contract_number} beginnt nach dem Vertragsbeginn",
                "detail": f"{'Mietkonto ab' if contract.ledger_start else 'Vertragsbeginn'} {_day(begins)}, erster "
                          f"Mietstand ab {_day(periods[0].valid_from)}: Für die Zeit dazwischen entsteht kein Mietsoll.",
                "entity_type": "contract", "entity_id": contract.id, "link": "/contracts"})
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
        if contract.deposit_amount and _money(contract.deposit_amount) > 3 * _money(first.cold_rent):
            items.append({
                "kind": "deposit_too_high", "severity": "warning",
                "title": f"Kaution von {contract.contract_number} über drei Kaltmieten",
                "detail": f"Kaution {_eur(contract.deposit_amount)}, erlaubt sind höchstens "
                          f"{_eur(3 * _money(first.cold_rent))} (3 × {_eur(first.cold_rent)}, § 551 BGB).",
                "entity_type": "contract", "entity_id": contract.id, "link": "/contracts"})
        taken_over = (first.source == "contract_start" and len(periods) == 1
                      and (first.created_at - contract.created_at).days >= 1  # written by the migration
                      and local_date(unit.updated_at) > contract.start_date)
        if taken_over:
            items.append({
                "kind": "history_taken_over", "severity": "info",
                "title": f"Mietverlauf von {contract.contract_number} aus der heutigen Einheitsmiete übernommen",
                "detail": f"Ab Vertragsbeginn {_day(contract.start_date)} gilt {_eur(first.cold_rent)} Kaltmiete. "
                          "Die Einheit wurde nach Vertragsbeginn geändert; war die Miete anfangs anders, bitte "
                          "den Verlauf mit einer Mietanpassung oder einem manuellen Mietstand korrigieren.",
                "entity_type": "contract", "entity_id": contract.id, "link": "/contracts"})

    numbers = {c.id: c.contract_number for c in contracts}
    by_id = {c.id: c for c in contracts}
    for adjustment in store.list_rent_adjustments():
        if adjustment.status == "rejected":
            continue
        number = numbers.get(adjustment.contract_id, "—")
        if adjustment.status == "pending" and adjustment.effective_date.day != 1:
            items.append({
                "kind": "adjustment_mid_month", "severity": "warning",
                "title": f"Mietanpassung für {number} nicht zum Monatsersten",
                "detail": f"Wirksam ab {_day(adjustment.effective_date)}; Mieten ändern sich zum 1. eines Monats.",
                "entity_type": "rent_adjustment", "entity_id": adjustment.id, "link": "/rent-adjustments"})
        if adjustment.status == "pending" and adjustment.previous_rent and adjustment.new_rent < adjustment.previous_rent:
            items.append({
                "kind": "rent_decrease", "severity": "warning",
                "title": f"Mietanpassung für {number} senkt die Miete",
                "detail": f"{_eur(adjustment.previous_rent)} → {_eur(adjustment.new_rent)} "
                          f"({(adjustment.new_rent / adjustment.previous_rent - 1) * 100:.1f} %). Ist das gewollt "
                          "oder ein Tippfehler?",
                "entity_type": "rent_adjustment", "entity_id": adjustment.id, "link": "/rent-adjustments"})
        contract = by_id.get(adjustment.contract_id)
        if contract is None or adjustment.adjustment_type not in ("comparative", "mietspiegel", "increase"):
            continue
        steps = rent_steps(store, contract)
        base_day = max(contract.start_date, adjustment.effective_date - timedelta(days=3 * 365))
        earlier = charge_on(steps, base_day)
        # increases after modernization (§ 559) and operating-cost changes (§ 560) do not count (R12-16)
        excluded = sum((after.charge.cold_rent - before.charge.cold_rent
                        for before, after, kind in zip(steps, steps[1:], rent_change_kinds(store, contract)[1:])
                        if kind and base_day < after.valid_from <= adjustment.effective_date), Decimal("0"))
        if (earlier and earlier.cold_rent > 0
                and _money(adjustment.new_rent) - excluded > earlier.cold_rent * Decimal("1.2")):
            items.append({
                "kind": "increase_over_cap", "severity": "warning",
                "title": f"Mieterhöhung für {number} über der Kappungsgrenze",
                "detail": f"{_eur(earlier.cold_rent)} → {_eur(adjustment.new_rent)} innerhalb von drei Jahren "
                          f"(+{(adjustment.new_rent / float(earlier.cold_rent) - 1) * 100:.1f} %); erlaubt sind höchstens "
                          "20 %, in angespannten Märkten 15 % (§ 558 Abs. 3 BGB).",
                "entity_type": "rent_adjustment", "entity_id": adjustment.id, "link": "/rent-adjustments"})

    for period in store.list_billing_periods():
        if (period.end_date - period.start_date).days > 366:
            items.append({
                "kind": "statement_period_too_long", "severity": "warning",
                "title": f"Abrechnungszeitraum „{period.label}“ länger als zwölf Monate",
                "detail": f"{_day(period.start_date)} – {_day(period.end_date)}; nach § 556 Abs. 3 BGB höchstens "
                          "zwölf Monate.",
                "entity_type": "billing_period", "entity_id": period.id, "link": "/statements"})

    for invoice in store.list_invoices():
        if invoice.gross_amount < 0 and invoice.status != "paid":
            items.append({
                "kind": "invoice_negative", "severity": "info",
                "title": f"Rechnung {invoice.invoice_number or invoice.supplier} mit negativem Betrag",
                "detail": f"{_eur(invoice.gross_amount)}: eine Gutschrift? Dann bitte als Gutschrift vermerken, "
                          "sonst den Betrag prüfen.",
                "entity_type": "invoice", "entity_id": invoice.id, "link": "/invoices"})
        if invoice.due_date and invoice.due_date < invoice.invoice_date:
            items.append({
                "kind": "invoice_due_before_date", "severity": "info",
                "title": f"Rechnung {invoice.invoice_number or invoice.supplier} fällig vor Rechnungsdatum",
                "detail": f"Rechnungsdatum {_day(invoice.invoice_date)}, fällig {_day(invoice.due_date)}.",
                "entity_type": "invoice", "entity_id": invoice.id, "link": "/invoices"})

    for adjustment in store.list_rent_adjustments():
        if adjustment.status == "pending" and adjustment.effective_date <= today:
            items.append({
                "kind": "adjustment_not_applied", "severity": "warning",
                "title": f"Mietanpassung für {numbers.get(adjustment.contract_id, '—')} ist fällig, aber nicht angewendet",
                "detail": f"Wirksam seit {_day(adjustment.effective_date)}: {_eur(adjustment.previous_rent)} → "
                          f"{_eur(adjustment.new_rent)}.",
                "entity_type": "rent_adjustment", "entity_id": adjustment.id, "link": "/rent-adjustments"})

    same_iban: dict[str, list[Any]] = {}
    for account in store.list_accounts():
        if compact(account.iban):
            same_iban.setdefault(compact(account.iban), []).append(account)
    for iban, accounts in same_iban.items():
        if len(accounts) > 1:
            names = ", ".join(f"„{a.name}“" for a in accounts)
            items.append({
                "kind": "duplicate_iban", "severity": "warning",
                "title": f"{len(accounts)} Konten mit derselben IBAN: {names}",
                "detail": f"IBAN {mask_iban(iban)}: Ein Bankkonto ist mehrfach angelegt, sein Saldo zählt mehrfach. "
                          "Buchungen auf ein Konto umbuchen und die übrigen löschen.",
                "entity_type": "account", "entity_id": accounts[0].id, "link": "/accounts"})

    # owners: a property with shares whose money partly belongs to nobody recorded (services.ownership)
    from .ownership import Ownership

    ownership = Ownership(store)
    if ownership.recorded:
        units_of: dict[str, list[Any]] = {}
        for unit in store.list_units():
            units_of.setdefault(unit.property_id, []).append(unit)
        for prop in store.list_properties():
            if not ownership.has_shares(prop.id):
                continue
            gaps = [(unit.label, ownership.weights(prop.id, unit.id, today).get(None, Decimal("0")))
                    for unit in sorted(units_of.get(prop.id, []), key=lambda u: u.label or "")]
            gaps = [(label, rest) for label, rest in gaps if rest > 0]
            whole = ownership.weights(prop.id, None, today).get(None, Decimal("0"))
            if gaps or whole > 0:
                parts = [f"{label}: {_percent(rest)} ohne Eigentümer" for label, rest in gaps]
                if whole > 0 and not gaps:
                    parts.append(f"das Objekt: {_percent(whole)} ohne Eigentümer")
                items.append({
                    "kind": "ownership_incomplete", "severity": "warning",
                    "title": f"Eigentumsanteile von {prop.name} unvollständig",
                    "detail": "Heute gehören " + "; ".join(parts) + ". Dieser Teil fehlt in den Berichten je "
                              "Eigentümer und steht dort unter „Ohne Eigentümer“.",
                    "entity_type": "property", "entity_id": prop.id, "link": f"/properties/{prop.id}"})

    bookings = store.list_bookings()
    credited: dict[str, Decimal] = {}
    for rows in credited_by_tenant(store, bookings=bookings).values():
        for booking, _, amount in rows:
            credited[booking.id] = credited.get(booking.id, Decimal("0")) + amount
    for booking_id, share in non_rent_shares(store, [b.id for b in bookings]).items():
        credited[booking_id] = credited.get(booking_id, Decimal("0")) + share
    # a reversal is decided with the booking it cancels: their rests and amounts add up
    reversed_amount: dict[str, Decimal] = {}
    reversed_rest: dict[str, Decimal] = {}
    known = {b.id for b in bookings}
    for booking in bookings:
        if booking.reverses_booking_id in known and booking.booking_date <= today:
            original = booking.reverses_booking_id
            reversed_amount[original] = reversed_amount.get(original, Decimal("0")) + _money(booking.amount)
            reversed_rest[original] = (reversed_rest.get(original, Decimal("0")) + _money(booking.amount)
                                       - credited.get(booking.id, Decimal("0")))
    # grouped by tenant, in booking order within each tenant
    for booking in sorted((b for b in bookings if b.tenant_id), key=lambda b: b.tenant_id):
        if booking.booking_date > today or booking.reverses_booking_id in known:
            continue
        rest = (_money(booking.amount) - credited.get(booking.id, Decimal("0"))
                + reversed_rest.get(booking.id, Decimal("0")))
        if rest:
            items.append({
                "kind": "unassigned_payment", "severity": "info",
                "title": f"Zahlung von {tenants.get(booking.tenant_id, '—')} nicht (ganz) zugeordnet",
                "detail": f"{_day(booking.booking_date)}: {_eur(booking.amount)}, davon {_eur(rest)} ohne Vertrag"
                          + (f" – „{booking.payment_text}“" if booking.payment_text else ""),
                "entity_type": "booking", "entity_id": booking.id,
                "link": f"/bookings?booking_id={quote(booking.id, safe='')}"})

    for booking in bookings:
        day = booking.booking_date
        # R12-14: a tenant's payment in the last days of December is often the January rent
        if (booking.tenant_id and booking.amount > 0 and booking.tax_year is None and not booking.reverses_booking_id
                and (day.month, day.day) >= (12, 22) and day.year >= today.year - 1 and day <= today):
            items.append({
                "kind": "turn_of_year_payment", "severity": "info",
                "title": f"Zahlung von {tenants.get(booking.tenant_id, '—')} am {_day(day)}: Steuerjahr prüfen",
                "detail": f"{_eur(booking.amount)}. Ist das die Januarmiete, gehört sie steuerlich ins Jahr {day.year + 1} "
                          "(§ 11 Abs. 1 Satz 2 EStG): bitte in der Buchung das Steuerjahr eintragen, sonst das Jahr "
                          "des Buchungsdatums.",
                "entity_type": "booking", "entity_id": booking.id,
                "link": f"/bookings?booking_id={quote(booking.id, safe='')}"})
        if (booking.amount > 0 and not booking.tenant_id and not booking.category_id and booking.booking_date <= today
                and not booking.reverses_booking_id
                and _money(booking.amount) + reversed_amount.get(booking.id, Decimal("0"))):
            items.append({
                "kind": "payment_without_tenant", "severity": "info",
                "title": "Zahlungseingang ohne Mieter und Kategorie",
                "detail": f"{_day(booking.booking_date)}: {_eur(booking.amount)}"
                          + (f" – „{booking.payment_text}“" if booking.payment_text else ""),
                "entity_type": "booking", "entity_id": booking.id,
                "link": f"/bookings?booking_id={quote(booking.id, safe='')}"})
    return items
