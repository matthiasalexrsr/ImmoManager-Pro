"""Phase 3: implausible and invalid input, on a copy of the simulated data.

Each case says what a careful property management program should do:
  reject  refuse with a 4xx and a message (accepting it is a LÜCKE, a 5xx is KRITISCH)
  warn    may be accepted, but should not pass silently (accepting it is a HINWEIS)
After an accepted case the stored record is read back: numbers must come back as sent
(no silent rounding or clipping) and text must not be altered.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .core import Client, Findings, Server, setup_users

LONG = "Ä" * 5000


def references(c: Client) -> dict:
    contracts = [x for x in c.all("/contracts") if x["status"] == "active"]
    contract = contracts[0]
    other = next(x for x in contracts if x["tenant_id"] != contract["tenant_id"] and x["property_id"] != contract["property_id"])
    units = c.all("/units")
    accounts = c.all("/accounts")
    periods = c.ok("GET", f"/contracts/{contract['id']}/rent-periods") or []
    meters = c.all("/meters")
    return {"contract": contract, "other": other, "unit": next(u for u in units if u["id"] == contract["unit_id"]),
            "free_unit": next((u for u in units if u["status"] == "vacant"), units[-1]),
            "account": accounts[0]["id"], "rent": periods[-1]["cold_rent"] if periods else 500,
            "meter": meters[0]["id"] if meters else None}


def cases(r: dict) -> list[tuple[str, str, str, str, dict, str]]:
    """(area, case, method, path, body, expectation)"""
    c, o, u, free, acc = r["contract"], r["other"], r["unit"], r["free_unit"], r["account"]
    rent = r["rent"]
    today = date.today()
    unit = {"property_id": u["property_id"], "label": "Test", "unit_type": "Wohnung"}
    contract = {"contract_number": "X-1", "property_id": free["property_id"], "unit_id": free["id"],
                "tenant_id": c["tenant_id"], "start_date": "2026-01-01"}
    booking = {"account_id": acc, "booking_date": "2026-05-03", "amount": 100.0}
    adj = {"contract_id": c["id"], "adjustment_type": "index", "effective_date": "2027-01-01",
           "previous_rent": rent, "new_rent": round(rent * 1.03, 2)}
    out = [
        # units
        ("Einheit", "negative Kaltmiete", "POST", "/units", {**unit, "cold_rent": -500}, "reject"),
        ("Einheit", "Fläche 0 m²", "POST", "/units", {**unit, "area_sqm": 0}, "reject"),
        ("Einheit", "negative Fläche", "POST", "/units", {**unit, "area_sqm": -10}, "reject"),
        ("Einheit", "Fläche 10 Mio. m²", "POST", "/units", {**unit, "area_sqm": 1e7}, "warn"),
        ("Einheit", "Kaltmiete 1 Billion €", "POST", "/units", {**unit, "cold_rent": 1e12}, "warn"),
        ("Einheit", "Kaltmiete als Text „abc“", "POST", "/units", {**unit, "cold_rent": "abc"}, "reject"),
        ("Einheit", "Miete im deutschen Format „1.200,50“", "POST", "/units", {**unit, "cold_rent": "1.200,50"}, "reject"),
        ("Einheit", "negative Personenzahl", "POST", "/units", {**unit, "person_count": -2}, "reject"),
        ("Einheit", "25 Zimmer auf 30 m²", "POST", "/units", {**unit, "area_sqm": 30, "rooms": 25}, "warn"),
        ("Einheit", "leere Bezeichnung", "POST", "/units", {**unit, "label": ""}, "reject"),
        ("Einheit", "Bezeichnung nur Leerzeichen", "POST", "/units", {**unit, "label": "   "}, "reject"),
        ("Einheit", "5000 Zeichen Bezeichnung", "POST", "/units", {**unit, "label": LONG}, "warn"),
        ("Einheit", "unbekannte Immobilie", "POST", "/units", {**unit, "property_id": "gibt-es-nicht"}, "reject"),
        ("Einheit", "Nullbyte im Text", "POST", "/units", {**unit, "label": "WE\u00001"}, "reject"),
        # contracts
        ("Vertrag", "Ende vor Beginn", "POST", "/contracts", {**contract, "end_date": "2025-01-01"}, "reject"),
        ("Vertrag", "Beginn im Jahr 1800", "POST", "/contracts", {**contract, "start_date": "1800-01-01"}, "reject"),
        ("Vertrag", "Beginn im Jahr 2200", "POST", "/contracts", {**contract, "start_date": "2200-01-01"}, "reject"),
        ("Vertrag", "Überschneidung mit laufendem Vertrag", "POST", "/contracts",
         {**contract, "unit_id": u["id"], "property_id": u["property_id"], "contract_number": "X-2"}, "reject"),
        ("Vertrag", "doppelte Vertragsnummer", "POST", "/contracts", {**contract, "contract_number": c["contract_number"]},
         "reject"),
        ("Vertrag", "negative Kaution", "POST", "/contracts", {**contract, "deposit_amount": -100}, "reject"),
        ("Vertrag", "Kaution über drei Kaltmieten (§ 551 BGB)", "POST", "/contracts",
         {**contract, "deposit_amount": round((free.get("cold_rent") or rent) * 5, 2)}, "warn"),
        ("Vertrag", "Einheit gehört zu anderer Immobilie", "POST", "/contracts",
         {**contract, "property_id": o["property_id"]}, "reject"),
        ("Vertrag", "unbekannter Mieter", "POST", "/contracts", {**contract, "tenant_id": "fehlt"}, "reject"),
        ("Vertrag", "unbekannter Status", "POST", "/contracts", {**contract, "status": "vielleicht"}, "reject"),
        ("Vertrag", "Datum im deutschen Format", "POST", "/contracts", {**contract, "start_date": "01.02.2026"}, "reject"),
        ("Vertrag", "negative Personenzahl", "POST", "/contracts", {**contract, "persons": -1}, "reject"),
        ("Vertrag", "Ende vor Beginn per Änderung", "PATCH", f"/contracts/{c['id']}",
         {"end_date": "1999-12-31"}, "reject"),
        # tenants
        ("Mieter", "leerer Name", "POST", "/tenants", {"full_name": ""}, "reject"),
        ("Mieter", "Name nur Leerzeichen", "POST", "/tenants", {"full_name": "   "}, "reject"),
        ("Mieter", "E-Mail ohne @", "POST", "/tenants", {"full_name": "Test", "email": "kein-email"}, "reject"),
        ("Mieter", "Telefon „abc“", "POST", "/tenants", {"full_name": "Test", "phone": "abc"}, "warn"),
        ("Mieter", "SEPA-Mandat mit ungültiger IBAN", "POST", "/tenants",
         {"full_name": "Test", "payment_method": "sepa", "sepa_mandate": "DE00123"}, "warn"),
        ("Mieter", "Skript im Namen", "POST", "/tenants", {"full_name": "<img src=x onerror=alert(1)>"}, "warn"),
        ("Mieter", "Emoji und Rechts-nach-links-Schrift", "POST", "/tenants", {"full_name": "Ayşe 🏠 محمد"}, "accept"),
        # bookings
        ("Buchung", "Betrag 0", "POST", "/bookings", {**booking, "amount": 0}, "reject"),
        ("Buchung", "Betrag 1 Billion €", "POST", "/bookings", {**booking, "amount": 1e12}, "warn"),
        ("Buchung", "Bruchteil eines Cents", "POST", "/bookings", {**booking, "amount": 100.005}, "warn"),
        ("Buchung", "Datum im Jahr 1900", "POST", "/bookings", {**booking, "booking_date": "1900-01-01"}, "reject"),
        ("Buchung", "Datum im Jahr 2100", "POST", "/bookings", {**booking, "booking_date": "2100-01-01"}, "reject"),
        ("Buchung", "unbekanntes Konto", "POST", "/bookings", {**booking, "account_id": "fehlt"}, "reject"),
        ("Buchung", "unbekannter Mieter", "POST", "/bookings", {**booking, "tenant_id": "fehlt"}, "reject"),
        ("Buchung", "Einheit gehört nicht zur Immobilie", "POST", "/bookings",
         {**booking, "property_id": o["property_id"], "unit_id": u["id"]}, "reject"),
        ("Buchung", "Betrag als Wahrheitswert", "POST", "/bookings", {**booking, "amount": True}, "reject"),
        ("Buchung", "Betrag „1.200,50“", "POST", "/bookings", {**booking, "amount": "1.200,50"}, "reject"),
        # payment split
        ("Zahlungszuordnung", "an Vertrag eines anderen Mieters", "PUT", "/bookings/{booking}/allocations",
         [{"contract_id": o["id"], "amount": 50}], "reject"),
        ("Zahlungszuordnung", "mehr als der Betrag", "PUT", "/bookings/{booking}/allocations",
         [{"contract_id": c["id"], "amount": 5000}], "reject"),
        ("Zahlungszuordnung", "negativer Teil einer Zahlung", "PUT", "/bookings/{booking}/allocations",
         [{"contract_id": c["id"], "amount": -50}], "reject"),
        # rent adjustments
        ("Mietanpassung", "neue Miete negativ", "POST", "/rent-adjustments", {**adj, "new_rent": -10}, "reject"),
        ("Mietanpassung", "Erhöhung um 60 % (Kappungsgrenze)", "POST", "/rent-adjustments",
         {**adj, "new_rent": round(rent * 1.6, 2), "adjustment_type": "comparative"}, "warn"),
        ("Mietanpassung", "Senkung als Erhöhung", "POST", "/rent-adjustments", {**adj, "new_rent": round(rent * 0.5, 2)},
         "warn"),
        ("Mietanpassung", "wirksam vor Vertragsbeginn", "POST", "/rent-adjustments",
         {**adj, "effective_date": "1990-01-01"}, "reject"),
        ("Mietanpassung", "wirksam am 15. eines Monats", "POST", "/rent-adjustments",
         {**adj, "effective_date": "2027-01-15"}, "warn"),
        ("Mietanpassung", "unbekannter Vertrag", "POST", "/rent-adjustments", {**adj, "contract_id": "fehlt"}, "reject"),
        # manual rent period
        ("Mietverlauf", "Mietstand mitten im Monat", "POST", f"/contracts/{c['id']}/rent-periods",
         {"contract_id": c["id"], "valid_from": "2027-02-14", "cold_rent": rent}, "warn"),
        ("Mietverlauf", "negativer Mietstand", "POST", f"/contracts/{c['id']}/rent-periods",
         {"contract_id": c["id"], "valid_from": "2027-03-01", "cold_rent": -1}, "reject"),
        # deposits
        ("Kaution", "negativer Betrag", "POST", "/deposits", {"contract_id": c["id"], "amount": -50}, "reject"),
        ("Kaution", "Abzüge höher als Kaution", "POST", "/deposits",
         {"contract_id": c["id"], "amount": 100, "deductions": 500}, "reject"),
        ("Kaution", "Rückzahlung vor Eingang", "POST", "/deposits",
         {"contract_id": c["id"], "amount": 100, "held_date": "2025-01-01", "return_date": "2024-01-01",
          "status": "returned"}, "reject"),
        # invoices
        ("Rechnung", "Brutto ≠ Netto + MwSt", "POST", "/invoices",
         {"supplier": "X", "invoice_date": "2026-01-10", "net_amount": 100, "vat_rate": 19, "vat_amount": 19,
          "gross_amount": 150}, "reject"),
        ("Rechnung", "MwSt-Satz 190 %", "POST", "/invoices",
         {"supplier": "X", "invoice_date": "2026-01-10", "net_amount": 100, "vat_rate": 190, "gross_amount": 290},
         "reject"),
        ("Rechnung", "fällig vor Rechnungsdatum", "POST", "/invoices",
         {"supplier": "X", "invoice_date": "2026-03-10", "due_date": "2026-01-01", "net_amount": 100, "vat_rate": 19,
          "vat_amount": 19, "gross_amount": 119}, "warn"),
        ("Rechnung", "negativer Betrag", "POST", "/invoices",
         {"supplier": "X", "invoice_date": "2026-01-10", "net_amount": -100, "vat_rate": 19, "vat_amount": -19,
          "gross_amount": -119}, "warn"),
        # properties and accounts
        ("Immobilie", "Baujahr 3000", "POST", "/properties",
         {"portfolio_id": "{portfolio}", "name": "T", "property_type": "residential", "year_built": 3000}, "reject"),
        ("Immobilie", "negative Wohnfläche", "POST", "/properties",
         {"portfolio_id": "{portfolio}", "name": "T", "property_type": "residential", "living_area_sqm": -5}, "reject"),
        ("Immobilie", "PLZ „ABCDE“", "POST", "/properties",
         {"portfolio_id": "{portfolio}", "name": "T", "property_type": "residential", "postal_code": "ABCDE",
          "country": "DE"}, "warn"),
        ("Immobilie", "unbekannter Typ", "POST", "/properties",
         {"portfolio_id": "{portfolio}", "name": "T", "property_type": "raumschiff"}, "reject"),
        ("Konto", "IBAN mit falscher Prüfziffer", "POST", "/accounts",
         {"portfolio_id": "{portfolio}", "name": "T", "account_type": "bank", "iban": "DE00370400440532013000"}, "warn"),
        ("Konto", "unbekannte Kontoart", "POST", "/accounts",
         {"portfolio_id": "{portfolio}", "name": "T", "account_type": "bitcoin"}, "reject"),
        # meters
        ("Zähler", "negativer Zählerstand", "POST", "/meters/{meter}/readings",
         {"meter_id": "{meter}", "reading_date": "2026-06-30", "value": -5}, "reject"),
        ("Zähler", "Ablesung in der Zukunft", "POST", "/meters/{meter}/readings",
         {"meter_id": "{meter}", "reading_date": (today + timedelta(days=400)).isoformat(), "value": 99999}, "reject"),
        # utility billing
        ("NK-Abrechnung", "Ende vor Beginn", "POST", "/billing/periods",
         {"property_id": u["property_id"], "label": "T", "start_date": "2025-12-31", "end_date": "2025-01-01"}, "reject"),
        ("NK-Abrechnung", "Zeitraum 24 Monate (§ 556 BGB: max. 12)", "POST", "/billing/periods",
         {"property_id": u["property_id"], "label": "T", "start_date": "2023-01-01", "end_date": "2024-12-31"}, "warn"),
        ("NK-Abrechnung", "unbekannte Schlüsselart", "POST", "/billing/allocation-keys",
         {"property_id": u["property_id"], "name": "T", "key_type": "mondphase"}, "reject"),
        # maintenance and tasks
        ("Wartung", "negative Kosten", "POST", "/maintenance",
         {"property_id": u["property_id"], "title": "T", "estimated_cost": -100}, "reject"),
        ("Aufgabe", "unbekannte Priorität", "POST", "/tasks", {"title": "T", "priority": "sofort!!!"}, "reject"),
        # ids, paging, search
        ("API", "sehr lange ID", "GET", "/contracts/" + "a" * 5000, None, "reject"),
        ("API", "ID mit Pfadsprung", "GET", "/tenants/..%2F..%2Fetc%2Fpasswd", None, "reject"),
        ("API", "limit=-1", "GET", "/bookings?limit=-1", None, "reject"),
        ("API", "limit=100000", "GET", "/bookings?limit=100000", None, "warn"),
        ("API", "skip=-5", "GET", "/bookings?skip=-5", None, "reject"),
        ("API", "Suche mit % und Anführungszeichen", "GET", "/search?q=%25%27%22%3B--", None, "accept"),
        ("API", "Stichtag „gestern“", "GET", f"/tenants/{c['tenant_id']}/account?as_of=gestern", None, "reject"),
    ]
    return out


def run(server: Server, f: Findings) -> None:
    previous = f.phase
    f.phase = "fehldaten"
    server.stop()
    copy = server.clone("fehldaten")
    server.start()
    copy.start()
    try:
        users = setup_users(copy, f)
        c = users["verwalter"]
        refs = references(c)
        portfolio = c.all("/portfolios")[0]["id"]
        booking = c.ok("POST", "/bookings", {"account_id": refs["account"], "tenant_id": refs["contract"]["tenant_id"],
                                             "booking_date": "2026-05-03", "amount": 120.0, "payment_text": "Test"})
        def review_count() -> int:
            return (c.ok("GET", "/review", area="Prüfliste") or {}).get("count", 0)

        for area, name, method, path, body, expectation in cases(refs):
            flagged_before = review_count() if expectation == "warn" else 0
            path = path.replace("{booking}", booking["id"] if booking else "x").replace("{meter}", refs["meter"] or "x")
            if isinstance(body, dict):
                body = {k: (v.replace("{portfolio}", portfolio).replace("{meter}", refs["meter"] or "x")
                            if isinstance(v, str) else v) for k, v in body.items()}
            status, result = c.call(method, path, body, expect=tuple(range(200, 500)), area=area)
            if status is None or status >= 500:
                continue
            accepted = status < 400
            if expectation == "reject" and accepted:
                f.add("LÜCKE", area, f"„{name}“ wird angenommen", result if isinstance(result, dict) else None)
            elif expectation == "warn" and accepted:
                warned = isinstance(result, dict) and (result.get("warnings") or result.get("warning"))
                if not warned and review_count() <= flagged_before:
                    f.add("HINWEIS", area, f"„{name}“ wird ohne Hinweis (auch nicht in der Prüfliste) angenommen")
            elif expectation == "accept" and not accepted:
                f.add("FALSCH", area, f"„{name}“ wird abgelehnt ({status})", result)
            if accepted and method == "POST" and isinstance(result, dict) and isinstance(body, dict):
                for key, sent in body.items():
                    got = result.get(key)
                    if isinstance(sent, float) and isinstance(got, (int, float)) and abs(got - sent) > 1e-9:
                        f.add("HINWEIS", area, f"„{name}“: {key} gespeichert als {got} statt {sent}")
                    if isinstance(sent, str) and isinstance(got, str) and sent.strip() and got != sent and key != "id":
                        f.add("HINWEIS", area, f"„{name}“: Text {key} verändert gespeichert")
            if not accepted and isinstance(result, dict):
                # the UI shows the "msg" parts; English default texts are not understandable for users
                detail = result.get("detail")
                messages = [str(d.get("msg", "")) for d in detail] if isinstance(detail, list) else \
                    [str(detail or (result.get("error") or {}).get("message") or "")]
                english = [m for m in messages if re.search(r"Input should|Field required|value is not|not a valid|"
                                                            r"unable to parse|Not Found|Method Not Allowed", m)]
                f.check(not english, "HINWEIS", area, f"„{name}“: Fehlermeldung nur auf Englisch", english[:2])
    finally:
        copy.stop()
        f.phase = previous
