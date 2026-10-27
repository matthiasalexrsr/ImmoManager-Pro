"""Documents of metering services: local reading, the AI path, the proposal and taking it over."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    UnitCreate,
)
from backend.services import assistant_providers, meter_documents
from backend.services.assistant_provider_protocol import ProviderError
from backend.services.data_snapshot import clear_business_data
from backend.services.file_storage import get_file_storage

ISTA = """ista Deutschland GmbH
Heizkosten- und Warmwasserkostenabrechnung
Liegenschaft: Bautzner Straße 61, 01099 Dresden
Abrechnungszeitraum: 01.01.2025 - 31.12.2025
Ablesedatum: 31.12.2025
Aufstellung der Kosten
Brennstoffkosten Erdgas      8.412,37 €
Betriebsstrom Heizung      214,80 €
Wartung der Heizungsanlage      356,00 €
Immissionsmessung Schornsteinfeger      68,50 €
Verbrauchserfassung und Abrechnung (ista)      412,16 €
Gerätemiete Heizkostenverteiler      198,40 €
Summe der Heizkosten      9.662,23 €
Aufteilung: 30 % Grundkosten nach Wohnfläche, 70 % Verbrauchskosten
Ableseergebnisse
Nutzeinheit 001 EG links
Gerät-Nr. 10456789 HKV Küche Vorjahr 0 Ablesewert 145 Verbrauch 145
Gerät-Nr. 10456790 HKV Wohnen 0 288 288
Nutzeinheit 002 EG rechts
Gerät-Nr. 10456791 HKV Küche 0 97 97
Gerät-Nr. 77777777 WWZ Bad 12,105 31,420 19,315
Kosten je Nutzeinheit
Nutzeinheit 001 EG links      1.234,56 €
Nutzeinheit 002 EG rechts      987,65 €"""


def _pdf(text: str) -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    for index, line in enumerate(text.splitlines()):
        page.drawString(50, 800 - 14 * index, line)
    page.showPage()
    page.save()
    return output.getvalue()


def test_local_rules_read_a_heating_cost_statement():
    result = meter_documents.extract_local(ISTA, {"10456789", "10456790", "10456791"})
    assert (result.company, result.kind) == ("ista", "heating_statement")
    assert (result.period_start, result.period_end, result.reading_date) == (date(2025, 1, 1), date(2025, 12, 31), date(2025, 12, 31))
    assert result.consumption_share == 70 and result.total == Decimal("9662.23")
    assert [(cost["label"], cost["amount"], cost["category"]) for cost in result.costs] == [
        ("Brennstoffkosten Erdgas", Decimal("8412.37"), "heating"), ("Betriebsstrom Heizung", Decimal("214.80"), "heating"),
        ("Wartung der Heizungsanlage", Decimal("356.00"), "heating"),
        ("Immissionsmessung Schornsteinfeger", Decimal("68.50"), "heating"),
        ("Verbrauchserfassung und Abrechnung (ista)", Decimal("412.16"), "heating"),
        ("Gerätemiete Heizkostenverteiler", Decimal("198.40"), "heating")]
    assert not result.notes                                  # the positions add up to the document's sum
    readings = {item["serial"]: (item["previous"], item["value"], item["consumption"], item["medium"]) for item in result.readings}
    assert readings == {"10456789": (0, 145, 145, "heating"), "10456790": (0, 288, 288, "heating"),
                        "10456791": (0, 97, 97, "heating"),
                        "77777777": (Decimal("12.105"), Decimal("31.420"), Decimal("19.315"), "hot_water")}
    assert [(item["label"], item["amount"]) for item in result.unit_results] == [
        ("001 EG links", Decimal("1234.56")), ("002 EG rechts", Decimal("987.65"))]


def test_numbers_and_water_costs():
    assert meter_documents.german_number("1.234,56") == Decimal("1234.56")
    assert meter_documents.german_number("12,345") == Decimal("12.345")
    assert meter_documents.german_number("1.234") == Decimal("1234")
    assert meter_documents.serial_keys("WZ 0026958890") == {"WZ0026958890", "26958890"}
    assert meter_documents.serial_keys("12-34") == {"1234"}
    text = "Wasserkostenabrechnung\nZeitraum 01.07.2024 bis 30.06.2025\nFrischwasser      1.020,00 €\nAbwasser      980,50 €\n" \
           "Miete Kaltwasserzähler      84,00 €\nGesamtbetrag      2.084,50 €"
    result = meter_documents.extract_local(text)
    assert result.kind == "water_statement" and result.period_start == date(2024, 7, 1)
    assert [(cost["label"], cost["category"]) for cost in result.costs] == [
        ("Frischwasser", "water"), ("Abwasser", "water"), ("Miete Kaltwasserzähler", "water")]
    wrong = meter_documents.extract_local("Heizkostenabrechnung\nBrennstoff      100,00 €\nSumme      150,00 €")
    assert wrong.notes and "150,00" in wrong.notes[0]


@pytest.fixture
def case(monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage())
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    users = {role: auth.register_user(f"meter-{role}", f"{role}@example.test", f"{role.title()} Nutzer", "Secret123", role)
             for role in ("eigentuemer", "techniker", "buchhaltung", "readonly")}
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61", property_type="residential"))
    left = store.create_unit(UnitCreate(property_id=prop.id, label="EG links", unit_type="apartment", area_sqm=60))
    right = store.create_unit(UnitCreate(property_id=prop.id, label="EG rechts", unit_type="apartment", area_sqm=40))
    meters = {serial: store.create_meter(MeterCreate(unit_id=unit.id, meter_type="heating", measure_unit="HKV", serial_number=serial))
              for serial, unit in (("10456789", left), ("10456790", left), ("10456791", right))}
    area = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Wohnfläche", key_type="area_sqm"))
    heating = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Heizung (HKV)", key_type="consumption",
                                                              meter_type="heating", measure_unit="HKV"))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="Nebenkosten 2025",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    clients = {role: TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
               for role, user in users.items()}
    key = f"documents/{uuid4().hex}_ista-2025.pdf"
    get_file_storage().save(key, BytesIO(_pdf(ISTA)), content_type="application/pdf")
    document = clients["eigentuemer"].post("/api/v1/documents", json={
        "title": "ista Heizkostenabrechnung 2025", "property_id": prop.id, "file_url": f"/uploads/{key}"}).json()
    yield {"clients": clients, "property": prop, "period": period, "meters": meters, "area": area, "heating": heating,
           "document": document, "units": (left, right)}
    for client in clients.values():
        client.close()
    auth.clear_users()
    clear_business_data(store)


def _analysis(case, reader="local", role="eigentuemer"):
    return case["clients"][role].post(f"/api/v1/billing/meter-documents/{case['document']['id']}/analysis",
                                      json={"billing_period_id": case["period"].id, "reader": reader})


def test_the_proposal_matches_meters_units_and_keys_and_is_taken_over_once(case):
    response = _analysis(case)
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert (proposal["company"], proposal["kind_label"], proposal["reader_label"]) == ("ista", "Heizkostenabrechnung", "Lokale Regeln")
    assert {cost["allocation_key_id"] for cost in proposal["costs"]} == {case["heating"].id}
    assert {(cost["consumption_share"], cost["fixed_key_id"]) for cost in proposal["costs"]} == {(70, case["area"].id)}
    matched = {item["serial"]: item["meter_id"] for item in proposal["readings"]}
    assert matched == {serial: meter.id for serial, meter in case["meters"].items()} | {"77777777": None}
    assert all(item["reading_date"] == "2025-12-31" for item in proposal["readings"])
    assert any("77777777" in note for note in proposal["notes"])
    left, right = case["units"]
    assert [(item["unit_id"], item["amount"]) for item in proposal["unit_results"]] == [(left.id, 1234.56), (right.id, 987.65)]

    costs = [{key: cost[key] for key in ("description", "amount", "cost_category", "allocation_key_id", "is_recoverable",
                                         "consumption_share", "fixed_key_id")} for cost in proposal["costs"]]
    readings = [{"meter_id": item["meter_id"], "reading_date": item["reading_date"], "value": item["value"]}
                for item in proposal["readings"] if item["meter_id"]]
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=case["meters"]["10456789"].id,
                                                                      reading_date=date(2025, 12, 31), value=145))
    body = {"billing_period_id": case["period"].id, "costs": costs, "readings": readings}
    applied = case["clients"]["eigentuemer"].post(f"/api/v1/billing/meter-documents/{case['document']['id']}/apply", json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["readings_created"] == 2 and applied.json()["readings_skipped"] == 1   # the same value was there
    items = [item for item in store.list_cost_items() if item.billing_period_id == case["period"].id]
    assert len(items) == 6 and {item.source_document_id for item in items} == {case["document"]["id"]}
    assert round(sum(item.amount for item in items), 2) == 9662.23
    assert {(item.consumption_share, item.fixed_key_id) for item in items} == {(70, case["area"].id)}
    note = [reading for reading in store.list_standalone_meter_readings() if reading.meter_id == case["meters"]["10456790"].id]
    assert [(reading.value, reading.notes) for reading in note] == [(288, "aus „ista Heizkostenabrechnung 2025“")]

    again = case["clients"]["eigentuemer"].post(f"/api/v1/billing/meter-documents/{case['document']['id']}/apply", json=body)
    assert again.status_code == 409 and "schon 6 Kostenpositionen" in again.json()["error"]["message"]
    other = dict(body, costs=[], readings=[{"meter_id": case["meters"]["10456791"].id, "reading_date": "2025-12-31", "value": 98}])
    conflict = case["clients"]["eigentuemer"].post(f"/api/v1/billing/meter-documents/{case['document']['id']}/apply", json=other)
    assert conflict.status_code == 409 and "gespeichert 97" in conflict.json()["error"]["message"]


def test_readings_out_of_order_with_stored_ones_are_refused(case):
    """A later reading below the document's value would make the consumption negative."""
    meter = case["meters"]["10456790"]
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter.id, reading_date=date(2026, 3, 31),
                                                                      value=200))
    url = f"/api/v1/billing/meter-documents/{case['document']['id']}/apply"
    body = {"billing_period_id": case["period"].id, "costs": [],
            "readings": [{"meter_id": meter.id, "reading_date": "2025-12-31", "value": 288}]}
    refused = case["clients"]["eigentuemer"].post(url, json=body)
    assert refused.status_code == 422
    assert "10456790 am 31.12.2025: Zählerstand 288 ist größer als der spätere Stand 200" in refused.json()["error"]["message"]
    own = dict(body, readings=[{"meter_id": meter.id, "reading_date": "2025-06-30", "value": 150},
                               {"meter_id": meter.id, "reading_date": "2025-12-31", "value": 140}])
    refused = case["clients"]["eigentuemer"].post(url, json=own)
    assert refused.status_code == 422 and "kleiner als der Stand 150 vom 30.06.2025" in refused.json()["error"]["message"]
    assert [r.value for r in store.list_standalone_meter_readings() if r.meter_id == meter.id] == [200]


def test_roles_take_over_their_part_only(case):
    proposal = _analysis(case).json()
    cost = {key: proposal["costs"][0][key] for key in ("description", "amount", "cost_category", "allocation_key_id",
                                                       "consumption_share", "fixed_key_id")}
    reading = {"meter_id": case["meters"]["10456791"].id, "reading_date": "2025-12-31", "value": 97}
    url = f"/api/v1/billing/meter-documents/{case['document']['id']}/apply"
    period = case["period"].id
    clients = case["clients"]
    assert clients["readonly"].post(url, json={"billing_period_id": period, "readings": [reading]}).status_code == 403
    assert clients["techniker"].post(url, json={"billing_period_id": period, "costs": [cost]}).status_code == 403
    assert clients["buchhaltung"].post(url, json={"billing_period_id": period, "readings": [reading]}).status_code == 403
    foreign = dict(cost, allocation_key_id="fremd")
    refused = clients["eigentuemer"].post(url, json={"billing_period_id": period, "costs": [foreign]})
    assert refused.status_code == 422 and "gehört nicht zu dieser Immobilie" in refused.json()["error"]["message"]
    assert clients["techniker"].post(url, json={"billing_period_id": period, "readings": [reading]}).status_code == 200
    assert clients["buchhaltung"].post(url, json={"billing_period_id": period, "costs": [cost]}).status_code == 200


def test_an_account_of_another_portfolio_reaches_neither_the_document_nor_the_property(case):
    elsewhere = store.create_portfolio(PortfolioCreate(name="Anderer Bestand"))
    staff = auth.register_user("meter-staff", "staff@example.test", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[elsewhere.id])
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(staff.id)}) as client:
        url = f"/api/v1/billing/meter-documents/{case['document']['id']}"
        reading = {"meter_id": case["meters"]["10456791"].id, "reading_date": "2025-12-31", "value": 97}
        responses = [client.post(f"{url}/analysis", json={"billing_period_id": case["period"].id}),
                     client.post(f"{url}/apply", json={"billing_period_id": case["period"].id, "readings": [reading]}),
                     client.get("/api/v1/billing/guide", params={"property_id": case["property"].id})]
    for response in responses:
        assert response.status_code in (403, 404), response.text
        assert "Bautzner" not in response.text
    assert store.list_standalone_meter_readings() == [] and store.list_cost_items() == []


def test_the_ai_reads_the_document_through_the_connected_account(case, monkeypatch):
    seen: dict = {}

    def execute(actor_id, provider, request, emit, cancelled):
        seen.update(provider=provider, request=request)
        return {"text": """Hier die Werte:
```immomanager-meter-extract
{"company": "Techem", "document_kind": "heating_statement", "period_start": "2025-01-01", "period_end": "2025-12-31",
 "reading_date": "2025-12-31", "consumption_share_percent": 60, "total": "1200.00",
 "costs": [{"label": "Fernwärme", "amount": "1000.00", "category": "heating", "recoverable": true},
           {"label": "Messdienst", "amount": "200", "category": "heating"},
           {"label": "Kaputt", "amount": "abc", "category": "heating"}],
 "readings": [{"serial": "10456791", "device_type": "HKV", "value": "97", "previous": "0", "date": "2025-12-31"}],
 "unit_results": [{"unit_label": "EG rechts", "amount": "480.10"}]}
```"""}

    monkeypatch.setattr(assistant_providers, "execute", execute)
    response = _analysis(case, reader="claude")
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert seen["provider"] == "claude" and seen["request"]["web_research"] is False
    assert "Bautzner" in seen["request"]["attachments"][0]["text"]
    assert {"serial": "10456791", "type": "heating", "unit": "EG rechts"} in seen["request"]["context"]["property"]["meters"]
    assert (proposal["company"], proposal["reader_label"], proposal["consumption_share"]) == ("Techem", "Claude", 60)
    assert [(cost["description"], cost["amount"], cost["consumption_share"]) for cost in proposal["costs"]] == [
        ("Fernwärme", 1000.0, 60), ("Messdienst", 200.0, 60)]
    assert proposal["readings"][0]["meter_id"] == case["meters"]["10456791"].id
    assert proposal["unit_results"][0]["unit_id"] == case["units"][1].id

    def refused(*args):
        raise ProviderError("Bitte zuerst das Claude-Konto verbinden.", "authentication_required")

    monkeypatch.setattr(assistant_providers, "execute", refused)
    failed = _analysis(case, reader="claude")
    assert failed.status_code == 409 and "Claude-Konto" in failed.json()["error"]["message"]
    monkeypatch.setattr(assistant_providers, "execute", lambda *args: {"text": "kein JSON"})
    assert _analysis(case, reader="codex").status_code == 502


def test_readers_name_the_local_rules_and_the_accounts(case):
    readers = case["clients"]["eigentuemer"].get("/api/v1/billing/meter-documents/readers").json()
    assert [(item["id"], item["available"]) for item in readers][0] == ("local", True)
    assert {item["id"] for item in readers} == {"local", "claude", "codex"}


def test_the_proposal_prefers_the_periods_keys_and_names_costs_already_there(case):
    from backend.models import CostItemCreate
    older = store.create_allocation_key(AllocationKeyCreate(property_id=case["property"].id, name="Personen 2023",
                                                            key_type="person_count"))
    used = store.create_allocation_key(AllocationKeyCreate(property_id=case["property"].id, name="Personen 2025",
                                                           key_type="person_count"))
    store.create_cost_item(CostItemCreate(billing_period_id=case["period"].id, description="Wasser/Abwasser", amount=812.4,
                                          allocation_key_id=used.id))
    facts = meter_documents.property_facts(store, case["property"].id)
    facts.preferred, facts.year = {used.id}, 2025
    assert meter_documents.suggest_key("water", facts, None)["allocation_key_id"] == used.id
    facts.preferred = set()
    assert meter_documents.suggest_key("water", facts, None)["allocation_key_id"] == used.id   # named after the year
    facts.year = 2023
    assert meter_documents.suggest_key("water", facts, None)["allocation_key_id"] == older.id

    water = "Wasserkostenabrechnung\nAbrechnungszeitraum 01.01.2025 - 31.12.2025\nFrischwasser      700,00 €\n" \
            "Abrechnungsservice Wasser      42,00 €"
    extraction = meter_documents.extract_local(water)
    assert [cost["category"] for cost in extraction.costs] == ["water", "water"]
    document = store.get_document(case["document"]["id"])
    result = meter_documents.proposal(store, document, extraction, property_id=case["property"].id, period=case["period"])
    assert {cost["allocation_key_id"] for cost in result["costs"]} == {used.id}
    assert any("„Wasser/Abwasser“ (812,40 €)" in note and "doppelt" in note for note in result["notes"])
