"""Reading documents into forms: surfaces, prompts, the conversation, existing records, settings and rights.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite. The AI answers are simulated
(`assistant_providers.execute`); what goes to the provider is checked instead.
"""
import json
from datetime import date, timedelta
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
from backend.models import BillingPeriodCreate, InvoiceCreate, MeterCreate, PortfolioCreate, PropertyCreate, UnitCreate
from backend.services import ai_reading, assistant_providers
from backend.services.assistant_provider_prompt import READING_PROMPT, SYSTEM_PROMPT, system_prompt
from backend.services.file_storage import get_file_storage

INVOICE = """Stadtwerke Leipzig GmbH
Rechnung Nr. SW-2026-4711
Rechnungsdatum: 03.03.2026
Leistungszeitraum: 01.01.2025 - 31.12.2025
Wasserversorgung Gohliser Straße 17
Summe netto 1.000,00 EUR
MwSt 7 % 70,00 EUR
Gesamtbetrag 1.070,00 EUR
zahlbar bis 31.03.2026
IBAN DE89 3704 0044 0532 0130 00
2 % Skonto bei Zahlung innerhalb von 10 Tagen"""


def _pdf(text: str) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for number, line in enumerate(text.splitlines()):
        pdf.drawString(50, 800 - 14 * number, line)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _upload(content: bytes, name: str = "rechnung.pdf") -> str:
    key = f"documents/{uuid4().hex}_{name}"
    get_file_storage().save(key, BytesIO(content), content_type="application/pdf")
    return f"/uploads/{key}"


def _reset_ai_rules():
    """Installation-wide AI settings a test changed (store.clear_all keeps setting rules)."""
    if hasattr(store, "db"):
        from sqlalchemy import delete

        from backend.db.daily_models import SettingRuleORM
        store.db.execute(delete(SettingRuleORM).where(SettingRuleORM.key.like("ai\\_%", escape="\\")))
        store.db.commit()
    else:
        rules = store.__dict__.get("_daily_rules", {})
        for key in [key for key in rules if key[1].startswith("ai_")]:
            rules.pop(key)


@pytest.fixture
def case(monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage())
    purge_originals(store)
    store.clear_all()
    _reset_ai_rules()
    auth.clear_users()
    monkeypatch.setattr(ai_reading, "_calls", {})
    users = {role: auth.register_user(f"ai-{role}", f"{role}@ai.example.test", f"{role.title()} Nutzer", "Secret123", role)
             for role in ("eigentuemer", "buchhaltung", "techniker", "readonly")}
    clients = {role: TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
               for role, user in users.items()}
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Gohliser Straße 17", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="EG links", unit_type="apartment", area_sqm=60))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="Nebenkosten 2025",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    seen: list[dict] = []

    def connected(actor_id, provider):
        return {"connected": provider == "claude", "client_available": True}
    monkeypatch.setattr(assistant_providers, "connection_status", connected)
    yield {"clients": clients, "users": users, "property": prop, "unit": unit, "period": period, "seen": seen}
    for client in clients.values():
        client.close()
    purge_originals(store)
    store.clear_all()
    _reset_ai_rules()
    auth.clear_users()


def _answer(monkeypatch, case, text: str):
    def execute(actor_id, provider, request, emit, cancelled):
        case["seen"].append({"provider": provider, "request": request})
        return {"text": text, "proposals": []}
    monkeypatch.setattr(assistant_providers, "execute", execute)


def _start(case, role="eigentuemer", **body):
    payload = {"surface": "invoice", "params": {"property_id": case["property"].id}, "idempotency_key": uuid4().hex, **body}
    return case["clients"][role].post("/api/v1/ai/readings", json=payload)


def _set_global(case, key, value):
    client = case["clients"]["eigentuemer"]
    items = client.get("/api/v1/auth/users/me/settings").json()["items"]
    item = next(entry for entry in items if entry["key"] == key and entry["scope"] == "global")
    response = client.put("/api/v1/auth/users/me/settings", json={"values": {key: value}, "scope": "global",
                                                                   "base_revision": item["revision"], "idempotency_key": uuid4().hex})
    assert response.status_code == 200, response.text


def test_the_reading_prompt_is_chosen_by_the_server_only():
    assert system_prompt({"_task": "document_reading"}) == READING_PROMPT
    assert system_prompt({}) == SYSTEM_PROMPT and system_prompt({"_task": "anything else"}) == SYSTEM_PROMPT
    assert "untrusted_evidence" in READING_PROMPT and "immomanager-reading" in READING_PROMPT


def test_local_rules_read_an_invoice_upload_and_leave_the_conversation_to_the_ai(case):
    response = _start(case, file_url=_upload(_pdf(INVOICE)), reader="local")
    assert response.status_code == 201, response.text
    reading = response.json()
    values = {name: item["value"] for name, item in reading["values"].items()}
    assert values["invoice_number"] == "SW-2026-4711" and values["invoice_date"] == "2026-03-03"
    assert values["gross_amount"] == "1070.00" and values["net_amount"] == "1000.00" and values["vat_rate"] == "7"
    assert values["iban"] == "DE89370400440532013000" and values["due_date"] == "2026-03-31"
    assert values["supplier"] == "Stadtwerke Leipzig GmbH" and values["skonto_percent"] == "2" and values["skonto_days"] == "10"
    assert values["cost_category"] == "water" and values["document_kind"] == "invoice"
    assert (values["performance_start"], values["performance_end"]) == ("2025-01-01", "2025-12-31")
    assert all(item["source"] == "local" for item in reading["values"].values())
    assert reading["reader"] == "local" and reading["chat"] is False and reading["status"] == "open"
    assert [message["role"] for message in reading["messages"]] == ["assistant"]
    refused = case["clients"]["eigentuemer"].post(f"/api/v1/ai/readings/{reading['id']}/messages",
                                                  json={"text": "Was ist das?", "expected_revision": reading["revision"],
                                                        "idempotency_key": uuid4().hex})
    assert refused.status_code == 409 and "Claude oder ChatGPT" in refused.json()["error"]["message"]


def test_the_ai_gets_the_surface_task_house_rules_and_facts_and_its_values_are_checked(case, monkeypatch):
    _set_global(case, "ai_rules_invoice", "Stadtwerke Leipzig sind immer Kostenart Wasser.")
    _answer(monkeypatch, case, "Rechnung der Stadtwerke über die Wasserversorgung 2025.\n```immomanager-reading\n" + json.dumps({
        "values": {"supplier": {"value": "Stadtwerke Leipzig GmbH", "evidence": "Stadtwerke Leipzig GmbH", "confidence": "high"},
                   "invoice_number": {"value": "SW-2026-4711", "confidence": "high"},
                   "invoice_date": {"value": "2026-03-03", "confidence": "high"},
                   "gross_amount": {"value": "1070.00", "confidence": "high"},
                   "iban": {"value": "DE00 1234", "confidence": "low"},              # no valid IBAN: dropped
                   "due_date": {"value": "31.02.2026"},                               # no such day: dropped
                   "invented": {"value": "x"}},                                       # no such field: ignored
        "questions": ["Gehört die Rechnung zur Gohliser Straße 17?"], "notes": []}) + "\n```")
    response = _start(case, file_url=_upload(_pdf(INVOICE)), reader="claude", instruction="Bitte als Wasserkosten erfassen.")
    assert response.status_code == 201, response.text
    reading = response.json()
    request = case["seen"][-1]["request"]
    assert request["_task"] == "document_reading" and request["web_research"] is False
    task = request["messages"][0]["content"]
    assert "Eingangsrechnung" in task and "house_rules:\nStadtwerke Leipzig sind immer Kostenart Wasser." in task
    assert request["messages"][1] == {"role": "user", "content": "Bitte als Wasserkosten erfassen."}
    assert request["context"]["known"]["property"] == "Gohliser Straße 17" and request["context"]["known"]["units"] == ["EG links"]
    assert "SW-2026-4711" in request["attachments"][0]["text"]
    assert set(reading["values"]) == {"supplier", "invoice_number", "invoice_date", "gross_amount"}
    assert reading["values"]["supplier"]["evidence"] == "Stadtwerke Leipzig GmbH"
    assert set(reading["dropped"]) == {"IBAN des Lieferanten", "Fällig am"}
    assert reading["questions"] == ["Gehört die Rechnung zur Gohliser Straße 17?"]
    assert [message["role"] for message in reading["messages"]] == ["user", "assistant"]
    assert reading["messages"][1]["text"] == "Rechnung der Stadtwerke über die Wasserversorgung 2025."
    assert reading["chat"] is True and reading["confirm_mode"] == "confirm"


def test_the_conversation_changes_values_and_keeps_the_order(case, monkeypatch):
    _answer(monkeypatch, case, "Erkannt.\n```immomanager-reading\n" + json.dumps({"values": {
        "supplier": {"value": "Stadtwerke Leipzig GmbH"}, "gross_amount": {"value": "1070.00"},
        "due_date": {"value": "2026-03-31"}}}) + "\n```")
    reading = _start(case, file_url=_upload(_pdf(INVOICE)), reader="claude").json()
    _answer(monkeypatch, case, "Ich habe Skonto ergänzt und das Fälligkeitsdatum entfernt.\n```immomanager-reading\n" + json.dumps({
        "values": {"skonto_percent": {"value": "2"}, "skonto_days": {"value": "10"}, "due_date": {"value": None}}}) + "\n```")
    command = {"text": "Bitte Skonto übernehmen und die Fälligkeit leer lassen.", "expected_revision": reading["revision"],
               "idempotency_key": uuid4().hex}
    client = case["clients"]["eigentuemer"]
    answered = client.post(f"/api/v1/ai/readings/{reading['id']}/messages", json=command)
    assert answered.status_code == 200, answered.text
    after = answered.json()
    assert set(after["values"]) == {"supplier", "gross_amount", "skonto_percent", "skonto_days"}
    assert set(after["changed"]) == {"skonto_percent", "skonto_days", "due_date"}
    assert [message["role"] for message in after["messages"]] == ["assistant", "user", "assistant"]
    request = case["seen"][-1]["request"]
    assert request["messages"][-1] == {"role": "user", "content": command["text"]}
    assert request["messages"][-2]["role"] == "assistant" and request["context"]["current_values"]["due_date"] == "2026-03-31"
    again = client.post(f"/api/v1/ai/readings/{reading['id']}/messages", json=command)
    assert again.status_code == 200 and again.json()["revision"] == after["revision"]          # the same command, answered once
    assert len(case["seen"]) == 2
    stale = client.post(f"/api/v1/ai/readings/{reading['id']}/messages",
                        json={**command, "idempotency_key": uuid4().hex})
    assert stale.status_code == 409


def test_an_invoice_already_recorded_is_found_and_the_decision_kept(case, monkeypatch):
    existing = store.create_invoice(InvoiceCreate(property_id=case["property"].id, supplier="Stadtwerke Leipzig GmbH",
                                                  invoice_date=date(2026, 3, 4), net_amount=1000.0, vat_rate=7.0,
                                                  vat_amount=70.0, gross_amount=1070.0))
    reading = _start(case, file_url=_upload(_pdf(INVOICE)), reader="local").json()
    assert [(item["kind"], item["id"], item["reason"]) for item in reading["duplicates"]] == [
        ("invoice", existing.id, "same_amount_near_date")]
    assert reading["duplicates"][0]["reason_label"] == "gleicher Betrag des Lieferanten in Datumsnähe"
    client = case["clients"]["eigentuemer"]
    wrong = client.post(f"/api/v1/ai/readings/{reading['id']}/decision", json={
        "action": "use_existing", "record_kind": "invoice", "record_id": "other", "expected_revision": reading["revision"],
        "idempotency_key": uuid4().hex})
    assert wrong.status_code == 422
    decided = client.post(f"/api/v1/ai/readings/{reading['id']}/decision", json={
        "action": "use_existing", "record_kind": "invoice", "record_id": existing.id, "expected_revision": reading["revision"],
        "idempotency_key": uuid4().hex})
    assert decided.status_code == 200 and decided.json()["decision"]["action"] == "use_existing"
    finished = client.post(f"/api/v1/ai/readings/{reading['id']}/finish", json={
        "outcome": "taken_over", "record_kind": "invoice", "record_id": existing.id,
        "expected_revision": decided.json()["revision"], "idempotency_key": uuid4().hex})
    assert finished.status_code == 200 and finished.json()["status"] == "taken_over"
    twice = client.post(f"/api/v1/ai/readings/{reading['id']}/finish", json={
        "outcome": "cancelled", "expected_revision": finished.json()["revision"], "idempotency_key": uuid4().hex})
    assert twice.status_code == 409


def test_the_same_file_or_text_as_an_existing_document_is_found(case):
    from backend.services import document_text
    content = _pdf(INVOICE + "\n" + "Weitere Zeile mit ausreichend Text für den Vergleich. " * 4)
    client = case["clients"]["eigentuemer"]
    first = client.post("/api/v1/documents", json={"title": "Stadtwerke März", "property_id": case["property"].id,
                                                   "file_url": _upload(content), "document_type": "Rechnung"}).json()
    document_text.index_document(store, store.get_document(first["id"]))
    if hasattr(store, "db"):
        store.db.commit()                                   # the indexing job commits its own work
    reading = _start(case, surface="document", file_url=_upload(content), reader="local").json()
    assert [(item["kind"], item["id"], item["reason"]) for item in reading["duplicates"]] == [("document", first["id"], "same_text")]
    assert reading["duplicates"][0]["can_update"] is True and reading["duplicates"][0]["href"] == f"/documents/{first['id']}"


def test_who_may_read_where_and_what_the_settings_switch_off(case, monkeypatch):
    upload = _upload(_pdf(INVOICE))
    assert _start(case, "readonly", file_url=upload, reader="local").status_code == 403
    assert _start(case, "techniker", file_url=upload, reader="local").status_code == 403          # invoices are bookkeeping
    assert _start(case, "buchhaltung", file_url=upload, reader="local").status_code == 201
    photo = _start(case, "techniker", surface="meter_photo", file_url=upload, reader="local")
    assert photo.status_code == 422 and "braucht die KI" in photo.json()["error"]["message"]
    _answer(monkeypatch, case, "```immomanager-reading\n{\"values\": {}}\n```")
    _set_global(case, "ai_surface_invoice", False)
    off = _start(case, file_url=upload, reader="claude")
    assert off.status_code == 409 and "Rechnungseingang" in off.json()["error"]["message"]
    assert _start(case, file_url=upload, reader="auto").json()["reader"] == "local"              # auto falls back to the rules
    _set_global(case, "ai_reading_enabled", False)
    assert _start(case, surface="document", file_url=upload, reader="claude").status_code == 409
    assert case["seen"] == []
    options = case["clients"]["eigentuemer"].get("/api/v1/ai/readings/options").json()
    assert options["ai_enabled"] is False and {item["id"] for item in options["readers"]} == {"local", "claude", "codex"}
    assert next(item for item in options["surfaces"] if item["id"] == "invoice")["ai_allowed"] is False


def test_readings_stay_out_of_the_assistant_and_are_deleted_after_the_kept_days(case, monkeypatch):
    client = case["clients"]["eigentuemer"]
    reading = _start(case, file_url=_upload(_pdf(INVOICE)), reader="local").json()
    assert client.get("/api/v1/assistant/conversations").json()["items"] == []
    assert client.get(f"/api/v1/assistant/conversations/{reading['id']}").status_code == 404
    assert client.get(f"/api/v1/ai/readings/{reading['id']}").status_code == 200
    assert case["clients"]["buchhaltung"].get(f"/api/v1/ai/readings/{reading['id']}").status_code == 404   # someone else's
    from backend.db.assistant_models import AssistantConversationORM
    from backend.services import assistant_storage
    with assistant_storage.work(store, case["users"]["eigentuemer"].id, write=True) as unit:
        row = assistant_storage.get(unit, AssistantConversationORM, reading["id"])
        row.updated_at = row.updated_at - timedelta(days=31)
        if unit.db is not None:
            unit.db.flush()
    _start(case, file_url=_upload(_pdf(INVOICE)), reader="local")
    assert client.get(f"/api/v1/ai/readings/{reading['id']}").status_code == 404


def test_too_many_ai_requests_are_refused(case, monkeypatch):
    monkeypatch.setattr(ai_reading, "CALLS_PER_WINDOW", 2)
    _answer(monkeypatch, case, "```immomanager-reading\n{\"values\": {}}\n```")
    upload = _upload(_pdf(INVOICE))
    assert [_start(case, file_url=upload, reader="claude").status_code for _ in range(3)] == [201, 201, 429]


def test_a_meter_photo_is_matched_to_the_meter_and_a_stored_reading_is_found(case, monkeypatch):
    meter = store.create_meter(MeterCreate(unit_id=case["unit"].id, meter_type="cold_water", measure_unit="m³",
                                           serial_number="WZ 26958890"))
    store.create_standalone_meter_reading(__import__("backend.models", fromlist=["StandaloneMeterReadingCreate"])
                                          .StandaloneMeterReadingCreate(meter_id=meter.id, reading_date=date(2025, 12, 31), value=640))
    _answer(monkeypatch, case, "Kaltwasserzähler 26958890, Stand 647.6.\n```immomanager-reading\n" + json.dumps({"values": {
        "serial": {"value": "26958890"}, "value": {"value": "647.6"}, "reading_date": {"value": "2025-12-31"},
        "meter_type": {"value": "cold_water"}}}) + "\n```")
    photo = BytesIO()
    from PIL import Image
    Image.new("RGB", (40, 20), "white").save(photo, "PNG")
    key = f"documents/{uuid4().hex}_zaehler.png"
    get_file_storage().save(key, BytesIO(photo.getvalue()), content_type="image/png")
    response = _start(case, "techniker", surface="meter_photo", file_url=f"/uploads/{key}", reader="claude",
                      params={"unit_id": case["unit"].id})
    assert response.status_code == 201, response.text
    reading = response.json()
    request = case["seen"][-1]["request"]
    assert request["attachments"][1]["mime"] == "image/png"                                   # the photo itself goes along
    assert request["context"]["known"]["meters"] == [{"serial": "WZ 26958890", "type": "cold_water", "unit": "EG links"}]
    assert reading["values"]["value"]["value"] == "647.6"
    assert [(item["kind"], item["reason"]) for item in reading["duplicates"]] == [("meter_reading", "same_day")]
