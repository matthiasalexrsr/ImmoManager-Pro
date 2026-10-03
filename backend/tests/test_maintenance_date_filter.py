"""No hidden inventory cap in the existing maintenance date-filter API."""

from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend.db.orm_models import MaintenanceCaseORM
from backend.models import MaintenanceCase
from backend.routers import maintenance as router
from backend.services.maintenance_list import filtered_maintenance
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor, seed
from backend.tests.test_portfolio_access_http import access_http as access_http


def add_cases(store, rows):
    if hasattr(store, "db"):
        store.db.execute(MaintenanceCaseORM.__table__.insert(), [row.model_dump() for row in rows])
        store.db.commit()
    else:
        store.__dict__["maintenance_cases"].update({row.id: row for row in rows})


def cases(store, count=10025):
    contract, portfolio = seed(store)
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for start in range(0, count, 500):
        add_cases(store, [MaintenanceCase(id=f"case-{n:06d}", property_id=contract.property_id,
            unit_id=contract.unit_id, title=f"Fall {n:06d}", due_date=date(2030 if n == count - 1 else 2020, 1, 1),
            created_at=stamp, updated_at=stamp) for n in range(start, min(count, start + 500))])
    return contract, portfolio


def read(store, **kwargs):
    return filtered_maintenance(store, **dict(skip=0, limit=2, filters={"property_id": None, "status": None},
        sort_by="title", descending=False, date_from=date(2020, 1, 1), date_to=None) | kwargs)


def test_finds_late_case_without_global_lists_or_ten_thousand_cutoff(active, monkeypatch):
    cases(active)
    def forbidden(*args, **kwargs):
        raise AssertionError("Global list must not be used")
    monkeypatch.setattr(active, "_list_paginated", forbidden)
    monkeypatch.setattr(active, "list_maintenance_cases", forbidden)
    monkeypatch.setattr(router, "store", active)
    result = router.list_maintenance_cases(skip=0, limit=2, property_id=None, status_filter="open",
        sort_by="title", sort_order="asc", date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
    assert [row.id for row in result] == ["case-010024"]


def test_offset_scope_and_deterministic_null_ties(active, monkeypatch):
    contract, portfolio = cases(active, 5)
    hidden, _ = seed(active, "hidden")
    add_cases(active, [MaintenanceCase(id="hidden-case", property_id=hidden.property_id, title="Hidden", due_date=date(2020, 1, 1))])
    assert [row.id for row in read(active, skip=1, limit=2, sort_by="estimated_cost", descending=True)] == ["case-000004", "case-000003"]
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        rows = read(active, limit=10)
        assert len(rows) == 5 and all(row.property_id == contract.property_id for row in rows)
        assert not read(active, filters={"property_id": contract.property_id, "status": "completed"})
        user["is_active"] = False
        with pytest.raises(HTTPException) as error:
            read(active)
        assert error.value.status_code == 403


def test_sql_limit_without_identity_map_or_autoflush(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL identity map only")
    cases(active, 3)
    case = active.db.get(MaintenanceCaseORM, "case-000000")
    case.title = "Pending unrelated edit"
    statements = []
    def capture(_conn, _cursor, sql, *_):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = read(active)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and "LIMIT" in statements[0].upper()
    assert len(result) == 2 and result[0].title != case.title
    assert case in active.db.dirty
    active.db.rollback()


def test_legacy_http_date_parameters_and_array_shape(access_http):
    client, _, owner, *_ = access_http
    response = client.get("/api/v1/maintenance", headers=owner,
                          params={"date_from": "2020-01-01", "date_to": "2030-12-31", "skip": 0, "limit": 2})
    assert response.status_code == 200 and isinstance(response.json(), list)
