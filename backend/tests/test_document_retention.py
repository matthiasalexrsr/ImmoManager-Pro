"""Retention periods: class by type or choice, period end, deletion lock, override with a reason."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient

from backend import audit, auth
from backend.app import app
from backend.dependencies import store
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services import document_retention as retention
from backend.services.data_snapshot import clear_business_data

YEARS = {"document_retention_booking_years": 8, "document_retention_accounts_years": 10,
         "document_retention_letters_years": 6, "document_retention_contract_years": 3}


def _doc(**values):
    base = dict(document_type=None, retention_class=None, document_date=None, valid_until=None,
                created_at=datetime(2026, 10, 20, tzinfo=timezone.utc))
    return SimpleNamespace(**{**base, **values})


@pytest.mark.parametrize("values, contract_end, expected", [
    ({"document_type": "Rechnung", "document_date": date(2024, 3, 1)}, None, ("booking_record", "2032-12-31", "running")),
    ({"document_type": "invoice", "document_date": date(2016, 6, 1)}, None, ("booking_record", "2024-12-31", "ended")),
    ({"document_type": "Steuerbescheid", "document_date": date(2020, 1, 1)}, None, ("accounts", "2030-12-31", "running")),
    ({"document_type": "dunning_letter", "document_date": date(2019, 5, 1)}, None, ("business_letter", "2025-12-31", "ended")),
    ({"document_type": "Mietvertrag"}, None, ("contract", None, "open")),
    ({"document_type": "Mietvertrag"}, date(2022, 6, 30), ("contract", "2025-12-31", "ended")),
    ({"document_type": "Versicherung", "valid_until": date(2027, 3, 1)}, None, ("contract", "2030-12-31", "running")),
    ({"document_type": "Grundbuchauszug"}, None, ("permanent", None, "permanent")),
    ({"document_type": "Energieausweis"}, None, ("none", None, "none")),
    ({"document_type": None}, None, ("none", None, "none")),
    # chosen on the document beats the type; without a date the creation year counts
    ({"document_type": "Sonstiges", "retention_class": "booking_record"}, None, ("booking_record", "2034-12-31", "running")),
    ({"document_type": "Rechnung", "retention_class": "none"}, None, ("none", None, "none")),
])
def test_class_and_period_end(values, contract_end, expected):
    result = retention.assess(_doc(**values), contract_end, YEARS, today=date(2026, 10, 20))
    assert (result["retention_class"], result["until"], result["state"]) == expected
    assert result["locked"] is (expected[2] in ("running", "open", "permanent"))
    assert result["chosen"] is bool(values.get("retention_class"))


def test_the_period_ends_on_31_december_and_the_next_day_is_free():
    invoice = _doc(document_type="Rechnung", document_date=date(2018, 12, 31))
    assert retention.assess(invoice, None, YEARS, today=date(2026, 12, 31))["locked"] is True
    assert retention.assess(invoice, None, YEARS, today=date(2027, 1, 1))["locked"] is False
    longer = {**YEARS, "document_retention_booking_years": 10}
    assert retention.assess(invoice, None, longer, today=date(2027, 1, 1))["until"] == "2028-12-31"


@pytest.fixture
def case(monkeypatch):
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    audit.clear_audit_logs()
    owner = auth.register_user("keep-owner", "keep@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    booker = auth.register_user("keep-books", "books@example.test", "Nora Buch", "Secret123", "buchhaltung")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="EG links", unit_type="apartment", area_sqm=58))
    tenant = store.create_tenant(TenantCreate(full_name="Sabine Krause"))
    ended = store.create_contract(ContractCreate(contract_number="MV-1", property_id=prop.id, unit_id=unit.id,
                                                 tenant_id=tenant.id, start_date=date(2015, 1, 1),
                                                 end_date=date(2021, 3, 31), status="expired"))
    clients = {name: TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
               for name, user in (("owner", owner), ("books", booker))}
    yield {"property": prop, "contract": ended, **clients}
    for client in clients.values():
        client.close()
    auth.clear_users()
    clear_business_data(store)


def _create(case, **values):
    response = case["owner"].post("/api/v1/documents", json={"title": values.pop("title", "Dokument"),
                                                            "property_id": case["property"].id,
                                                            "file_url": "/uploads/documents/x.pdf", **values})
    assert response.status_code == 201, response.text
    return response.json()


def test_deleting_is_refused_while_the_period_runs_and_allowed_after_it(case):
    owner = case["owner"]
    invoice = _create(case, title="Heizungswartung 2025", document_type="Rechnung", document_date="2025-11-03")
    old = _create(case, title="Rechnung 2015", document_type="Rechnung", document_date="2015-02-01")
    lease = _create(case, title="Mietvertrag MV-1", document_type="Mietvertrag", contract_id=case["contract"].id)
    loose = _create(case, title="Notiz", document_type="Sonstiges")

    listed = owner.get("/api/v1/documents/retention").json()
    assert listed["items"][invoice["id"]]["until"] == "2033-12-31"
    assert listed["items"][lease["id"]]["until"] == "2024-12-31"              # ended 2021 + 3 years
    assert {item["key"]: item["years"] for item in listed["rules"]["classes"]}["booking_record"] == 8

    refused = owner.delete(f"/api/v1/documents/{invoice['id']}")
    assert refused.status_code == 409
    assert "aufzubewahren bis 31.12.2033" in refused.json()["error"]["message"]
    for document in (old, lease, loose):                                      # ended or no period
        assert owner.delete(f"/api/v1/documents/{document['id']}").status_code == 204

    bulk = owner.post("/api/v1/admin/bulk-delete/documents", json={"ids": [invoice["id"]]}).json()
    assert bulk["deleted"] == 0 and "31.12.2033" in bulk["errors"][0]["error"]
    assert store.get_document(invoice["id"]).title == "Heizungswartung 2025"


def test_an_owner_deletes_despite_the_period_only_with_a_reason_kept_in_the_audit_journal(case):
    duplicate = _create(case, title="Rechnung doppelt abgelegt", document_type="Rechnung", document_date="2026-10-01")
    path = f"/api/v1/documents/{duplicate['id']}"
    assert case["books"].delete(path, params={"retention_override": "Duplikat der Rechnung R-17"}).status_code == 403
    assert case["owner"].delete(path, params={"retention_override": "zu kurz"}).status_code == 422
    assert case["owner"].delete(path, params={"retention_override": "Duplikat der Rechnung R-17"}).status_code == 204
    entries = [entry for entry in audit.list_audit_logs() if entry.action == "document_retention_override"]
    assert len(entries) == 1 and entries[0].entity_id == duplicate["id"]
    changes = entries[0].changes or ""
    assert "Duplikat der Rechnung R-17" in changes and "2034-12-31" in changes


def test_the_class_can_be_chosen_on_the_document_and_the_years_are_settings(case):
    owner = case["owner"]
    paper = _create(case, title="Kaufvertrag", document_type="Sonstiges", retention_class="permanent")
    assert owner.get("/api/v1/documents/retention").json()["items"][paper["id"]]["state"] == "permanent"
    assert owner.delete(f"/api/v1/documents/{paper['id']}").status_code == 409
    changed = owner.patch(f"/api/v1/documents/{paper['id']}", json={"retention_class": "none"})
    assert changed.status_code == 200 and changed.json()["retention_class"] == "none"
    assert owner.patch(f"/api/v1/documents/{paper['id']}", json={"retention_class": "forever"}).status_code == 422

    # nine years old: eight years of retention are over, ten are not (a fixed 2017 ended on 31.12.2027)
    year = date.today().year - 9
    invoice = _create(case, title=f"Rechnung {year}", document_type="Rechnung", document_date=f"{year}-05-01")
    assert owner.get("/api/v1/documents/retention").json()["items"][invoice["id"]]["state"] == "ended"
    saved = owner.put("/api/v1/auth/users/me/settings", json={
        "values": {"document_retention_booking_years": 10}, "base_revision": 0, "idempotency_key": "keep-10-years",
        "scope": "global"})
    assert saved.status_code in (200, 201), saved.text
    assert owner.get("/api/v1/documents/retention").json()["items"][invoice["id"]]["until"] == f"{year + 10}-12-31"
    assert owner.delete(f"/api/v1/documents/{invoice['id']}").status_code == 409
