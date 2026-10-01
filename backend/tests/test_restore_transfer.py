"""Atomic JSON restore and relationship-preservation regressions."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.db.orm_models import Base
from backend.models import ContactCreate, LeadCreate, ListingCreate, RentAdjustmentCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import admin
from backend.storage import InMemoryStore
from backend.tests.test_payments import payload, seed


@pytest.fixture(params=["memory", "sql"])
def active_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}")
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def canonical_snapshot(active_store):
    data = admin._export_store_data(active_store)
    data.pop("exported_at", None)
    for value in data.values():
        if isinstance(value, list):
            value.sort(key=lambda item: item.get("id", ""))
    return data


def build_snapshot():
    source = InMemoryStore()
    receivable = seed(source, "receivable")
    source.record_payment("receivable", receivable.id, payload())
    contract = source.get_contract(receivable.contract_id)
    source.create_rent_adjustment(
        RentAdjustmentCreate(
            contract_id=contract.id,
            adjustment_type="index",
            effective_date=date(2026, 10, 1),
            previous_rent=100.0,
            new_rent=105.0,
        )
    )
    listing = source.create_listing(ListingCreate(unit_id=contract.unit_id, title="Restore listing"))
    source.create_lead(
        LeadCreate(
            listing_id=listing.id,
            unit_id=contract.unit_id,
            full_name="Restore Lead",
        )
    )
    source.create_contact(
        ContactCreate(
            contact_type="supplier",
            company_name="Restore Supplier",
            tax_id=receivable.id,
        )
    )
    return admin._export_store_data(source), receivable.id


def seed_existing(active_store):
    receivable = seed(active_store, "receivable")
    active_store.record_payment("receivable", receivable.id, payload("10.00"))
    return receivable


def test_business_replacement_preserves_closed_owner_setup(tmp_path):
    from backend.db.auth_models import AuthSetupORM

    engine = create_engine(f"sqlite:///{tmp_path / 'setup-preservation.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AuthSetupORM(id=1))
        db.commit()
        completed = db.get(AuthSetupORM, 1).completed_at
        active = SQLAlchemyStore(db)
        seed_existing(active)
        snapshot, _ = build_snapshot()
        admin._import_store_data(snapshot, replace_existing=True, active_store=active)
    with Session(engine) as fresh:
        assert fresh.get(AuthSetupORM, 1).completed_at == completed
        assert len(SQLAlchemyStore(fresh).list_payments()) == 1
    engine.dispose()


def test_replacement_preserves_technical_lock_but_refuses_schedule_history(tmp_path):
    from backend.db.operational_models import OperationalLockORM, OperationalTickORM

    engine = create_engine(f"sqlite:///{tmp_path / 'schedule-preservation.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(OperationalLockORM(id=1, generation=17))
        db.commit()
        active = SQLAlchemyStore(db)
        snapshot, _ = build_snapshot()
        admin._import_store_data(snapshot, replace_existing=True, active_store=active)
        assert db.get(OperationalLockORM, 1).generation == 17
        db.add(OperationalTickORM(id="historic-tick", as_of=date(2026, 1, 1), result={"created": 2}))
        db.commit()
        before = canonical_snapshot(active)
        with pytest.raises(admin.TransferError, match="operational_ticks"):
            admin._import_store_data(snapshot, replace_existing=True, active_store=active)
        assert canonical_snapshot(active) == before
        assert db.get(OperationalTickORM, "historic-tick").result == {"created": 2}
    engine.dispose()


def test_restore_roundtrip_preserves_supported_relationships_and_identifiers(active_store):
    snapshot, original_receivable_id = build_snapshot()
    result = admin._restore_store_data(snapshot, active_store)
    assert result["errors"] == []

    restored = active_store.list_receivables()[0]
    assert restored.amount_paid == pytest.approx(40.10)
    assert active_store.list_payments("receivable", restored.id)[0].amount == Decimal("40.10")
    assert len(active_store.list_rent_adjustments()) == 1

    lead = active_store.list_leads()[0]
    assert active_store.get_listing(lead.listing_id).title == "Restore listing"
    assert active_store.get_unit(lead.unit_id).id == lead.unit_id

    contact = active_store.list_contacts()[0]
    assert contact.tax_id == original_receivable_id


def test_restore_rolls_back_when_middle_entity_import_fails(active_store, monkeypatch):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()

    original = type(active_store).create_tenant
    calls = []

    def fail_tenant(target, payload):
        original(target, payload)
        calls.append(True)
        raise RuntimeError("failure after tenant repository commit")

    monkeypatch.setattr(type(active_store), "create_tenant", fail_tenant)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert calls == [True]
    assert canonical_snapshot(active_store) == before
    if isinstance(active_store, SQLAlchemyStore):
        with Session(active_store.db.get_bind()) as fresh:
            assert canonical_snapshot(SQLAlchemyStore(fresh)) == before


def test_restore_rolls_back_when_payment_import_fails(active_store, monkeypatch):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()

    original = type(active_store).import_payment
    calls = []

    def fail_payment(target, payment):
        original(target, payment)
        calls.append(True)
        raise RuntimeError("failure after payment repository commit")

    monkeypatch.setattr(type(active_store), "import_payment", fail_payment)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert calls == [True]
    assert canonical_snapshot(active_store) == before
    if isinstance(active_store, SQLAlchemyStore):
        with Session(active_store.db.get_bind()) as fresh:
            assert canonical_snapshot(SQLAlchemyStore(fresh)) == before


def test_incomplete_replacement_snapshot_is_rejected_before_mutation(active_store):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    incoming.pop("rent_adjustments", None)

    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert canonical_snapshot(active_store) == before


def test_export_failure_is_not_silently_replaced_with_empty_collection(active_store, monkeypatch):
    seed_existing(active_store)

    def fail_list():
        raise RuntimeError("injected export failure")

    monkeypatch.setattr(active_store, "list_units", fail_list)
    with pytest.raises(admin.TransferError):
        admin._export_store_data(active_store)


def test_restore_endpoint_reports_conflict_without_mutating_data(active_store, monkeypatch, tmp_path):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    incoming.pop("payments", None)
    backup = tmp_path / "backup_invalid.json"
    import json
    backup.write_text(json.dumps(incoming, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(admin, "store", active_store)
    monkeypatch.setattr(admin, "_BACKUP_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        admin.restore_backup(backup.name)
    assert exc.value.status_code == 409
    assert canonical_snapshot(active_store) == before


@pytest.fixture
def http_client(active_store, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import clear_users, create_access_token, register_user
    from backend.routers import admin_runtime

    clear_users()
    owner = register_user("restore-owner", "restore@example.test", "Test Owner", "Secret123", "eigentuemer")
    reader = register_user("restore-reader", "reader@example.test", "Test Reader", "Secret123", "readonly")
    monkeypatch.setattr(admin, "store", active_store)
    monkeypatch.setattr(admin_runtime, "_BACKUP_DIR", tmp_path)
    owner_headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
    reader_headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
    with TestClient(app) as client:
        yield client, owner_headers, reader_headers, tmp_path
    clear_users()


def test_http_runtime_route_restores_real_store(active_store, http_client):
    import json
    client, headers, _, directory = http_client
    seed_existing(active_store)
    incoming, _ = build_snapshot()
    (directory / "backup_http.json").write_text(json.dumps(incoming), encoding="utf-8")
    response = client.post("/api/v1/admin/restore/backup_http.json", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    assert active_store.list_receivables()[0].amount_paid == pytest.approx(40.10)
    assert active_store.list_payments()[0].amount == Decimal("40.10")


@pytest.mark.parametrize("method", ["create_tenant", "import_payment"])
def test_http_failure_after_repository_commit_is_rolled_back(active_store, http_client, monkeypatch, method):
    import json
    client, headers, _, directory = http_client
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    (directory / "backup_late.json").write_text(json.dumps(incoming), encoding="utf-8")
    original = getattr(type(active_store), method)
    calls = []

    def fail_after_commit(target, payload):
        original(target, payload)
        calls.append(True)
        raise RuntimeError("injected failure after repository commit")

    monkeypatch.setattr(type(active_store), method, fail_after_commit)
    response = client.post("/api/v1/admin/restore/backup_late.json", headers=headers)
    assert response.status_code == 409, response.text
    assert calls == [True]
    assert canonical_snapshot(active_store) == before
    if isinstance(active_store, SQLAlchemyStore):
        with Session(active_store.db.get_bind()) as fresh:
            assert canonical_snapshot(SQLAlchemyStore(fresh)) == before


@pytest.mark.parametrize("raw", [b'[]', b'{"portfolios": [7]}', b'{"portfolios": [], "portfolios": []}', b'{"portfolios": [NaN]}'])
def test_http_invalid_import_preserves_store(active_store, http_client, raw):
    client, headers, _, _ = http_client
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    response = client.post("/api/v1/admin/import", headers=headers,
                           files={"file": ("invalid.json", raw, "application/json")})
    assert response.status_code == 400, response.text
    assert canonical_snapshot(active_store) == before


def test_http_permission_size_and_binary_restore_guards(active_store, http_client, monkeypatch):
    client, headers, reader, directory = http_client
    (directory / "backup_unsafe.db").write_bytes(b"not a database")
    url = "/api/v1/admin/restore/backup_unsafe.db"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=reader).status_code == 403
    assert client.post(url, headers=headers).status_code == 409
    monkeypatch.setattr(admin.settings, "max_upload_size_bytes", 10)
    response = client.post("/api/v1/admin/import", headers=headers,
                           files={"file": ("large.json", b"x" * 11, "application/json")})
    assert response.status_code == 413


def test_http_export_failure_does_not_create_partial_backup(active_store, http_client, monkeypatch):
    client, headers, _, directory = http_client

    def broken_export():
        raise RuntimeError("injected export failure")

    monkeypatch.setattr(active_store, "list_units", broken_export)
    assert client.get("/api/v1/admin/export", headers=headers).status_code == 500
    assert client.post("/api/v1/admin/backup", headers=headers).status_code == 500
    assert not list(directory.glob("backup_*"))


def test_document_annotations_and_invoice_links_survive_transfer(active_store):
    incoming, _ = build_snapshot()
    incoming["documents"] = [{"id": "doc", "title": "Invoice source", "file_url": "uploads/invoice.pdf",
                               "ai_summary": "Preserve annotation", "ai_confidence": 0.9}]
    incoming["invoices"] = [{"id": "invoice", "supplier": "Supplier", "invoice_date": "2026-09-01",
                             "net_amount": 100, "gross_amount": 119, "source_document_id": "doc"}]
    admin._restore_store_data(incoming, active_store)
    doc = active_store.list_documents()[0]
    assert doc.ai_summary == "Preserve annotation"
    assert active_store.list_invoices()[0].source_document_id == doc.id


def test_polymorphic_unexported_photo_prevents_destructive_replacement(active_store):
    from backend.models import EntityPhotoCreate
    item = seed_existing(active_store)
    photo = active_store.create_entity_photo(EntityPhotoCreate(entity_type="receivable", entity_id=item.id,
                                                              file_url="uploads/preserved.jpg"))
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)
    assert canonical_snapshot(active_store) == before
    assert active_store.get_entity_photo(photo.id).entity_id == item.id


def test_sql_restore_has_one_physical_commit(active_store):
    if not isinstance(active_store, SQLAlchemyStore):
        return
    seed_existing(active_store)
    incoming, _ = build_snapshot()
    committed = []
    engine = active_store.db.get_bind()

    def on_commit(connection):
        committed.append(True)

    event.listen(engine, "commit", on_commit)
    try:
        admin._restore_store_data(incoming, active_store)
    finally:
        event.remove(engine, "commit", on_commit)
    assert committed == [True]


def test_sql_export_is_a_consistent_snapshot_during_a_concurrent_commit(active_store, monkeypatch):
    if not isinstance(active_store, SQLAlchemyStore):
        return
    from sqlalchemy import update

    from backend.db.orm_models import PortfolioORM, PropertyORM

    seed_existing(active_store)
    original = SQLAlchemyStore.list_properties
    engine = active_store.db.get_bind()
    calls = []

    def concurrent_change(target):
        with Session(engine) as writer:
            writer.execute(update(PortfolioORM).values(name="Changed after export began"))
            writer.execute(update(PropertyORM).values(name="Changed after export began"))
            writer.commit()
        calls.append(True)
        return original(target)

    monkeypatch.setattr(SQLAlchemyStore, "list_properties", concurrent_change)
    snapshot = admin._export_store_data(active_store)
    assert calls == [True]
    assert snapshot["portfolios"][0]["name"] == "Test"
    assert snapshot["properties"][0]["name"] == "Haus"
    with Session(engine) as fresh:
        assert fresh.query(PortfolioORM).first().name == "Changed after export began"
