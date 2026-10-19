"""Neuvermietung: a vacant unit as a project from the offer to the tenancy and the deletion of applicants.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite.
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest
from archive_helpers import purge_deposits, purge_handover, purge_originals
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.routers.files import _file_url_to_key
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot
from backend.services.file_storage import get_file_storage

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
API = "/api/v1"
BASE = f"{API}/reletting"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _reset_data():
    purge_deposits(store)
    purge_handover(store)
    purge_originals(store)
    clear_business_data(store)


@pytest.fixture(autouse=True)
def _clean():
    _reset_data()
    auth.clear_users()
    yield
    _reset_data()
    auth.clear_users()


def _user(name, role="eigentuemer", **access):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role, **access)


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.fixture
def client():
    return _client(_user("linda.reiser"))


def _estate(name="Nord", number="V-1", city="Dresden"):
    portfolio = store.create_portfolio(PortfolioCreate(name=name, owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"{name} Bautzner Straße 61",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city=city, year_built=1994))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="Wohnung", rooms=2,
                                        area_sqm=60.5, floor="2. OG", cold_rent=500, service_charge_advance=150,
                                        heating_advance=50))
    old = store.create_tenant(TenantCreate(full_name=f"Vormieter {number}"))
    store.create_contract(ContractCreate(contract_number=number, property_id=prop.id, unit_id=unit.id,
                                         tenant_id=old.id, start_date=date(2020, 1, 1),
                                         end_date=date.today() - timedelta(days=20), status="expired"))
    return {"portfolio": portfolio, "property": prop, "unit": unit}


OFFER = {"available_from": "2026-12-01", "target_rent": 800, "service_charge": 150, "heating_charge": 50,
         "deposit_amount": 2400, "income_factor": 3, "max_persons": 3, "pets": "not_allowed",
         "headline": "Helle 2-Zimmer-Wohnung mit Balkon", "description": "Ruhige Lage im Hinterhaus.",
         "features_text": "Balkon, Einbauküche", "location_text": "Nahe Alaunpark",
         "contact_name": "Linda Reiser", "contact_phone": "0351 123456", "contact_email": "vermietung@example.com"}
GOOD = {"full_name": "Anna Bergmann", "email": "anna@example.com", "phone": "0170 111", "household_size": 2,
        "net_income": 3200, "employment": "permanent", "move_in_date": "2026-12-01", "pets": "keine",
        "doc_self_disclosure": True, "doc_income": True, "doc_credit_report": True,
        "doc_landlord_reference": True, "doc_id_checked": True}
WEAK = {"full_name": "Bernd Krause", "email": "bernd@example.com", "household_size": 4, "net_income": 2500,
        "employment": "temporary", "move_in_date": "2027-03-01", "pets": "Hund"}


def _project(client, estate):
    started = client.post(BASE, json={"unit_id": estate["unit"].id})
    assert started.status_code == 201, started.text
    project = started.json()["project"]
    updated = client.put(f"{BASE}/{project['id']}", json={**OFFER, "base_updated_at": project["updated_at"]})
    assert updated.status_code == 200, updated.text
    return updated.json()


def _applicants(detail):
    return {row["full_name"]: row for row in detail["applicants"]}


def test_a_project_starts_from_the_unit_and_the_overview_shows_vacancies(client):
    estate = _estate()
    overview = client.get(BASE).json()
    assert [row["unit_id"] for row in overview["vacancies"]] == [estate["unit"].id]
    assert overview["vacancies"][0]["vacant_since"] == (date.today() - timedelta(days=20)).isoformat()
    started = client.post(BASE, json={"unit_id": estate["unit"].id})
    assert started.status_code == 201, started.text
    data = started.json()
    project = data["project"]
    assert (project["target_rent"], project["service_charge"], project["heating_charge"]) == (500, 150, 50)
    assert project["deposit_amount"] == 1500 and project["year_built"] == 1994
    assert project["headline"] == "2-Zimmer-Wohnung in Dresden"
    assert data["warm_rent"] == 700 and data["unit"]["label"] == "WE 3"
    assert data["property"]["address"] == "Bautzner Straße 61, 01099 Dresden"
    assert [step["key"] for step in data["steps"]] == ["offer", "expose", "applicants", "viewings", "choice",
                                                       "contract", "privacy"]
    assert "Art des Energieausweises" in data["missing_for_ad"]
    again = client.post(BASE, json={"unit_id": estate["unit"].id})
    assert again.status_code == 409 and "bereits" in again.json()["error"]["message"]
    overview = client.get(BASE).json()
    assert overview["vacancies"] == [] and overview["totals"]["open"] == 1
    assert overview["projects"][0]["href"] == f"/reletting/{project['id']}"
    # a newer change is not overwritten by an older form
    stale = client.put(f"{BASE}/{project['id']}", json={**OFFER, "base_updated_at": "2000-01-01T00:00:00"})
    assert stale.status_code == 409


def test_applicants_are_compared_by_the_same_criteria_and_viewings_count(client):
    estate = _estate()
    detail = _project(client, estate)
    project_id = detail["project"]["id"]
    assert detail["warm_rent"] == 1000
    for applicant in (WEAK, GOOD):
        response = client.post(f"{BASE}/{project_id}/applicants", json=applicant)
        assert response.status_code == 201, response.text
    rows = response.json()["applicants"]
    assert [row["full_name"] for row in rows] == ["Anna Bergmann", "Bernd Krause"]        # most requirements met
    good, weak = _applicants(response.json())["Anna Bergmann"], _applicants(response.json())["Bernd Krause"]
    states = lambda row: {c["key"]: c["state"] for c in row["criteria"]}  # noqa: E731
    assert states(good) == {"income": "met", "persons": "met", "move_in": "met", "pets": "met", "documents": "met",
                            "viewing": "open"}
    assert states(weak) == {"income": "not_met", "persons": "not_met", "move_in": "not_met", "pets": "not_met",
                            "documents": "open", "viewing": "open"}
    income = next(c for c in good["criteria"] if c["key"] == "income")
    assert income["label"] == "Einkommen mindestens 3,0-fache Warmmiete" and income["detail"] == "3,2-fache Warmmiete"
    assert good["rent_share"] == 31.2 and good["project_id"] == project_id and good["unit_id"] == estate["unit"].id
    when = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    planned = client.post(f"{BASE}/{project_id}/viewings", json={"lead_id": good["id"], "scheduled_at": when})
    assert planned.status_code == 201, planned.text
    good = _applicants(planned.json())["Anna Bergmann"]
    assert good["status"] == "viewing_scheduled"
    viewing = planned.json()["viewings"][0]
    assert viewing["lead_name"] == "Anna Bergmann" and viewing["unit_id"] == estate["unit"].id
    # the viewing appears in the viewing calendar
    assert [v["id"] for v in client.get(f"{API}/viewings").json()] == [viewing["id"]]
    assert client.get(BASE).json()["projects"][0]["next_viewing"] is not None
    done = client.put(f"{BASE}/{project_id}/viewings/{viewing['id']}",
                      json={"lead_id": good["id"], "scheduled_at": when, "status": "completed", "rating": 5,
                            "notes": "Pünktlich, freundlich"})
    assert done.status_code == 200, done.text
    good = _applicants(done.json())["Anna Bergmann"]
    assert states(good)["viewing"] == "met" and good["viewing_rating"] == 5
    assert next(step for step in done.json()["steps"] if step["key"] == "viewings")["done"] is True
    # the calendar's own form keeps the rating it does not show
    kept = client.put(f"{API}/viewings/{viewing['id']}", json={"lead_id": good["id"], "unit_id": estate["unit"].id,
                                                              "scheduled_at": when, "status": "completed"})
    assert kept.status_code == 200 and kept.json()["rating"] == 5
    # so does the leads page for the applicant details
    kept = client.put(f"{API}/leads/{good['id']}", json={"full_name": "Anna Bergmann", "status": "viewing_scheduled",
                                                         "notes": "Rückruf"})
    assert kept.status_code == 200, kept.text
    assert (kept.json()["project_id"], kept.json()["net_income"], kept.json()["doc_income"]) == (project_id, 3200, True)
    # a viewing is not planned for an applicant someone else's project owns
    other = _estate("Süd", "V-2", "Leipzig")
    foreign = _project(client, other)
    wrong = client.post(f"{BASE}/{foreign['project']['id']}/viewings", json={"lead_id": good["id"], "scheduled_at": when})
    assert wrong.status_code == 404


def test_accepting_an_applicant_makes_the_tenant_prefills_the_contract_and_closes(client):
    estate = _estate()
    detail = _project(client, estate)
    project_id = detail["project"]["id"]
    client.post(f"{BASE}/{project_id}/applicants", json=GOOD)
    weak = client.post(f"{BASE}/{project_id}/applicants", json=WEAK).json()
    good, bad = _applicants(weak)["Anna Bergmann"], _applicants(weak)["Bernd Krause"]
    accepted = client.post(f"{BASE}/{project_id}/accept", json={"lead_id": good["id"]})
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()
    tenant = store.get_tenant(data["project"]["tenant_id"])
    assert (tenant.full_name, tenant.email, tenant.phone) == ("Anna Bergmann", "anna@example.com", "0170 111")
    assert data["tenant"]["href"] == f"/tenants/{tenant.id}/account"
    assert data["contract_prefill"] == {"property_id": estate["property"].id, "unit_id": estate["unit"].id,
                                        "tenant_id": tenant.id, "status": "active", "start_date": "2026-12-01",
                                        "deposit_amount": 2400, "persons": 2}
    assert data["rent_applied"] is True
    unit = store.get_unit(estate["unit"].id)
    assert (unit.cold_rent, unit.service_charge_advance, unit.heating_advance) == (800, 150, 50)
    assert _applicants(data)["Anna Bergmann"]["status"] == "accepted"
    second = client.post(f"{BASE}/{project_id}/accept", json={"lead_id": bad["id"]})
    assert second.status_code == 409 and "Anna Bergmann" in second.json()["error"]["message"]
    # the contract form saves the prefilled contract; its first rent is the offered rent
    contract = client.post(f"{API}/contracts", json={**data["contract_prefill"], "contract_number": "MV-2026-7"})
    assert contract.status_code == 201, contract.text
    assert client.get(f"{API}/contracts/current-rents", params={"as_of": "2026-12-15"}).json()[
        contract.json()["id"]]["cold_rent"] == 800
    other = _estate("Süd", "V-2", "Leipzig")
    elsewhere = store.create_contract(ContractCreate(contract_number="MV-9", property_id=other["property"].id,
                                                     unit_id=other["unit"].id, tenant_id=tenant.id,
                                                     start_date=date(2026, 12, 1)))
    wrong = client.post(f"{BASE}/{project_id}/close", json={"contract_id": elsewhere.id})
    assert wrong.status_code == 409 and "Einheit" in wrong.json()["error"]["message"]
    listing = client.post(f"{BASE}/{project_id}/listing")
    assert listing.status_code == 200, listing.text
    closed = client.post(f"{BASE}/{project_id}/close", json={"contract_id": contract.json()["id"]})
    assert closed.status_code == 200, closed.text
    project = closed.json()["project"]
    assert project["status"] == "closed" and project["contract_id"] == contract.json()["id"]
    assert store.get_listing(project["listing_id"]).status == "closed"
    assert client.put(f"{BASE}/{project_id}", json=OFFER).status_code == 409
    # once let, every remaining applicant may be deleted, the taken-over one included
    purge = client.post(f"{BASE}/{project_id}/purge", json={"lead_ids": [good["id"], bad["id"]], "confirmed": True})
    assert purge.status_code == 200, purge.text
    assert purge.json()["deleted"] == 2 and purge.json()["applicants"] == []
    assert next(step for step in purge.json()["steps"] if step["key"] == "privacy")["done"] is True
    assert store.get_tenant(tenant.id).full_name == "Anna Bergmann"           # the tenant record stays


def test_rejected_applicants_are_deleted_with_their_documents_and_traces(client):
    estate = _estate()
    project_id = _project(client, estate)["project"]["id"]
    client.post(f"{BASE}/{project_id}/applicants", json=GOOD)
    data = client.post(f"{BASE}/{project_id}/applicants", json=WEAK).json()
    good, weak = _applicants(data)["Anna Bergmann"], _applicants(data)["Bernd Krause"]
    uploaded = client.post(f"{BASE}/{project_id}/applicants/{weak['id']}/attachments",
                           files={"file": ("Selbstauskunft.pdf", PDF, "application/pdf")}, data={"title": "Selbstauskunft"})
    assert uploaded.status_code == 201, uploaded.text
    attachment = _applicants(uploaded.json())["Bernd Krause"]["attachments"][0]
    assert (attachment["kind"], attachment["title"]) == ("document", "Selbstauskunft")
    key = _file_url_to_key(attachment["file_url"])
    assert key.startswith(f"applicants/{weak['id']}/") and get_file_storage().get(key) == PDF
    assert client.get(attachment["file_url"]).content == PDF                      # served to the office
    refused = client.post(f"{BASE}/{project_id}/applicants/{weak['id']}/attachments",
                          files={"file": ("page.html", b"<script>", "text/html")})
    assert refused.status_code == 415
    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()
    client.post(f"{BASE}/{project_id}/viewings", json={"lead_id": weak["id"], "scheduled_at": when})
    store.add_change_history("lead", weak["id"], "notes", None, "rief an", reason="Feld geändert")
    store.add_change_history("lead", good["id"], "notes", None, "bleibt", reason="Feld geändert")
    assert client.post(f"{BASE}/{project_id}/purge", json={"lead_ids": [weak["id"]]}).status_code == 422
    open_lead = client.post(f"{BASE}/{project_id}/purge", json={"lead_ids": [good["id"]], "confirmed": True})
    assert open_lead.status_code == 409 and "Anna Bergmann" in open_lead.json()["error"]["message"]
    rejected = client.post(f"{BASE}/{project_id}/reject", json={"lead_ids": [weak["id"]]})
    assert rejected.status_code == 200
    row = _applicants(rejected.json())["Bernd Krause"]
    assert row["status"] == "rejected" and row["decided_at"] and row["deletable"] and row["purge_due"] is False
    assert client.post(f"{BASE}/{project_id}/viewings", json={"lead_id": weak["id"], "scheduled_at": when}).status_code == 409
    purged = client.post(f"{BASE}/{project_id}/purge", json={"lead_ids": [weak["id"]], "confirmed": True})
    assert purged.status_code == 200, purged.text
    assert (purged.json()["deleted"], purged.json()["deleted_files"]) == (1, 1)
    assert purged.json()["project"]["deleted_applicants"] == 1
    assert [row["full_name"] for row in purged.json()["applicants"]] == ["Anna Bergmann"]
    assert get_file_storage().get(key) is None
    assert client.get(f"{API}/leads/{weak['id']}").status_code == 404
    assert [v for v in store.list_viewing_appointments() if v.lead_id == weak["id"]] == []
    assert [a for a in store.list_lead_attachments() if a.lead_id == weak["id"]] == []
    assert {h.entity_id for h in store.list_change_history() if h.entity_type == "lead"} == {good["id"]}


def test_portal_text_expose_and_the_ai_question_name_no_applicant(client):
    estate = _estate()
    project_id = _project(client, estate)["project"]["id"]
    text = client.get(f"{BASE}/{project_id}/portal-text").json()
    assert "Art des Energieausweises" in text["missing"]
    energy = {**OFFER, "energy_certificate": "consumption", "energy_value": 112.5, "energy_class": "D",
              "energy_carrier": "Erdgas", "heating_type": "Zentralheizung", "year_built": 1994}
    assert client.put(f"{BASE}/{project_id}", json=energy).status_code == 200
    text = client.get(f"{BASE}/{project_id}/portal-text").json()
    assert text["missing"] == []
    blocks = {block["key"]: block["text"] for block in text["blocks"]}
    assert "Warmmiete: 1.000,00 €" in blocks["facts"] and "Wohnfläche: 60,5 m²" in blocks["facts"]
    assert "Bezugsfrei ab: 01.12.2026" in blocks["facts"] and "Haustiere: nicht erlaubt" in blocks["facts"]
    assert blocks["energy"].splitlines() == ["Energieausweis: Verbrauchsausweis",
                                             "Endenergieverbrauch: 112,5 kWh/(m²·a)", "Energieeffizienzklasse: D",
                                             "Wesentlicher Energieträger: Erdgas", "Baujahr laut Energieausweis: 1994",
                                             "Heizungsart: Zentralheizung"]
    assert blocks["all"].startswith("Helle 2-Zimmer-Wohnung mit Balkon\n\nEckdaten und Kosten\n")
    pdf = client.get(f"{BASE}/{project_id}/expose")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"] == "application/pdf" and "no-store" in pdf.headers["cache-control"]
    assert client.get(f"{BASE}/{project_id}/ai-question").status_code == 409            # nobody to compare yet
    client.post(f"{BASE}/{project_id}/applicants", json={**GOOD, "notes": "kennt den Hausmeister"})
    client.post(f"{BASE}/{project_id}/applicants", json=WEAK)
    question = client.get(f"{BASE}/{project_id}/ai-question").json()
    assert question["applicants"] == 2
    body = question["question"]
    assert "Bewerbung A:" in body and "Bewerbung B:" in body and "§ 1 AGG" in body
    assert "Warmmiete: 1.000,00 €" in body and "Einkommen mindestens 3,0-fache Warmmiete: erfüllt" in body
    for private in ("Anna", "Bergmann", "Krause", "anna@example.com", "0170", "Hausmeister", "3.200", "3200"):
        assert private not in body


def test_a_project_stays_inside_the_portfolio_boundary_and_writes_need_the_area(client):
    north, south = _estate("Nord", "V-1"), _estate("Süd", "V-2", "Leipzig")
    hidden = client.post(BASE, json={"unit_id": south["unit"].id}).json()["project"]["id"]
    staff = _client(_user("staff", "verwalter", portfolio_access="selected", portfolio_ids=[north["portfolio"].id]))
    assert staff.get(f"{BASE}/{hidden}").status_code == 404
    assert staff.post(f"{BASE}/{hidden}/applicants", json=GOOD).status_code == 404
    overview = staff.get(BASE).json()
    assert overview["projects"] == [] and [row["unit_id"] for row in overview["vacancies"]] == [north["unit"].id]
    assert staff.post(BASE, json={"unit_id": south["unit"].id}).status_code == 404
    assert staff.post(BASE, json={"unit_id": north["unit"].id}).status_code == 201
    technician = _client(_user("hausmeister", "techniker"))
    refused = technician.post(BASE, json={"unit_id": north["unit"].id})
    assert refused.status_code == 403
    assert technician.get(BASE).status_code == 200


def test_the_project_travels_with_snapshots_and_guards_its_unit(client):
    estate = _estate()
    project_id = _project(client, estate)["project"]["id"]
    lead = client.post(f"{BASE}/{project_id}/applicants", json=GOOD).json()["applicants"][0]
    client.post(f"{BASE}/{project_id}/applicants/{lead['id']}/attachments",
                files={"file": ("Gehalt.pdf", PDF, "application/pdf")})
    removed = client.delete(f"{API}/units/{estate['unit'].id}")
    assert removed.status_code == 409 and "Neuvermietungsprojekt" in removed.json()["error"]["message"]
    snapshot = export_snapshot(store)
    assert [row["id"] for row in snapshot["reletting_projects"]] == [project_id]
    assert snapshot["leads"][0]["net_income"] == 3200
    assert len(snapshot["lead_attachments"]) == 1
    clear_business_data(store)
    import_snapshot(store, snapshot, replace=True)
    restored = client.get(f"{BASE}/{project_id}").json()
    assert restored["project"]["headline"] == OFFER["headline"]
    assert _applicants(restored)["Anna Bergmann"]["doc_income"] is True
    assert len(_applicants(restored)["Anna Bergmann"]["attachments"]) == 1
    # deleting the lead on the leads page also removes its document
    url = _applicants(restored)["Anna Bergmann"]["attachments"][0]["file_url"]
    assert client.delete(f"{API}/leads/{lead['id']}").status_code == 204
    assert get_file_storage().get(_file_url_to_key(url)) is None
    assert store.list_lead_attachments() == []
