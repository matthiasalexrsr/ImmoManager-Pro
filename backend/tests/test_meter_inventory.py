"""Bounded current meters, original standalone readings and complete authorized exports."""

import csv
import io
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from backend import auth
from backend.db.orm_models import MeterORM, StandaloneMeterReadingORM
from backend.models import Meter, MeterCreate, StandaloneMeterReading
from backend.routers import meter_inventory as router
from backend.services import meter_inventory as service
from backend.services.meter_inventory import MeterInventoryQuery as Query
from backend.services.meter_inventory import MeterReadingsQuery as ReadingQuery
from backend.services.meter_inventory_export import csv_chunks
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor, seed
from backend.tests.test_portfolio_access_http import access_http as access_http

STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def insert(store, items, model, collection):
    if hasattr(store, "db"):
        store.db.execute(model.__table__.insert(), [row.model_dump() for row in items])
        store.db.commit()
    else:
        store.__dict__[collection].update({row.id: row for row in items})


def meters(store, count=3, prefix="Müller"):
    contract, portfolio = seed(store, prefix)
    for start in range(0, count, 500):
        insert(store, [Meter(id=f"meter-{n:06d}", unit_id=contract.unit_id, meter_type="district_loop_x",
            measurement_unit="therm-custom" if n % 2 else None, serial_number=f"Meter {n:06d}",
            next_inspection=date(2026, 10, 2) if n % 2 else None, is_active=n % 3 != 0,
            created_at=STAMP, updated_at=STAMP) for n in range(start, min(count, start + 500))], MeterORM, "meters")
    return contract, portfolio


def readings(store, count=3, meter_id="meter-000000"):
    for start in range(0, count, 500):
        insert(store, [StandaloneMeterReading(id=f"reading-{n:06d}", meter_id=meter_id,
            reading_date=date(2000, 1, 1) + timedelta(days=n // 2), value=n, recorded_by="Straße",
            notes="Original = %_", created_at=STAMP, updated_at=STAMP)
            for n in range(start, min(count, start + 500))], StandaloneMeterReadingORM, "standalone_meter_readings")


def forbid_lists(store, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Whole inventory/history reader forbidden")
    for name in ("list_meters", "list_standalone_meter_readings", "list_units", "list_properties", "_list_paginated"):
        monkeypatch.setattr(store, name, forbidden)


def test_complete_late_inventory_summary_and_csv(active, monkeypatch):
    meters(active, 10002)
    readings(active, 2)
    forbid_lists(active, monkeypatch)
    for n in (100, 1000, 10000):
        page = service.meter_inventory_page(active, Query(search=f"Meter {n:06d}", page_size=1))
        assert [row.id for row in page.items] == [f"meter-{n:06d}"]
    summary = service.meter_inventory_summary(active, Query(as_of=date(2026, 10, 3)))
    assert summary == dict(total=10002, active=6668, inactive=3334, no_reading=10001,
                           unknown_unit=5001, overdue=5001, due_soon=0)
    exported = list(csv.DictReader(io.StringIO(b"".join(csv_chunks(active, Query(), chunk_size=1000)).decode("utf-8-sig")), delimiter=";"))
    assert len(exported) == len({row["id"] for row in exported}) == 10002
    assert exported[10000]["serial_number"] == "Meter 010000"
    assert exported[1]["measurement_unit"] == "therm-custom"


@pytest.mark.parametrize("sort", ["serial_number", "next_inspection", "last_reading_date", "last_reading_value"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_duplicate_and_null_keysets(active, sort, direction):
    contract, _ = meters(active, 4)
    insert(active, [Meter(id="meter-null", unit_id=contract.unit_id, meter_type="cold_water",
        serial_number=None, created_at=STAMP, updated_at=STAMP)], MeterORM, "meters")
    readings(active, 3)
    values = dict(page_size=2, sort_by=sort, sort_order=direction)
    found, cursor, first = [], None, None
    while True:
        page = service.meter_inventory_page(active, Query(**values, cursor=cursor))
        found.extend(row.id for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        first = first or cursor
    assert len(found) == len(set(found)) == 5
    with pytest.raises(HTTPException) as error:
        service.meter_inventory_page(active, Query(**values, cursor=first, search="changed"))
    assert error.value.status_code == 422


def test_latest_tie_and_bounded_long_original_history(active, monkeypatch):
    meters(active, 2)
    readings(active, 10003)
    forbid_lists(active, monkeypatch)
    row = service.meter_inventory_detail(active, "meter-000000")
    assert row.last_reading_id == "reading-010002" and row.last_reading_value == 10002
    assert row.measurement_unit is None
    page = service.meter_readings_page(active, row.id, ReadingQuery(page_size=25))
    assert len(page.items) == 25 and page.has_more
    assert [item.id for item in page.items[:3]] == ["reading-010002", "reading-010001", "reading-010000"]
    second = service.meter_readings_page(active, row.id, ReadingQuery(page_size=25, cursor=page.next_cursor))
    assert not ({item.id for item in second.items} & {item.id for item in page.items})
    assert all(not hasattr(item, "measurement_unit") for item in page.items)
    assert service.meter_readings_page(active, row.id, ReadingQuery(search="STRASSE", date_from=row.last_reading_date)).items
    with pytest.raises(HTTPException) as error:
        service.meter_readings_page(active, "meter-000001", ReadingQuery(page_size=25, cursor=page.next_cursor))
    assert error.value.status_code == 422
    assert service.meter_readings_page(active, "meter-000001", ReadingQuery()).items == []
    with pytest.raises(HTTPException) as error:
        service.meter_readings_page(active, "absent", ReadingQuery())
    assert error.value.status_code == 404


def test_reading_day_ties_both_directions_and_literal_search(active):
    meters(active)
    readings(active, 9)
    for direction in ("asc", "desc"):
        found, cursor = [], None
        while True:
            page = service.meter_readings_page(active, "meter-000000", ReadingQuery(page_size=2, sort_order=direction, search="%_", cursor=cursor))
            found.extend(row.id for row in page.items)
            if not page.has_more:
                break
            cursor = page.next_cursor
        expected = [f"reading-{n:06d}" for n in range(9)]
        assert found == (expected if direction == "asc" else expected[::-1])
    assert service.meter_inventory_page(active, Query(search="MÜLLER")).items
    assert not service.meter_inventory_page(active, Query(search="%_")).items


def test_current_mapping_custom_dimensions_and_filters(active):
    contract, _ = meters(active)
    readings(active)
    assert service.meter_inventory_summary(active, Query(view="no_reading"))["total"] == 2
    assert service.meter_inventory_summary(active, Query(view="unknown_unit"))["total"] == 2
    assert service.meter_inventory_summary(active, Query(is_active=False))["total"] == 1
    assert service.meter_inventory_page(active, Query(measurement_unit="therm-custom")).items[0].meter_type == "district_loop_x"
    assert service.meter_inventory_summary(active, Query(property_id=contract.property_id, view="overdue", as_of=date(2026, 10, 3)))["total"] == 1
    assert service.meter_inventory_summary(active, Query(view="due_soon", as_of=date(2026, 10, 2)))["total"] == 1
    for query in (dict(inspection_from="2026-12-01", inspection_to="2026-01-01"), dict(sort_by="notes")):
        with pytest.raises(ValueError):
            Query(**query)


def test_bounded_sql_never_autoflush_or_load_all_history(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL statement and dirty-object gate")
    meters(active)
    readings(active, 31)
    meter = active.db.get(MeterORM, "meter-000000")
    meter.supplier = "Unflushed edit"
    statements = []
    def capture(_conn, _cursor, sql, parameters, _context, _many):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = service.meter_inventory_page(active, Query(page_size=2))
        assert len(statements) == 1 and "LIMIT" in statements[0].upper()
        assert "ROW_NUMBER" not in statements[0].upper()
        statements.clear()
        history = service.meter_readings_page(active, "meter-000000", ReadingQuery(page_size=2))
        assert len(statements) == 2 and all("LIMIT" in sql.upper() for sql in statements)
        assert len(page.items) == len(history.items) == 2
        assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "CREATE", "DELETE")) for sql in statements)
        assert meter in active.db.dirty and all(row.supplier != meter.supplier for row in page.items)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        active.db.rollback()


def test_scope_detail_history_summary_export_and_revoke(active, monkeypatch):
    _, portfolio = meters(active)
    hidden_contract, _ = seed(active, "Hidden")
    insert(active, [Meter(id="hidden-meter", unit_id=hidden_contract.unit_id, meter_type="gas",
        serial_number="Hidden secret", created_at=STAMP, updated_at=STAMP)], MeterORM, "meters")
    readings(active, 3)
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        assert service.meter_inventory_summary(active, Query())["total"] == 3
        assert "Hidden secret" not in b"".join(csv_chunks(active, Query())).decode()
        for operation in (service.meter_inventory_detail, lambda store, identifier: service.meter_readings_page(store, identifier, ReadingQuery())):
            with pytest.raises(HTTPException) as error:
                operation(active, "hidden-meter")
            assert error.value.status_code == 404
        chunks = csv_chunks(active, Query(), chunk_size=1)
        assert next(chunks).startswith(b"\xef\xbb\xbf")
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException) as error:
            next(chunks)
        assert error.value.status_code == 403
        chunks.close()


def test_independent_latest_reading_change_aborts_export(active):
    if not hasattr(active, "db"):
        pytest.skip("Independent SQL snapshot writer")
    meters(active)
    readings(active, 1, "meter-000001")
    engine = active.db.get_bind()
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    chunks = csv_chunks(active, Query(), chunk_size=1)
    try:
        assert next(chunks).startswith(b"\xef\xbb\xbf")
        with engine.begin() as writer:
            writer.execute(update(StandaloneMeterReadingORM).where(StandaloneMeterReadingORM.id == "reading-000000").values(value=999))
        with pytest.raises(HTTPException) as error:
            next(chunks)
        assert error.value.status_code == 409
    finally:
        chunks.close()


def test_http_private_routes_and_payload_meter_mismatch_no_disclosure(access_http):
    client, store, owner, member, _, _, _, contracts, *_ = access_http
    with scope_context(None):
        own = store.create_meter(MeterCreate(unit_id=contracts[0].unit_id, meter_type="cold_water"))
        hidden = store.create_meter(MeterCreate(unit_id=contracts[1].unit_id, meter_type="private-secret-type"))
    for suffix in ("inventory/page", "inventory/summary", "inventory/export", f"inventory/detail/{own.id}", f"{own.id}/readings/page"):
        url = "/api/v1/meters/" + suffix
        assert client.get(url).status_code == 401
        response = client.get(url, headers=member)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert "private-secret-type" not in response.text
    rejected = client.post(f"/api/v1/meters/{own.id}/readings", headers=member,
                          json=dict(meter_id=hidden.id, reading_date="2026-10-03", value=47))
    assert rejected.status_code == 400
    assert hidden.id not in rejected.text and "private-secret-type" not in rejected.text
    assert client.get(f"/api/v1/meters/{hidden.id}/readings/page", headers=owner).json()["items"] == []
    assert client.post(f"/api/v1/meters/{own.id}/readings", headers=member,
                       json=dict(meter_id=own.id, reading_date="2026-10-03", value=47)).status_code == 201
    assert client.get(f"/api/v1/meters/{hidden.id}/readings/page", headers=member).status_code == 404
    assert isinstance(client.get("/api/v1/meters", headers=owner).json(), list)
    for values in (dict(unknown=1), dict(page_size=0), dict(cursor="bad"), dict(sort_by="notes")):
        assert client.get("/api/v1/meters/inventory/page", params=values, headers=member).status_code == 422


@pytest.mark.parametrize("operation", ["page", "summary", "detail", "readings"])
def test_http_late_revoke_publishes_no_meter_content(access_http, monkeypatch, operation):
    client, store, _, member, actor, _, _, contracts, *_ = access_http
    with scope_context(None):
        meter = store.create_meter(MeterCreate(unit_id=contracts[0].unit_id, meter_type="cold_water"))
    names = dict(page="meter_inventory_page", summary="meter_inventory_summary", detail="meter_inventory_detail", readings="meter_readings_page")
    original = getattr(router, names[operation])
    def revoke(*args):
        result = original(*args)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result
    monkeypatch.setattr(router, names[operation], revoke)
    suffix = f"{meter.id}/readings/page" if operation == "readings" else f"inventory/detail/{meter.id}" if operation == "detail" else f"inventory/{operation}"
    assert client.get("/api/v1/meters/" + suffix, headers=member).status_code == 403
