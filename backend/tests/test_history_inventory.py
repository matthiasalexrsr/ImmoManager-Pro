"""Complete native field-change pages, filter scope and publication fences."""

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import Session

from backend import auth
from backend.db.orm_models import Base, ChangeHistoryORM
from backend.models import ChangeHistoryEntry, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import history as legacy
from backend.routers import history_inventory as router
from backend.services import history_inventory as service
from backend.services.history_inventory import HistoryInventoryQuery as Query
from backend.services.inventory_export import csv_chunks
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor
from backend.tests.test_portfolio_access_http import access_http as access_http


def add_rows(store, rows):
    if hasattr(store, "db"):
        store.db.execute(ChangeHistoryORM.__table__.insert(), [row.model_dump() for row in rows])
        store.db.commit()
    else:
        store.__dict__["change_history"].update({row.id: row for row in rows})


def row(number, **values):
    return ChangeHistoryEntry(**dict(id=f"history-{number:06d}", entity_type="property", entity_id="synthetic-property",
        field_name="name", old_value="vorher", new_value=f"Änderung {number:06d}", reason="Grund Müller",
        changed_by="synthetic-actor", changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)) | values)


def walk(store, query):
    seen, cursor = [], None
    while True:
        page = service.history_inventory_page(store, query.model_copy(update={"cursor": cursor}))
        seen.extend(item.id for item in page.items)
        if not page.has_more:
            assert page.next_cursor is None
            return seen
        assert page.items and page.next_cursor and page.next_cursor != cursor
        cursor = page.next_cursor
        assert len(seen) <= 11000, "Synthetic finite set must terminate"


def test_complete_large_source_filter_summary_legacy_and_export(active, monkeypatch):
    for start in range(0, 10002, 500):
        add_rows(active, [row(number) for number in range(start, min(10002, start + 500))])
    monkeypatch.setattr(active, "list_change_history", lambda: pytest.fail("No whole history materialization"))
    for number in (100, 1000, 10000):
        result = service.history_inventory_page(active, Query(search=f"Änderung {number:06d}", page_size=1))
        assert [item.id for item in result.items] == [f"history-{number:06d}"]
    assert service.history_inventory_summary(active, Query())["total"] == 10002
    seen = walk(active, Query(page_size=500))
    assert seen == [f"history-{number:06d}" for number in reversed(range(10002))]
    monkeypatch.setattr(legacy, "store", active)
    old = legacy.list_history(skip=10000, limit=2, entity_type="property", entity_id="synthetic-property")
    assert [item.id for item in old] == ["history-000001", "history-000000"]
    text = b"".join(csv_chunks(active, Query(), inventory=service, fields=service.FIELDS, chunk_size=500)).decode("utf-8-sig")
    exported = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert [item["id"] for item in exported] == seen
    assert exported[0]["reason"] == "Grund Müller"


def test_ties_unicode_search_exact_fields_interval_and_cursor_binding(active):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    add_rows(active, [row(0, id="history-é", changed_at=stamp), row(1, id="history-Z", changed_at=stamp),
        row(2, id="history-z", field_name="rent", changed_at=stamp + timedelta(microseconds=1)),
        row(3, id="history-ä", changed_by="other", new_value="literal 100%_value")])
    assert walk(active, Query(page_size=1)) == ["history-z", "history-é", "history-ä", "history-Z"]
    assert service.history_inventory_summary(active, Query(search="MÜLLER"))["total"] == 4
    assert service.history_inventory_summary(active, Query(search="100%_"))["total"] == 1
    assert service.history_inventory_summary(active, Query(field_name="rent", changed_by="synthetic-actor"))["total"] == 1
    assert service.history_inventory_summary(active, Query(changed_from=stamp, changed_before=stamp + timedelta(microseconds=1)))["total"] == 3
    query = Query(page_size=1)
    first = service.history_inventory_page(active, query).next_cursor
    for change in ({"search": "Müller"}, {"page_size": 2}, {"entity_id": "other"}):
        with pytest.raises(HTTPException) as error:
            service.history_inventory_page(active, Query(cursor=first, **change))
        assert error.value.status_code == 422


@pytest.mark.parametrize("active", ["sqlite"], indirect=True)
def test_sqlite_actual_seconds_microseconds_and_no_autoflush(active):
    with active.db.get_bind().begin() as connection:
        for identifier in ("history-A", "history-z", "history-é"):
            connection.exec_driver_sql("INSERT INTO change_history (id,entity_type,entity_id,field_name,changed_at) "
                "VALUES (?, 'property', 'synthetic-property', 'name', CURRENT_TIMESTAMP)", (identifier,))
    stamp = active.db.get(ChangeHistoryORM, "history-A").changed_at
    add_rows(active, [row(0, id="history-ä", changed_at=stamp),
                     row(1, id="history-micro", changed_at=stamp + timedelta(microseconds=1))])
    with active.db.get_bind().connect() as connection:
        before = dict(connection.exec_driver_sql("SELECT id,changed_at FROM change_history").all())
    assert len(before["history-A"]) == 19 and before["history-ä"].endswith(".000000")
    pending = active.db.get(ChangeHistoryORM, "history-A")
    pending.new_value = "unflushed-private-write"
    statements = []
    def capture(_connection, _cursor, sql, *_):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert walk(active, Query(page_size=1)) == ["history-micro", "history-é", "history-ä", "history-z", "history-A"]
        assert all("LIMIT" in sql.upper() and "INSERT" not in sql.upper() and "UPDATE" not in sql.upper() for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert pending in active.db.dirty
    with engine.connect() as connection:
        assert dict(connection.exec_driver_sql("SELECT id,changed_at FROM change_history").all()) == before
    active.db.rollback()


def test_sqlite_legacy_missing_dates_are_reached_after_dated_rows(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "legacy-history.sqlite").as_posix())
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "change_history"])
    table = ChangeHistoryORM.__table__.to_metadata(MetaData())
    table.c.changed_at.nullable = True
    table.create(engine)
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            add_rows(store, [row(0, id="history-dated")])
            db.execute(table.insert(), [row(number, id=identifier).model_dump() | {"changed_at": None}
                                       for number, identifier in enumerate(["history-é", "history-A", "history-z"])])
            db.commit()
            assert walk(store, Query(page_size=1)) == ["history-dated", "history-é", "history-z", "history-A"]
            assert service.history_inventory_summary(store, Query())["total"] == 4
    finally:
        engine.dispose()


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00+02:00", "9999-12-31T23:59:59-02:00"])
def test_utc_overflow_is_a_validation_error_without_capping(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="UTC-Umrechnung"):
        Query(changed_from=value)


def test_polymorphic_portfolio_scope_and_cursor_actor_binding(active, monkeypatch):
    portfolios = [active.create_portfolio(PortfolioCreate(name=f"Portfolio {number}")) for number in range(2)]
    properties = [active.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Property {number}", property_type="residential"))
                  for number, portfolio in enumerate(portfolios)]
    add_rows(active, [row(number, entity_id=properties[number % 2].id) for number in range(6)])
    scope, user = install_actor(monkeypatch, [portfolios[0].id])
    with scope_context(scope):
        assert service.history_inventory_summary(active, Query())["total"] == 3
        assert walk(active, Query(page_size=1)) == ["history-000004", "history-000002", "history-000000"]
        cursor = service.history_inventory_page(active, Query(page_size=1)).next_cursor
        chunks = csv_chunks(active, Query(), inventory=service, fields=service.FIELDS, chunk_size=1)
        try:
            assert b"history-000004" in next(chunks)
            user["portfolio_ids"] = []
            with pytest.raises(HTTPException) as error:
                next(chunks)
            assert error.value.status_code == 403
        finally:
            chunks.close()
    user["portfolio_ids"] = [portfolios[1].id]
    from dataclasses import replace
    changed = replace(scope, portfolio_ids=(portfolios[1].id,))
    with scope_context(changed), pytest.raises(HTTPException) as error:
        service.history_inventory_page(active, Query(page_size=1, cursor=cursor))
    assert error.value.status_code == 422


@pytest.mark.parametrize("access_http", ["sql"], indirect=True)
@pytest.mark.parametrize("operation", ["page", "summary"])
def test_real_sql_http_private_scope_and_publication_after_revoke(access_http, monkeypatch, operation):
    client, store, owner, member, actor, _, properties, *_ = access_http
    add_rows(store, [row(number, entity_id=properties[number].id) for number in range(2)])
    path = "/api/v1/history/inventory/" + operation
    assert client.get(path).status_code == 401
    response = client.get(path, headers=member)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert "authorization" in {item.strip().lower() for item in response.headers["vary"].split(",")}
    if operation == "page":
        assert [item["id"] for item in response.json()["items"]] == ["history-000000"]
        assert isinstance(client.get("/api/v1/history", headers=owner).json(), list)
    else:
        assert response.json() == {"total": 1}
    original = getattr(router, "history_inventory_" + operation)
    def revoke(*args):
        result = original(*args)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result
    monkeypatch.setattr(router, "history_inventory_" + operation, revoke)
    assert client.get(path, headers=member).status_code == 403
