"""Mandatory native history proof on the matrix runner's explicitly owned database.

The runner creates/drops its immoqa_pro_<uuid> database. This test only adds
uniquely named fixtures; it never creates, truncates, resets or drops databases.
No backend imports occur before the native-target guard, so a skipped case does
not initialize an unrelated configured database through its own imports.
"""

import os
import re
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa


def _owned_native_target() -> bool:
    if os.environ.get("TEST_STORE_BACKEND") != "sql":
        return False
    configured = os.environ.get("DATABASE_URL", "")
    try:
        url = sa.engine.make_url(configured)
    except (sa.exc.ArgumentError, ValueError):
        return False
    return (url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost", "::1"}
            and re.fullmatch(r"immoqa_pro_[0-9a-f]{32}", url.database or "") is not None)


pytestmark = pytest.mark.skipif(not _owned_native_target(),
    reason="requires TEST_STORE_BACKEND=sql and an explicitly owned loopback immoqa_pro_<uuid> PostgreSQL database")


def test_owned_native_postgres_history_keyset_pages_respect_current_scope():
    assert _owned_native_target(), "Native target changed after collection; no fixture writes are permitted"
    from backend import dependencies
    from backend.db.orm_models import ChangeHistoryORM
    from backend.models import ChangeHistoryEntry, PortfolioCreate, PropertyCreate
    from backend.repositories import SQLAlchemyStore
    from backend.routers import history
    from backend.services.portfolio_scope import AccessScope, current_scope, scope_context

    source = dependencies.store
    assert isinstance(source, SQLAlchemyStore), "Native gate must use the application's SQL store"
    registry = dependencies._scoped_session
    assert registry is not None
    assert source.db is registry, "Exercise the real scoped Session and its authorization hooks"
    assert current_scope() is None, "Fixture setup requires the test's installation context"
    engine = registry.get_bind()
    assert isinstance(engine, sa.Engine)
    expected = sa.engine.make_url(os.environ["DATABASE_URL"])
    assert engine.dialect.name == "postgresql"
    assert (engine.url.host, engine.url.port, engine.url.database, engine.url.username) == (
        expected.host, expected.port, expected.database, expected.username)
    indexes = {index["name"]: index["column_names"] for index in sa.inspect(engine).get_indexes("change_history")}
    assert indexes["idx_change_history_cursor"] == ["changed_at", "id"]

    unique = uuid4().hex[:12]
    north = source.create_portfolio(PortfolioCreate(name=f"Native history north {unique}"))
    south = source.create_portfolio(PortfolioCreate(name=f"Native history south {unique}"))
    visible = source.create_property(PropertyCreate(name=f"Native north {unique}", property_type="residential", portfolio_id=north.id))
    hidden = source.create_property(PropertyCreate(name=f"Native south {unique}", property_type="residential", portfolio_id=south.id))
    rows = [ChangeHistoryEntry(id=f"{unique}-{index:04}", entity_type="property", entity_id=visible.id,
        field_name="iban", new_value=f"NORTH-{index}",
        changed_at=datetime(2000, 1, 1) + timedelta(days=index // 4)) for index in range(603)]
    private_rows = [ChangeHistoryEntry(id=f"{unique}-private-{index}", entity_type="property", entity_id=hidden.id,
        field_name="iban", new_value=f"DE-SOUTH-PRIVATE-BANK-{unique}-{index}", changed_at=datetime(2026, 1, index + 1))
        for index in range(2)]
    registry.add_all(ChangeHistoryORM(**row.model_dump()) for row in [*rows, *private_rows])
    registry.commit()

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM change_history" in statement:
            statements.append((statement, parameters))

    def page(cursor=None, *, entity_id=None):
        return history.history_page(cursor=cursor, limit=47, entity_type="property", entity_id=entity_id)

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        with scope_context(AccessScope(f"native-{unique}", "verwalter", False, (north.id,))):
            first = page()
            # The two newer foreign rows must be removed by PostgreSQL's scope
            # predicates before LIMIT, rather than shortening a page afterward.
            assert len(first.items) == 47
            assert all(item.entity_id == visible.id for item in first.items)
            assert "SOUTH-PRIVATE" not in first.model_dump_json()
            first_cursor = first.next_cursor
            assert first_cursor is not None

        # A committed newer row cannot shift older keyset pages as offsets do.
        newest = ChangeHistoryEntry(id=f"{unique}-newest", entity_type="property", entity_id=visible.id,
            field_name="iban", new_value="NORTH-NEWEST", changed_at=datetime(2099, 1, 1))
        registry.add(ChangeHistoryORM(**newest.model_dump()))
        registry.commit()

        seen = [item.id for item in first.items]
        cursor = first_cursor
        with scope_context(AccessScope(f"native-{unique}", "verwalter", False, (north.id,))):
            while cursor is not None:
                result = page(cursor)
                assert len(result.items) <= 47
                assert all(item.entity_id == visible.id for item in result.items)
                assert "SOUTH-PRIVATE" not in result.model_dump_json()
                seen.extend(item.id for item in result.items)
                cursor = result.next_cursor
            assert seen == [item.id for item in sorted(rows, key=lambda item: (item.changed_at, item.id), reverse=True)]
            assert len(set(seen)) == 603
            assert page().items[0].id == newest.id
            assert page(entity_id=hidden.id).items == []

        # Cursor knowledge never grants access after the account loses a portfolio.
        with scope_context(AccessScope(f"native-{unique}", "verwalter", False, ())):
            assert page(first_cursor).items == []
        with scope_context(AccessScope(f"native-{unique}", "verwalter", False, (south.id,))):
            assert {item.id for item in page().items} == {item.id for item in private_rows}
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    # These are the actual PostgreSQL DBAPI statements, not a SQLite fixture or
    # a compiled approximation. Every read is bounded at the database boundary.
    selects = [(sql, parameters) for sql, parameters in statements if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(selects) >= 16
    assert all("LIMIT" in sql and isinstance(parameters, dict) and 48 in parameters.values()
               for sql, parameters in selects)
    assert any("(change_history.changed_at, change_history.id) <" in sql for sql, _ in selects)
    assert all("WHERE" in sql.rsplit("FROM change_history", 1)[1].split("LIMIT", 1)[0] for sql, _ in selects)
