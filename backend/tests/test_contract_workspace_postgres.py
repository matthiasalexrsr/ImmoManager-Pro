"""Actual PostgreSQL acceptance, using an owned Alembic-upgraded UUID schema."""

from datetime import date

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.db.orm_models import ContractORM, PropertyORM
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_contract_workspace import insert, install_actor, page, pages, seed


@pytest.mark.parametrize(
    "stored,search",
    [
        ("ÜBER Größe ÄRGER ÖSTERREICH STRAẞE", "über grösse ärger österreich strasse"),
        ("Σίσυφος", "σίσυφοσ"),
        ("Ligature ﬃ", "ligature FFI"),
        ("İstanbul", "i\u0307stanbul"),
    ],
)
def test_pg_search_has_identical_unicode_casefold_semantics(postgres, stored, search):
    row, _ = seed(postgres.store, stored)
    for suffix in ("lease", "building", "apartment", "person"):
        assert [item.id for item in page(postgres.store, search=search + " " + suffix).items] == [row.id]


def test_pg_nullable_text_ties_filters_and_fresh_scoped_display_contexts(postgres, monkeypatch):
    store = postgres.store
    template, portfolio = seed(store, "Scoped workspace")
    ids = ["B", "a", "b", "Ü legacy " + "x" * 120]
    insert(
        store,
        [
            template.model_copy(
                update={
                    "id": identifier,
                    "contract_number": "PG-" + str(index),
                    "end_date": None if index in (1, 3) else date(2026, 12, 31),
                }
            )
            for index, identifier in enumerate(ids)
        ],
    )
    hidden, _ = seed(store, "Private foreign")
    insert(
        store, [template.model_copy(update={"id": "broken", "contract_number": "Broken PG", "unit_id": hidden.unit_id})]
    )
    scope, _ = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        all_rows = pages(store, property_id=template.property_id, sort_by="end_date", page_size=2)
        known = sorted([template.id, "B", "b"], key=lambda value: value.encode("utf-8"))
        unknown = sorted(["a", ids[3]], key=lambda value: value.encode("utf-8"))
        assert [row.id for row in all_rows] == known + unknown
        assert all(
            row.property_name == "Scoped workspace building" and row.tenant_name == "Scoped workspace person"
            for row in all_rows
        )
        assert page(store, search="Private foreign").items == []
        limited = page(
            store,
            property_id=template.property_id,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 31),
            status="draft",
            sort_by="end_date",
            page_size=2,
        )
        assert [row.id for row in limited.items] == known[:2] and limited.has_more


def test_pg_late_match_beyond_ten_thousand_is_one_bounded_select(postgres):
    store = postgres.store
    template, _ = seed(store, "Late PG 100%_literal")
    for start in range(0, 10001, 500):
        insert(
            store,
            [
                template.model_copy(
                    update={
                        "id": f"old-{index:05d}",
                        "contract_number": f"PG-old-{index:05d}",
                        "start_date": date(2010, 1, 1),
                        "end_date": date(2010, 12, 31),
                    }
                )
                for index in range(start, min(start + 500, 10001))
            ],
        )
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(postgres.engine, "before_cursor_execute", capture)
    try:
        result = page(
            store, search="pg 100%_literal", date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), page_size=1
        )
    finally:
        event.remove(postgres.engine, "before_cursor_execute", capture)
    assert [row.id for row in result.items] == [template.id]
    assert len(statements) == 1
    statement, parameters = statements[0]
    assert "LIMIT" in statement.upper() and "OFFSET" not in statement.upper() and "COUNT(" not in statement.upper()
    assert 2 in parameters.values()


def test_pg_independent_connection_context_change_and_insert_are_not_cached(postgres):
    store = postgres.store
    template, _ = seed(store, "B workspace")
    insert(store, [template.model_copy(update={"id": "d", "contract_number": "D workspace"})])
    first = page(store, property_id=template.property_id, page_size=1)
    with Session(postgres.engine) as writer:
        reader_pid = store.db.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        writer_pid = writer.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        assert reader_pid != writer_pid
        writer.execute(
            PropertyORM.__table__.update()
            .where(PropertyORM.id == template.property_id)
            .values(name="Fresh display context")
        )
        writer.execute(
            ContractORM.__table__.insert(),
            template.model_copy(update={"id": "c", "contract_number": "C workspace"}).model_dump(),
        )
        writer.commit()
    next_page = page(store, property_id=template.property_id, page_size=1, cursor=first.next_cursor)
    assert next_page.items[0].id == "c"
    assert next_page.items[0].property_name == "Fresh display context"
    assert store.db.scalar(select(ContractORM.contract_number).where(ContractORM.id == "c")) == "C workspace"
