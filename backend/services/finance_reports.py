"""Version 2 performance and forecast reports; one definition for every output."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from ..domain.billing_engine import allocate_cents
from ..domain.lease_engine import ChargeConfig, LeaseEngine, RentStep, charge_on
from ..domain.money import ZERO, money
from ..domain.occupancy import NON_BILLABLE_STATUSES
from ..finance_models import ReportDefinition, SavedReport, SaveReport
from ..storage import NotFoundError
from .finance_ledger import (
    Dimensions,
    FinanceFilter,
    add_months,
    booking_side,
    booking_sources,
    month_end,
    month_key,
    month_start,
    months_between,
    validate_filter,
)
from .maintenance_projects import work
from .maintenance_rows import Rows
from .receivable_residuals import ResidualReader, digest
from .rent_history import rent_steps


def validate_scope(store, definition):
    validate_filter(store, _filter(definition), require_visible=True)
    dims = Dimensions(store, _filter(definition))
    for unit_id in definition.vacant_unit_ids:
        if not dims.unit_record_matches(store.get_unit(unit_id)):
            raise HTTPException(422, "Eine als leerstehend gewählte Einheit liegt außerhalb des Berichtsfilters.")
    if definition.date_from and definition.date_to and definition.date_from > definition.date_to:
        raise HTTPException(422, "Der Berichtszeitraum beginnt nach seinem Ende.")
    if definition.kind == "performance-period-v2":
        first = definition.date_from or date(definition.as_of.year, 1, 1)
        last = definition.date_to or date(definition.as_of.year, 12, 31)
        if first > last:
            raise HTTPException(422, "Der Berichtszeitraum beginnt nach seinem Ende (einschließlich der Jahresvorgaben).")
        if definition.date_from and definition.date_from.day != 1:
            raise HTTPException(422, "Das Leistungsperiodenergebnis v2 beginnt am ersten Tag eines Kalendermonats.")
        if definition.date_to and definition.date_to != month_end(definition.date_to):
            raise HTTPException(422, "Das Leistungsperiodenergebnis v2 endet am letzten Tag eines Kalendermonats.")
    identities = [f.identity for f in definition.planned_flows]
    if len(identities) != len(set(identities)):
        raise HTTPException(422, "Eine geplante Quelle darf nur einmal vorkommen.")


def _filter(d):
    return FinanceFilter(portfolio_id=d.portfolio_id, property_id=d.property_id, unit_id=d.unit_id)


def invoice_scope_amount(store, invoice, amount, flt, period_start, period_end):
    """One invoice identity, projected through its project or weighted contract locations."""
    rows, dims = Rows.reading(store), Dimensions(store, flt)
    project = rows.find("maintenance_order_invoices", invoice_id=invoice.id)
    if project:
        case = rows.get("maintenance_cases", project[0].case_id)
        return amount if case and dims.matches(case.property_id, case.unit_id) else ZERO
    linked = rows.find("service_contract_invoices", invoice_id=invoice.id)
    if linked:
        from ..domain.service_contract_finance import active_in
        from .portfolio_scope import scope_context
        # Hidden locations must retain their budget share, without disclosing their names/IDs.
        with scope_context(None):
            locations = rows.find("service_contract_locations", service_contract_id=linked[0].service_contract_id)
        locations = sorted([loc for loc in locations if active_in(loc, period_start, period_end)], key=lambda loc: loc.id)
        if locations:
            portions = allocate_cents(amount, [Decimal(str(loc.share_weight)) for loc in locations])
            visible = {p.id for p in store.list_properties()}
            return sum((part for loc, part in zip(locations, portions) if loc.property_id in visible and dims.matches(loc.property_id, loc.unit_id)), ZERO)
    return amount if not flt.unit_id and dims.matches(invoice.property_id) else ZERO


def location_amount(store, contract_id, amount, flt, day):
    from ..domain.service_contract_finance import active_in
    from .portfolio_scope import scope_context
    rows, dims = Rows.reading(store), Dimensions(store, flt)
    with scope_context(None):
        locations = rows.find("service_contract_locations", service_contract_id=contract_id)
    locations = sorted([loc for loc in locations if active_in(loc, day, day)], key=lambda loc: loc.id)
    if not locations:
        return ZERO
    portions = allocate_cents(amount, [Decimal(str(loc.share_weight)) for loc in locations])
    visible = {p.id for p in store.list_properties()}
    return sum((part for loc, part in zip(locations, portions) if loc.property_id in visible and dims.matches(loc.property_id, loc.unit_id)), ZERO)


def cash(store, d):
    """The canonical cash calculation, with the exact bookings behind its rows."""
    from .report_service import compute_cashflow
    applied = _filter(d).with_period(d.date_from, d.date_to or d.as_of)
    calculated = compute_cashflow(store, applied, decimal_strings=True)
    dimensions = Dimensions(store, applied)
    selected = booking_sources(store, applied)
    selected_property = d.property_id or dimensions.unit_property(d.unit_id)
    selected_portfolio = d.portfolio_id or dimensions.property_portfolio(selected_property)
    if selected_portfolio:
        portfolio_currencies = {portfolio.id: portfolio.currency for portfolio in store.list_portfolios()}
        expected_currency = portfolio_currencies[selected_portfolio]
        accounts = {account.id: account for account in store.list_accounts()}
        for booking in selected:
            source_currency = portfolio_currencies[accounts[booking.account_id].portfolio_id]
            if source_currency != expected_currency:
                raise HTTPException(422, "Die Buchungsquelle hat eine andere Währung als der gewählte Immobilienbestand.")
    categories = {category.id: category.category_type for category in store.list_categories()}
    sources = [{"identity": "booking:" + booking.id, "day": booking.booking_date.isoformat(),
                "month": month_key(booking.booking_date), "amount": str(money(booking.amount)),
                "label": booking.payment_text or "Buchung " + booking.booking_date.isoformat(),
                "side": booking_side(categories.get(booking.category_id), booking),
                "url": "/bookings?booking_id=" + booking.id, "basis": "Buchungsdatum"}
               for booking in selected]
    actual_first = applied.date_from or (selected[0].booking_date if selected else None)
    return {"filters": applied.with_period(actual_first, applied.date_to).echo(),
            "monthly": [{"month": row["month"], **{key: str(money(row[key])) for key in ("income", "expense", "net")}}
                        for row in calculated["monthly"]],
            "totals": {key: str(money(calculated[key + "Total"])) for key in ("income", "expense", "net")},
            "sources": sorted(sources, key=lambda source: (source["day"], source["identity"])), "warnings": []}


def performance(store, d):
    from .invoice_review import flows
    from .report_service import rent_due_by_month
    flt = _filter(d)
    first = d.date_from or date(d.as_of.year, 1, 1)
    last = d.date_to or date(d.as_of.year, 12, 31)
    months = months_between(first, last)
    applied = flt.with_period(first, last)
    dims, rows = Dimensions(store, flt), Rows.reading(store)
    rent = rent_due_by_month(store, flt, first, last)
    values = {month_key(m): {"rent_due": rent.get(month_key(m), ZERO), "other_income": ZERO, "costs": ZERO} for m in months}
    sources, warnings = [], []
    # Warm contractual rent already includes agreed advances. A finalized utility
    # difference adjusts those advances to the actual attributable cost, once.
    from .final_statements import FINAL_STATUSES
    periods = {p.id: p for p in store.list_billing_periods() if p.status in FINAL_STATUSES}
    superseded = {p.corrects_period_id for p in periods.values() if p.corrects_period_id}
    contracts = {c.id: c for c in store.list_contracts()}
    for statement in store.list_utility_statements():
        period = periods.get(statement.billing_period_id)
        contract = contracts.get(statement.contract_id)
        if not period or period.id in superseded or not contract or not dims.contract_matches(contract):
            continue
        start, end = statement.usage_start or period.start_date, statement.usage_end or period.end_date
        span = months_between(start, end)
        shares = allocate_cents(money(statement.balance), [Decimal((min(month_end(m), end) - max(m, start)).days + 1) for m in span])
        for m, share in zip(span, shares):
            key = month_key(m)
            if key in values:
                values[key]["other_income"] += share
                sources.append({"identity": "utility-statement:" + statement.id, "month": key, "amount": str(share), "contribution": "other_income",
                                "url": "/statements?period_id=" + period.id, "basis": "Finale Abrechnungsdifferenz zu Sollvorauszahlungen"})
    for contract in contracts.values():
        if contract.status in NON_BILLABLE_STATUSES or not dims.contract_matches(contract):
            continue
        # as in rent_due_by_month: a tenancy that ended before the period owes nothing in it
        if contract.start_date > last or (contract.end_date and contract.end_date < max(first, contract.start_date)):
            continue
        for line in LeaseEngine.build_monthly_receivables(contract_start=max(first, contract.start_date),
                contract_end=contract.end_date, rent_steps=rent_steps(store, contract), until_including=last):
            if month_key(line.period_start) in values:
                sources.append({"identity": "rent:" + contract.id + ":" + month_key(line.period_start),
                                "month": month_key(line.period_start), "amount": str(line.total_amount), "contribution": "rent_due",
                                "url": "/contracts?contract_id=" + contract.id, "basis": "Sollwarmmiete einschließlich Vorauszahlungen"})
    invoices = store.list_invoices()
    reviewed = flows(rows, invoices)
    links = {link.invoice_id: link for link in rows.find("service_contract_invoices", invoice_id=[i.id for i in invoices])}
    identified: dict[str, Decimal] = defaultdict(lambda: ZERO)
    # Reserve each linked cash share only once, regardless of project/contract paths.
    allocations = [("invoice_payments", p) for p in rows.find("invoice_payments")]
    allocations += [("service_contract_payments", p) for p in rows.find("service_contract_payments")]
    bookings_by_id = {b.id: b for b in store.list_bookings()}
    for table, p in allocations:
        booking = bookings_by_id.get(p.booking_id)
        if booking:
            sign = Decimal(1) if money(booking.amount) < 0 else Decimal(-1)
            available = max(abs(money(booking.amount)) - abs(identified[p.booking_id]), ZERO)
            identified[p.booking_id] += min(abs(money(p.amount)), available) * sign
    for invoice in invoices:
        link = links.get(invoice.id)
        start = invoice.performance_start or (link.period_start if link else invoice.invoice_date)
        end = invoice.performance_end or (link.period_end if link else invoice.invoice_date)
        amount = reviewed.get(invoice.id, ("legacy", money(invoice.gross_amount)))[1]
        amount = invoice_scope_amount(store, invoice, amount, flt, start, end)
        if not amount:
            continue
        if bool(invoice.performance_start) != bool(invoice.performance_end) or end < start:
            raise HTTPException(409, "Ungültiger Leistungszeitraum bei Rechnung " + invoice.id)
        if end < first or start > last:
            continue
        if not invoice.performance_start and not link:
            warnings.append({"source": "invoice:" + invoice.id, "message": "Leistungszeitraum fehlt; Rechnungsdatum verwendet."})
        period_months = months_between(start, end)
        days = [(min(month_end(m), end) - max(m, start)).days + 1 for m in period_months]
        shares = allocate_cents(amount, [Decimal(n) for n in days])
        for m, share in zip(period_months, shares):
            key = month_key(m)
            if key in values:
                values[key]["costs"] += share
                sources.append({"identity": "invoice:" + invoice.id, "month": key, "amount": str(share), "contribution": "costs",
                                "url": "/invoice-review/" + invoice.id, "basis": "Leistung"})
    categories = {c.id: c.category_type for c in store.list_categories()}
    # Unlinked cash remains an explicitly labelled fallback. Never add invoice-paid cash twice.
    bookings = store.list_bookings()
    reverses = {b.id: b for b in bookings}
    booking_dimensions = Dimensions(store, applied)
    for b in bookings:
        if not booking_dimensions.booking_matches(b) or b.tenant_id:
            continue
        amount = money(b.amount)
        identified_amount = identified.get(b.id, ZERO)
        if b.reverses_booking_id:
            original = reverses.get(b.reverses_booking_id)
            if original and money(original.amount):
                identified_amount = -identified.get(original.id, ZERO) * abs(amount / money(original.amount))
        # outgoing supplier allocation amounts are positive; cash amounts are negative
        amount += identified_amount
        if not amount:
            continue
        side = booking_side(categories.get(b.category_id), b)
        key = month_key(b.booking_date)
        field = "costs" if side == "expense" else "other_income"
        contribution = -amount if side == "expense" else amount
        values[key][field] += contribution
        sources.append({"identity": "booking:" + b.id, "month": key, "amount": str(contribution), "contribution": field,
                        "url": "/bookings?booking_id=" + b.id, "basis": "Buchungsdatum (ohne Leistungsbeleg)"})
    monthly = []
    for key, value in values.items():
        value["result"] = value["rent_due"] + value["other_income"] - value["costs"]
        monthly.append({"month": key, **{k: str(money(v)) for k, v in value.items()}})
    return {"monthly": monthly, "sources": sources, "warnings": warnings,
            "totals": {key: str(sum((money(row[key]) for row in monthly), ZERO))
                       for key in ("rent_due", "other_income", "costs", "result")}}


def forecast(store, d):
    from .invoice_review import settlements
    from .report_service import current_balance
    flt, rows = _filter(d), Rows.reading(store)
    dims = Dimensions(store, flt)
    first, last = month_start(d.as_of), month_end(add_months(month_start(d.as_of), d.months - 1))
    events: dict[str, dict[str, Any]] = {}
    warnings = []

    def event(identity, day, amount, label, url="", priority=0):
        if day <= d.as_of:
            return
        if d.as_of < day <= last and (identity not in events or priority > events[identity]["priority"]):
            events[identity] = {"identity": identity, "day": day.isoformat(), "amount": str(money(amount)),
                                "label": label, "url": url, "priority": priority}

    contracts = [c for c in store.list_contracts() if dims.contract_matches(c) and c.status not in NON_BILLABLE_STATUSES]
    adjustments = store.list_rent_adjustments()
    for c in contracts:
        steps = rent_steps(store, c)
        for a in sorted(adjustments, key=lambda a: (a.effective_date, a.id)):
            if a.contract_id == c.id and a.status == "pending":
                prior = charge_on(steps, a.effective_date)
                if prior:
                    steps = [s for s in steps if s.valid_from != a.effective_date] + [RentStep(a.effective_date,
                        ChargeConfig(money(a.new_rent), prior.service_charge_advance, prior.heating_advance))]
        from .payment_allocations import contract_ledger
        claims, payments = contract_ledger(store, c, last, steps=steps, payments_until=d.as_of)
        settled_rent = LeaseEngine.build_settlement_report(claims, payments, today=d.as_of)
        arrears = ZERO
        for line in settled_rent:
            m = month_start(line.period_start)
            day = max(line.period_start, m.replace(day=min(d.rent_payment_day, month_end(m).day)))
            if day <= d.as_of:
                arrears += line.outstanding_amount
                continue
            if c.unit_id in d.vacant_unit_ids:
                continue
            event("rent:" + c.id + ":" + month_key(m), day,
                  money(line.outstanding_amount * d.rent_collection_percent / 100), "Erwartete Miete " + c.contract_number,
                  "/contracts?contract_id=" + c.id)
        if arrears and d.arrears_collection_percent:
            event("rent-arrears:" + c.id, add_months(d.as_of, 1), money(arrears * d.arrears_collection_percent / 100),
                  "Erwarteter Eingang Mietrückstand " + c.contract_number, "/contracts?contract_id=" + c.id)
    # Future bookings have higher priority than an expectation of the same identified event.
    bills = store.list_invoices()
    service_bills = rows.find("service_contract_invoices")
    from ..domain.service_contract_finance import planned_instalments
    from ..domain.service_contract_terms import Terms
    for contract in store.list_service_contracts():
        tariffs = store.list_service_contract_tariffs(contract.id)
        for instalment in planned_instalments(tariffs, contract.start_date, Terms.of(contract).effective_end,
                                              d.as_of + timedelta(days=1), last):
            # A concrete regular invoice replaces the tariff expectation for that period.
            if any(link.service_contract_id == contract.id and link.kind == "regular" and
                   link.period_start <= instalment.due_date <= link.period_end for link in service_bills):
                continue
            amount = location_amount(store, contract.id, instalment.amount, flt, instalment.due_date)
            event("service-instalment:" + contract.id + ":" + month_key(instalment.due_date), instalment.due_date,
                  -amount, "Abschlag " + contract.title, "/service-contracts/" + contract.id)
    settled = settlements(rows, bills, d.as_of)
    for i in bills:
        s = settled[i.id]
        if s.open > 0 and i.status not in ("cancelled", "rejected"):
            link = next((link for link in service_bills if link.invoice_id == i.id), None)
            outstanding = s.open - (money(link.advances_credited) if link else ZERO)
            amount = invoice_scope_amount(store, i, outstanding, flt, i.performance_start or i.invoice_date, i.performance_end or i.invoice_date)
            event("invoice:" + i.id, max(s.due_on or i.due_date or i.invoice_date, d.as_of + timedelta(days=1)), -amount,
                  "Rechnung " + i.supplier, "/invoice-review/" + i.id)
    allocations = rows.find("invoice_payments")
    contract_bills = {b.id: b.invoice_id for b in rows.find("service_contract_invoices")}
    for p in rows.find("service_contract_payments"):
        if p.service_contract_invoice_id in contract_bills:
            allocations.append(SimpleNamespace(invoice_id=contract_bills[p.service_contract_invoice_id], booking_id=p.booking_id, amount=p.amount))
    by_booking = defaultdict(list)
    service_payments = rows.find("service_contract_payments")
    for p in allocations:
        by_booking[p.booking_id].append((p.invoice_id, money(p.amount)))
    def reduce_expected(identity, amount):
        entry = events.get(identity)
        if entry:
            current = money(entry["amount"])
            rest = max(abs(current) - abs(amount), ZERO)
            entry["amount"] = str(rest if current >= 0 else -rest)
    for b in store.list_bookings():
        if not d.as_of < b.booking_date <= last or not dims.booking_matches(b):
            continue
        identity = "booking:" + b.id
        # Explicit invoice identity wins; a single cash booking can pay several bills.
        for invoice_id, amount in by_booking.get(b.id, []):
            reduce_expected("invoice:" + invoice_id, amount)
        pairs = store.list_payment_allocations(booking_id=b.id)
        for p in pairs:
            reduce_expected("rent:" + p.contract_id + ":" + month_key(b.booking_date), money(p.amount))
        for p in service_payments:
            if p.booking_id == b.id and not p.service_contract_invoice_id:
                reduce_expected("service-instalment:" + p.service_contract_id + ":" + month_key(b.booking_date), money(p.amount))
        event(identity, b.booking_date, money(b.amount), b.payment_text or "Geplante Buchung", "/bookings?booking_id=" + b.id, 2)
    residual_reader = ResidualReader(store)
    for r in store.list_receivables():
        c = next((c for c in contracts if c.id == r.contract_id), None)
        if not c:
            continue
        state = residual_reader.read(r, d.as_of)
        if state["unresolved_legacy"]:
            warnings.append({"source": "receivable:" + r.id, "message": "Ungeklärter Altbestand wird nicht als Zahlung prognostiziert."})
            continue
        amount = money(state["residual"])
        if r.due_date <= d.as_of:
            amount = money(amount * d.arrears_collection_percent / 100)
            due = min(last, add_months(d.as_of, 1))
        else:
            due = r.due_date
        event("receivable:" + r.id, due, amount, "Forderungsrest", "/receivables?contract_id=" + c.id)
    for f in d.planned_flows:
        event(f.identity, f.day, f.amount, f.label, priority=3)
    balance = current_balance(store, flt, d.as_of)
    opening = balance
    monthly = []
    for m in months_between(first, last):
        selected = [e for e in events.values() if e["day"][:7] == month_key(m)]
        income = sum((max(money(e["amount"]), ZERO) for e in selected), ZERO)
        expense = -sum((min(money(e["amount"]), ZERO) for e in selected), ZERO)
        balance += income - expense
        monthly.append({"month": month_key(m), "income": str(income), "expense": str(expense), "balance": str(balance)})
    return {"opening_balance": str(opening), "closing_balance": str(balance), "monthly": monthly,
            "sources": sorted(events.values(), key=lambda e: (e["day"], e["identity"])), "warnings": warnings}


def compute(store, definition):
    validate_scope(store, definition)
    dims = Dimensions(store, _filter(definition))
    currencies = {p.currency for p in store.list_portfolios() if
                  (not definition.portfolio_id or p.id == definition.portfolio_id) and
                  (not definition.property_id or any(prop.id == definition.property_id and prop.portfolio_id == p.id for prop in store.list_properties())) and
                  (not definition.unit_id or dims.property_portfolio(dims.unit_property(definition.unit_id)) == p.id)}
    if len(currencies) > 1:
        raise HTTPException(422, "Mehrere Währungen: bitte ein Portfolio wählen. Eine Währungsumrechnung wird nicht angenommen.")
    if definition.kind == "cash-v2":
        data = cash(store, definition)
    elif definition.kind == "performance-period-v2":
        data = performance(store, definition)
    else:
        data = forecast(store, definition)
    if definition.kind == "liquidity-v2":
        baseline = definition.model_copy(update={"rent_collection_percent": Decimal(100), "arrears_collection_percent": Decimal(0),
                                                  "vacant_unit_ids": [], "planned_flows": []})
        data["baseline_monthly"] = forecast(store, baseline)["monthly"]
    if definition.kind == "cash-v2":
        period_from, period_to = definition.date_from, definition.date_to or definition.as_of
    elif definition.kind == "performance-period-v2":
        period_from = definition.date_from or date(definition.as_of.year, 1, 1)
        period_to = definition.date_to or date(definition.as_of.year, 12, 31)
    else:
        period_from, period_to = definition.as_of + timedelta(days=1), month_end(add_months(month_start(definition.as_of), definition.months - 1))
    result = {"definition": definition.model_dump(mode="json"), "definition_hash": digest(definition.model_dump(mode="json")),
              "currency": next(iter(currencies), "EUR"), "basis": definition.kind,
              "filters": _filter(definition).with_period(period_from, period_to).echo(), **data}
    result["result_hash"] = digest(result)
    from .portfolio_scope import current_scope, refresh_scope
    refresh_scope(current_scope())
    return result


def save(store, payload: SaveReport, owner_id):
    key = digest([owner_id, "saved-finance-report", payload.idempotency_key])
    request_hash = digest(payload.model_dump(mode="json"))
    with work(store, owner_id, ("/reports",)) as unit:
        validate_scope(unit.store, payload.definition)
        rows = Rows.of(unit)
        current = rows.get("saved_finance_reports", key)
        if current:
            if current.owner_id != owner_id or current.request_hash != request_hash:
                raise HTTPException(409, "Dieser Wiederholungsschlüssel wurde bereits anders verwendet.")
            return current.model_dump(mode="json")
        if payload.expected_revision is not None:
            raise HTTPException(409, "Berichtsdefinitionen sind unveränderlich. Als neue Fassung speichern.")
        record = SavedReport(id=key, owner_id=owner_id, name=payload.name,
                             definition=payload.definition.model_dump(mode="json"), revision=request_hash, request_hash=request_hash)
        rows.add("saved_finance_reports", record)
        return record.model_dump(mode="json")


def saved(store, owner_id, identifier=None):
    rows = Rows.reading(store).find("saved_finance_reports", owner_id=owner_id)
    if identifier:
        rows = [r for r in rows if r.id == identifier]
        if not rows:
            raise NotFoundError("Gespeicherter Bericht nicht gefunden")
        validate_scope(store, ReportDefinition.model_validate(rows[0].definition))
        return rows[0]
    visible = []
    for r in rows:
        try:
            validate_scope(store, ReportDefinition.model_validate(r.definition))
        except (NotFoundError, HTTPException):
            continue
        visible.append(r.model_dump(mode="json"))
    return visible
