"""Letters from templates: letterhead, placeholders, legal checks, preview, archived original, own templates."""
import hashlib
from datetime import date
from io import BytesIO
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain.calendar_days import easter
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
            # bound patterns: a literal "%" is a placeholder for the PostgreSQL driver
            connection.execute(text("DELETE FROM daily_setting_rules WHERE key LIKE :letters OR key LIKE :documents "
                                    "OR key LIKE :index"),
                               {"letters": "letter_template:%", "documents": "document_%", "index": "price_index:%"})
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


def test_a_modernization_increase_counts_neither_for_the_waiting_period_nor_for_the_cap(case):
    """R12-16: § 558 Abs. 1 Satz 3, Abs. 3 BGB leave increases after § 559 out; the check counted every
    change of the cold rent, so a modernization in January blocked a comparative increase for a year."""
    from backend.models import RentAdjustmentCreate
    adjustment = store.create_rent_adjustment(RentAdjustmentCreate(
        contract_id=case["contract"].id, adjustment_type="modernization", effective_date=date(2026, 1, 1),
        previous_rent=650, new_rent=700, status="applied"))
    store.create_contract_rent_period(ContractRentPeriodCreate(
        contract_id=case["contract"].id, valid_from=date(2026, 1, 1), cold_rent=700, service_charge_advance=150,
        heating_advance=80, source="adjustment", rent_adjustment_id=adjustment.id))

    composed = compose(case, "builtin:rent_increase", {**RENT_INCREASE, "new_cold_rent": "765"})

    assert not [check for check in composed["checks"] if check["level"] == "error"], composed["checks"]
    # 20 % on the 600 € of 1.1.2024 plus the 50 € of the modernization
    assert any("höchstens 770,00 €" in check["text"] and "§§ 559, 560" in check["text"]
               for check in composed["checks"])


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
    assert easter(2026) == date(2026, 4, 5) and easter(2027) == date(2027, 3, 28)
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


def test_the_owners_placeholder_names_the_owners_on_the_letter_date(case):
    from backend.models import ContactCreate
    from backend.models_ownership import OwnershipShareCreate
    from backend.services import ownership

    created = case["client"].post("/api/v1/letter-templates", json={
        "kind": "free", "name": "Eigentümer", "subject": "Eigentümer", "body": "Eigentümer: {{eigentuemer.namen}}",
        "idempotency_key": "template-owners-01"})
    assert created.status_code == 201, created.text
    template = created.json()["id"]
    assert compose(case, template)["data"]["body"] == "Eigentümer: Linda Reiser"      # no shares: the portfolio's owner
    anna = store.create_contact(ContactCreate(contact_type="owner", first_name="Anna", last_name="Berg"))
    ben = store.create_contact(ContactCreate(contact_type="owner", first_name="Ben", last_name="Berg"))
    for owner, first, last in ((anna, None, date(2026, 6, 30)), (ben, date(2026, 7, 1), None)):
        ownership.create_share(store, OwnershipShareCreate(owner_contact_id=owner.id, property_id=case["property"].id,
                                                           share_percent=100, valid_from=first, valid_to=last), None)
    assert compose(case, template)["data"]["body"] == "Eigentümer: Ben Berg"
    assert compose(case, template, issue="2026-03-01")["data"]["body"] == "Eigentümer: Anna Berg"
    assert templates.known_placeholders("free")["eigentuemer.namen"] == "Eigentümer der Einheit zum Briefdatum"


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

    # bullet points of a letter came out of the PDF as DEL (0x7f) and reached the snippet
    notice = compose(case, "builtin:appointment_notice", {"appointment_type": "meter_reading",
        "appointment_date": "2026-11-23", "time_from": "08:00", "time_to": "12:00", "company": "Techem",
        "reason": "Ablesung der Heizkostenverteiler"})
    payload, shown = preview(case, notice)
    saved = case["client"].post(base(case), json={**payload, "review_hash": shown["review_hash"],
                                                  "idempotency_key": "letter-index-02"}).json()
    while document_text.index_pending(store)[1] is not None:
        pass
    if hasattr(store, "db"):
        store.db.commit()
    row = document_text.get(store, saved["document_id"])
    assert row is not None
    text = row.text
    assert "Ausführung: Techem" in text
    assert not any(ord(char) < 32 and char != "\n" or 127 <= ord(char) < 160 for char in text)
    found = case["client"].get("/api/v1/documents/search", params={"q": "heizkostenverteiler"}).json()
    assert [item["id"] for item in found["items"]] == [saved["document_id"]]
    assert "\x7f" not in found["items"][0]["snippet"]


VPI = {"base_year": 2020, "values": {"2024-03": "117.4", "2026-09": "123.6"}}   # test values, not Destatis figures


def test_index_rent_follows_the_price_index_and_keeps_a_year_between_changes(case):
    from backend.models import ContractPatch
    client = case["client"]
    path = "/api/v1/letter-templates/price-index"
    assert client.get(path).json()["values"] == {}
    saved = client.put(path, json={**VPI, "base_revision": 0, "idempotency_key": "vpi-2026-09"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1 and saved.json()["months"] == ["2024-03", "2026-09"]
    assert client.put(path, json={**VPI, "base_revision": 0, "idempotency_key": "vpi-2026-09"}).json() == saved.json()
    assert client.put(path, json={**VPI, "base_revision": 0, "idempotency_key": "vpi-stale-1"}).status_code == 409
    for wrong in ({"2026-13": "120"}, {"2026-09": "0"}, {"2026-09": "120.1234"}, {"2026-09": "abc"}):
        assert client.put(path, json={"base_year": 2020, "values": wrong, "base_revision": 1,
                                      "idempotency_key": f"vpi-bad-{len(str(wrong))}"}).status_code == 422

    # suggestions from the rent history and the series; refused without an index clause
    composed = compose(case, "builtin:index_rent")
    assert composed["inputs"] == {"receipt_date": "2026-10-23", "base_month": "2024-03", "base_index": "117.4",
                                  "new_month": "2026-09", "new_index": "123.6"}
    assert any(check["level"] == "error" and "keine Indexmiete" in check["text"] for check in composed["checks"])

    store._patch_entity("contract", case["contract"].id, ContractPatch(index_rent="index"))
    if hasattr(store, "db"):
        store.db.commit()
    composed = compose(case, "builtin:index_rent")
    assert not [check for check in composed["checks"] if check["level"] == "error"], composed["checks"]
    body = composed["data"]["body"]
    assert "von 117,4 Punkten im März 2024 auf 123,6 Punkte im September 2026 gestiegen (2020 = 100)" in body
    assert "Veränderung um 5,28 %" in body                      # 123.6 / 117.4 − 1
    assert "von 650,00 € um 34,33 € auf **684,33 €**" in body    # 650 × 123.6 ÷ 117.4, to the cent
    assert "ab dem **01.12.2026**" in body                       # second month after receipt in October
    rows = composed["blocks"]["indexmiete"]["rows"]
    assert rows[1][1:] == ["117,4 (März 2024)", "123,6 (September 2026)"] and rows[-1][1:] == ["880,00 €", "914,33 €"]

    # the rent must stay unchanged for a year; a lower index gives no increase; entries differing from the series warn
    early = compose(case, "builtin:index_rent", {"receipt_date": "2024-12-20", "base_month": "2024-03", "base_index": "117.4",
                                                  "new_month": "2024-11", "new_index": "119"}, issue="2024-12-15")
    assert any(check["level"] == "error" and "frühestens wirksam ab 01.03.2025" in check["text"] for check in early["checks"])
    assert any(check["level"] == "warning" and "November 2024" in check["text"] for check in early["checks"])
    lower = compose(case, "builtin:index_rent", {**composed["inputs"], "new_index": "117.0"})
    assert any("nicht gestiegen" in check["text"] for check in lower["checks"] if check["level"] == "error")
    assert any("weicht vom hinterlegten Wert 123,6 ab" in check["text"] for check in lower["checks"])
    bad = case["client"].post(base(case) + "/compose", json={"template_id": "builtin:index_rent", "issue_date": ISSUE,
                                                             "inputs": {**composed["inputs"], "new_month": "2026-9"}})
    assert bad.status_code == 422

    # archived like every letter
    payload, shown = preview(case, composed)
    archived = client.post(base(case), json={**payload, "review_hash": shown["review_hash"], "idempotency_key": "index-letter-1"})
    assert archived.status_code in (200, 201), archived.text


def test_only_owner_or_manager_keep_the_price_index(case):
    clerk = auth.register_user("letter-books", "books-letters@example.test", "Nora Buch", "Secret123", "buchhaltung")
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(clerk.id)}) as client:
        assert client.get("/api/v1/letter-templates/price-index").json()["can_edit"] is False
        refused = client.put("/api/v1/letter-templates/price-index", json={**VPI, "base_revision": 0,
                                                                          "idempotency_key": "vpi-clerk-1"})
        assert refused.status_code == 403


@pytest.mark.parametrize("stored, model", [("index", "index"), ("Indexmiete (VPI)", "index"), ("stepped", "stepped"),
                                           ("Staffelmiete", "stepped"), ("fixed", "fixed"), ("Festmiete", "fixed"),
                                           (None, None), ("", None)])
def test_the_rent_model_is_read_from_keys_and_older_texts(stored, model):
    from backend.services.letter_templates import rent_model
    assert rent_model({"index_rent": stored}) == model


def test_rent_letters_name_business_premises(case):
    from backend.models import UnitPatch
    store._patch_entity("unit", case["unit"].id, UnitPatch(unit_type="Gewerbe"))
    if hasattr(store, "db"):
        store.db.commit()
    increase = compose(case, "builtin:rent_increase", RENT_INCREASE)
    assert any(check["level"] == "error" and "nur für Wohnraum" in check["text"] for check in increase["checks"])
    index = compose(case, "builtin:index_rent", {"receipt_date": "2026-10-23", "base_month": "2024-03",
                                                 "base_index": "117.4", "new_month": "2026-09", "new_index": "123.6"})
    assert any(check["level"] == "warning" and "Wertsicherungsklausel" in check["text"] for check in index["checks"])
