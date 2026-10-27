"""Global search: DB-side match, keyset pages, exact totals, CSV export, portfolio scope.

Store-level tests run on the memory store and SQLite; the HTTP scope tests use the
configured store (TEST_STORE_BACKEND).
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

import pytest
from archive_helpers import lease_with_document
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth, models
from backend.app import app
from backend.db.orm_models import Base, TenantORM
from backend.dependencies import store as app_store
from backend.models import AccountCreate, BookingCreate, TenantCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import search
from backend.services import global_search as gs
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sql"])
def search_store(request, monkeypatch):
    store: Any
    if request.param == "memory":
        store = InMemoryStore()
        monkeypatch.setattr(search, "store", store)
        yield store
        return
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        monkeypatch.setattr(search, "store", store)
        yield store
    engine.dispose()


def _bulk_tenants(store, count, name="Bulk Mieter"):
    names = [f"{name} {index:05d}" for index in range(count)]
    if hasattr(store, "db"):
        store.db.add_all(TenantORM(id=str(uuid.uuid4()), full_name=value) for value in names)
        store.db.commit()
    else:
        for value in names:
            store.create_tenant(TenantCreate(full_name=value))


def _all_pages(q, entity_type, limit):
    ids: list[str] = []
    cursor, pages = None, 0
    while True:
        body = search.global_search(q=q, type=entity_type, limit=limit, cursor=cursor, semantic=False)
        pages += 1
        ids.extend(hit["id"] for hit in body["results"])
        assert body["has_more"] == (body["next_cursor"] is not None)
        if not body["has_more"]:
            return ids, body["total"], pages
        cursor = body["next_cursor"]


def test_every_search_field_exists_on_table_and_model():
    for spec in gs.SEARCH_TYPES:
        table = Base.metadata.tables[spec.table]
        name = {"maintenance": "MaintenanceCase"}.get(spec.entity_type, spec.entity_type.title())
        model = getattr(models, name)
        for field in spec.fields:
            assert field in table.c, (spec.table, field)
            assert field in model.model_fields, (model.__name__, field)
        assert callable(getattr(InMemoryStore, spec.list_method))
        assert callable(getattr(SQLAlchemyStore, spec.list_method))


@pytest.mark.parametrize("count,limit", [(100, 100), (101, 100), (1000, 100), (1001, 100)])
def test_boundaries_page_completely(search_store, count, limit):
    _bulk_tenants(search_store, count)
    _bulk_tenants(search_store, 3, name="Andere Person")
    ids, total, pages = _all_pages("bulk mieter", "tenant", limit)
    assert total == count
    assert len(ids) == count == len(set(ids))
    assert ids == sorted(ids)
    assert pages == -(-count // limit)

    overview = search.global_search(q="Bulk Mieter", semantic=False)
    group = next(g for g in overview["groups"] if g["entity_type"] == "tenant")
    assert group["total"] == count and group["has_more"] is True
    assert len([h for h in overview["results"] if h["entity_type"] == "tenant"]) == gs.DEFAULT_LIMIT


def test_more_than_ten_thousand_rows(search_store):
    _bulk_tenants(search_store, 10_050)
    ids, total, pages = _all_pages("BULK", "tenant", 100)
    assert total == 10_050 and len(set(ids)) == 10_050 and pages == 101
    exported = list(gs.iter_all(search_store, gs.get_type("tenant"), "bulk"))
    assert [hit["id"] for hit in exported] == ids


def test_exact_page_has_no_dangling_cursor(search_store):
    _bulk_tenants(search_store, 100)
    body = search.global_search(q="Bulk", type="tenant", limit=100, semantic=False)
    assert body["count"] == 100 and body["has_more"] is False and body["next_cursor"] is None


def test_like_wildcards_are_literal(search_store):
    for value in ("100% Miete", "1000 Miete", "a_b Kontor", "axb Kontor", "back\\slash"):
        search_store.create_tenant(TenantCreate(full_name=value))
    names = lambda q: sorted(h["display"] for h in search.global_search(q=q, type="tenant", semantic=False)["results"])  # noqa: E731
    assert names("100%") == ["100% Miete"]
    assert names("a_b") == ["a_b Kontor"]
    assert names("%") == ["100% Miete"]
    assert names("_") == ["a_b Kontor"]
    assert names("k\\s") == ["back\\slash"]


def test_case_folding_matches_memory_including_umlauts(search_store):
    search_store.create_tenant(TenantCreate(full_name="ÖZTÜRK Ärger"))
    assert search.global_search(q="öztürk ärger", type="tenant", semantic=False)["total"] == 1


def test_bad_type_and_cursor_are_rejected(search_store):
    _bulk_tenants(search_store, 3)
    with pytest.raises(HTTPException) as unknown:
        search.global_search(q="x", type="nope", semantic=False)
    assert unknown.value.status_code == 400
    with pytest.raises(HTTPException):
        search.global_search(q="x", type="tenant", cursor="!!garbage", semantic=False)
    foreign = gs.encode_cursor("property", "0")
    with pytest.raises(HTTPException):
        search.global_search(q="x", type="tenant", cursor=foreign, semantic=False)
    with pytest.raises(HTTPException):
        search.global_search(q="x", cursor=foreign, semantic=False)


# ── HTTP: portfolio scope and export ──

@pytest.fixture
def scoped():
    auth.clear_users()
    app_store.clear_all()
    sides = {}
    for side, number in (("north", "N-1"), ("south", "S-1")):
        lease = lease_with_document(app_store, number=number, file_url=f"/uploads/documents/{side}.pdf")
        account = app_store.create_account(AccountCreate(portfolio_id=lease["portfolio"].id, name=f"Konto {side}",
                                                         account_type="bank"))
        lease["booking"] = app_store.create_booking(BookingCreate(
            account_id=account.id, property_id=lease["property"].id, unit_id=lease["unit"].id,
            booking_date=date(2026, 1, 3), amount=850.0, payment_text=f"Miete {side}"))
        sides[side] = lease
    staff = auth.register_user("staff", "staff@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[sides["north"]["portfolio"].id])
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer",
                               portfolio_access="all", portfolio_ids=[])
    yield sides, {"Authorization": f"Bearer {auth.create_access_token(staff.id)}"}, \
        {"Authorization": f"Bearer {auth.create_access_token(owner.id)}"}
    auth.clear_users()
    app_store.clear_all()


def test_restricted_account_sees_no_foreign_hits_or_counts(scoped):
    sides, staff, owner = scoped
    client = TestClient(app)
    north, south = sides["north"], sides["south"]

    body = client.get("/api/v1/search", params={"q": "Bautzner", "semantic": "false"}, headers=staff).json()
    assert {h["id"] for h in body["results"]} == {north["property"].id}
    assert {g["entity_type"]: g["total"] for g in body["groups"]} == {"property": 1}

    for q, entity_type, key in (("Miete", "booking", "booking"), ("WE 3", "unit", "unit"),
                                ("Bautzner", "property", "property")):
        page = client.get("/api/v1/search", params={"q": q, "type": entity_type}, headers=staff).json()
        assert [h["id"] for h in page["results"]] == [north[key].id] and page["total"] == 1, entity_type
        everyone = client.get("/api/v1/search", params={"q": q, "type": entity_type}, headers=owner).json()
        assert everyone["total"] == 2 and south[key].id in {h["id"] for h in everyone["results"]}

    export = client.get("/api/v1/search/export", params={"q": "Miete", "type": "booking"}, headers=staff)
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
    assert [row["id"] for row in rows] == [north["booking"].id]


def test_http_validation(scoped):
    _, staff, _ = scoped
    client = TestClient(app)
    assert client.get("/api/v1/search", params={"q": "x", "limit": 101}, headers=staff).status_code == 422
    assert client.get("/api/v1/search", params={"q": "x", "type": "nope"}, headers=staff).status_code == 400
    assert client.get("/api/v1/search/export", params={"q": "x", "type": "nope"}, headers=staff).status_code == 400


def test_csv_cells_cannot_start_formulas():
    assert search._csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert search._csv_cell("Miete") == "Miete"
