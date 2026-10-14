"""Build the test version's history through the app's own API, month by month.

Every record goes through the same endpoints, checks and services as when a person
enters it: rent histories, payment allocation, utility statements and dunning are
the app's own results. Runs in-process (FastAPI TestClient), so it needs no server.
"""

from __future__ import annotations

import calendar
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from .dataset import (
    COMPANY_TENANTS,
    CONTRACTORS,
    PORTFOLIOS,
    PropertySpec,
    TenancySpec,
    TenantSpec,
    UnitSpec,
    build_properties,
    email_for,
    person_name,
    phone_for,
)

CPI = {2020: 0.005, 2021: 0.031, 2022: 0.069, 2023: 0.059, 2024: 0.022, 2025: 0.021, 2026: 0.02, 2027: 0.02}
MARKET_GROWTH = 0.03


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def german_iban(bank_code: int, account: int) -> str:
    bban = f"{bank_code:08d}{account:010d}"
    check = 98 - int(bban + "131400") % 97
    return f"DE{check:02d}{bban}"


class ApiError(RuntimeError):
    pass


class Builder:
    def __init__(self, client: Any, headers: dict[str, dict], today: Optional[date] = None, seed: int = 15,
                 progress: Callable[[str], None] = print):
        self.c, self.h = client, headers
        self.today = today or date.today()
        self.start = date(self.today.year - 3, 1, 1)
        self.rnd = random.Random(seed)
        self.progress = progress
        self.props: list[PropertySpec] = build_properties(self.rnd)
        self.tenancies: list[TenancySpec] = []
        self.portfolio_ids: dict[str, str] = {}
        self.accounts: dict[str, str] = {}
        self.categories: dict[str, dict[str, str]] = {}
        self.contractors: dict[str, str] = {}
        # property id -> year -> item -> €
        self.costs: dict[Optional[str], dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        self.meters: dict[str, tuple[str, float]] = {}     # unit id -> (meter id, last value)
        self.deposits: dict[str, str] = {}                 # contract id -> deposit id
        self.pending_adjustment: Optional[tuple] = None
        self.names: set[str] = set()

    # --- api ---------------------------------------------------------------------------------------
    def api(self, who: str, method: str, path: str, body: Any = None) -> Any:
        resp = self.c.request(method, f"/api/v1{path}", json=body, headers=self.h[who])
        if resp.status_code >= 400:
            raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.content else None

    def book(self, body: dict, contract_id: Optional[str] = None) -> None:
        """A booking straight into the store, credited to its contract as the bookings endpoint would.

        Thousands of payments through the HTTP stack (five middlewares, token checks, audit
        log) took five minutes; this is what POST /bookings does for a rent payment.
        """
        from ..dependencies import store
        from ..models import BookingCreate, PaymentAllocationCreate

        booking = store.create_booking(BookingCreate(**body))
        if contract_id and body.get("tenant_id"):
            store.create_payment_allocation(PaymentAllocationCreate(
                booking_id=booking.id, contract_id=contract_id, amount=float(body["amount"]), source="auto"))

    # --- plan --------------------------------------------------------------------------------------
    def market(self, cold_today: float, day: date) -> float:
        years = max((self.today - day).days / 365.25, 0)
        return round(cold_today / ((1 + MARKET_GROWTH) ** years), 0)

    def new_tenant(self, unit: UnitSpec, prop: PropertySpec, behaviour: str) -> TenantSpec:
        company = COMPANY_TENANTS.get(f"{unit.label}|{prop.name}")
        name = company[0] if company else person_name(self.rnd, self.names)
        payment = "sepa_direct_debit" if behaviour == "sepa" else "bank_transfer"
        return TenantSpec(name, email_for(name, self.rnd), phone_for(prop.city, self.rnd), bool(company), payment)

    def behaviour(self) -> str:
        roll = self.rnd.random()
        return "late" if roll < 0.08 else "sepa" if roll < 0.2 else "punctual"

    def plan(self) -> None:
        start, today = self.start, self.today
        number = 0
        vacant_now = {("Bautzner Straße 61", "3. OG rechts"), ("Weststraße 50", "2. OG links")}
        for prop in self.props:
            for unit in prop.units:
                # every unit is let when the history starts
                first_start = date(self.rnd.randint(start.year - 14, start.year - 1), self.rnd.randint(1, 12), 1)
                if unit.kind == "commercial":
                    first_start = date(self.rnd.randint(start.year - 9, start.year - 2), self.rnd.choice([1, 4, 7, 10]), 1)
                chain: list[tuple[date, Optional[date]]]
                if (prop.name, unit.label) in vacant_now:
                    end = month_end(add_months(today, -self.rnd.randint(2, 4)))
                    chain = [(first_start, end)]
                elif unit.kind in ("flat", "parking") and self.rnd.random() < 0.24:
                    end = month_end(add_months(start, self.rnd.randint(3, 30)))
                    nxt = add_months(end + timedelta(days=1), self.rnd.choice([0, 0, 1, 2]))
                    chain = [(first_start, end), (nxt, None)]
                else:
                    chain = [(first_start, None)]
                for begin, until in chain:
                    number += 1
                    model = ("index" if unit.kind == "commercial" else
                             "stepped" if unit.kind == "flat" and begin.year >= 2021 and self.rnd.random() < 0.4 else
                             "fixed")
                    behaviour = self.behaviour()
                    notice = add_months(until, -3) if until else None
                    self.tenancies.append(TenancySpec(
                        unit, prop, self.new_tenant(unit, prop, behaviour), begin, until, notice, model, behaviour,
                        0 if unit.kind == "parking" else (2 if self.rnd.random() < 0.2 else 3),
                        number=f"MV-{begin.year}-{number:03d}"))
        # living stories the tester meets: rent arrears, partial payer, a notice with a successor already signed
        running = [t for t in self.tenancies if t.end is None and t.unit.kind == "flat" and t.start < start]
        self.rnd.shuffle(running)
        running[0].behaviour = "arrears"
        running[1].behaviour = "partial"
        for t in running[3:5]:
            t.behaviour = "unassigned"      # this month's rent arrives without a tenant (bank statement)
        leaving = running[2]
        leaving.end = month_end(add_months(today, 2))
        leaving.notice = add_months(today.replace(day=1), -1)
        successor_start = leaving.end + timedelta(days=1)
        number += 1
        self.tenancies.append(TenancySpec(
            leaving.unit, leaving.prop, self.new_tenant(leaving.unit, leaving.prop, "punctual"), successor_start,
            None, None, "stepped", "punctual", 3, number=f"MV-{successor_start.year}-{number:03d}"))

    # --- setup -------------------------------------------------------------------------------------
    def setup(self) -> None:
        for n, (name, owner, description) in enumerate(PORTFOLIOS):
            pf = self.api("owner", "POST", "/portfolios", {"name": name, "owner_name": owner, "description": description})
            self.portfolio_ids[name] = pf["id"]
            self.accounts[name] = self.api("owner", "POST", "/accounts", {
                "portfolio_id": pf["id"], "name": f"Mietkonto {owner}", "bank_name": "Sparkasse Leipzig",
                "iban": german_iban(86055592, 1100457800 + n * 17), "bic": "WELADE8LXXX", "account_type": "bank",
                "opening_balance": [48_500.0, 92_300.0, 18_750.0][n]})["id"]
            self.categories[name] = {}
            for cat, kind in [("Mieteinnahmen", "income"), ("Saldovortrag Vorsystem", "income"),
                              ("Nebenkostennachzahlung", "income"),
                              ("Kaution", "income"), ("Betriebskosten", "expense"), ("Instandhaltung", "expense"),
                              ("Verwaltung", "expense"), ("Nebenkostenerstattung", "expense")]:
                self.categories[name][cat] = self.api("owner", "POST", "/categories", {
                    "portfolio_id": pf["id"], "name": cat, "category_type": kind})["id"]
        for company, trade, phone, city in CONTRACTORS:
            contact = self.api("verwalter", "POST", "/contacts", {
                "contact_type": "supplier", "company_name": company, "phone": phone, "city": city,
                "email": "info@" + company.split()[0].lower().replace("ä", "ae").replace("ü", "ue")
                .replace("ö", "oe").replace("&", "") + "-handwerk.example",
                "notes": f"Gewerk: {trade}"})
            self.contractors[trade] = company
            del contact
        for prop in self.props:
            living = sum(u.area or 0 for u in prop.units if u.kind in ("flat", "house"))
            usable = sum(u.area or 0 for u in prop.units if u.kind == "commercial")
            year, month, day, price = prop.purchase
            prop.id = self.api("owner", "POST", "/properties", {
                "portfolio_id": self.portfolio_ids[prop.portfolio], "name": prop.name,
                "property_type": prop.property_type, "address_line": prop.street, "postal_code": prop.postal_code,
                "city": prop.city, "country": "DE", "year_built": prop.year_built,
                "living_area_sqm": living or None, "usable_area_sqm": usable or None,
                "purchase_price": price, "purchase_date": date(year, month, day).isoformat(),
                "market_value": prop.market_value, "valuation_date": date(self.today.year - 1, 12, 31).isoformat()})["id"]
            for unit in prop.units:
                unit.id = self.api("verwalter", "POST", "/units", {
                    "property_id": prop.id, "label": unit.label, "unit_type": unit.unit_type, "area_sqm": unit.area,
                    "rooms": unit.rooms, "floor": unit.floor, "person_count": unit.persons, "status": "vacant",
                    "cold_rent": unit.cold, "service_charge_advance": unit.service,
                    "heating_advance": unit.heating})["id"]
                if unit.kind in ("flat", "commercial", "house"):
                    meter = self.api("techniker", "POST", "/meters", {
                        "unit_id": unit.id, "meter_type": "cold_water", "serial_number": f"WZ {self.rnd.randint(10**7, 10**8 - 1)}",
                        "location": "Bad" if unit.kind != "commercial" else "Technikraum",
                        "installation_date": "2019-06-01", "next_inspection": "2027-06-01",
                        "supplier": "Stadtwerke"})
                    value = round(self.rnd.uniform(80, 400), 1)
                    self.api("techniker", "POST", f"/meters/{meter['id']}/readings", {
                        "meter_id": meter["id"], "reading_date": add_months(self.start, -1).replace(day=31).isoformat(),
                        "value": value, "recorded_by": "Jens Vogel"})
                    self.meters[unit.id] = (meter["id"], value)
            self.api("verwalter", "POST", "/insurances", {
                "property_id": prop.id, "insurance_type": "building",
                "provider": "Mitteldeutsche Gebäudeversicherung AG", "policy_number": f"GV-{self.rnd.randint(100000, 999999)}",
                "coverage_amount": round(prop.market_value * 1.3, -3),
                "premium_amount": round(sum(u.area or 15 for u in prop.units) * 2.6, 2), "premium_interval": "annual",
                "start_date": date(year, month, 1).isoformat(), "contact_person": "Herr Seidel",
                "contact_phone": "0341 8890012"})
            if prop.property_type not in ("condominium", "single_family"):
                self.api("verwalter", "POST", "/insurances", {
                    "property_id": prop.id, "insurance_type": "liability", "provider": "Elbtal Haftpflicht VVaG",
                    "policy_number": f"HH-{self.rnd.randint(100000, 999999)}", "coverage_amount": 5_000_000,
                    "premium_amount": round(120 + len(prop.units) * 9.5, 2), "premium_interval": "annual",
                    "start_date": date(year, month, 1).isoformat()})

    # --- tenancies ---------------------------------------------------------------------------------
    def portfolio(self, prop: PropertySpec) -> str:
        return prop.portfolio

    def move_in(self, t: TenancySpec) -> None:
        cold = self.market(t.unit.cold, t.start)
        service, heating = t.unit.service, t.unit.heating
        if t.start < self.start:
            service, heating = round(service * 0.92, 0), round(heating * 0.85, 0)
        future = t.start > self.today
        if future:          # signed successor: the unit keeps the current tenant's rent and status
            previous = self.api("verwalter", "GET", f"/units/{t.unit.id}")
        self.api("verwalter", "PATCH", f"/units/{t.unit.id}", {
            "cold_rent": cold, "service_charge_advance": service, "heating_advance": heating,
            **({} if future else {"status": "occupied"})})
        tenant = t.tenant
        if not tenant.id:
            tenant.id = self.api("verwalter", "POST", "/tenants", {
                "full_name": tenant.name, "email": tenant.email, "phone": tenant.phone,
                "payment_method": tenant.payment,
                "sepa_mandate": f"MR-{self.rnd.randint(100000, 999999)}" if tenant.payment == "sepa_direct_debit" else None,
                "city": t.prop.city if t.start < self.start else None})["id"]
        known_end = t.end if t.notice and t.notice <= self.today else None
        deposit = round(cold * t.deposit_months, 2) if t.deposit_months else None
        contract = self.api("verwalter", "POST", "/contracts", {
            "contract_number": t.number, "property_id": t.prop.id, "unit_id": t.unit.id, "tenant_id": tenant.id,
            "start_date": t.start.isoformat(), "end_date": known_end.isoformat() if known_end else None,
            "status": "terminated" if known_end else "active",
            "notice_period": "3 Monate" if t.unit.kind != "commercial" else "6 Monate zum Quartalsende",
            "deposit_amount": deposit,
            "index_rent": {"index": "Indexmiete (VPI)", "stepped": "Staffelmiete"}.get(t.rent_model),
            "persons": t.unit.persons if t.unit.kind in ("flat", "house") else None})
        t.id = contract["id"]
        t.steps = [(t.start, cold, service, heating)]
        if deposit:
            dep = self.api("verwalter", "POST", "/deposits", {
                "contract_id": t.id, "amount": deposit, "status": "held", "held_date": t.start.isoformat(),
                "notes": "Mietkautionskonto" if self.rnd.random() < 0.6 else "Barkaution, angelegt auf Kautionskonto"})
            self.deposits[t.id] = dep["id"]
        if self.start <= t.start <= self.today and t.unit.kind != "parking":
            self.handover(t, "move_in", t.start)
        if future:
            self.api("verwalter", "PATCH", f"/units/{t.unit.id}", {
                key: previous[key] for key in ("cold_rent", "service_charge_advance", "heating_advance")})

    def handover(self, t: TenancySpec, kind: str, day: date) -> None:
        reading = None
        if t.unit.id in self.meters:
            meter_id, last = self.meters[t.unit.id]
            reading = round(last + self.rnd.uniform(5, 40), 1)
            self.api("techniker", "POST", f"/meters/{meter_id}/readings", {
                "meter_id": meter_id, "reading_date": day.isoformat(), "value": reading,
                "recorded_by": "Jens Vogel"})
            self.meters[t.unit.id] = (meter_id, reading)
        self.api("techniker", "POST", "/handover-protocols", {
            "contract_id": t.id, "unit_id": t.unit.id, "protocol_type": kind, "protocol_date": day.isoformat(),
            "key_count": self.rnd.randint(2, 4), "overall_condition": self.rnd.choice(["good", "good", "fair"]),
            "status": "completed",
            "notes": f"Wasserzähler {reading:.1f} m³" if reading is not None else None})

    def move_out(self, t: TenancySpec) -> None:
        assert t.end is not None and t.id is not None
        end = t.end
        if t.unit.kind != "parking":
            self.handover(t, "move_out", end)
        self.api("verwalter", "PATCH", f"/units/{t.unit.id}", {"status": "vacant"})
        dep = self.deposits.get(t.id)
        if dep:
            deduction = self.rnd.choice([0, 0, 0, 185.0, 420.0])
            returned = min(end + timedelta(days=self.rnd.randint(30, 90)), self.today - timedelta(days=1))
            self.api("p.lindner", "PATCH", f"/deposits/{dep}", {
                "status": "partially_returned" if deduction else "returned", "return_date": returned.isoformat(),
                "deductions": deduction or None,
                "deduction_reason": "Malerarbeiten Wohnzimmer laut Übergabeprotokoll" if deduction else None})

    def opening_balances(self) -> None:
        """Tenancies older than the history: their accounts are taken over balanced (Saldovortrag).

        The app owes rent from the contract start; payments before the history live in the
        previous system, so one booking per contract carries the paid total over.
        """
        cutover = self.start - timedelta(days=1)
        for t in self.tenancies:
            if not t.id or t.start >= self.start:
                continue
            account = self.api("p.lindner", "GET", f"/tenants/{t.tenant.id}/account?as_of={cutover.isoformat()}")
            row = next(r for r in account["contracts"] if r["contract_id"] == t.id)
            if row["outstanding"] <= 0:
                continue
            pf = self.portfolio(t.prop)
            self.book({
                "account_id": self.accounts[pf], "property_id": t.prop.id, "unit_id": t.unit.id,
                "tenant_id": t.tenant.id, "booking_date": cutover.isoformat(), "amount": row["outstanding"],
                "status": "booked", "category_id": self.categories[pf]["Saldovortrag Vorsystem"],
                "payment_text": f"Saldovortrag aus dem Vorsystem: Mieten {t.start:%m/%Y}–{cutover:%m/%Y} bezahlt "
                                f"({t.number})"}, contract_id=t.id)

    # --- money -------------------------------------------------------------------------------------
    @staticmethod
    def step_on(t: TenancySpec, day: date) -> tuple:
        current = t.steps[0]
        for step in t.steps:
            if step[0] <= day:
                current = step
        return current

    def payments(self, month: date) -> None:
        for t in self.tenancies:
            if not t.id or month < t.start.replace(day=1) or (t.end and month > t.end):
                continue
            _, cold, service, heating = self.step_on(t, month)
            due = round(cold + service + heating, 2)
            amount, day = due, self.rnd.randint(1, 3)
            if t.behaviour == "late":
                day = self.rnd.randint(6, 18)
            elif t.behaviour == "sepa":
                day = 3
            elif t.behaviour == "arrears" and month >= add_months(self.today.replace(day=1), -3):
                continue                                 # stopped paying four months ago
            elif t.behaviour == "partial" and month >= add_months(self.today.replace(day=1), -2):
                amount = round(due * 0.8, 2)
            elif t.behaviour == "unassigned" and month == self.today.replace(day=1):
                continue                                 # booked in finish() without tenant
            when = month.replace(day=day)
            if when > self.today:
                continue
            pf = self.portfolio(t.prop)
            name = t.tenant.name.split(",")[0]
            self.book({
                "account_id": self.accounts[pf], "property_id": t.prop.id, "unit_id": t.unit.id,
                "tenant_id": t.tenant.id, "booking_date": when.isoformat(), "amount": amount, "status": "booked",
                "category_id": self.categories[pf]["Mieteinnahmen"],
                "payment_text": (f"SEPA-Lastschrift Miete {month:%m/%Y} {t.number}" if t.behaviour == "sepa"
                                 else f"Miete {month:%m/%Y} {t.unit.label} {name}")}, contract_id=t.id)

    def expense(self, prop: PropertySpec, day: date, item: str, amount: float, category: str,
                recoverable: bool = True) -> None:
        if day > self.today:
            return
        pf = self.portfolio(prop)
        self.book({
            "account_id": self.accounts[pf], "property_id": prop.id, "category_id": self.categories[pf][category],
            "booking_date": day.isoformat(), "amount": -round(amount, 2), "status": "booked",
            "payment_text": f"{item} {day:%m/%Y} {prop.name}"})
        if recoverable:
            self.costs[prop.id][day.year][item] += round(amount, 2)

    def expenses(self, month: date) -> None:
        for prop in self.props:
            area = sum(u.area or 12 for u in prop.units)
            count = len(prop.units)
            people = sum(u.persons or 0 for u in prop.units)
            single = prop.property_type in ("condominium", "single_family")
            if prop.property_type == "parking":
                if month.month in (2, 5, 8, 11):
                    self.expense(prop, month.replace(day=15), "Grundsteuer", area * 0.9 / 4, "Betriebskosten")
                if month.month == 1:
                    self.expense(prop, month.replace(day=20), "Gebäudeversicherung", area * 1.1, "Betriebskosten")
                continue
            if single:
                if month.month in (2, 5, 8, 11) and prop.property_type == "condominium":
                    self.expense(prop, month.replace(day=5), "Hausgeld WEG", area * 3.4 * 3, "Betriebskosten",
                                 recoverable=False)
                if month.month == 1:
                    self.expense(prop, month.replace(day=20), "Gebäudeversicherung", area * 2.4, "Betriebskosten",
                                 recoverable=False)
                continue
            season = 1.35 if month.month in (11, 12, 1, 2, 3) else 0.65
            inflation = 1 + 0.04 * (month.year - self.start.year)
            self.expense(prop, month.replace(day=10), "Heizkosten (Gas)", area * 1.05 * season * inflation, "Betriebskosten")
            self.expense(prop, month.replace(day=12), "Hausmeister", area * 0.28 * inflation, "Betriebskosten")
            self.expense(prop, month.replace(day=12), "Allgemeinstrom", count * 6.4 * self.rnd.uniform(0.85, 1.15),
                         "Betriebskosten")
            self.expense(prop, month.replace(day=14), "Müllabfuhr", count * 13.8 * inflation, "Betriebskosten")
            self.expense(prop, month.replace(day=16), "Wasser/Abwasser",
                         max(people, 1) * 15.5 * self.rnd.uniform(0.9, 1.1) * inflation, "Betriebskosten")
            if month.month in (2, 5, 8, 11):
                self.expense(prop, month.replace(day=15), "Grundsteuer", area * 2.0 / 4, "Betriebskosten")
            if month.month == 1:
                self.expense(prop, month.replace(day=20), "Gebäudeversicherung", area * 2.6 * inflation, "Betriebskosten")
                self.expense(prop, month.replace(day=22), "Verwaltervergütung", count * 290.0, "Verwaltung",
                             recoverable=False)
            if month.month == 9:
                self.expense(prop, month.replace(day=8), "Schornsteinfeger", 95.0 + count * 6, "Betriebskosten")
            if month.month in (4, 6, 8, 10):
                self.expense(prop, month.replace(day=25), "Gartenpflege", area * 0.12, "Betriebskosten")

    # --- rent changes ------------------------------------------------------------------------------
    @staticmethod
    def last_cold_change(t: TenancySpec) -> tuple[date, float]:
        """When the cold rent last changed (a new advance does not count) and what it is."""
        since, cold = t.steps[0][0], t.steps[0][1]
        for step in t.steps[1:]:
            if step[1] != cold:
                since, cold = step[0], step[1]
        return since, cold

    def adjust(self, t: TenancySpec, kind: str, month: date, new_cold: float, apply: bool = True,
               note: Optional[str] = None) -> None:
        _, cold, service, heating = self.step_on(t, month)
        adj = self.api("verwalter", "POST", "/rent-adjustments", {
            "contract_id": t.id, "adjustment_type": kind, "effective_date": month.isoformat(),
            "previous_rent": cold, "new_rent": new_cold, "increase_percent": round((new_cold / cold - 1) * 100, 2),
            "notes": note})
        if apply:
            self.api("verwalter", "POST", f"/rent-adjustments/{adj['id']}/apply", {})
            t.steps.append((month, new_cold, service, heating))
        else:
            self.pending_adjustment = (adj["id"], t)

    def adjustments(self, month: date) -> None:
        for t in self.tenancies:
            if not t.id or (t.end and t.end < month) or t.start > month:
                continue
            last_from, cold = self.last_cold_change(t)
            since = (month.year - last_from.year) * 12 + month.month - last_from.month
            if any(step[0] == month for step in t.steps):
                continue
            if t.rent_model == "index" and month.month == 1 and since >= 12:
                rate = CPI.get(month.year - 1, 0.02)
                new_cold = round(cold * (1 + rate), 2)
                apply = not (month.year == self.today.year and self.pending_adjustment is None)
                self.adjust(t, "index", month, new_cold, apply,
                            f"VPI {month.year - 1}: +{rate * 100:.1f} % (Indexklausel § 4 Mietvertrag)")
            elif t.rent_model == "stepped" and since >= 12 and month.month == t.start.month:
                self.adjust(t, "stepped", month, round(cold + self.rnd.choice([20, 25, 30, 35]), 2),
                            note="Staffelmiete laut Anlage 2 zum Mietvertrag")
            elif (t.rent_model == "fixed" and t.unit.kind == "flat" and month == date(self.start.year + 1, 7, 1)
                  and t.start.year <= self.start.year - 3 and self.rnd.random() < 0.55):
                self.adjust(t, "comparative", month, round(cold * self.rnd.uniform(1.07, 1.11), 0),
                            note="Mieterhöhung auf die ortsübliche Vergleichsmiete (§ 558 BGB), Mietspiegel")

    # --- utility statements ------------------------------------------------------------------------
    def billing(self, year: int, leave_open: set[str]) -> None:
        for prop in self.props:
            if not prop.bill or not self.costs[prop.id].get(year):
                continue
            label = f"Betriebskosten {year}"
            period = self.api("verwalter", "POST", "/billing/periods", {
                "property_id": prop.id, "label": label, "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"})
            shops_only = all(u.kind != "flat" for u in prop.units if u.kind != "parking")
            keys = {}
            for key_type, name in [("area_sqm", "Wohn-/Nutzfläche"), ("unit_count", "Einheiten"),
                                   ("person_count", "Personen")]:
                if key_type == "person_count" and shops_only:
                    continue
                keys[key_type] = self.api("verwalter", "POST", "/billing/allocation-keys", {
                    "property_id": prop.id, "name": f"{name} {year}", "key_type": key_type})["id"]
            by_item = {"Müllabfuhr": "person_count", "Wasser/Abwasser": "person_count", "Allgemeinstrom": "unit_count",
                       "Schornsteinfeger": "unit_count"}
            for item, amount in sorted(self.costs[prop.id][year].items()):
                key = by_item.get(item, "area_sqm")
                self.api("verwalter", "POST", "/billing/cost-items", {
                    "billing_period_id": period["id"], "description": item, "amount": round(amount, 2),
                    "allocation_key_id": keys.get(key, keys["area_sqm"]), "is_recoverable": True})
            self.api("verwalter", "POST", f"/billing/periods/{period['id']}/generate", {})
            if prop.name in leave_open:
                continue                                  # for the tester: check, finalize, create receivables
            self.api("verwalter", "POST", f"/billing/periods/{period['id']}/submit-review", {})
            self.api("verwalter", "POST", f"/billing/periods/{period['id']}/finalize", {})
            self.api("verwalter", "POST", f"/billing/periods/{period['id']}/create-receivables", {})
            self.settle(prop, period["id"], year)

    def settle(self, prop: PropertySpec, period_id: str, year: int) -> None:
        """Tenants pay their back payments, credits are paid out; a big back payment raises the advance."""
        statements = self.api("verwalter", "GET", f"/billing/statements?billing_period_id={period_id}")
        receivables = self.api("p.lindner", "GET", "/receivables?limit=1000")
        by_statement = {r.get("statement_id"): r for r in receivables if r.get("statement_id")}
        pf = self.portfolio(prop)
        pay_day = date(year + 1, 6, self.rnd.randint(5, 25))
        for s in statements:
            if s.get("party") == "vacancy" or not s.get("contract_id"):
                continue
            balance = round(s["balance"], 2)
            t = next((x for x in self.tenancies if x.id == s["contract_id"]), None)
            if t is None or abs(balance) < 0.01 or pay_day > self.today:
                continue
            receivable = by_statement.get(s["id"])
            if balance > 0:
                self.book({
                    "account_id": self.accounts[pf], "property_id": prop.id,
                    "category_id": self.categories[pf]["Nebenkostennachzahlung"],
                    "booking_date": pay_day.isoformat(), "amount": balance, "status": "booked",
                    "payment_text": f"Nachzahlung Betriebskosten {year} {t.tenant.name}"})
                if receivable:
                    self.api("p.lindner", "PATCH", f"/receivables/{receivable['id']}", {"status": "paid"})
            else:
                self.book({
                    "account_id": self.accounts[pf], "property_id": prop.id,
                    "category_id": self.categories[pf]["Nebenkostenerstattung"],
                    "booking_date": pay_day.isoformat(), "amount": balance, "status": "booked",
                    "payment_text": f"Guthaben Betriebskosten {year} {t.tenant.name}"})
                if receivable:
                    self.api("p.lindner", "PATCH", f"/receivables/{receivable['id']}", {"status": "paid"})
            # more than 15 % of the yearly advances back: the advance goes up from July
            # a month without a planned rent change (stepped rent, comparative increase in July)
            raise_from = next(date(year + 1, m, 1) for m in (6, 8, 9, 10)
                              if m != t.start.month and not any(step[0] == date(year + 1, m, 1) for step in t.steps))
            _, cold, service, heating = self.step_on(t, raise_from)
            if (service > 0 and balance > 0.15 * (service + heating) * 12 and (t.end is None or t.end > raise_from)
                    and raise_from <= self.today):
                extra = round(balance / 12 / 5, 0) * 5
                self.api("verwalter", "POST", f"/contracts/{t.id}/rent-periods", {
                    "contract_id": t.id, "valid_from": raise_from.isoformat(), "cold_rent": cold,
                    "service_charge_advance": service + extra, "heating_advance": heating,
                    "notes": f"Anpassung der Vorauszahlung nach Abrechnung {year} (§ 560 Abs. 4 BGB)"})
                t.steps.append((raise_from, cold, service + extra, heating))

    # --- building care -----------------------------------------------------------------------------
    CASES = [
        ("Heizung", "Heizkörper wird nicht warm", "Mieter meldet kalten Heizkörper im Wohnzimmer, Entlüften half nicht."),
        ("Sanitär", "Tropfender Wasserhahn Küche", "Kartusche der Küchenarmatur tauschen."),
        ("Sanitär", "Verstopfter Abfluss Bad", "Rohrreinigung Badewannenablauf."),
        ("Elektro", "Treppenhausbeleuchtung defekt", "Bewegungsmelder 2. OG ausgefallen."),
        ("Dach", "Feuchtigkeit unter dem Dach", "Nach Starkregen feuchte Stelle im Dachgeschoss, Ziegel prüfen."),
        ("Maler", "Treppenhaus streichen", "Wände im Treppenhaus EG–2. OG, Angebot liegt vor."),
        ("Schlüssel", "Haustürschloss klemmt", "Schließzylinder Haustür tauschen, 12 Schlüssel nachbestellen."),
        ("Elektro", "Klingelanlage ohne Funktion", "Klingel und Gegensprechanlage für 1. OG ausgefallen."),
        ("Heizung", "Jahreswartung Gastherme", "Wartung und Abgasmessung der Zentralheizung."),
        ("Garten", "Baumschnitt Hof", "Kastanie im Hof zurückschneiden, Genehmigung liegt vor."),
    ]

    def caretaking(self, month: date) -> None:
        for prop in self.props:
            if prop.property_type == "parking" or self.rnd.random() > 0.09:
                continue
            trade, title, description = self.rnd.choice(self.CASES)
            unit = self.rnd.choice(prop.units)
            reported = month.replace(day=self.rnd.randint(1, 25))
            if reported > self.today:
                continue
            recent = reported > self.today - timedelta(days=30)
            cost = round(self.rnd.uniform(120, 2800) if trade != "Maler" else self.rnd.uniform(3500, 7800), 2)
            self.api("techniker", "POST", "/maintenance", {
                "property_id": prop.id, "unit_id": unit.id if trade in ("Heizung", "Sanitär", "Elektro") else None,
                "title": title, "description": description, "category": trade,
                "priority": self.rnd.choice(["low", "medium", "medium", "high"]),
                "status": self.rnd.choice(["open", "in_progress"]) if recent else "completed",
                "reported_by": "Jens Vogel", "assignee": "Jens Vogel",
                "due_date": (reported + timedelta(days=14)).isoformat(), "estimated_cost": cost,
                "contractor": self.contractors.get(trade, "Hausmeisterservice Weiß")})
            if recent:
                continue
            invoice_day = reported + timedelta(days=self.rnd.randint(7, 25))
            paid = invoice_day + timedelta(days=14) <= self.today
            net = round(cost / 1.19, 2)
            self.api("p.lindner", "POST", "/invoices", {
                "property_id": prop.id, "supplier": self.contractors.get(trade, "Hausmeisterservice Weiß"),
                "invoice_number": f"R-{invoice_day:%y%m}-{self.rnd.randint(100, 999)}",
                "invoice_date": invoice_day.isoformat(), "due_date": (invoice_day + timedelta(days=14)).isoformat(),
                "net_amount": net, "vat_rate": 19, "vat_amount": round(cost - net, 2), "gross_amount": cost,
                "category": "maintenance", "status": "paid" if paid else "open"})
            if paid:
                self.expense(prop, invoice_day + timedelta(days=12), f"Rechnung {title}", cost, "Instandhaltung",
                             recoverable=False)
        if month.month == 12:
            for unit_id, (meter_id, last) in list(self.meters.items()):
                day = month_end(month)
                if day > self.today:
                    continue
                unit = next(u for p in self.props for u in p.units if u.id == unit_id)
                value = round(last + max(unit.persons or 1, 1) * self.rnd.uniform(28, 42), 1)
                self.api("techniker", "POST", f"/meters/{meter_id}/readings", {
                    "meter_id": meter_id, "reading_date": day.isoformat(), "value": value,
                    "recorded_by": "Jens Vogel"})
                self.meters[unit_id] = (meter_id, value)

    # --- the month ---------------------------------------------------------------------------------
    def month(self, month: date, leave_open: set[str]) -> None:
        for t in self.tenancies:
            if not t.id and t.start >= self.start and t.start.replace(day=1) == month and t.start <= self.today:
                self.move_in(t)
        self.adjustments(month)
        self.payments(month)
        self.expenses(month)
        self.caretaking(month)
        if month.month == 4 and month.year > self.start.year:
            self.billing(month.year - 1, leave_open if month.year == self.today.year else set())
        for t in self.tenancies:
            if t.id and t.end and t.end.replace(day=1) == month and t.end < self.today:
                self.move_out(t)

    def run(self) -> None:
        self.plan()
        self.setup()
        for t in sorted(self.tenancies, key=lambda x: x.start):
            if t.start < self.start:
                self.move_in(t)
        self.opening_balances()
        leave_open = {"Bautzner Straße 61", "Weststraße 50"}
        month = self.start
        while month <= self.today:
            self.month(month, leave_open)
            if month.month in (3, 6, 9, 12):
                self.progress(f"  … {month:%m/%Y}")
            month = add_months(month, 1)
        self.finish()

    # --- rent overview, arrears, documents ----------------------------------------------------------
    def rent_ledger(self) -> None:
        """Monthly rent charges of the last months (Mietübersicht) and receivables for rent arrears."""
        from ..dependencies import store
        from ..models import ReceivableCreate, RentChargeCreate

        today = self.today
        first = add_months(today.replace(day=1), -3)
        for t in self.tenancies:
            if not t.id or t.start > today or (t.end and t.end < first):
                continue
            month = max(first, t.start.replace(day=1))
            while month <= today and (t.end is None or month <= t.end):
                _, cold, service, heating = self.step_on(t, month)
                due = round(cold + service + heating, 2)
                paid_day = month.replace(day=3 if t.behaviour != "late" else 18)
                if t.behaviour == "arrears":
                    paid = 0.0
                elif t.behaviour == "partial" and month >= add_months(today.replace(day=1), -2):
                    paid = round(due * 0.8, 2)
                elif t.behaviour == "unassigned" and month == today.replace(day=1):
                    paid = 0.0
                else:
                    paid = due if paid_day <= today else 0.0
                overdue = month.replace(day=3) < today - timedelta(days=10)
                status = ("paid" if paid >= due else "partial" if paid else "overdue" if overdue else "open")
                store.create_rent_charge(RentChargeCreate(
                    contract_id=t.id, month=f"{month:%Y-%m}", cold_rent=cold, service_charge=service,
                    heating_charge=heating, amount_paid=paid, status=status))
                if t.behaviour == "arrears" and month.replace(day=3) < today:
                    age = (today - month.replace(day=3)).days
                    store.create_receivable(ReceivableCreate(
                        contract_id=t.id, due_date=month.replace(day=3), amount_due=due,
                        dunning_level="2" if age > 60 else "1" if age > 30 else None, status="open",
                        description=f"Mietrückstand {month:%m/%Y} {t.unit.label}, {t.prop.name}"))
                month = add_months(month, 1)

    def open_work_orders(self) -> None:
        today = self.today
        cases = [
            (self.props[0], "Heizung", "Heizung im 2. OG links fällt nachts aus",
             "Therme schaltet ab, Fehlercode F28. Mieterin mit Kleinkind, bitte dringend.", "urgent", "in_progress", 2),
            (self.props[6], "Sanitär", "Wasserfleck an der Decke 1. OG rechts",
             "Vermutlich undichter Siphon in der Wohnung darüber. Termin mit Mieter vereinbaren.", "high", "open", 5),
            (self.props[11], "Elektro", "Tiefgaragentor öffnet nicht zuverlässig",
             "Antrieb stockt, Lichtschranke prüfen lassen.", "medium", "open", 8),
            (self.props[9], "Dach", "Dachrinne verstopft",
             "Laub im Fallrohr, Wasser läuft an der Fassade herunter.", "medium", "open", -4),
        ]
        for prop, trade, title, description, priority, status, due_in in cases:
            self.api("techniker", "POST", "/maintenance", {
                "property_id": prop.id, "title": title, "description": description, "category": trade,
                "priority": priority, "status": status, "reported_by": "Mieter", "assignee": "Jens Vogel",
                "due_date": (today + timedelta(days=due_in)).isoformat(),
                "estimated_cost": round(self.rnd.uniform(180, 1400), 2), "contractor": self.contractors.get(trade)})
        for prop, supplier, net, days_ago, number in [
            (self.props[1], "Grünwerk Gartenpflege", 384.0, 6, "GW-2026-1187"),
            (self.props[7], "Heizungsbau Lorenz GmbH", 1268.5, 12, "HL-26-0934"),
        ]:
            invoice_day = today - timedelta(days=days_ago)
            self.api("p.lindner", "POST", "/invoices", {
                "property_id": prop.id, "supplier": supplier, "invoice_number": number,
                "invoice_date": invoice_day.isoformat(), "due_date": (invoice_day + timedelta(days=14)).isoformat(),
                "net_amount": net, "vat_rate": 19, "vat_amount": round(net * 0.19, 2),
                "gross_amount": round(net * 1.19, 2), "status": "open"})

    def contract_documents(self) -> None:
        """A one-page PDF per running contract, filed with the contract (Dokumente)."""
        for t in self.tenancies:
            if not t.id or (t.end and t.end < self.today):
                continue
            pdf = contract_pdf(t, self.step_on(t, t.start))
            resp = self.c.post("/api/v1/documents/import", headers=self.h["verwalter"], files={
                "file": (f"Mietvertrag_{t.number}.pdf", pdf, "application/pdf")}, data={
                "title": f"Mietvertrag {t.number} – {t.tenant.name}", "document_type": "contract",
                "document_date": t.start.isoformat(), "tags": "Mietvertrag,Testdaten",
                "property_id": t.prop.id, "unit_id": t.unit.id, "contract_id": t.id})
            if resp.status_code >= 400:
                raise ApiError(f"POST /documents/import -> {resp.status_code}: {resp.text[:300]}")

    # --- the present -------------------------------------------------------------------------------
    def finish(self) -> None:
        today = self.today
        for t in self.tenancies:
            if not t.id and t.start > today:
                self.move_in(t)                       # the successor who signed already
        # this month's rent of two tenants came in by bank statement without a tenant: to be assigned
        for t in [x for x in self.tenancies if x.behaviour == "unassigned"]:
            pf = self.portfolio(t.prop)
            _, cold, service, heating = self.step_on(t, today)
            self.book({
                "account_id": self.accounts[pf], "booking_date": min(today, today.replace(day=2)).isoformat(),
                "amount": round(cold + service + heating, 2), "status": "open",
                "payment_text": f"Überweisung {t.tenant.name.split()[-1].upper()} MIETE {t.unit.label.upper()} "
                                f"{t.prop.street.upper()}"})
        self.rent_ledger()
        self.open_work_orders()
        self.contract_documents()
        for name, entity, field_name, days, action, role, severity in [
            ("Mietrückstand: Verwaltung informieren", "receivable", "due_date", 14, "notify", "verwalter", "warning"),
            ("Mietrückstand über 30 Tage: Eigentümer informieren", "receivable", "due_date", 30, "notify",
             "eigentuemer", "critical"),
            ("Wartung überfällig: Priorität erhöhen", "maintenance", "due_date", 7, "escalate_priority", None, "warning"),
            ("Aufgabe überfällig: Erinnerung", "task", "due_date", 3, "notify", "verwalter", "info"),
        ]:
            self.api("verwalter", "POST", "/escalation/rules", {
                "name": name, "entity_type": entity, "condition_field": field_name, "days_overdue": days,
                "action": action, "target_role": role, "notification_severity": severity, "is_active": True})
        self.api("verwalter", "POST", "/escalation/run", {})
        # vacant flats: listing, prospects, viewings
        for t in [x for x in self.tenancies if x.end and x.end < today]:
            if any(o.unit is t.unit and (o.end is None or o.end >= today) and o.start <= add_months(today, 3)
                   for o in self.tenancies if o is not t):
                continue
            unit = t.unit
            listing = self.api("verwalter", "POST", "/listings", {
                "unit_id": unit.id, "title": f"{unit.rooms:g}-Zimmer-Wohnung, {unit.area:g} m², {t.prop.city}",
                "description": f"Helle {unit.rooms:g}-Zimmer-Wohnung im {unit.floor} in der {t.prop.street}. "
                               "Laminat, Wannenbad mit Fenster, Keller. Ab sofort frei.",
                "portal": "ImmoScout24", "status": "published", "target_rent": unit.cold,
                "service_charge": unit.service + unit.heating, "available_from": today.isoformat(),
                "contact_name": "Sandra Krause", "contact_email": "s.krause@reiser-verwaltung.example"})
            for n, (status, source) in enumerate([("new", "ImmoScout24"), ("contacted", "ImmoScout24"),
                                                  ("viewing_scheduled", "Empfehlung")]):
                name = person_name(self.rnd, self.names)
                lead = self.api("verwalter", "POST", "/leads", {
                    "listing_id": listing["id"], "unit_id": unit.id, "full_name": name,
                    "email": email_for(name, self.rnd), "phone": phone_for(t.prop.city, self.rnd), "source": source,
                    "status": status, "priority": n, "notes": "Selbstauskunft und Schufa liegen vor" if n == 2 else None})
                if status == "viewing_scheduled":
                    when = datetime.combine(today + timedelta(days=3 + n), datetime.min.time()).replace(hour=17)
                    self.api("verwalter", "POST", "/viewings", {
                        "lead_id": lead["id"], "unit_id": unit.id, "scheduled_at": when.isoformat(),
                        "agent": "Sandra Krause", "notes": "Treffpunkt vor dem Haus"})
        # open work
        main = self.props[0]
        for title, description, days, priority, prop in [
            ("Nebenkostenabrechnung Bautzner Straße prüfen", "Abrechnung des Vorjahres ist erzeugt, aber noch nicht "
             "abgeschlossen: Positionen prüfen, abschließen, Forderungen erzeugen.", 10, "high", self.props[6]),
            ("Rauchwarnmelder-Wartung beauftragen", "Jährliche Prüfung aller Rauchwarnmelder (Sächsische BauO).",
             21, "medium", None),
            ("Mahnung Mietrückstand nachhalten", "Mieter mit Rückstand anrufen, Ratenzahlung anbieten.", 5, "high", None),
            ("Angebot Treppenhausanstrich einholen", "Drei Angebote für das Treppenhaus anfragen.", 30, "low", main),
            ("Wohnungsübergabe vorbereiten", "Auszug zum Monatsende: Termin, Protokoll, Zählerstände.", 14, "medium",
             None),
        ]:
            self.api("s.krause", "POST", "/tasks", {
                "title": title, "description": description, "due_date": (today + timedelta(days=days)).isoformat(),
                "priority": priority, "status": "open", "assignee": "Sandra Krause",
                "property_id": prop.id if prop else None})
        for title, kind, days, prop in [
            ("Heizungswartung", "maintenance", 9, self.props[6]),
            ("Eigentümerversammlung WEG Kurt-Eisner-Straße 70", "meeting", 17, self.props[3]),
            ("Wohnungsbesichtigung", "viewing", 4, None),
            ("Treppenhausreinigung Abnahme", "inspection", 12, self.props[1]),
            ("Termin Steuerberatung Jahresabschluss", "meeting", 25, None),
        ]:
            self.api("s.krause", "POST", "/calendar", {
                "title": title, "event_type": kind, "event_date": (today + timedelta(days=days)).isoformat(),
                "event_time": "10:00", "property_id": prop.id if prop else None,
                "location": prop.street if prop else None})
        for prop in self.props:
            if prop.property_type == "parking":
                continue
            area = sum(u.area or 0 for u in prop.units)
            self.api("owner", "POST", "/budgets", {
                "property_id": prop.id, "year": today.year, "category": "maintenance",
                "planned_amount": round(area * 9.5, -2) or 1000.0, "notes": "Instandhaltungsrücklage nach Peters"})


def contract_pdf(t: TenancySpec, first_step: tuple) -> bytes:
    """A short contract summary as PDF (the full contract would come from the contract wizard)."""
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    def eur(value: float) -> str:
        return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Mietvertrag {t.number}")
    y = 790
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(60, y, "Mietvertrag (Auszug)")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(60, y - 16, "Testdaten der ImmoManager-Pro-Testversion – alle Angaben sind frei erfunden.")
    _, cold, service, heating = first_step
    rows = [
        ("Vertragsnummer", t.number), ("Vermieter", t.prop.portfolio), ("Mieter", t.tenant.name),
        ("Mietobjekt", f"{t.unit.label}, {t.prop.street}, {t.prop.postal_code} {t.prop.city}"),
        ("Fläche", f"{t.unit.area:g} m²" if t.unit.area else "–"), ("Mietbeginn", t.start.strftime("%d.%m.%Y")),
        ("Kaltmiete bei Beginn", eur(cold)), ("Vorauszahlung Betriebskosten", eur(service)),
        ("Vorauszahlung Heizkosten", eur(heating)), ("Gesamtmiete", eur(cold + service + heating)),
        ("Mietmodell", {"index": "Indexmiete (VPI)", "stepped": "Staffelmiete"}.get(t.rent_model, "Festmiete")),
        ("Kaution", f"{t.deposit_months} Kaltmieten" if t.deposit_months else "keine"),
    ]
    y -= 56
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(60, y, label)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(230, y, value)
        y -= 18
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
