"""Native SQLite ASCII matching must preserve the existing Unicode substring contract."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, insert, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from backend.db.orm_models import TenantORM
from backend.db.privacy_models import PrivacyControlORM, RestoreReviewORM
from backend.services import global_search as search


def test_sqlite_avoids_python_callbacks_for_plain_ascii_and_preserves_every_value():
    engine = create_engine("sqlite:///:memory:")
    table = Table("samples", MetaData(), Column("id", Integer, primary_key=True), Column("value", Text))
    table.create(engine)
    values: list[str | None] = [f"Synthetic BOOKING {index}" for index in range(10000)]
    values += ["ÖZTÜRK", "ẞ", "İ", "ΟΣ", "A\u0308", "Straße", "😀ASCII", "line\nBREAK", "A\0B", "", None]
    with Session(engine) as db:
        db.execute(insert(table), [{"id": index, "value": value} for index, value in enumerate(values)])
        lower = search._sql_lower(db)
        calls = []

        def counted(value):
            calls.append(value)
            return value.lower() if isinstance(value, str) else value

        connection = db.connection().connection.driver_connection
        assert connection is not None
        connection.create_function("immo_lower", 1, counted, deterministic=True)
        actual = list(db.scalars(select(lower(table.c.value)).order_by(table.c.id)))
        assert actual == [value.lower() if isinstance(value, str) else value for value in values]
        # CASE must short-circuit: ordinary ASCII and newlines never call into Python.
        # SQLite length(text) stops at NUL; the conservative branch still preserves that text.
        assert calls == [value for value in values if value is None or not value.isascii() or "\0" in value]
    engine.dispose()


@pytest.mark.parametrize("query", ["search", "ÖZTÜRK", "ẞ", "STRASSE", "İ", "i\u0307", "ΟΣ", "ος",
                                   "%", "_", "\\", "line\nbreak", "ÄRGER", "ascii@", "search tail"])
def test_native_and_unicode_branches_match_memory_counts_pages_and_export(query):
    engine = create_engine("sqlite:///:memory:")
    table = TenantORM.__table__
    assert isinstance(table, Table)
    table.create(engine)
    for model in (PrivacyControlORM, RestoreReviewORM):
        private_table = model.__table__
        assert isinstance(private_table, Table)
        private_table.create(engine)
    names = ["SEARCH ordinary", "SEARCH ÖZTÜRK ÄRGER", "SEARCH Straße ẞ", "SEARCH İSTANBUL I",
             "SEARCH ΟΣ", "SEARCH a_%\\line\nBREAK", "SEARCH tail"]
    rows = [SimpleNamespace(id=f"row-{index:03d}", full_name=name,
                            email="ASCII@EXAMPLE.TEST" if index % 2 else None)
            for index, name in enumerate(names)]
    memory = SimpleNamespace(list_tenants=lambda: rows)
    spec = search.get_type("tenant")
    expected = search.search_page(memory, spec, query, limit=100)
    with Session(engine) as db:
        db.execute(insert(TenantORM), [{"id": row.id, "full_name": row.full_name, "email": row.email} for row in rows])
        sql = SimpleNamespace(db=db)
        actual, cursor = [], None
        while True:
            page = search.search_page(sql, spec, query, limit=2, cursor=cursor)
            actual.extend(page.items)
            assert page.total == expected.total
            if not page.has_more:
                assert page.next_cursor is None
                break
            cursor = page.next_cursor
        assert actual == expected.items
        assert list(search.iter_all(sql, spec, query, batch=2)) == expected.items
    engine.dispose()


def test_postgres_keeps_its_database_lower_without_sqlite_callbacks():
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    expression = search._sql_lower(db)(literal("ÖZTÜRK"))
    compiled = str(expression.compile(dialect=postgresql.dialect()))
    assert compiled.startswith("lower(")
    assert "immo_lower" not in compiled and "CASE" not in compiled
