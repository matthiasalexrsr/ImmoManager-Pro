"""Party documents are complete, paginated and scoped to explicit ownership."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.orm_models import Base, DocumentORM
from backend.models import (
    ContractCreate,
    ContractRentPeriodCreate,
    DocumentCreate,
    DocumentPatch,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    TenantDocumentPage,
    TenantOverview,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.storage import InMemoryStore, NotFoundError, ValidationError


@pytest.fixture(params=["memory", "sqlite"])
def workspace_store(request):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield SQLAlchemyStore(session)
    engine.dispose()


@pytest.fixture
def parties(workspace_store):
    store = workspace_store
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand"))
    property_ = store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Haus A", property_type="residential",
    ))
    unit = store.create_unit(UnitCreate(property_id=property_.id, label="WE 1", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    other = store.create_tenant(TenantCreate(full_name="Nachmieter"))
    historical = store.create_contract(ContractCreate(
        contract_number="ALT", tenant_id=tenant.id, property_id=property_.id, unit_id=unit.id,
        status="terminated", start_date=date(2020, 1, 1), end_date=date(2022, 12, 31),
    ))
    draft = store.create_contract(ContractCreate(
        contract_number="ENTWURF", tenant_id=tenant.id, property_id=property_.id, unit_id=unit.id,
        status="draft", start_date=date(2030, 1, 1),
    ))
    unrelated = store.create_contract(ContractCreate(
        contract_number="NEU", tenant_id=other.id, property_id=property_.id, unit_id=unit.id,
        start_date=date(2023, 1, 1),
    ))
    return {"tenant": tenant, "other": other, "property": property_, "unit": unit,
            "historical": historical, "draft": draft, "unrelated": unrelated}


def _set_created_at(store, document, created_at):
    if isinstance(store, InMemoryStore):
        store.documents[document.id] = document.model_copy(update={"created_at": created_at})
    else:
        store.db.get(DocumentORM, document.id).created_at = created_at
        store.db.commit()


def test_documents_paginate_beyond_100_with_stable_newest_order(workspace_store, parties):
    store = workspace_store
    tenant = parties["tenant"]
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    documents = []
    for index in range(137):
        document = store.create_document(DocumentCreate(
            title=f"Dokument {index:03}", file_url=f"/uploads/{index}.pdf",
            tenant_id=tenant.id if index % 2 == 0 else None,
            contract_id=parties["historical"].id if index % 2 else None,
            document_type="Selten" if index == 0 else "Mietvertrag",
        ))
        # Several records share a timestamp: the id is the stable tie-breaker.
        created_at = timestamp + timedelta(days=index // 4)
        _set_created_at(store, document, created_at)
        documents.append((created_at, document.id))
    # Direct and contract membership together must count only once.
    both = store.create_document(DocumentCreate(
        title="Beides", file_url="/uploads/both.pdf", tenant_id=tenant.id,
        contract_id=parties["draft"].id, document_type="Antrag",
    ))
    _set_created_at(store, both, timestamp + timedelta(days=100))
    documents.append((timestamp + timedelta(days=100), both.id))
    for payload in (
        {"contract_id": parties["unrelated"].id},
        {"tenant_id": parties["other"].id},
        {"unit_id": parties["unit"].id},
        {"property_id": parties["property"].id},
        {},
    ):
        store.create_document(DocumentCreate(title="Nicht Mia", file_url="/uploads/other.pdf", **payload))

    overview = TenantOverview.model_validate(store.get_tenant_overview(tenant.id))
    assert overview.document_count == 138
    assert overview.document_types == ["Antrag", "Mietvertrag", "Selten"]
    assert {contract.id for contract in overview.contracts} == {parties["historical"].id, parties["draft"].id}
    assert all(contract.property_name == "Haus A" and contract.unit_label == "WE 1"
               for contract in overview.contracts)
    loaded: list = []
    for skip in range(0, 150, 25):
        page = TenantDocumentPage.model_validate(store.list_tenant_documents(tenant.id, skip=skip, limit=25))
        assert (page.total, page.skip, page.limit) == (138, skip, 25)
        assert page.has_more == (skip + 25 < 138)
        loaded.extend(document.id for document in page.items)
    assert loaded == [document_id for _created_at, document_id in sorted(documents, reverse=True)]
    assert len(set(loaded)) == 138
    assert store.list_tenant_documents(tenant.id, skip=200)["items"] == []
    assert store.list_tenant_documents(tenant.id, skip=200)["has_more"] is False


def test_search_type_and_contract_filters_run_over_complete_membership(workspace_store, parties):
    store = workspace_store
    tenant = parties["tenant"]
    for index in range(105):
        store.create_document(DocumentCreate(title=f"Füller {index}", file_url="/f.pdf", tenant_id=tenant.id))
    title = store.create_document(DocumentCreate(
        title="50%_Antrag", file_url="/title.pdf", tenant_id=tenant.id, document_type="Antrag",
    ))
    tagged = store.create_document(DocumentCreate(
        title="Info", file_url="/tag.pdf", contract_id=parties["historical"].id,
        tags="KAUTION, wichtig", description="Briefwechsel", document_type="Brief",
    ))
    store.create_document(DocumentCreate(
        title="50xxAntrag", file_url="/false.pdf", tenant_id=tenant.id,
    ))
    assert store.list_tenant_documents(tenant.id, q=" 50%_aNTRAG ")["items"] == [title]
    assert store.list_tenant_documents(tenant.id, q="kaution")["items"] == [tagged]
    assert store.list_tenant_documents(tenant.id, q="briefwechsel")["items"] == [tagged]
    assert store.list_tenant_documents(tenant.id, q="brief", document_type="Antrag")["total"] == 0
    assert store.list_tenant_documents(tenant.id, document_type="Antrag")["items"] == [title]
    assert store.list_tenant_documents(tenant.id, contract_id=parties["historical"].id)["items"] == [tagged]
    assert store.list_tenant_documents(tenant.id, contract_id=parties["draft"].id)["total"] == 0
    for contract_id in (parties["unrelated"].id, "missing"):
        with pytest.raises(ValidationError, match="Vertrag gehört nicht zum Mieter"):
            store.list_tenant_documents(tenant.id, contract_id=contract_id)


def test_german_search_is_consistent_across_memory_and_sqlite(workspace_store, parties):
    tenant_id = parties["tenant"].id
    document = workspace_store.create_document(DocumentCreate(
        title="ÜBERGABE", file_url="/unicode.pdf", tenant_id=tenant_id,
        description="Straße 2", tags="ÄNDERUNG, ÖFFENTLICH", document_type="BESTÄTIGUNG",
    ))
    for search in ("übergabe", "Übergabe", "straße", "STRASSE", "änderung", "öffentlich", "bestätigung"):
        assert workspace_store.list_tenant_documents(tenant_id, q=search)["items"] == [document]


def test_explicit_document_tenant_survives_contract_reassignment(workspace_store, parties):
    store = workspace_store
    contract = parties["historical"]
    direct = store.create_document(DocumentCreate(
        title="Mias Antrag", file_url="/mia.pdf", tenant_id=parties["tenant"].id, contract_id=contract.id,
    ))
    inherited = store.create_document(DocumentCreate(
        title="Vertrag", file_url="/contract.pdf", contract_id=contract.id,
    ))
    store.update_contract(contract.id, ContractCreate(**{
        **contract.model_dump(include=set(ContractCreate.model_fields)), "tenant_id": parties["other"].id,
    }))
    assert store.list_tenant_documents(parties["tenant"].id)["items"] == [direct]
    assert store.list_tenant_documents(parties["other"].id)["items"] == [inherited]
    assert store.get_tenant_overview(parties["tenant"].id)["document_count"] == 1
    assert store.get_tenant_overview(parties["other"].id)["document_count"] == 1


@pytest.mark.parametrize("field", ["tenant_id", "contract_id", "property_id", "unit_id"])
def test_invalid_document_foreign_keys_rejected_before_mutation(workspace_store, parties, field):
    store = workspace_store
    document = store.create_document(DocumentCreate(title="Alt", file_url="/a.pdf", tenant_id=parties["tenant"].id))
    invalid = DocumentCreate.model_validate({"title": "Neu", "file_url": "/b.pdf", field: "missing"})
    with pytest.raises(ValidationError):
        store.create_document(invalid)
    with pytest.raises(ValidationError):
        store.update_document(document.id, invalid)
    with pytest.raises(ValidationError):
        store._patch_entity("document", document.id, DocumentPatch.model_validate({field: "missing"}))
    assert store.get_document(document.id).title == "Alt"
    assert len(store.list_documents()) == 1


def test_document_contract_tenant_and_context_must_match(workspace_store, parties):
    store = workspace_store
    document = store.create_document(DocumentCreate(
        title="Alt", file_url="/a.pdf", tenant_id=parties["tenant"].id,
        contract_id=parties["historical"].id,
    ))
    invalid = DocumentCreate(
        title="Falsch", file_url="/b.pdf", tenant_id=parties["tenant"].id,
        contract_id=parties["unrelated"].id,
    )
    with pytest.raises(ValidationError, match="Vertrag gehört nicht zum Mieter"):
        store.create_document(invalid)
    with pytest.raises(ValidationError, match="Vertrag gehört nicht zum Mieter"):
        store.update_document(document.id, invalid)
    for patch in (DocumentPatch(contract_id=parties["unrelated"].id),
                  DocumentPatch(tenant_id=parties["other"].id)):
        with pytest.raises(ValidationError, match="Vertrag gehört nicht zum Mieter"):
            store._patch_entity("document", document.id, patch)
    other_property = store.create_property(PropertyCreate(
        portfolio_id=parties["property"].portfolio_id, name="Haus B", property_type="residential",
    ))
    other_unit = store.create_unit(UnitCreate(property_id=other_property.id, label="B1", unit_type="apartment"))
    for patch in (DocumentPatch(property_id=other_property.id), DocumentPatch(unit_id=other_unit.id)):
        with pytest.raises(ValidationError):
            store._patch_entity("document", document.id, patch)
    # Explicit null clears an association, while an omitted field preserves it.
    cleared = store._patch_entity("document", document.id, DocumentPatch(contract_id=None, title="Direkt"))
    assert cleared.contract_id is None and cleared.tenant_id == parties["tenant"].id


def test_tenant_without_contract_and_legacy_documents_remain_supported(workspace_store):
    store = workspace_store
    tenant = store.create_tenant(TenantCreate(full_name="Vor Vertrag"))
    legacy = store.create_document(DocumentCreate(title="Allgemein", file_url="/legacy.pdf"))
    direct = store.create_document(DocumentCreate(title="Antrag", file_url="/direct.pdf", tenant_id=tenant.id))
    assert legacy.tenant_id is None
    overview = store.get_tenant_overview(tenant.id)
    assert overview["contracts"] == [] and overview["document_count"] == 1
    assert store.list_tenant_documents(tenant.id)["items"] == [direct]
    for method in (store.get_tenant_overview, store.list_tenant_documents):
        with pytest.raises(NotFoundError):
            method("missing")


def test_overview_rent_uses_historical_contract_periods(workspace_store, parties):
    store = workspace_store
    contract = parties["historical"]
    for valid_from, rent in ((date(2020, 1, 1), 500), (date(2022, 1, 1), 550), (date(2025, 1, 1), 900)):
        store.create_contract_rent_period(ContractRentPeriodCreate(
            contract_id=contract.id, valid_from=valid_from, cold_rent=rent,
            service_charge_advance=100, heating_advance=80,
        ))
    contracts = store.get_tenant_overview(parties["tenant"].id)["contracts"]
    historical = next(row for row in contracts if row["id"] == contract.id)
    draft = next(row for row in contracts if row["id"] == parties["draft"].id)
    assert historical["current_rent"] == {
        "cold_rent": 550, "service_charge": 100, "heating_charge": 80, "valid_from": date(2022, 1, 1),
    }
    assert draft["current_rent"] is None


def test_sql_workspace_queries_are_bounded(workspace_store, parties, monkeypatch):
    if isinstance(workspace_store, InMemoryStore):
        pytest.skip("SQL query budget")
    store = workspace_store
    for index in range(110):
        store.create_contract(ContractCreate(
            contract_number=f"D-{index}", tenant_id=parties["tenant"].id,
            property_id=parties["property"].id, unit_id=parties["unit"].id,
            status="draft", start_date=date(2030, 1, 1),
        ))
    # Global stock loaders would silently reintroduce the default-page bug.
    def forbid_stock_load(*_args, **_kwargs):
        raise AssertionError("workspace must not load unrelated entity stock")
    monkeypatch.setattr(store, "list_contracts", forbid_stock_load)
    monkeypatch.setattr(store, "list_documents", forbid_stock_load)
    queries = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    event.listen(store.db.get_bind(), "before_cursor_execute", capture)
    try:
        overview = store.get_tenant_overview(parties["tenant"].id)
        assert len(overview["contracts"]) == 112
        assert len(queries) <= 5  # tenant + joined contracts + periods + distinct types + count
        queries.clear()
        store.list_tenant_documents(parties["tenant"].id, skip=25, limit=25)
        assert len(queries) <= 3  # tenant + count + page
        page_query = queries[-1].upper()
        assert "LIMIT" in page_query and "OFFSET" in page_query and "ORDER BY" in page_query
    finally:
        event.remove(store.db.get_bind(), "before_cursor_execute", capture)


@pytest.fixture
def workspace_client(workspace_store, monkeypatch, tmp_path):
    from backend.auth import require_auth
    from backend.routers import documents, tenants
    from backend.services.file_storage import LocalStorage

    monkeypatch.setattr(documents, "store", workspace_store)
    monkeypatch.setattr(tenants, "store", workspace_store)
    monkeypatch.setattr(documents, "get_file_storage", lambda: LocalStorage(tmp_path))
    app = FastAPI()
    app.include_router(tenants.router, dependencies=[Depends(require_auth)])
    app.include_router(documents.router, dependencies=[Depends(require_auth)])
    # Auth remains a router-level dependency; override only within this isolated fixture.
    app.dependency_overrides[require_auth] = lambda: {"id": "fixture"}
    with TestClient(app) as client:
        yield client


def test_http_workspace_shape_defaults_and_validation(workspace_client, parties):
    client = workspace_client
    tenant_id = parties["tenant"].id
    created = client.post("/documents", json={"title": "Direkt", "file_url": "/a.pdf", "tenant_id": tenant_id})
    assert created.status_code == 201
    assert created.json()["tenant_id"] == tenant_id
    page = client.get(f"/tenants/{tenant_id}/documents").json()
    assert set(page) == {"items", "total", "skip", "limit", "has_more"}
    assert (page["total"], page["skip"], page["limit"], page["has_more"]) == (1, 0, 25, False)
    overview = client.get(f"/tenants/{tenant_id}/overview")
    assert overview.status_code == 200
    assert set(overview.json()) == {"tenant", "contracts", "document_count", "document_types"}
    assert client.get(f"/tenants/{tenant_id}/documents?skip=-1").status_code == 422
    assert client.get(f"/tenants/{tenant_id}/documents?limit=0").status_code == 422
    assert client.get(f"/tenants/{tenant_id}/documents?contract_id={parties['unrelated'].id}").status_code == 400
    assert client.get("/tenants/missing/overview").status_code == 404
    assert client.get("/tenants/missing/documents").status_code == 404
    assert client.patch(f"/documents/{created.json()['id']}", json={
        "contract_id": parties["unrelated"].id,
    }).status_code == 400


def test_import_document_links_tenant_and_rejects_mismatch_before_file_write(workspace_client, parties, tmp_path):
    client = workspace_client
    response = client.post("/documents/import", data={
        "title": "Antrag", "tenant_id": parties["tenant"].id,
    }, files={"file": ("antrag.txt", b"Application", "text/plain")})
    assert response.status_code == 201
    assert response.json()["tenant_id"] == parties["tenant"].id
    assert response.json()["contract_id"] is None
    before = list(tmp_path.rglob("*"))
    response = client.post("/documents/import", data={
        "title": "Falsch", "tenant_id": parties["tenant"].id, "contract_id": parties["unrelated"].id,
    }, files={"file": ("falsch.txt", b"No", "text/plain")})
    assert response.status_code == 400
    assert list(tmp_path.rglob("*")) == before


def test_direct_tenant_documents_are_kept_by_existing_deletion_guard(workspace_client):
    client = workspace_client
    tenant = client.post("/tenants", json={"full_name": "Vor Vertrag"}).json()
    document = client.post("/documents", json={
        "title": "Antrag", "file_url": "/application.pdf", "tenant_id": tenant["id"],
    }).json()
    assert client.delete(f"/tenants/{tenant['id']}").status_code == 409
    assert client.get(f"/documents/{document['id']}").status_code == 200


def test_workspace_endpoints_keep_auth_dependency(workspace_client, parties):
    workspace_client.app.dependency_overrides.clear()
    for endpoint in ("overview", "documents"):
        assert workspace_client.get(f"/tenants/{parties['tenant'].id}/{endpoint}").status_code == 401
