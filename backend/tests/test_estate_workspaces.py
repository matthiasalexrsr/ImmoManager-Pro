"""Property, unit and document files use the same associations as their sources."""

from datetime import date
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    ContractCreate,
    DocumentCreate,
    PortfolioCreate,
    PropertyCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import document_text
from backend.services.file_storage import get_file_storage


@pytest.fixture
def estate():
    store.clear_all()
    auth.clear_users()
    user = auth.register_user("estate-review", "estate@example.test", "Prüfung", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand"))
    props = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=name, property_type="MFH"))
             for name in ("Haus A", "Haus B")]
    units = [store.create_unit(UnitCreate(property_id=prop.id, label="Wohnung", unit_type="Wohnung")) for prop in props]
    tenant = store.create_tenant(TenantCreate(full_name="Partei"))
    contract = store.create_contract(ContractCreate(contract_number="MV-1", property_id=props[0].id,
        unit_id=units[0].id, tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    yield client, portfolio, props, units, tenant, contract
    auth.clear_users()
    store.clear_all()


@pytest.mark.parametrize("kind,field", [("properties", "portfolio_id"), ("units", "property_id")])
def test_partial_edits_validate_parent_before_writing(estate, kind, field):
    client, _, props, units, _, _ = estate
    record = props[0] if kind == "properties" else units[0]
    result = client.patch(f"/api/v1/{kind}/{record.id}", json={field: "missing-parent"})
    assert result.status_code == 400, result.text
    assert client.get(f"/api/v1/{kind}/{record.id}").json()[field] == getattr(record, field)


@pytest.mark.parametrize("changes", [{"cold_rent": -1}, {"heating_advance": -0.01}, {"person_count": -1},
                                     {"rooms": -1}, {"label": "   "}])
def test_invalid_unit_defaults_are_rejected_and_remain_correctable(estate, changes):
    client, _, props, units, _, _ = estate
    response = client.post("/api/v1/units", json={"property_id": props[0].id, "label": "Neu", "unit_type": "Wohnung", **changes})
    assert response.status_code == 400, response.text
    assert len(store.list_units()) == len(units)


def test_invalid_legacy_rent_does_not_leave_a_half_created_contract(estate):
    client, _, props, units, tenant, contract = estate
    bad_unit = store.update_unit(units[1].id, UnitCreate(property_id=props[1].id, label="Alte Vorgabe", unit_type="Wohnung", cold_rent=-20))
    response = client.post("/api/v1/contracts", json={"contract_number": "MV-Fehlversuch", "property_id": props[1].id,
        "unit_id": bad_unit.id, "tenant_id": tenant.id, "start_date": "2026-01-01"})
    assert response.status_code == 400, response.text
    assert [row.id for row in store.list_contracts()] == [contract.id]
    # The legacy record can still be read and corrected; no new validator hides the whole list.
    assert client.get(f"/api/v1/units/{bad_unit.id}").status_code == 200
    assert client.patch(f"/api/v1/units/{bad_unit.id}", json={"cold_rent": 0}).status_code == 200
    assert client.post("/api/v1/contracts", json={"contract_number": "MV-Fehlversuch", "property_id": props[1].id,
        "unit_id": bad_unit.id, "tenant_id": tenant.id, "start_date": "2026-01-01"}).status_code == 201


@pytest.mark.parametrize("method", ["put", "patch"])
def test_unit_move_cannot_invalidate_an_existing_contract(estate, method):
    client, _, props, units, _, contract = estate
    values = units[0].model_dump(mode="json", include=set(UnitCreate.model_fields)) if method == "put" else {}
    result = getattr(client, method)(f"/api/v1/units/{units[0].id}", json={**values, "property_id": props[1].id})
    assert result.status_code == 409, result.text
    assert "Vertrag" in result.text
    assert store.get_unit(units[0].id).property_id == store.get_contract(contract.id).property_id


def test_unit_move_protects_tasks_but_an_unreferenced_unit_can_be_corrected(estate):
    client, _, props, units, _, _ = estate
    task = store.create_task(TaskCreate(title="Ablesen", property_id=props[1].id, unit_id=units[1].id))
    result = client.patch(f"/api/v1/units/{units[1].id}", json={"property_id": props[0].id})
    assert result.status_code == 409, result.text
    assert "Aufgabe" in result.text
    store.delete_task(task.id)
    result = client.patch(f"/api/v1/units/{units[1].id}", json={"property_id": props[0].id})
    assert result.status_code == 200, result.text
    assert result.json()["property_id"] == props[0].id


def test_contract_unit_filter_is_applied_before_pagination(estate):
    client, _, props, units, tenant, contract = estate
    store.create_contract(ContractCreate(contract_number="MV-2", property_id=props[1].id,
        unit_id=units[1].id, tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    response = client.get("/api/v1/contracts", params={"unit_id": units[0].id, "limit": 1})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [contract.id]
    assert client.get("/api/v1/contracts", params={"unit_id": units[0].id, "skip": 1}).json() == []


def test_property_and_unit_documents_include_indirect_links_without_duplicates(estate):
    client, _, props, units, _, contract = estate
    def document(title, **binding):
        return store.create_document(DocumentCreate(title=title, file_url="/uploads/documents/test.pdf", **binding))
    direct = document("Objekt", property_id=props[0].id)
    via_unit = document("Einheit", unit_id=units[0].id)
    via_contract = document("Vertrag", contract_id=contract.id)
    full = document("Vollständig", property_id=props[0].id, unit_id=units[0].id, contract_id=contract.id)
    document("Anderes Objekt", unit_id=units[1].id)
    document("Ohne Zuordnung")
    for params, expected in [({"property_id": props[0].id}, {direct.id, via_unit.id, via_contract.id, full.id}),
                             ({"unit_id": units[0].id}, {via_unit.id, via_contract.id, full.id}),
                             ({"contract_id": contract.id}, {via_contract.id, full.id}),
                             ({"property_id": props[1].id, "unit_id": units[0].id}, set())]:
        pages = [client.get("/api/v1/documents", params={**params, "limit": 2, "skip": skip}) for skip in (0, 2, 4)]
        assert all(page.status_code == 200 for page in pages)
        ids = [row["id"] for page in pages for row in page.json()]
        assert set(ids) == expected
        assert len(ids) == len(expected)


def test_document_file_resolves_contract_location_and_party_without_rewriting_source(estate):
    client, _, props, units, tenant, contract = estate
    doc = store.create_document(DocumentCreate(title="Vertragsschreiben", file_url="/uploads/documents/test.pdf",
                                               contract_id=contract.id))
    response = client.get(f"/api/v1/documents/{doc.id}/details")
    assert response.status_code == 200, response.text
    details = response.json()
    assert details["document"]["property_id"] is None
    assert details["context"] == {"property_id": props[0].id, "unit_id": units[0].id,
                                   "contract_id": contract.id, "tenant_id": tenant.id}
    assert details["places"] == {"property": props[0].name, "unit": units[0].label,
                                  "contract": contract.contract_number, "tenant": tenant.full_name}


def test_indirect_document_pages_continue_after_one_thousand_records(estate):
    client, _, props, _, _, contract = estate
    expected = {store.create_document(DocumentCreate(title=f"Beleg {number:04}", contract_id=contract.id,
                    file_url="/uploads/documents/test.pdf")).id for number in range(1001)}
    pages = [client.get("/api/v1/documents", params={"property_id": props[0].id, "skip": skip,
                                                   "limit": 1000, "sort_by": "title"}) for skip in (0, 1000)]
    assert all(response.status_code == 200 for response in pages)
    assert [len(response.json()) for response in pages] == [1000, 1]
    ids = [row["id"] for response in pages for row in response.json()]
    assert len(ids) == len(set(ids)) == 1001
    assert set(ids) == expected


def test_unit_documents_without_a_document_date_still_show_newest_first(estate):
    client, _, _, units, _, contract = estate
    documents = [store.create_document(DocumentCreate(title=f"Undatiert {number}", contract_id=contract.id,
                     file_url="/uploads/documents/test.pdf")) for number in range(3)]
    response = client.get("/api/v1/documents", params={"unit_id": units[0].id,
        "sort_by": "document_date", "sort_order": "desc", "limit": 2})
    assert response.status_code == 200, response.text
    expected = sorted(documents, key=lambda row: (row.created_at, row.id), reverse=True)
    assert [row["id"] for row in response.json()] == [row.id for row in expected[:2]]


def test_indirect_documents_do_not_cross_the_viewers_portfolio(estate):
    client, portfolio, props, units, _, contract = estate
    own = store.create_document(DocumentCreate(title="Eigener Vertragsbeleg", contract_id=contract.id,
                                               file_url="/uploads/documents/own.pdf"))
    foreign_portfolio = store.create_portfolio(PortfolioCreate(name="Fremder Bestand"))
    foreign = store.create_property(PropertyCreate(portfolio_id=foreign_portfolio.id, name="Fremdes Haus", property_type="MFH"))
    foreign_unit = store.create_unit(UnitCreate(property_id=foreign.id, label="Wohnung", unit_type="Wohnung"))
    hidden = store.create_document(DocumentCreate(title="Vertraulicher Fremdbeleg", unit_id=foreign_unit.id,
                                                  file_url="/uploads/documents/foreign.pdf"))
    staff = auth.register_user("estate-staff", "estate-staff@example.test", "Verwaltung", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[portfolio.id])
    client.headers["Authorization"] = f"Bearer {auth.create_access_token(staff.id)}"
    for binding in ({"property_id": props[0].id}, {"unit_id": units[0].id}):
        response = client.get("/api/v1/documents", params=binding)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == [own.id]
    for binding in ({"property_id": foreign.id}, {"unit_id": foreign_unit.id}):
        response = client.get("/api/v1/documents", params=binding)
        assert response.status_code in (200, 403, 404)
        assert hidden.id not in response.text and hidden.title not in response.text
    assert client.get(f"/api/v1/documents/{hidden.id}/details").status_code == 404


def test_document_content_search_and_index_counts_share_the_file_context_and_all_pages(estate, monkeypatch):
    client, _, props, units, _, contract = estate
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage())
    path = f"documents/{uuid4().hex}-wartung.txt"
    get_file_storage().save(path, BytesIO("Rauchwarnmelder geprüft".encode()), content_type="text/plain")

    def indexed(title, **binding):
        document = store.create_document(DocumentCreate(title=title, file_url="/uploads/" + path, **binding))
        document_text.index_document(store, document)
        return document

    own = [indexed(f"Protokoll {number:02}", contract_id=contract.id) for number in range(31)]
    other = indexed("Anderes Haus", unit_id=units[1].id)
    if hasattr(store, "db"):
        store.db.commit()

    expected = [row.id for row in sorted(own, key=lambda row: (row.created_at, row.id), reverse=True)]
    for binding in ({"property_id": props[0].id}, {"unit_id": units[0].id}, {"contract_id": contract.id}):
        assert client.get("/api/v1/documents/text-index", params=binding).json() == {
            "documents": 31, "indexed": 31, "unreadable": 0}
        first = client.get("/api/v1/documents/search", params={"q": "RAUCHWARNMELDER", **binding})
        assert first.status_code == 200, first.text
        page = first.json()
        assert page["total"] == page["index"]["documents"] == 31
        assert page["has_more"] and page["next_skip"] == 25
        second = client.get("/api/v1/documents/search", params={"q": "RAUCHWARNMELDER", "skip": page["next_skip"], **binding}).json()
        assert [len(page["items"]), len(second["items"])] == [25, 6]
        assert [item["id"] for item in page["items"] + second["items"]] == expected
        assert not second["has_more"] and second["next_skip"] is None
        assert second["total"] == 31

    foreign = client.get("/api/v1/documents/search", params={"q": "Rauchwarnmelder", "unit_id": units[1].id}).json()
    assert [row["id"] for row in foreign["items"]] == [other.id]
    assert foreign["total"] == foreign["index"]["documents"] == 1
    empty = client.get("/api/v1/documents/search", params={"q": "Rauchwarnmelder", "property_id": props[1].id,
                                                         "unit_id": units[0].id}).json()
    assert empty["total"] == empty["index"]["documents"] == 0 and empty["items"] == []
    assert client.get("/api/v1/documents/search", params={"q": "Rauchwarnmelder", "skip": -1}).status_code == 422
