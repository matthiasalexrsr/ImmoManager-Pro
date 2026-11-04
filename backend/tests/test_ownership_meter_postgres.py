"""F01/F20: real connections and a forced stale-read window, no SQLite substitute."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401

from backend import auth
from backend.models import (
    ContactCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    UnitCreate,
)
from backend.models_ownership import OwnershipShareCreate, OwnershipTransferCreate, TransferReceiver
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import meter_writes, ownership
from backend.services.data_snapshot import SnapshotError, prepare_import
from backend.services.maintenance_rows import Rows
from backend.storage import ValidationError


def estate(engine):
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Concurrent audit"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
        unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 1", unit_type="flat"))
        owners = [store.create_contact(ContactCreate(contact_type="owner", first_name=name)) for name in ["A", "B", "C"]]
        meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="water"))
    users = [auth.register_user(f"writer{i}", f"w{i}@example.test", "Writer", "Synthetic123!", "eigentuemer") for i in range(2)]
    return prop.id, [o.id for o in owners], meter.id, [u.id for u in users]


@pytest.mark.parametrize("scenario", ["create", "transfer", "transfer_vs_manual"])
def test_ownership_mutations_share_one_postgres_write_boundary(postgres, monkeypatch, scenario):  # noqa: F811
    engine, _ = postgres
    prop, owners, _, actors = estate(engine)
    if scenario != "create":
        with Session(engine) as db:
            original_share = ownership.create_share(SQLAlchemyStore(db), OwnershipShareCreate(owner_contact_id=owners[0], property_id=prop, share_percent=100), actors[0])
    first_read = threading.local()
    find = Rows.find

    def delayed(self, table, **criteria):
        result = find(self, table, **criteria)
        if table == "ownership_shares" and not getattr(first_read, "seen", False):
            first_read.seen = True
            time.sleep(.15)  # Without a shared lock both validators see the pre-write state.
        return result

    monkeypatch.setattr(Rows, "find", delayed)
    start = threading.Barrier(2)

    def change(index):
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            start.wait(timeout=10)
            try:
                if scenario == "create":
                    ownership.create_share(store, OwnershipShareCreate(owner_contact_id=owners[index+1], property_id=prop, share_percent=100), actors[index])
                elif scenario == "transfer_vs_manual" and index:
                    ownership.update_share(store, original_share.id, OwnershipShareCreate(owner_contact_id=owners[2], property_id=prop, share_percent=100), actors[index])
                else:
                    ownership.record_transfer(store, OwnershipTransferCreate(property_id=prop, from_owner_contact_id=owners[0],
                        effective_date=date(2026, 2, 1), receivers=[TransferReceiver(owner_contact_id=owners[index+1], percent=100)]), actors[index])
                return 201
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(change, range(2)))
    assert sorted(results) == [201, 409]
    with Session(engine) as db:
        rows = ownership.list_shares(SQLAlchemyStore(db), property_id=prop)
        assert sum(row.share_percent for row in rows if ownership.active_on(row, date(2026, 3, 1))) == 100


def test_concurrent_meter_readings_validate_after_the_postgres_lock(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    _, _, meter, _ = estate(engine)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        for day, value in [(1, 100), (4, 400)]:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, day), value=value))
    validate = meter_writes.validate_reading

    def delayed(*args, **kwargs):
        validate(*args, **kwargs)
        time.sleep(.15)

    monkeypatch.setattr(meter_writes, "validate_reading", delayed)
    start = threading.Barrier(2)

    def create(pair):
        day, value = pair
        with Session(engine) as db:
            start.wait(timeout=10)
            try:
                SQLAlchemyStore(db).create_standalone_meter_reading(StandaloneMeterReadingCreate(
                    meter_id=meter, reading_date=date(2026, 1, day), value=value))
                return 201
            except ValidationError:
                return 400

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(create, [(2, 300), (3, 200)])) == [201, 400]
    with Session(engine) as db:
        rows = sorted(SQLAlchemyStore(db).list_standalone_meter_readings(), key=lambda r: r.reading_date)
        assert len(rows) == 3 and all(a.value <= b.value for a, b in zip(rows, rows[1:]))


@pytest.mark.parametrize("family", ["ownership", "meter"])
def test_prepared_import_waits_for_normal_writer_and_rechecks_current_state(postgres, monkeypatch, family):  # noqa: F811
    engine, _ = postgres
    prop, owners, meter, actors = estate(engine)
    if family == "meter":
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            for day, value in [(1, 100), (4, 400)]:
                store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, day), value=value))
    ready, checked, release = threading.Event(), threading.Event(), threading.Event()
    original = ownership._check if family == "ownership" else meter_writes.validate_reading

    def pause_after_validating(*args, **kwargs):
        original(*args, **kwargs)
        checked.set()
        assert release.wait(10)

    monkeypatch.setattr(ownership if family == "ownership" else meter_writes,
                        "_check" if family == "ownership" else "validate_reading", pause_after_validating)

    def importer():
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            payload = ({"ownership_shares": [{"owner_contact_id": owners[1], "property_id": prop, "share_percent": 100}]}
                       if family == "ownership" else {"standalone_meter_readings": [
                           {"meter_id": meter, "reading_date": "2026-01-03", "value": 200}]})
            prepared = prepare_import(store, payload, replace=False)
            ready.set()
            assert checked.wait(10)
            try:
                prepared.apply()
                return "accepted"
            except SnapshotError:
                return "rejected"

    def writer():
        assert ready.wait(10)
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            if family == "ownership":
                ownership.create_share(store, OwnershipShareCreate(owner_contact_id=owners[0], property_id=prop, share_percent=100), actors[0])
            else:
                store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, 2), value=300))
        return "accepted"

    with ThreadPoolExecutor(2) as pool:
        importing, writing = pool.submit(importer), pool.submit(writer)
        try:
            assert checked.wait(10)
            time.sleep(.1)
            assert not importing.done(), "Snapshot writer crossed the normal writer's validation/commit fence"
        finally:
            release.set()
        assert writing.result(timeout=10) == "accepted"
        assert importing.result(timeout=10) == "rejected"
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        if family == "ownership":
            shares = ownership.list_shares(store, property_id=prop)
            assert len(shares) == 1 and shares[0].owner_contact_id == owners[0]
        else:
            readings = sorted(store.list_standalone_meter_readings(), key=lambda row: row.reading_date)
            assert [row.value for row in readings] == [100, 300, 400]


def test_meter_update_competes_with_a_new_day_on_the_same_key(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    _, _, meter, _ = estate(engine)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        existing = {}
        for day, value in [(1, 100), (2, 200), (4, 400)]:
            row = store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, day), value=value))
            existing[day] = row.id
    validate = meter_writes.validate_reading

    def delayed(*args, **kwargs):
        validate(*args, **kwargs)
        time.sleep(.15)

    monkeypatch.setattr(meter_writes, "validate_reading", delayed)
    start = threading.Barrier(2)

    def change(index):
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            start.wait(timeout=10)
            try:
                if index:
                    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, 3), value=250))
                else:
                    store.update_standalone_meter_reading(existing[2], StandaloneMeterReadingCreate(meter_id=meter, reading_date=date(2026, 1, 2), value=300))
                return 201
            except ValidationError:
                return 400

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(change, range(2))) == [201, 400]
    with Session(engine) as db:
        rows = sorted(SQLAlchemyStore(db).list_standalone_meter_readings(), key=lambda row: row.reading_date)
        assert all(left.value <= right.value for left, right in zip(rows, rows[1:]))
