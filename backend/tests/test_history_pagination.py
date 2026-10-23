"""History keyset pages retain portfolio boundaries and reach old records."""

from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend import db as _db  # noqa: F401 (register all portfolio graph tables)
from backend.db.orm_models import Base, ChangeHistoryORM
from backend.models import ChangeHistoryEntry, PortfolioCreate, PropertyCreate, UserRead
from backend.repositories import SQLAlchemyStore
from backend.routers import history
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import InMemoryStore

migration = import_module("backend.db.migrations.versions.f020a1b2c001_history_cursor_index")
ACTOR = UserRead(id="history-test", username="history-test", email="history@example.test", full_name="History Test", role="readonly")


@pytest.fixture(params=["memory", "sql"])
def source(request, tmp_path, monkeypatch):
    engine = None
    session = None
    store: InMemoryStore | SQLAlchemyStore
    if request.param == "sql":
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'history.db'}")
        Base.metadata.create_all(engine)
        session = Session(engine)
        store = SQLAlchemyStore(session)
    else:
        store = InMemoryStore()
    monkeypatch.setattr(history, "store", store)
    yield store
    if session is not None:
        session.close()
    if engine is not None:
        engine.dispose()


def put(source, rows):
    if hasattr(source, "db"):
        source.db.add_all(ChangeHistoryORM(**row.model_dump()) for row in rows)
        source.db.commit()
    else:
        source.change_history.update({row.id: row for row in rows})


def page(*, cursor=None, limit=47, entity_type=None, entity_id=None):
    return history.history_page(actor=ACTOR, cursor=cursor, limit=limit, entity_type=entity_type, entity_id=entity_id)


def test_all_pages_reach_twenty_year_old_rows_beyond_the_previous_500_limit(source):
    rows = [ChangeHistoryEntry(id=f"h-{index:04}", entity_type="property", entity_id="p1", field_name="name",
        changed_at=datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(days=index // 4)) for index in range(603)]
    put(source, rows)
    cursor = None
    seen: list[str] = []
    while True:
        result = page(cursor=cursor)
        assert len(result.items) <= 47
        seen.extend(row.id for row in result.items)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert seen == [row.id for row in sorted(rows, key=history._key, reverse=True)]
    assert len(set(seen)) == 603


def test_new_rows_do_not_shift_the_next_page_and_cursors_are_bound_to_filters(source):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    put(source, [ChangeHistoryEntry(id=identifier, entity_type="property", entity_id="p1", field_name="name", changed_at=stamp)
                 for identifier in ("a", "b", "c", "d")])
    first = page(limit=2, entity_type="property", entity_id="p1")
    assert [row.id for row in first.items] == ["d", "c"]
    put(source, [ChangeHistoryEntry(id="z", entity_type="property", entity_id="p1", field_name="name", changed_at=stamp)])
    second = page(cursor=first.next_cursor, limit=2, entity_type="property", entity_id="p1")
    assert [row.id for row in second.items] == ["b", "a"]
    assert second.next_cursor is None
    with pytest.raises(HTTPException) as rejected:
        page(cursor=first.next_cursor, entity_type="property", entity_id="other")
    assert rejected.value.status_code == 422


def test_every_page_uses_current_portfolio_access_before_limiting_or_exposing_values(source):
    north = source.create_portfolio(PortfolioCreate(name="Nord"))
    south = source.create_portfolio(PortfolioCreate(name="Süd"))
    visible = source.create_property(PropertyCreate(name="Nordhaus", property_type="residential", portfolio_id=north.id))
    hidden = source.create_property(PropertyCreate(name="Südhaus", property_type="residential", portfolio_id=south.id))
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    put(source, [ChangeHistoryEntry(id=identifier, entity_type="property", entity_id=parent, field_name="iban",
        new_value=value, changed_at=stamp) for identifier, parent, value in (
            ("z-hidden", hidden.id, "DE-SOUTH-PRIVATE-BANK"),
            ("d-visible", visible.id, "DE-NORTH-1"), ("c-visible", visible.id, "DE-NORTH-2"),
            ("b-hidden", hidden.id, "DE-SOUTH-OTHER-PRIVATE-BANK"), ("a-visible", visible.id, "DE-NORTH-3"))])
    restricted = AccessScope("reader", "verwalter", False, (north.id,))
    with scope_context(restricted):
        first = page(limit=2)
        assert [row.id for row in first.items] == ["d-visible", "c-visible"]
        assert "SOUTH" not in first.model_dump_json()
        second = page(limit=2, cursor=first.next_cursor)
        assert [row.id for row in second.items] == ["a-visible"]
        assert second.next_cursor is None
        assert page(entity_type="property", entity_id=hidden.id).items == []
        # Identical source visibility to the old, authorized store API.
        assert {row.id for row in source.list_change_history()} == {"d-visible", "c-visible", "a-visible"}
    with scope_context(AccessScope("reader", "verwalter", False, ())):
        assert page(cursor=first.next_cursor).items == []


def test_sql_pages_are_bounded_queries_without_materializing_the_history_store(source, monkeypatch):
    if not hasattr(source, "db"):
        pytest.skip("SQL query shape")
    put(source, [ChangeHistoryEntry(id=f"h{i}", entity_type="property", entity_id="p1", field_name="name") for i in range(10)])
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    monkeypatch.setattr(source, "list_change_history", lambda: pytest.fail("SQL page must not materialize the full store"))
    sa.event.listen(source.db.get_bind(), "before_cursor_execute", capture)
    try:
        first = page(limit=2)
        page(limit=2, cursor=first.next_cursor)
    finally:
        sa.event.remove(source.db.get_bind(), "before_cursor_execute", capture)
    selects = [(sql, params) for sql, params in statements if "SELECT" in sql.upper() and "FROM change_history" in sql]
    assert len(selects) == 2
    assert all("LIMIT" in sql.upper() and params[-2:] == (3, 0) for sql, params in selects)
    assert "(change_history.changed_at, change_history.id) <" in selects[1][0]


def test_http_page_validation_and_legacy_api_shape(source):
    app = FastAPI()
    app.include_router(history.router)
    app.dependency_overrides[history.require_auth] = lambda: ACTOR
    with TestClient(app) as client:
        assert client.get("/history/page?limit=251").status_code == 422
        assert client.get("/history/page?cursor=not-a-cursor").status_code == 422
        assert client.get("/history/page").json() == {"items": [], "next_cursor": None}
        assert client.get("/history").json() == []


def test_index_migration_upgrade_adoption_and_downgrade_preserve_history(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        connection.exec_driver_sql("CREATE TABLE change_history (id TEXT PRIMARY KEY, changed_at DATETIME NOT NULL, payload TEXT)")
        connection.exec_driver_sql("INSERT INTO change_history VALUES ('retained','2000-01-01','private historical value')")
        migration.upgrade()
        migration.upgrade()  # Existing create_all index can be adopted.
        actual = {index["name"]: index["column_names"] for index in sa.inspect(connection).get_indexes("change_history")}
        assert actual[migration.INDEX] == ["changed_at", "id"]
        plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT * FROM change_history WHERE (changed_at,id) < ('2026-01-01','boundary') ORDER BY changed_at DESC,id DESC LIMIT 101").all()
        assert migration.INDEX in str(plan) and "SEARCH" in str(plan) and "TEMP B-TREE" not in str(plan)
        migration.downgrade()
        assert migration.INDEX not in {index["name"] for index in sa.inspect(connection).get_indexes("change_history")}
        assert connection.exec_driver_sql("SELECT payload FROM change_history").scalar_one() == "private historical value"
    engine.dispose()


def test_index_migration_rejects_an_incorrect_existing_index(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bad-index.db'}")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        connection.exec_driver_sql("CREATE TABLE change_history (id TEXT PRIMARY KEY, changed_at DATETIME NOT NULL)")
        connection.exec_driver_sql(f"CREATE INDEX {migration.INDEX} ON change_history (id)")
        with pytest.raises(RuntimeError, match="index mismatch"):
            migration.upgrade()
    engine.dispose()
