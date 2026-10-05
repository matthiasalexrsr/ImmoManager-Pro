"""Phase 2: five years of property management, month by month, by the people who do it.

owner        sets up portfolios, accounts and buildings, runs backups
verwalter    units, tenants, contracts, notices, rent adjustments, deposits, utility billing
buchhaltung  payments, bank imports, assigning payments, invoices, expenses, deposit returns
hausmeister  handovers, meters and readings, maintenance cases
steuerberater only reads (reports); every write attempt must be refused
"""

from __future__ import annotations

import calendar
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .core import Client, Findings
from .ledger import Ledger, advances_between, money, monthly_due, step_on
from .world import Tenancy, World, add_months, month_end, months

MARKET_GROWTH = 0.025          # yearly growth of new-letting rents
CPI = {2021: 0.031, 2022: 0.069, 2023: 0.059, 2024: 0.022, 2025: 0.021, 2026: 0.02, 2027: 0.02}
RECOVERABLE = [  # description, key type, share of yearly costs per m² (approx.)
    ("Grundsteuer", "area_sqm", 2.1), ("Gebäudeversicherung", "area_sqm", 2.6), ("Hausmeister", "area_sqm", 3.0),
    ("Müllabfuhr", "unit_count", 0.0), ("Wasser/Abwasser", "person_count", 0.0), ("Allgemeinstrom", "unit_count", 0.0),
]


def german_iban(bank_code: int, account: int) -> str:
    """A German IBAN with correct check digits (ISO 13616, mod 97)."""
    bban = f"{bank_code:08d}{account:010d}"
    check = 98 - int(bban + "131400") % 97          # "DE" = 13 14, then "00"
    return f"DE{check:02d}{bban}"


class Simulation:
    def __init__(self, world: World, users: dict[str, Client], findings: Findings, seed: int):
        self.w, self.u, self.f = world, users, findings
        self.rnd = random.Random(seed + 1)
        self.ledger = Ledger()
        self.created: set[int] = set()        # id() of tenancies with a contract
        self.notified: set[int] = set()
        self.closed: set[int] = set()
        self.costs = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))  # property id -> year -> item -> amount
        self.billed: set[tuple[str, int]] = set()
        self.meters: dict[str, str] = {}      # unit id -> meter id
        self.meter_values: dict[str, float] = {}
        self.read_meters: set[str] = set()     # meters with at least one reading stored in the app
        self.pending_adjustments: list[tuple[str, Tenancy, tuple]] = []
        self.csv_bookings: list[tuple[str, Tenancy, Decimal]] = []
        self.arrears_until: dict[int, date] = {}
        self.cash_account: dict[str, str] = {}

    # --- helpers -------------------------------------------------------------------------------
    def market(self, base: float, day: date) -> float:
        years = (self.w.end - day).days / 365.25
        return round(base / ((1 + MARKET_GROWTH) ** max(years, 0)), 2)

    def owner(self) -> Client:
        return self.u["owner"]

    # --- setup ---------------------------------------------------------------------------------
    def setup(self) -> None:
        self.f.phase = "aufbau"
        o, v = self.u["owner"], self.u["verwalter"]
        for n, pf in enumerate(self.w.portfolios):
            created = o.ok("POST", "/portfolios", {"name": pf.name, "owner_name": pf.owner}, area="Aufbau")
            pf.id = created["id"]
            account = o.ok("POST", "/accounts", {"portfolio_id": pf.id, "name": f"Mietkonto {pf.owner}",
                                                 "bank_name": "Sparkasse", "iban": german_iban(37040044, 532013000 + n),
                                                 "account_type": "bank", "opening_balance": 25000}, area="Aufbau")
            pf.account_id = account["id"]
            cash = o.ok("POST", "/accounts", {"portfolio_id": pf.id, "name": f"Barkasse {pf.owner}",
                                              "account_type": "cash", "opening_balance": 0}, area="Aufbau")
            self.cash_account[pf.id] = cash["id"] if cash else pf.account_id
            for name, kind in [("Mieteinnahmen", "income"), ("Betriebskosten", "expense"), ("Instandhaltung", "expense"),
                               ("Verwaltung", "expense"), ("Nebenkostennachzahlung", "income")]:
                cat = o.ok("POST", "/categories", {"portfolio_id": pf.id, "name": name, "category_type": kind}, area="Aufbau")
                pf.categories[name] = cat["id"] if cat else None
            for prop in pf.properties:
                body = {"portfolio_id": pf.id, "name": prop.name, "property_type": prop.kind, "city": prop.city,
                        "postal_code": prop.postal_code, "address_line": prop.street, "country": "DE",
                        "year_built": prop.year_built,
                        "living_area_sqm": sum(u.area or 0 for u in prop.units if u.kind == "flat") or None}
                prop.id = o.ok("POST", "/properties", body, area="Aufbau")["id"]
                for unit in prop.units:
                    created = v.ok("POST", "/units", {
                        "property_id": prop.id, "label": unit.label, "unit_type": unit.unit_type, "area_sqm": unit.area,
                        "rooms": unit.rooms, "floor": unit.floor, "person_count": unit.persons, "status": "vacant",
                        "cold_rent": self.market(unit.cold, self.w.start), "service_charge_advance": unit.service,
                        "heating_advance": unit.heating}, area="Aufbau")
                    unit.id = created["id"] if created else None
                    if unit.kind in ("flat", "commercial") and unit.id:
                        meter = self.u["hausmeister"].ok("POST", "/meters", {
                            "unit_id": unit.id, "meter_type": "water_cold", "serial_number": f"WZ-{unit.id[:8]}",
                            "installation_date": "2019-01-01"}, area="Zähler")
                        if meter:
                            self.meters[unit.id] = meter["id"]
                            self.meter_values[unit.id] = round(self.rnd.uniform(50, 400), 2)
        # tenancies that began before the test period
        for t in sorted(self.w.tenancies, key=lambda x: x.start):
            if t.start < self.w.start:
                self.move_in(t)

    # --- tenancies -------------------------------------------------------------------------------
    def move_in(self, t: Tenancy) -> None:
        v = self.u["verwalter"]
        prop = self.w.property_of(t.unit)
        cold = self.market(t.unit.cold, t.start)
        # the unit's rent is the default for the next contract
        v.call("PATCH", f"/units/{t.unit.id}", {"cold_rent": cold, "service_charge_advance": t.unit.service,
                                               "heating_advance": t.unit.heating, "status": "occupied"}, area="Einzug")
        if not t.tenant.id:
            created = v.ok("POST", "/tenants", {"full_name": t.tenant.name, "email": t.tenant.email,
                                                "phone": t.tenant.phone,
                                                "payment_method": "sepa" if t.behaviour == "sepa_return" else "transfer",
                                                "sepa_mandate": t.tenant.iban if t.behaviour == "sepa_return" else None},
                           area="Einzug")
            t.tenant.id = created["id"] if created else None
        if t.deposit:
            t.deposit = round(cold * 3, 2)       # three cold rents at the start (§ 551 BGB)
        notice_known = t.end is not None and add_months(t.end, -3) < self.w.start
        contract = v.ok("POST", "/contracts", {
            "contract_number": t.number, "property_id": prop.id, "unit_id": t.unit.id, "tenant_id": t.tenant.id,
            "start_date": t.start.isoformat(), "end_date": t.end.isoformat() if notice_known else None,
            "status": "terminated" if notice_known else "active", "notice_period": "3 Monate",
            "deposit_amount": t.deposit, "index_rent": t.rent_model,
            "persons": t.unit.persons}, area="Einzug")
        if not contract:
            return
        t.id = contract["id"]
        self.created.add(id(t))
        if notice_known:
            self.notified.add(id(t))
        t.steps = [(t.start, cold, t.unit.service, t.unit.heating)]
        periods = v.ok("GET", f"/contracts/{t.id}/rent-periods", area="Mietverlauf") or []
        self.f.check(len(periods) == 1 and abs(periods[0]["cold_rent"] - cold) < 0.005, "FALSCH", "Mietverlauf",
                     f"{t.number}: Startmiete {cold} nicht als Mietstand übernommen", periods)
        if t.deposit:
            v.call("POST", "/deposits", {"contract_id": t.id, "amount": t.deposit, "status": "held",
                                         "held_date": t.start.isoformat()}, area="Kaution")
        if t.start >= self.w.start:
            self.u["hausmeister"].call("POST", "/handover-protocols", {
                "contract_id": t.id, "unit_id": t.unit.id, "protocol_type": "move_in",
                "protocol_date": t.start.isoformat(), "key_count": self.rnd.randint(2, 5), "overall_condition": "good",
                "status": "completed"}, area="Übergabe")

    def give_notice(self, t: Tenancy, today: date) -> None:
        self.notified.add(id(t))
        self.u["verwalter"].call("PATCH", f"/contracts/{t.id}", {"end_date": t.end.isoformat(), "status": "terminated"},
                                 area="Kündigung")

    def move_out(self, t: Tenancy) -> None:
        self.closed.add(id(t))
        v, b, h = self.u["verwalter"], self.u["buchhaltung"], self.u["hausmeister"]
        if t.unit.kind != "parking" or t.combined_with is None:
            h.call("POST", "/handover-protocols", {
                "contract_id": t.id, "unit_id": t.unit.id, "protocol_type": "move_out",
                "protocol_date": t.end.isoformat(), "key_count": 3,
                "overall_condition": self.rnd.choice(["good", "fair", "poor"]), "status": "completed"}, area="Übergabe")
        v.call("PATCH", f"/units/{t.unit.id}", {"status": "vacant"}, area="Auszug")
        if t.deposit:
            deposits = [d for d in (b.ok("GET", "/deposits", area="Kaution") or []) if d.get("contract_id") == t.id]
            if deposits:
                deduction = self.rnd.choice([0, 0, 0, 150.0, 480.5])
                returned = (t.end + timedelta(days=self.rnd.randint(20, 120)))
                b.call("PATCH", f"/deposits/{deposits[0]['id']}", {
                    "status": "returned" if not deduction else "partially_returned",
                    "return_date": min(returned, self.w.end).isoformat(), "deductions": deduction or None,
                    "deduction_reason": "Schönheitsreparaturen" if deduction else None}, area="Kaution")

    # --- money -----------------------------------------------------------------------------------
    def due(self, t: Tenancy, month: date) -> Decimal:
        total = monthly_due(t, month)
        if t.combined_with and id(t.combined_with) in self.created:
            total += monthly_due(t.combined_with, month)
        return total

    def payments(self, month: date) -> None:
        b = self.u["buchhaltung"]
        for t in self.w.tenancies:
            if id(t) not in self.created or t.behaviour == "combined":
                continue
            last = t.end or self.w.end
            if month > last or month_end(month) < t.start:
                continue
            due = self.due(t, month)
            if due <= 0:
                continue
            amount, day, text = due, self.rnd.randint(1, 4), f"Miete {month:%m/%Y} {t.number}"
            kind = t.behaviour
            if kind == "late":
                day = self.rnd.randint(8, 27)
            elif kind == "partial" and self.rnd.random() < 0.3:
                amount = money(due * Decimal(str(self.rnd.choice([0.5, 0.8, 0.95]))))
            elif kind == "arrears":
                stop = self.arrears_until.setdefault(id(t), add_months(max(t.start, self.w.start), self.rnd.randint(4, 30)))
                if stop <= month < add_months(stop, 3):
                    continue
                if month == add_months(stop, 3):
                    amount = due * 4
                    text = f"Nachzahlung Mietrückstand {t.number}"
            elif kind == "overpay" and month.month == 6:
                amount = due * 2
            elif kind == "quarterly":
                if month.month % 3:
                    continue
                amount = due * 3
            elif kind == "typo" and month.month == 3 and month.year % 2:
                digits = list(f"{due:.2f}")
                digits[0], digits[1] = digits[1], digits[0]
                amount = money("".join(digits)) if digits[0] != "." else due
                text += " (Tippfehler im Betrag)"
            elif kind == "silent_stop" and month >= add_months(last.replace(day=1), -6):
                continue
            when = month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))
            if when > self.w.end or when < t.start - timedelta(days=5):
                continue
            pf = self.w.portfolio_of(t.unit)
            account = self.cash_account[pf.id] if kind == "cash" else pf.account_id
            if kind == "punctual" and month.month % 3 == 0 and self.rnd.random() < 0.15:
                # comes in with the quarterly bank import, without tenant; assigned by hand below
                self.csv_bookings.append((f"{when.isoformat()};{amount:.2f};{text}", t, amount))
                continue
            body = {"account_id": account, "property_id": self.w.property_of(t.unit).id, "tenant_id": t.tenant.id,
                    "booking_date": when.isoformat(), "amount": float(amount), "status": "booked",
                    "category_id": pf.categories.get("Mieteinnahmen"), "payment_text": text}
            if self.rnd.random() < 0.5 and not t.combined_with:
                body["unit_id"] = t.unit.id
            created = b.ok("POST", "/bookings", body, area="Zahlung")
            if created:
                self.ledger.pay(t.tenant.id, amount)
            if kind == "sepa_return" and month.month in (2, 9) and self.rnd.random() < 0.5 and created:
                back = dict(body, booking_date=(when + timedelta(days=4)).isoformat(), amount=-float(amount),
                            payment_text=f"Rücklastschrift {text}")
                if b.ok("POST", "/bookings", back, area="Rücklastschrift"):
                    self.ledger.pay(t.tenant.id, -amount)

    def bank_import(self, month: date) -> None:
        """Quarterly CSV import of the bank statement; imported rows have no tenant and get assigned by hand."""
        if not self.csv_bookings:
            return
        b = self.u["buchhaltung"]
        by_account: dict[str, list] = defaultdict(list)
        for line, t, amount in self.csv_bookings:
            by_account[self.w.portfolio_of(t.unit).account_id].append((line, t, amount))
        self.csv_bookings = []
        for account, rows in by_account.items():
            csv = "date;amount;text\n" + "\n".join(line for line, _, _ in rows)
            result = b.ok("POST", "/reports/bookings/import", {"account_id": account, "csv_content": csv}, area="Bankimport")
            if not result:
                continue
            self.f.check(result.get("imported") == len(rows), "FALSCH", "Bankimport",
                         f"{result.get('imported')} von {len(rows)} Zeilen importiert", result.get("details", {}).get("errors"))
            imported = [x["bookingId"] for x in result.get("details", {}).get("imported", [])]
            for booking_id, (_, t, amount) in zip(imported, rows):
                if self.rnd.random() < 0.1:
                    self.ledger.book(amount)    # stays open for the review list
                    continue
                if b.ok("PATCH", f"/bookings/{booking_id}", {"tenant_id": t.tenant.id, "status": "booked",
                                                             "property_id": self.w.property_of(t.unit).id},
                        area="Zuordnung"):
                    self.ledger.pay(t.tenant.id, amount)
                else:
                    self.ledger.book(amount)

    def expenses(self, month: date) -> None:
        b = self.u["buchhaltung"]
        for pf in self.w.portfolios:
            for prop in pf.properties:
                area = sum(u.area or 40 for u in prop.units)
                items = [("Hausmeister", round(area * 3.0 / 12 * self.rnd.uniform(0.9, 1.1), 2), "Betriebskosten"),
                         ("Allgemeinstrom", round(len(prop.units) * 6.5 * self.rnd.uniform(0.8, 1.2), 2), "Betriebskosten"),
                         ("Müllabfuhr", round(len(prop.units) * 14 * self.rnd.uniform(0.95, 1.05), 2), "Betriebskosten"),
                         ("Wasser/Abwasser", round(sum(u.persons or 1 for u in prop.units) * 18.0, 2), "Betriebskosten")]
                if month.month in (2, 5, 8, 11):
                    items.append(("Grundsteuer", round(area * 2.1 / 4, 2), "Betriebskosten"))
                if month.month == 1:
                    items.append(("Gebäudeversicherung", round(area * 2.6, 2), "Betriebskosten"))
                    items.append(("Verwaltungsgebühr", round(len(prop.units) * 300, 2), "Verwaltung"))
                for description, amount, category in items:
                    created = b.ok("POST", "/bookings", {
                        "account_id": pf.account_id, "property_id": prop.id, "category_id": pf.categories.get(category),
                        "booking_date": month.replace(day=15).isoformat(), "amount": -amount, "status": "booked",
                        "payment_text": f"{description} {month:%m/%Y}"}, area="Ausgaben")
                    if created:
                        self.ledger.book(-amount)
                        if category == "Betriebskosten":
                            self.costs[prop.id][month.year][description] += money(amount)

    # --- rent changes ------------------------------------------------------------------------------
    def adjustments(self, month: date) -> None:
        v = self.u["verwalter"]
        for t in self.w.tenancies:
            if id(t) not in self.created or not t.steps or (t.end and t.end < month):
                continue
            last_from, cold, service, heating = t.steps[-1]
            months_since = (month.year - last_from.year) * 12 + month.month - last_from.month
            new_cold = None
            if t.rent_model == "index" and month.month == 1 and months_since >= 12:
                new_cold = round(cold * (1 + CPI.get(month.year - 1, 0.02)), 2)
                kind = "index"
            elif t.rent_model == "stepped" and months_since >= 12 and month.month == self.anniversary(t):
                new_cold = round(cold + self.rnd.choice([15, 20, 25, 30]), 2)
                kind = "stepped"
            elif t.rent_model == "fixed" and months_since >= 36 and month.month == 7:
                new_cold = round(cold * 1.12, 2)          # §558 BGB, within the 15/20 % cap
                kind = "comparative"
            if new_cold is None:
                continue
            adj = v.ok("POST", "/rent-adjustments", {
                "contract_id": t.id, "adjustment_type": kind, "effective_date": month.isoformat(),
                "previous_rent": cold, "new_rent": new_cold,
                "increase_percent": round((new_cold / cold - 1) * 100, 2)}, area="Mietanpassung")
            if not adj:
                continue
            fate = self.rnd.random()
            if fate < 0.08:
                v.call("PATCH", f"/rent-adjustments/{adj['id']}", {"status": "rejected"}, area="Mietanpassung")
                continue
            if fate < 0.2:
                self.pending_adjustments.append((adj["id"], t, (month, new_cold, service, heating)))
                continue
            self.apply(adj["id"], t, (month, new_cold, service, heating))

    @staticmethod
    def anniversary(t: Tenancy) -> int:
        """Month a stepped rent rises: the start month, or the next one for a start after the 1st."""
        return add_months(t.start.replace(day=1), 1 if t.start.day > 1 else 0).month

    def apply(self, adj_id: str, t: Tenancy, step: tuple) -> None:
        result = self.u["verwalter"].ok("POST", f"/rent-adjustments/{adj_id}/apply", {}, area="Mietanpassung")
        if result:
            t.steps.append(step)
            if result.get("warnings"):
                self.f.add("HINWEIS", "Mietanpassung", f"{t.number}: Warnung beim Anwenden", result["warnings"])

    def late_applications(self) -> None:
        for adj_id, t, step in self.pending_adjustments:
            self.apply(adj_id, t, step)
        self.pending_adjustments = []

    # --- utility billing -----------------------------------------------------------------------------
    def billing(self, year: int) -> None:
        v = self.u["verwalter"]
        start, end = date(year, 1, 1), date(year, 12, 31)
        for pf in self.w.portfolios:
            for prop in pf.properties:
                if (prop.id, year) in self.billed or not self.costs[prop.id].get(year):
                    continue
                self.billed.add((prop.id, year))
                if start < self.w.start:
                    continue        # costs of a part year: skip, as a new manager would
                period = v.ok("POST", "/billing/periods", {"property_id": prop.id, "label": f"NK {year} {prop.name}",
                                                           "start_date": start.isoformat(), "end_date": end.isoformat()},
                              area="NK-Abrechnung")
                if not period:
                    continue
                keys = {}
                for key_type, name in [("area_sqm", "Wohnfläche"), ("unit_count", "Einheiten"), ("person_count", "Personen")]:
                    key = v.ok("POST", "/billing/allocation-keys", {"property_id": prop.id, "name": f"{name} {year}",
                                                                   "key_type": key_type}, area="NK-Abrechnung")
                    keys[key_type] = key["id"] if key else None
                total = Decimal("0")
                by_persons = []
                for description, amount in self.costs[prop.id][year].items():
                    key_type = dict((d, k) for d, k, _ in RECOVERABLE).get(description, "area_sqm")
                    item = v.ok("POST", "/billing/cost-items", {
                        "billing_period_id": period["id"], "description": description, "amount": float(amount),
                        "allocation_key_id": keys[key_type], "is_recoverable": True}, area="NK-Abrechnung")
                    if item:
                        total += amount
                        if key_type == "person_count":
                            by_persons.append(item["id"])
                v.call("GET", f"/billing/periods/{period['id']}/preflight", area="NK-Abrechnung")
                status, generated = v.call("POST", f"/billing/periods/{period['id']}/generate", {},
                                           expect=(200, 201, 400, 409, 422), area="NK-Abrechnung")
                if status == 400:
                    # what a manager does: fill in the missing areas and person counts, then try again
                    self.complete_units(prop)
                    status, generated = v.call("POST", f"/billing/periods/{period['id']}/generate", {},
                                               expect=(200, 201, 400, 409, 422), area="NK-Abrechnung")
                if status == 400 and "zusammen 0" in str(generated) and by_persons:
                    # nobody lives here (shops only): the manager distributes those costs by area instead
                    for item_id in by_persons:
                        v.call("PATCH", f"/billing/cost-items/{item_id}", {"allocation_key_id": keys["area_sqm"]},
                               area="NK-Abrechnung")
                    status, generated = v.call("POST", f"/billing/periods/{period['id']}/generate", {},
                                               expect=(200, 201, 400, 409, 422), area="NK-Abrechnung")
                if status not in (200, 201):
                    self.f.add("FALSCH", "NK-Abrechnung",
                               f"{prop.name} {year}: Erzeugen auch nach Ergänzen der Stammdaten abgelehnt ({status})",
                               generated)
                    continue
                statements = [s for s in (v.ok("GET", f"/billing/statements?billing_period_id={period['id']}",
                                                area="NK-Abrechnung") or []) if s.get("billing_period_id") == period["id"]]
                billed_total = sum(Decimal(str(s["total_cost"])) for s in statements)
                self.f.check(abs(billed_total - total) <= Decimal("0.05"), "FALSCH", "NK-Abrechnung",
                             f"{prop.name} {year}: Summe der Einzelabrechnungen {billed_total} ≠ Kosten {total}")
                for s in statements:
                    if not s.get("contract_id"):
                        continue
                    t = next((x for x in self.w.tenancies if x.id == s["contract_id"]), None)
                    if not t or not s.get("usage_start"):
                        continue
                    expected = advances_between(t, date.fromisoformat(s["usage_start"][:10]),
                                                date.fromisoformat(s["usage_end"][:10]))
                    self.f.check(abs(Decimal(str(s["advance_paid"])) - expected) <= Decimal("0.05"), "FALSCH",
                                 "NK-Abrechnung", f"{t.number} {year}: Vorauszahlungen {s['advance_paid']} statt {expected}")
                v.call("POST", f"/billing/periods/{period['id']}/submit-review", {}, expect=(200, 201, 400, 409),
                       area="NK-Abrechnung")
                v.call("POST", f"/billing/periods/{period['id']}/finalize", {}, expect=(200, 201, 400, 409),
                       area="NK-Abrechnung")
                v.call("POST", f"/billing/periods/{period['id']}/create-receivables", {}, expect=(200, 201, 400, 409),
                       area="NK-Abrechnung")
                # big back payment: raise the advances from next month (manual rent period)
                for s in statements:
                    t = next((x for x in self.w.tenancies if x.id == s.get("contract_id")), None)
                    if not t or (t.end and t.end.year <= year) or s["balance"] <= 0:
                        continue
                    current = step_on(t, date(year + 1, 4, 1))
                    if current and s["balance"] > 0.1 * (current[1] + current[2]) * 12:
                        raise_from = date(year + 1, 5, 1)
                        extra = round(s["balance"] / 12, 2)
                        new = (raise_from, current[0], round(current[1] + extra, 2), current[2])
                        if raise_from <= self.w.end and v.ok("POST", f"/contracts/{t.id}/rent-periods", {
                                "contract_id": t.id, "valid_from": raise_from.isoformat(), "cold_rent": current[0],
                                "service_charge_advance": new[2], "heating_advance": current[2],
                                "notes": f"Anpassung Vorauszahlung nach NK {year}"}, area="Mietverlauf"):
                            t.steps.append(new)

    def complete_units(self, prop) -> None:
        v = self.u["verwalter"]
        for unit in prop.units:
            patch = {}
            if unit.area is None and unit.kind in ("flat", "commercial"):
                unit.area = 45.0 if unit.kind == "flat" else 80.0
                patch["area_sqm"] = unit.area
            if unit.persons is None and unit.kind in ("flat", "commercial"):
                unit.persons = 2 if unit.kind == "flat" else 0     # a shop: 0 persons, entered on purpose
                patch["person_count"] = unit.persons
            if patch:
                v.call("PATCH", f"/units/{unit.id}", patch, area="Stammdaten")

    # --- the technician ------------------------------------------------------------------------------
    def caretaking(self, month: date) -> None:
        h, b = self.u["hausmeister"], self.u["buchhaltung"]
        for pf in self.w.portfolios:
            for prop in pf.properties:
                if self.rnd.random() < 0.12:
                    unit = self.rnd.choice(prop.units)
                    cost = round(self.rnd.uniform(80, 4500), 2)
                    h.call("POST", "/maintenance", {
                        "property_id": prop.id, "unit_id": unit.id, "title": self.rnd.choice(
                            ["Heizung ausgefallen", "Wasserschaden Bad", "Fenster undicht", "Klingel defekt", "Schimmel"]),
                        "priority": self.rnd.choice(["low", "medium", "high", "urgent"]),
                        "status": self.rnd.choice(["open", "in_progress", "completed", "completed"]),
                        "estimated_cost": cost, "contractor": "Handwerk Schmidt GmbH",
                        "due_date": (month + timedelta(days=21)).isoformat()}, area="Wartung")
                    inv = b.ok("POST", "/invoices", {
                        "property_id": prop.id, "supplier": "Handwerk Schmidt GmbH",
                        "invoice_date": (month + timedelta(days=10)).isoformat(),
                        "due_date": (month + timedelta(days=40)).isoformat(), "net_amount": round(cost / 1.19, 2),
                        "vat_rate": 19, "vat_amount": round(cost - cost / 1.19, 2), "gross_amount": cost,
                        "category": "maintenance", "status": "paid" if month < add_months(self.w.end, -2) else "open",
                        "invoice_number": f"RE-{month:%Y%m}-{self.rnd.randint(1000, 9999)}"}, area="Rechnung")
                    if inv and inv.get("status") == "paid":
                        if b.ok("POST", "/bookings", {
                                "account_id": pf.account_id, "property_id": prop.id,
                                "category_id": pf.categories.get("Instandhaltung"),
                                "booking_date": (month + timedelta(days=20)).isoformat(), "amount": -cost,
                                "status": "booked", "payment_text": f"Rechnung {inv.get('invoice_number')}"}, area="Ausgaben"):
                            self.ledger.book(-cost)
        if month.month == 12:   # yearly meter reading
            for unit_id, meter_id in self.meters.items():
                step = round(self.rnd.uniform(20, 120), 2)
                value = self.meter_values[unit_id] + step
                if self.rnd.random() < 0.02:
                    value = self.meter_values[unit_id] - 15     # read wrong: lower than last year
                status, _ = h.call("POST", f"/meters/{meter_id}/readings", {
                    "meter_id": meter_id, "reading_date": month_end(month).isoformat(), "value": value,
                    "recorded_by": "hausmeister"}, expect=(200, 201, 400, 422), area="Zähler")
                if value < self.meter_values[unit_id]:
                    # only a reading the app knows can be compared: the first one has nothing before it
                    if unit_id in self.read_meters:
                        self.f.check(status in (400, 422), "LÜCKE", "Zähler",
                                     "Zählerstand kleiner als im Vorjahr ohne Rückfrage angenommen")
                else:
                    self.meter_values[unit_id] = value
                if status in (200, 201):
                    self.read_meters.add(unit_id)

    # --- the month -------------------------------------------------------------------------------------
    def month(self, month: date) -> None:
        self.f.phase = f"{month:%Y-%m}"
        for t in sorted(self.w.tenancies, key=lambda x: x.start):
            if id(t) not in self.created and t.start <= month_end(month) and t.start >= self.w.start:
                self.move_in(t)
        for t in self.w.tenancies:
            if id(t) in self.created and t.end and id(t) not in self.notified and add_months(t.end, -3) <= month_end(month):
                self.give_notice(t, month)
        self.late_applications()
        self.adjustments(month)
        self.payments(month)
        self.expenses(month)
        self.caretaking(month)
        if month.month % 3 == 0:
            self.bank_import(month)
        if month.month == 4:
            self.billing(month.year - 1)
        for t in self.w.tenancies:
            if id(t) in self.created and id(t) not in self.closed and t.end and t.end <= month_end(month):
                self.move_out(t)
        if month.month in (3, 9):
            self.u["verwalter"].call("POST", "/escalation/run", {}, expect=(200, 201, 204), area="Mahnwesen")
        # the tax advisor looks, and must not be able to change anything
        s = self.u["steuerberater"]
        s.call("GET", "/reports/summary", area="Lesen")
        status, _ = s.call("POST", "/bookings", {"account_id": self.w.portfolios[0].account_id,
                                                  "booking_date": month.isoformat(), "amount": 1.0},
                           expect=(401, 403), area="Rechte")
        if status in (200, 201):
            self.f.add("RECHTE", "Rechte", "Nur-Lesen-Benutzer konnte eine Buchung anlegen")

    def run(self, on_month=None) -> None:
        self.setup()
        for month in months(self.w.start, self.w.end):
            self.month(month)
            if on_month:
                on_month(month)
        self.late_applications()
