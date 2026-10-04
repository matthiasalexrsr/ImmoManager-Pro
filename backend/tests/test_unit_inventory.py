"""Full search/aggregates/exports, stable pages and authorization at scale."""

import csv
import io
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.db.orm_models import UnitORM
from backend.models import Unit
from backend.routers import unit_inventory as router
from backend.services import unit_inventory as service
from backend.services.portfolio_scope import scope_context
from backend.services.unit_inventory import UnitInventoryQuery as Query
from backend.services.unit_inventory_export import csv_chunks
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import insert, install_actor, seed
from backend.tests.test_portfolio_access_http import access_http as access_http


def add_units(store, rows):
    if hasattr(store, "db"):
        store.db.execute(UnitORM.__table__.insert(), [row.model_dump() for row in rows])
        store.db.commit()
    else:
        store.__dict__["units"].update({row.id: row for row in rows})


def make_units(store, count):
    contract, portfolio = seed(store)
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for start in range(0, count, 500):
        add_units(store, [Unit(id=f"inventory-{n:06d}", property_id=contract.property_id, label=f"Einheit {n:06d}",
            unit_type="apartment", status="vacant", cold_rent=0 if n == 0 else 100, created_at=stamp, updated_at=stamp)
            for n in range(start, min(count, start + 500))])
    return contract, portfolio


def test_late_positions_full_aggregate_and_export_without_global_lists(active, monkeypatch):
    contract, _ = make_units(active, 10002)
    def forbidden(*args, **kwargs):
        raise AssertionError("Global list reader forbidden")
    for method in ("list_units", "list_contracts", "list_tenants", "list_properties", "_list_paginated"):
        monkeypatch.setattr(active, method, forbidden)
    for number in (100, 1000, 10000):
        page = service.unit_inventory_page(active, Query(search=f"Einheit {number:06d}", page_size=1))
        assert [row.id for row in page.items] == [f"inventory-{number:06d}"]
    summary = service.unit_inventory_summary(active, Query(search="Einheit", page_size=1))
    assert summary["total"] == summary["rent_count"] == 10002
    assert float(summary["average_cold_rent"]) == pytest.approx(100 * 10001 / 10002)
    result = b"".join(csv_chunks(active, Query(search="Einheit"), chunk_size=1000)).decode("utf-8-sig")
    records = list(csv.DictReader(io.StringIO(result), delimiter=";"))
    assert len(records) == 10002
    assert len({row["id"] for row in records}) == 10002
    assert records[10000]["label"] == "Einheit 010000"
    assert contract.unit_id not in {row["id"] for row in records}


@pytest.mark.parametrize("sort,direction", [("cold_rent", "asc"), ("cold_rent", "desc"), ("label", "asc"), ("label", "desc")])
def test_duplicate_and_null_sort_values_visit_every_unit(active, sort, direction):
    contract, _ = make_units(active, 5)
    base = active.get_unit(contract.unit_id)
    add_units(active, [base.model_copy(update={"id": "null-rent", "label": "Einheit 000000", "cold_rent": None})])
    expected = {base.id, "null-rent", *(f"inventory-{n:06d}" for n in range(5))}
    seen, cursor, first_cursor = [], None, None
    while True:
        page = service.unit_inventory_page(active, Query(property_id=contract.property_id, page_size=2, sort_by=sort, sort_order=direction, cursor=cursor))
        assert len(page.items) <= 2
        seen.extend(row.id for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        first_cursor = first_cursor or cursor
    assert set(seen) == expected and len(seen) == len(expected)
    if sort == "cold_rent":
        assert seen[-1] == "null-rent"
    with pytest.raises(HTTPException) as error:
        service.unit_inventory_page(active, Query(property_id=contract.property_id, page_size=2, sort_by=sort, sort_order=direction, cursor=first_cursor, search="changed"))
    assert error.value.status_code == 422


def test_active_parties_filters_and_null_rent_denominator(active):
    template, _ = seed(active, "Müllerstraße")
    insert(active, [template.model_copy(update={"id": f"active-{n}", "contract_number": f"Active {n}", "status": "active"}) for n in range(2)])
    page = service.unit_inventory_page(active, Query(search="MÜLLERSTRASSE", view="multiple_active"))
    assert len(page.items) == 1
    assert page.items[0].active_contract_count == 2 and page.items[0].tenant_name is None
    assert not service.unit_inventory_page(active, Query(view="no_contract")).items
    assert service.unit_inventory_summary(active, Query(rent_min=200))["average_cold_rent"] is None
    with pytest.raises(ValueError):
        Query(area_min=10, area_max=1)


def test_scope_bound_cursor_aggregate_and_export(active, monkeypatch):
    own, portfolio = make_units(active, 3)
    hidden, _ = seed(active, "Hidden")
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        page = service.unit_inventory_page(active, Query(page_size=1))
        assert service.unit_inventory_summary(active, Query())["total"] == 4
        exported = b"".join(csv_chunks(active, Query(), chunk_size=2)).decode()
        assert hidden.unit_id not in exported and own.unit_id in exported
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException) as error:
            service.unit_inventory_page(active, Query(page_size=1, cursor=page.next_cursor))
        assert error.value.status_code == 403


def test_sql_page_bounded_and_never_autoflush(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL identity map only")
    own, _ = make_units(active, 4)
    unit = active.db.get(UnitORM, own.unit_id)
    unit.label = "Unflushed private edit"
    statements = []
    def capture(_conn, _cursor, sql, parameters, _context, _many):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = service.unit_inventory_page(active, Query(page_size=2))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and "LIMIT" in statements[0].upper()
    assert all(row.label != unit.label for row in page.items)
    assert unit in active.db.dirty
    active.db.rollback()


def test_export_scope_revocation_stops_next_chunk(active, monkeypatch):
    _, portfolio = make_units(active, 3)
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        chunks = csv_chunks(active, Query(), chunk_size=1)
        assert next(chunks).startswith(b"\xef\xbb\xbf")
        user["is_active"] = False
        with pytest.raises(HTTPException):
            next(chunks)
        chunks.close()


def test_csv_formula_text_is_escaped(active):
    own, _ = seed(active)
    base = active.get_unit(own.unit_id)
    add_units(active, [base.model_copy(update={"id": "formula", "label": "  =1+1", "cold_rent": -2})])
    text = b"".join(csv_chunks(active, Query(search="=1+1"))).decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert row["label"].startswith("'") and row["cold_rent"] in {"-2", "-2.0"}


def test_http_additive_routes_private_and_legacy_compatible(access_http):
    client, _, owner, member, *_ = access_http
    for suffix in ("page", "summary", "export"):
        endpoint = "/api/v1/units/inventory/" + suffix
        assert client.get(endpoint).status_code == 401
        response = client.get(endpoint, headers=member)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
    assert isinstance(client.get("/api/v1/units", headers=owner).json(), list)
    for query in ({"page_size": 0}, {"unknown": 1}, {"sort_by": "not_a_column"}, {"cursor": "bad"}):
        assert client.get("/api/v1/units/inventory/page", headers=member, params=query).status_code == 422


@pytest.mark.parametrize("operation", ["page", "summary"])
def test_http_late_revocation_publishes_no_private_content(access_http, monkeypatch, operation):
    client, _, _, member, actor, *_ = access_http
    name = "unit_inventory_" + operation
    original = getattr(router, name)
    def revoke(*args):
        result = original(*args)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result
    monkeypatch.setattr(router, name, revoke)
    assert client.get("/api/v1/units/inventory/" + operation, headers=member).status_code == 403
