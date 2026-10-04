"""Complete operational case sources; actual costs are not derived here."""

import csv
import io
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.db.orm_models import MaintenanceCaseORM
from backend.models import MaintenanceCase
from backend.routers import maintenance_inventory as router
from backend.services import maintenance_inventory as service
from backend.services.maintenance_inventory import MaintenanceInventoryQuery as Query
from backend.services.maintenance_inventory_export import csv_chunks
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor, seed
from backend.tests.test_maintenance_date_filter import add_cases, cases
from backend.tests.test_portfolio_access_http import access_http as access_http


def test_full_operational_source_search_summary_export(active, monkeypatch):
    contract, _ = cases(active)
    def forbidden(*args, **kwargs):
        raise AssertionError("No global lists")
    for method in ("list_maintenance_cases", "list_properties", "list_units", "_list_paginated"):
        monkeypatch.setattr(active, method, forbidden)
    for position in (100, 1000, 10000):
        page = service.maintenance_inventory_page(active, Query(search=f"Fall {position:06d}", page_size=1))
        assert [row.id for row in page.items] == [f"case-{position:06d}"]
        assert page.items[0].property_name == "visible building"
        assert "description" not in page.items[0].model_dump()
    summary = service.maintenance_inventory_summary(active, Query(property_id=contract.property_id, as_of=date(2026, 1, 1)))
    assert summary == dict(total=10025, open=10025, in_progress=0, overdue=10024, no_appointment=10025,
                          no_assignee=10025, as_of=date(2026, 1, 1))
    rows = list(csv.DictReader(io.StringIO(b"".join(csv_chunks(active, Query(), chunk_size=1000)).decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == len({row["id"] for row in rows}) == 10025


@pytest.mark.parametrize("sort,direction", [("due_date", "asc"), ("appointment_at", "desc"), ("estimated_cost", "asc"), ("title", "desc")])
def test_cursor_null_ties_dates_and_zero_cost_are_stable(active, sort, direction):
    contract, _ = seed(active)
    add_cases(active, [MaintenanceCase(id=f"case-{n}", property_id=contract.property_id, title="Repeated title",
        due_date=date(2026, 1, 1) if n % 2 else None, appointment_at=datetime(2026, 1, 1, 15, 30) if n % 2 else None,
        estimated_cost=0 if n % 2 else None) for n in range(7)])
    seen, cursor, first = [], None, None
    while True:
        page = service.maintenance_inventory_page(active, Query(sort_by=sort, sort_order=direction, page_size=2, cursor=cursor))
        seen.extend(row.id for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        first = first or cursor
    assert len(seen) == len(set(seen)) == 7
    if sort != "title":
        assert set(seen[-4:]) == {"case-0", "case-2", "case-4", "case-6"}
    with pytest.raises(HTTPException) as error:
        service.maintenance_inventory_page(active, Query(sort_by=sort, sort_order=direction, page_size=2, cursor=first, status="open"))
    assert error.value.status_code == 422


def test_operational_filters_count_missing_values_and_explicit_day(active):
    contract, _ = seed(active)
    add_cases(active, [MaintenanceCase(id=f"case-{n}", property_id=contract.property_id, title="Müllerstraße",
        due_date=date(2026, 1, 1), status="completed" if n == 1 else "open", assignee=" " if n == 0 else "Assigned",
        priority="urgent" if n == 0 else "medium", appointment_at=datetime(2026, 1, 1, 23, 59, 59) if n == 1 else None) for n in range(3)])
    assert service.maintenance_inventory_summary(active, Query(view="overdue", as_of=date(2026, 1, 1)))["total"] == 0
    assert service.maintenance_inventory_summary(active, Query(view="overdue", as_of=date(2026, 1, 2)))["total"] == 2
    assert service.maintenance_inventory_summary(active, Query(view="no_assignee"))["total"] == 1
    assert service.maintenance_inventory_summary(active, Query(view="urgent"))["total"] == 1
    assert service.maintenance_inventory_summary(active, Query(search="MÜLLERSTRASSE"))["total"] == 3
    assert service.maintenance_inventory_summary(active, Query(appointment_from="2026-01-01", appointment_to="2026-01-01"))["total"] == 1
    with pytest.raises(ValueError):
        Query(appointment_from="2026-01-02", appointment_to="2026-01-01")


def test_scope_summary_cursor_and_running_export(active, monkeypatch):
    contract, portfolio = cases(active, 4)
    hidden, _ = seed(active, "Hidden")
    add_cases(active, [MaintenanceCase(id="hidden", property_id=hidden.property_id, title="Secret")])
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        assert service.maintenance_inventory_summary(active, Query())["total"] == 4
        page = service.maintenance_inventory_page(active, Query(page_size=1))
        chunks = csv_chunks(active, Query(property_id=contract.property_id), chunk_size=1)
        try:
            assert b"Secret" not in next(chunks)
            user["portfolio_ids"] = []
            with pytest.raises(HTTPException):
                next(chunks)
            with pytest.raises(HTTPException):
                service.maintenance_inventory_page(active, Query(page_size=1, cursor=page.next_cursor))
        finally:
            chunks.close()


def test_sql_bounded_metadata_read_without_autoflush(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL-only identity map assertion")
    cases(active, 3)
    pending = active.db.get(MaintenanceCaseORM, "case-000000")
    pending.title = "Unflushed"
    statements = []
    def capture(_conn, _cursor, sql, *_):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = service.maintenance_inventory_page(active, Query(page_size=1))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and "LIMIT" in statements[0].upper() and "description" not in statements[0]
    assert page.items[0].title != pending.title and pending in active.db.dirty
    active.db.rollback()


@pytest.mark.parametrize("operation", ["page", "summary"])
def test_http_private_and_final_publication_access(access_http, monkeypatch, operation):
    client, _, _, member, actor, *_ = access_http
    path = "/api/v1/maintenance/inventory/" + operation
    assert client.get(path).status_code == 401
    response = client.get(path, headers=member)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    original = getattr(router, "maintenance_inventory_" + operation)
    def revoke(*args):
        result = original(*args)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result
    monkeypatch.setattr(router, "maintenance_inventory_" + operation, revoke)
    assert client.get(path, headers=member).status_code == 403
