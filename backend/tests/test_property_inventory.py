"""Prepared synthetic Memory/SQLite parity; no native execution in source phase."""

import csv
import io
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from backend.db.orm_models import PropertyORM
from backend.services import property_inventory as service
from backend.services.property_inventory_export import csv_chunks
from backend.services.property_inventory_types import PropertyInventoryQuery as Query
from backend.tests.property_inventory_support import actor, properties, put, units
from backend.tests.property_inventory_support import property_box as property_box

DAY = date(2026, 10, 4)


def query(**values):
    return Query(**{"as_of": DAY, **values})


def walk(box, **values):
    seen, cursor = [], None
    while True:
        page = service.property_inventory_page(box.store, query(cursor=cursor, **values))
        assert len(page.items) <= values.get("page_size", 25)
        seen.extend(page.items)
        if not page.has_more:
            assert page.next_cursor is None
            return seen
        assert page.items and page.next_cursor
        cursor = page.next_cursor


def rent_seed(box):
    properties(box, [{"id": name, "portfolio_id": portfolio, "name": "Same", "city": city}
        for name, portfolio, city in [("e-zero", "eur", "X"), ("e-small", "eur", "X"),
            ("e-large", "eur", "X"), ("e-tie", "eur", "X"), ("e-null", "eur", None),
            ("u-zero", "usd", "X"), ("u-rent", "usd", "X"), ("unknown", "unknown", None)]])
    units(box, [{"id": "unit-" + prop, "property_id": prop, "cold_rent": rent}
        for prop, rent in [("e-small", 0.29), ("e-large", 9999999999.99), ("e-tie", 0.29),
                          ("e-null", None), ("u-rent", 0.01), ("unknown", 1)]])


@pytest.mark.parametrize("direction,expected", [
    ("asc", ["e-zero", "e-small", "e-tie", "e-large", "e-null", "u-zero", "u-rent", "unknown"]),
    ("desc", ["e-large", "e-tie", "e-small", "e-zero", "e-null", "u-rent", "u-zero", "unknown"]),
])
def test_currency_exact_rent_and_null_cursor_parity(property_box, direction, expected):
    box = property_box
    rent_seed(box)
    with actor(box):
        rows = walk(box, sort_by="unit_cold_rent_sum", sort_order=direction, page_size=2)
    assert [row.id for row in rows] == expected
    by_id = {row.id: row for row in rows}
    assert by_id["e-zero"].unit_cold_rent_sum == "0.00"
    assert by_id["e-small"].unit_cold_rent_sum == "0.29"
    assert by_id["e-large"].unit_cold_rent_sum == "9999999999.99"
    assert by_id["e-null"].unit_cold_rent_sum is None
    assert by_id["unknown"].unit_cold_rent_sum is by_id["unknown"].rent_currency is None


@pytest.mark.parametrize("sort,direction", [("name", "asc"), ("name", "desc"), ("city", "asc"), ("city", "desc")])
def test_text_ties_and_nulls_match_bytewise_source_order(property_box, sort, direction):
    box = property_box
    rent_seed(box)
    with actor(box):
        rows = walk(box, sort_by=sort, sort_order=direction, page_size=3)
    ids = [row.id for row in rows]
    if sort == "name":
        assert ids == sorted(ids, reverse=direction == "desc")
    else:
        nonnull = sorted(["e-zero", "e-small", "e-large", "e-tie", "u-zero", "u-rent"], reverse=direction == "desc")
        assert ids == nonnull + sorted(["e-null", "unknown"], reverse=direction == "desc")


def test_contract_date_parents_fanout_and_manual_status_are_distinct(property_box):
    box = property_box
    properties(box, [{"id": "p", "portfolio_id": "eur"}, {"id": "other", "portfolio_id": "eur"}])
    units(box, [{"id": "current", "property_id": "p", "cold_rent": 0.1, "status": "vacant"},
        {"id": "future", "property_id": "p", "cold_rent": 0.2, "status": "reserved"},
        {"id": "manual", "property_id": "p", "cold_rent": 0, "status": "rented"},
        {"id": "other-unit", "property_id": "other", "cold_rent": 10}])
    put(box, "tenants", [{"id": "t", "full_name": "Synthetic secret not projected"}])
    basis = {"property_id": "p", "tenant_id": "t", "status": "active", "start_date": date(2026, 1, 1)}
    put(box, "contracts", [{**basis, "id": name, "contract_number": name, "unit_id": unit, **extra}
        for name, unit, extra in [("a", "current", {"status": "terminated", "end_date": DAY}),
            ("b", "current", {}), ("f", "future", {"start_date": date(2026, 10, 5)}),
            ("past", "manual", {"end_date": date(2026, 10, 3)}), ("draft", "manual", {"status": "draft"}),
            ("expired", "manual", {"status": "expired"}), ("mismatch", "other-unit", {})]])
    put(box, "maintenance_cases", [{"id": name, "property_id": "p", "title": "Synthetic", "unit_id": unit, "status": status}
        for name, unit, status in [("m1", None, "open"), ("m2", "current", "in_progress"),
            ("bad", "other-unit", "open"), ("legacy", None, "legacy-unknown")]])
    with actor(box, "reader-eur"):
        row = service.property_inventory_page(box.store, query(search="p", page_size=10)).items
        actual = next(item for item in row if item.id == "p")
        assert actual.unit_count == 3 and actual.occupied_unit_count == 1
        assert actual.no_current_contract_unit_count == 2 and actual.multiple_current_contract_unit_count == 1
        assert (actual.manual_vacant_unit_count, actual.manual_reserved_unit_count, actual.manual_occupied_unit_count) == (1, 1, 1)
        assert actual.open_maintenance_count == 2 and actual.unknown_maintenance_status_count == 1
        assert actual.unit_cold_rent_sum == "0.30"
        assert "Synthetic secret" not in actual.model_dump_json()
        assert [item.id for item in service.property_inventory_page(box.store, query(view="multiple_current_contracts")).items] == ["p"]


def test_counts_scope_matching_and_actual_actor_cursor_are_independent(property_box):
    box = property_box
    rent_seed(box)
    with actor(box, "reader-eur"):
        first = service.property_inventory_page(box.store, query(page_size=1))
        summary = service.property_inventory_summary(box.store, query(search="e-null"))
        # Names are deliberately identical; exact portfolio matching is separate.
        assert summary.scope_totals.property_count == 5 and summary.matching_totals.property_count == 0
        assert summary.scope_totals.unit_count == 4
        assert {item.id for item in walk(box, page_size=2)} == {"e-zero", "e-small", "e-large", "e-tie", "e-null"}
        with pytest.raises(HTTPException) as error:
            service.property_inventory_page(box.store, query(page_size=1, cursor=first.next_cursor, as_of=date(2026, 10, 3)))
        assert error.value.status_code == 422
    with actor(box, "reader-usd"), pytest.raises(HTTPException) as error:
        service.property_inventory_page(box.store, query(page_size=1, cursor=first.next_cursor))
    assert error.value.status_code == 422


def test_known_missing_invalid_and_true_empty_rent_are_separate(property_box):
    box = property_box
    properties(box, [{"id": name, "portfolio_id": "eur"} for name in ("good", "mixed", "empty")])
    units(box, [{"id": name, "property_id": prop, "cold_rent": rent} for name, prop, rent in
        [("a", "good", 0.1), ("b", "good", 0.2), ("known", "mixed", 1), ("missing", "mixed", None), ("bad", "mixed", -1)]])
    with actor(box):
        rows = {row.id: row for row in walk(box)}
    assert rows["good"].unit_cold_rent_sum == "0.30" and rows["empty"].unit_cold_rent_sum == "0.00"
    assert rows["mixed"].unit_cold_rent_sum is None
    assert (rows["mixed"].rent_known_unit_count, rows["mixed"].rent_missing_unit_count, rows["mixed"].rent_invalid_unit_count) == (1, 1, 1)


def test_unicode_literal_search_and_complete_csv_share_public_money_keys(property_box):
    box = property_box
    rent_seed(box)
    put(box, "properties", [{"id": "literal", "portfolio_id": "eur", "name": "  =1+1 Müllerstraße %_\\", "property_type": "residential"}])
    with actor(box, "reader-eur"):
        assert [row.id for row in service.property_inventory_page(box.store, query(search="MÜLLERSTRASSE %_\\")).items] == ["literal"]
        result = b"".join(csv_chunks(box.store, query(sort_by="unit_cold_rent_sum"), token=box.tokens["reader-eur"], chunk_size=2))
    rows = list(csv.DictReader(io.StringIO(result.decode("utf-8-sig")), delimiter=";"))
    assert [row["id"] for row in rows] == ["e-zero", "literal", "e-small", "e-tie", "e-large", "e-null"]
    assert next(row for row in rows if row["id"] == "e-small")["unit_cold_rent_sum"] == "0.29"
    assert next(row for row in rows if row["id"] == "literal")["name"].startswith("'")
    assert "_rent_cents" not in rows[0] and "unknown" not in {row["id"] for row in rows}


def test_full_scoped_10002_inventory_no_global_list_or_stock_cap(property_box, monkeypatch):
    box = property_box
    for start in range(0, 10002, 500):
        properties(box, [{"id": f"property-{number:05d}", "portfolio_id": "eur", "name": f"House {number:05d}"}
                         for number in range(start, min(start + 500, 10002))])
    properties(box, [{"id": "hidden", "portfolio_id": "usd"}])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Global inventory list is forbidden")

    for name in ("list_properties", "list_portfolios", "list_units", "list_contracts", "list_maintenance_cases", "_list_paginated"):
        if hasattr(box.store, name):
            monkeypatch.setattr(box.store, name, forbidden)
    with actor(box, "reader-eur"):
        summary = service.property_inventory_summary(box.store, query(search="House"))
        assert summary.scope_totals.property_count == summary.matching_totals.property_count == 10002
        for number in (100, 1000, 10000):
            page = service.property_inventory_page(box.store, query(search=f"House {number:05d}", page_size=1))
            assert [row.id for row in page.items] == [f"property-{number:05d}"]
        rows = walk(box, page_size=200)
        exported = b"".join(csv_chunks(box.store, query(), token=box.tokens["reader-eur"], chunk_size=200))
    expected = [f"property-{number:05d}" for number in range(10002)]
    assert [row.id for row in rows] == expected
    reader = csv.DictReader(io.StringIO(exported.decode("utf-8-sig")), delimiter=";")
    csv_rows = list(reader)
    assert len(csv_rows) == 10002 and [row["id"] for row in csv_rows] == expected
    assert csv_rows[-1]["id"] == "property-10001"
    assert "hidden" not in {row["id"] for row in csv_rows}
    assert reader.fieldnames is not None and "_rent_cents" not in reader.fieldnames


def test_sql_materialization_bounded_and_dirty_caller_unflushed(property_box):
    box = property_box
    if box.engine is None:
        pytest.skip("Native SQL identity-map case; separate Memory cases cover parity")
    rent_seed(box)
    with actor(box):
        caller = box.db.get(PropertyORM, "e-small")
        caller.name = "Unflushed synthetic private edit"
        seen = []

        def observe(_connection, _cursor, sql, _parameters, _context, _many):
            seen.append(sql)

        event.listen(box.engine, "before_cursor_execute", observe)
        try:
            page = service.property_inventory_page(box.store, query(page_size=2))
        finally:
            event.remove(box.engine, "before_cursor_execute", observe)
        assert len(page.items) == 2 and caller in box.db.dirty
        assert all(row.name != caller.name for row in page.items)
        assert sum("PROPERTY_INVENTORY_PARENTS" in sql.upper() and "LIMIT" in sql.upper() for sql in seen) == 2
        assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in seen)
        with box.engine.connect() as actual:
            assert actual.scalar(select(PropertyORM.name).where(PropertyORM.id == "e-small")) == "Same"
        box.db.rollback()
