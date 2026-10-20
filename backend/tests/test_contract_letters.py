"""Letters from templates: letterhead, placeholders, legal checks, preview, archived original, own templates."""
import hashlib
from datetime import date
from io import BytesIO
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient
from PIL import Image

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    ContractCreate,
    ContractRentPeriodCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import letter_templates as templates
from backend.services.contract_letter_validation import DOC_TYPE, validate_contract_letter_snapshot
from backend.services.data_snapshot import clear_business_data
from backend.services.document_version_validation import validate_feature_snapshot

ISSUE = "2026-10-20"


def _clear_rules():
    if hasattr(store, "db"):
        store.db.rollback()
        with store.db.get_bind().connect() as connection, connection.begin():
            connection.exec_driver_sql("DELETE FROM daily_setting_rules WHERE key LIKE 'letter_template:%' "
                                       "OR key LIKE 'document_%'")
            connection.exec_driver_sql("DELETE FROM daily_commands")
    else:
        for key in ("_daily_rules", "_daily_commands"):
            store.__dict__.pop(key, None)


@pytest.fixture
def case():
    purge_originals(store)
    clear_business_data(store)
    _clear_rules()
    auth.clear_users()
    owner = auth.register_user("letter-owner", "letters@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", area_sqm=72.5,
                                        rooms=3))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster", address_line="Bautzner Straße 61",
                                              postal_code="01099", city="Dresden"))
    contract = store.create_contract(ContractCreate(contract_number="MV-7", property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2022, 1, 1), persons=2,
                                                    deposit_amount=1800))
    for valid_from, cold in ((date(2022, 1, 1), 600), (date(2024, 3, 1), 650)):
        store.create_contract_rent_period(ContractRentPeriodCreate(
            contract_id=contract.id, valid_from=valid_from, cold_rent=cold, service_charge_advance=150,
            heating_advance=80, source="contract_start" if cold == 600 else "manual"))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield {"portfolio": portfolio, "property": prop, "unit": unit, "tenant": tenant, "contract": contract,
           "owner": owner, "client": client}
    client.close()
    purge_originals(store)
    _clear_rules()
    auth.clear_users()
    clear_business_data(store)


def base(case):
    return f"/api/v1/contracts/{case['contract'].id}/letters"


def compose(case, template_id, inputs=None, issue=ISSUE):
    response = case["client"].post(base(case) + "/compose",
                                   json={"template_id": template_id, "inputs": inputs, "issue_date": issue})
    assert response.status_code == 200, response.text
    return response.json()


def preview(case, composed, **changes):
    payload = {"source_revision": composed["source_revision"], "template_id": composed["template"]["id"],
               "inputs": composed["inputs"], "data": {**composed["data"], **changes}}
    response = case["client"].post(base(case) + "/preview", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


RENT_INCREASE = {"receipt_date": "2026-10-23", "new_cold_rent": "715", "justification": "mietspiegel",
                 "justification_text": "Mietspiegel Dresden 2025, Spanne 9,10 bis 10,20 €/m²", "cap_percent": "20"}


def test_rent_increase_is_filled_with_deadlines_cap_and_table(case):
    composed = compose(case, "builtin:rent_increase", RENT_INCREASE)
    body = composed["data"]["body"]
    assert "**715,00 €**" in body and "**01.01.2027**" in body and "**31.12.2026**" in body
    assert "um 65,00 €" in body and "Mietspiegel – Mietspiegel Dresden 2025" in body
    assert "{{tabelle.mieterhoehung}}" in body and templates.MISSING_MARK not in body
    assert composed["data"]["recipient_address"] == "Bautzner Straße 61\n01099 Dresden"
    assert "Zustimmungserklärung" in composed["data"]["appendix"]
    assert not [check for check in composed["checks"] if check["level"] == "error"], composed["checks"]
    assert any("höchstens 720,00 €" in check["text"] for check in composed["checks"])
    table = composed["blocks"]["mieterhoehung"]["rows"]
    assert table[1] == ["Nettokaltmiete", "650,00 €", "715,00 €"]
    assert table[2] == ["Nettokaltmiete je m² Wohnfläche", "8,97 €", "9,86 €"]
    assert table[-1] == ["Gesamtmiete", "880,00 €", "945,00 €"]
    payload, shown = preview(case, composed)
    assert shown["review"]["draft"] is False
    pdf = case["client"].post(base(case) + "/preview-pdf", json=payload)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert hashlib.sha256(pdf.content).hexdigest() == shown["pdf_sha256"] == pdf.headers["X-Content-SHA256"]


@pytest.mark.parametrize("change, message", [
    ({"new_cold_rent": "800"}, "Kappungsgrenze"),
    ({"new_cold_rent": "640"}, "höher sein als die bisherige"),
    ({"receipt_date": "2026-10-01"}, "nicht vor dem Briefdatum"),
])
def test_rent_increase_errors_make_a_draft_that_cannot_be_archived(case, change, message):
    composed = compose(case, "builtin:rent_increase", {**RENT_INCREASE, **change})
    assert any(check["level"] == "error" and message in check["text"] for check in composed["checks"])
    payload, shown = preview(case, composed)
    assert shown["review"]["draft"] is True
    refused = case["client"].post(base(case), json={**payload, "review_hash": shown["review_hash"],
                                                     "idempotency_key": "letter-draft-01"})
    assert refused.status_code == 409 and message in refused.json()["error"]["message"]
    assert not [doc for doc in store.list_documents() if doc.document_type == DOC_TYPE]


def test_rent_increase_refuses_index_rent_and_a_waiting_period(case):
    contract = store.get_contract(case["contract"].id)
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
                                                         "index_rent": "stepped"}))
    composed = compose(case, "builtin:rent_increase", RENT_INCREASE)
    assert any("Staffelmiete" in check["text"] for check in composed["checks"] if check["level"] == "error")
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
                                                         "index_rent": None}))
    store.create_contract_rent_period(ContractRentPeriodCreate(
        contract_id=contract.id, valid_from=date(2026, 3, 1), cold_rent=660, service_charge_advance=150,
        heating_advance=80, source="manual"))
    composed = compose(case, "builtin:rent_increase", RENT_INCREASE)
    errors = " ".join(check["text"] for check in composed["checks"] if check["level"] == "error")
    assert "frühestens ein Jahr danach" in errors and "01.03.2027" in errors
    assert "15 Monaten unverändert" in errors and "01.06.2027" in errors


def test_publish_archives_original_replays_and_lists_it(case):
    composed = compose(case, "builtin:rent_increase", RENT_INCREASE)
    payload, shown = preview(case, composed)
    command = {**payload, "review_hash": shown["review_hash"], "idempotency_key": "letter-publish-01"}
    saved = case["client"].post(base(case), json=command)
    assert saved.status_code == 201, saved.text
    result = saved.json()
    assert result["pdf_sha256"] == shown["pdf_sha256"] and result["template"]["kind"] == "rent_increase"
    document = store.get_document(result["document_id"])
    assert document.document_type == DOC_TYPE and document.contract_id == case["contract"].id
    assert document.unit_id == case["unit"].id and document.property_id == case["property"].id
    original = case["client"].get("/api/v1" + result["download_url"])
    assert original.status_code == 200 and hashlib.sha256(original.content).hexdigest() == shown["pdf_sha256"]
    again = case["client"].post(base(case), json=command)
    assert again.status_code == 201 and again.json() == result
    other = case["client"].post(base(case), json={**command, "inputs": {**payload["inputs"], "new_cold_rent": "700"}})
    assert other.status_code == 409
    context = case["client"].get(base(case) + "/context").json()
    assert [item["document_id"] for item in context["originals"]] == [result["document_id"]]
    from backend.services import document_versions as archive
    with archive.work(store, case["owner"].id) as unit:
        row = archive.head(unit, document.id)
        assert row is not None
        validate_feature_snapshot(row, row.metadata_snapshot)
        assert validate_contract_letter_snapshot(row, row.metadata_snapshot)["review_hash"] == shown["review_hash"]
        broken = {**row.metadata_snapshot, DOC_TYPE: {**row.metadata_snapshot[DOC_TYPE], "review_hash": "0" * 64}}
        with pytest.raises(ValueError):
            validate_contract_letter_snapshot(row, broken)


def test_changed_source_or_letterhead_requires_a_new_preview(case):
    composed = compose(case, "builtin:free")
    store.update_tenant(case["tenant"].id, TenantCreate(full_name="Mia Muster-Neu", address_line="Bautzner Straße 61",
                                                        postal_code="01099", city="Dresden"))
    response = case["client"].post(base(case) + "/preview", json={
        "source_revision": composed["source_revision"], "template_id": "builtin:free", "inputs": {},
        "data": {**composed["data"], "body": "Text"}})
    assert response.status_code == 412


def test_open_placeholder_or_note_blocks_the_original(case):
    composed = compose(case, "builtin:free")
    assert composed["data"]["subject"] == "Ihr Mietverhältnis MV-7 – WE 3"
    _, shown = preview(case, composed, body="Kaution: {{kaution.betrag}}\n\nBitte [bitte ergänzen: Termin] beachten.")
    texts = [check["text"] for check in shown["review"]["checks"] if check["level"] == "error"]
    assert shown["review"]["draft"] is True
    assert any("nicht ausgefüllt" in text for text in texts) and any("[bitte ergänzen" in text for text in texts)
    _, fine = preview(case, composed, body="Die Kaution beträgt 1.800,00 €.")
    assert fine["review"]["draft"] is False


def test_certificate_marks_missing_rooms_and_only_states_no_arrears_when_confirmed(case):
    unit = store.get_unit(case["unit"].id)
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "rooms": None}))
    composed = compose(case, "builtin:rent_certificate", {"reference_date": ISSUE, "purpose": "dem Jobcenter"})
    body = composed["data"]["body"]
    assert "Zimmer: [bitte ergänzen: Zimmer]" in body and "keine Mietrückstände" not in body
    assert "Wohnfläche: 72,5 m²" in body and "Personen im Haushalt: 2" in body
    assert composed["blocks"]["miete"]["rows"][-1] == ["Gesamtmiete", "880,00 €"]
    confirmed = compose(case, "builtin:rent_certificate",
                        {"reference_date": ISSUE, "purpose": "dem Jobcenter", "no_arrears": True})
    assert "Zum Stichtag bestehen keine Mietrückstände." in confirmed["data"]["body"]


def test_advance_adjustment_and_appointment_checks(case):
    composed = compose(case, "builtin:advance_adjustment")
    assert composed["inputs"]["new_heating_advance"] == "80.00"
    assert composed["data"] is None        # no statement: the reference must be entered
    filled = compose(case, "builtin:advance_adjustment", {**composed["inputs"], "new_service_charge_advance": "170",
                                                          "statement_reference": "Betriebskostenabrechnung 2025"})
    assert "**900,00 €**" in filled["data"]["body"] and "**01.12.2026**" in filled["data"]["body"]
    assert any("keine ausgestellte Betriebskostenabrechnung" in check["text"] for check in filled["checks"])
    soon = compose(case, "builtin:appointment_notice", {"appointment_type": "meter_reading",
        "appointment_date": "2026-10-23", "time_from": "08:00", "time_to": "12:00", "company": "Techem",
        "reason": "Ablesung der Heizkostenverteiler"})
    assert "**Zählerablesung** am **23.10.2026**, zwischen 08:00 und 12:00 Uhr" in soon["data"]["body"]
    assert "bis zum 20.10.2026" in soon["data"]["body"]
    assert any(check["level"] == "warning" and "Woche" in check["text"] for check in soon["checks"])
    wrong = compose(case, "builtin:appointment_notice", {"appointment_type": "craftsman",
        "appointment_date": "2026-11-23", "time_from": "12:00", "time_to": "08:00", "company": "Elektro Kunze",
        "reason": "Prüfung der Elektrik"})
    assert any(check["level"] == "error" for check in wrong["checks"])


def test_termination_confirmation_counts_working_days():
    assert templates.easter(2026) == date(2026, 4, 5) and templates.easter(2027) == date(2027, 3, 28)
    # 1 October 2026 is a Thursday, 3 October a public holiday: the third working day is Monday 5 October
    assert templates.tenant_notice_end(date(2026, 10, 5)) == date(2026, 12, 31)
    assert templates.tenant_notice_end(date(2026, 10, 6)) == date(2027, 1, 31)
    # Saturdays count: after 1 May (holiday) come Saturday 2, Monday 4 and Tuesday 5 May
    assert templates.tenant_notice_end(date(2026, 5, 5)) == date(2026, 7, 31)
    assert templates.tenant_notice_end(date(2026, 5, 6)) == date(2026, 8, 31)


def test_termination_letter_warns_about_an_early_end(case):
    composed = compose(case, "builtin:termination_confirmation",
                       {"notice_received": "2026-10-20", "tenancy_end": "2026-12-31", "handover": None})
    assert "zum **31.12.2026**" in composed["data"]["body"] and "nach Absprache mit Ihnen" in composed["data"]["body"]
    assert any("frühestens am 31.01.2027" in check["text"] for check in composed["checks"] if check["level"] == "warning")


def test_own_templates_are_checked_versioned_and_archived(case):
    client = case["client"]
    created = client.post("/api/v1/letter-templates", json={
        "kind": "rent_increase", "based_on": "builtin:rent_increase", "name": "Mieterhöhung kurz",
        "subject": "Mieterhöhung {{vertrag.nummer}}", "salutation": "Hallo {{mieter.name}},",
        "body": "Neue Miete: {{erhoehung.neue_kaltmiete}} ab {{erhoehung.wirksam_ab}}.\n\n{{tabelle.mieterhoehung}}",
        "closing": "Viele Grüße", "appendix": "", "idempotency_key": "template-create-01"})
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["revision"] == 1 and template["kind"] == "rent_increase"
    replay = client.post("/api/v1/letter-templates", json={
        "kind": "rent_increase", "based_on": "builtin:rent_increase", "name": "Mieterhöhung kurz",
        "subject": "Mieterhöhung {{vertrag.nummer}}", "salutation": "Hallo {{mieter.name}},",
        "body": "Neue Miete: {{erhoehung.neue_kaltmiete}} ab {{erhoehung.wirksam_ab}}.\n\n{{tabelle.mieterhoehung}}",
        "closing": "Viele Grüße", "appendix": "", "idempotency_key": "template-create-01"})
    assert replay.status_code == 201 and replay.json()["id"] == template["id"]
    bad = client.post("/api/v1/letter-templates", json={"kind": "free", "name": "X", "subject": "{{mieter.alter}}",
                                                       "idempotency_key": "template-bad-01"})
    assert bad.status_code == 422 and "Unbekannter Platzhalter" in bad.json()["error"]["message"]
    inline = client.post("/api/v1/letter-templates", json={"kind": "free", "name": "X", "subject": "S",
                                                          "body": "Miete {{tabelle.miete}} heute",
                                                          "idempotency_key": "template-bad-02"})
    assert inline.status_code == 422 and "allein in einer Zeile" in inline.json()["error"]["message"]
    fixed = client.put(f"/api/v1/letter-templates/{template['id']}", json={
        **{key: template[key] for key in ("name", "subject", "salutation", "body", "closing", "appendix")},
        "closing": "Mit freundlichen Grüßen", "base_revision": 1, "idempotency_key": "template-edit-01"})
    assert fixed.status_code == 200 and fixed.json()["revision"] == 2
    stale = client.put(f"/api/v1/letter-templates/{template['id']}", json={
        **{key: template[key] for key in ("name", "subject", "salutation", "body", "closing", "appendix")},
        "base_revision": 1, "idempotency_key": "template-edit-02"})
    assert stale.status_code == 409
    assert client.put("/api/v1/letter-templates/builtin:free", json={"name": "x", "subject": "y", "base_revision": 1,
                                                                    "idempotency_key": "template-edit-03"}).status_code == 409
    composed = compose(case, template["id"], RENT_INCREASE)
    assert composed["data"]["body"].startswith("Neue Miete: 715,00 € ab 01.01.2027.")
    assert composed["data"]["closing"] == "Mit freundlichen Grüßen"
    archived = client.put(f"/api/v1/letter-templates/{template['id']}", json={
        **{key: fixed.json()[key] for key in ("name", "subject", "salutation", "body", "closing", "appendix")},
        "archived": True, "base_revision": 2, "idempotency_key": "template-archive-01"})
    assert archived.status_code == 200
    listing = client.get("/api/v1/letter-templates").json()
    assert template["id"] not in [item["id"] for item in listing["items"]]
    assert len([item for item in listing["items"] if item["builtin"]]) == len(templates.KINDS)
    assert template["id"] in [item["id"] for item in client.get("/api/v1/letter-templates?archived=true").json()["items"]]


def _png(width=600, height=200, mode="RGBA"):
    output = BytesIO()
    Image.new(mode, (width, height), (18, 111, 104, 255) if mode == "RGBA" else (18, 111, 104)).save(output, "PNG")
    return output.getvalue()


def test_letterhead_logo_is_normalized_versioned_and_printed(case):
    client = case["client"]
    view = client.get("/api/v1/letterhead").json()
    assert view["logo"] is None and view["logo_rules"]["global"]["revision"] == 0 and view["can_edit"]
    refused = client.post("/api/v1/letterhead/logo", data={"base_revision": "0", "idempotency_key": "logo-0001"},
                         files={"file": ("logo.txt", b"kein Bild", "text/plain")})
    assert refused.status_code == 415
    saved = client.post("/api/v1/letterhead/logo", data={"base_revision": "0", "idempotency_key": "logo-0002"},
                       files={"file": ("logo.png", _png(2400, 600), "image/png")})
    assert saved.status_code == 200, saved.text
    assert saved.json()["logo"]["width"] == 1200 and saved.json()["logo"]["height"] == 300
    stale = client.post("/api/v1/letterhead/logo", data={"base_revision": "0", "idempotency_key": "logo-0003"},
                       files={"file": ("logo.png", _png(), "image/png")})
    assert stale.status_code == 409
    png = client.get("/api/v1/letterhead/logo")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert hashlib.sha256(png.content).hexdigest() == saved.json()["logo"]["sha256"]
    sample = client.get("/api/v1/letterhead/sample-pdf")
    assert sample.status_code == 200 and sample.content.startswith(b"%PDF-")
    composed = compose(case, "builtin:free")
    _, shown = preview(case, composed, body="Text mit Logo.")
    assert shown["review"]["source"]["letterhead"]["logo"]["sha256"] == saved.json()["logo"]["sha256"]
    removed = client.delete("/api/v1/letterhead/logo", params={"base_revision": 1, "idempotency_key": "logo-0004"})
    assert removed.status_code == 200 and removed.json()["logo"] is None
    late = case["client"].post(base(case) + "/preview", json={
        "source_revision": composed["source_revision"], "template_id": "builtin:free", "inputs": {},
        "data": {**composed["data"], "body": "Text"}})
    assert late.status_code == 412


def test_letterhead_fields_reach_the_letter_and_staff_without_rights_cannot_write(case):
    client = case["client"]
    for key, value in (("document_bank", "IBAN DE02 1203 0000 0000 2020 51\nDeutsche Kreditbank"),
                       ("document_contact", "Telefon 0351 123456")):
        response = client.put("/api/v1/auth/users/me/settings", json={
            "values": {key: value}, "base_revision": 0, "idempotency_key": str(uuid4()), "scope": "global"})
        assert response.status_code == 200, response.text
    view = client.get("/api/v1/letterhead").json()
    assert view["fields"]["bank"]["value"].startswith("IBAN DE02") and view["fields"]["bank"]["origin"] == "global"
    composed = compose(case, "builtin:free")
    _, shown = preview(case, composed, body="Bitte überweisen Sie auf das Konto in der Fußzeile.")
    assert shown["review"]["source"]["letterhead"]["contact"] == "Telefon 0351 123456"
    technician = auth.register_user("letter-tech", "tech@example.test", "Tom Technik", "Secret123", "techniker")
    staff = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(technician.id)})
    try:
        assert staff.post("/api/v1/letterhead/logo", data={"base_revision": "0", "idempotency_key": "logo-0005"},
                         files={"file": ("logo.png", _png(), "image/png")}).status_code == 403
        assert staff.post("/api/v1/letter-templates", json={"kind": "free", "name": "X", "subject": "S",
                                                           "idempotency_key": "template-tech-1"}).status_code == 403
        payload, shown = preview(case, composed, body="Text")
        assert staff.post(base(case), json={**payload, "review_hash": shown["review_hash"],
                                            "idempotency_key": "letter-tech-01"}).status_code == 403
    finally:
        staff.close()


def test_archived_letters_are_found_by_their_content(case):
    from backend.services import document_text

    composed = compose(case, "builtin:rent_increase", RENT_INCREASE)
    payload, shown = preview(case, composed)
    saved = case["client"].post(base(case), json={**payload, "review_hash": shown["review_hash"],
                                                  "idempotency_key": "letter-index-01"}).json()
    while document_text.index_pending(store)[1] is not None:
        pass
    if hasattr(store, "db"):
        store.db.commit()
    row = document_text.get(store, saved["document_id"])
    assert row is not None and row.source == "pdf_text" and row.source_ref.startswith("version:")
    found = case["client"].get("/api/v1/documents/search", params={"q": "ortsüblichen vergleichsmiete"}).json()
    assert [item["id"] for item in found["items"]] == [saved["document_id"]]
