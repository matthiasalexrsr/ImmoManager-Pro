"""Payment allocation, persistence, permissions and restore regression tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base, PaymentORM
from backend.dependencies import store
from backend.models import (
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    RentChargeCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers.admin import _export_store_data, _import_store_data
from backend.services.payments import PaymentCreate
from backend.services.report_service import compute_receivables_aging
from backend.storage import InMemoryStore, ValidationError


def seed(active_store, entity_type):
    portfolio = active_store.create_portfolio(PortfolioCreate(name="Test"))
    prop = active_store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    unit = active_store.create_unit(UnitCreate(property_id=prop.id, label="WE1", unit_type="apartment"))
    tenant = active_store.create_tenant(TenantCreate(full_name="Test Mieter"))
    contract = active_store.create_contract(ContractCreate(contract_number="P-1", property_id=prop.id, unit_id=unit.id,
                                                        tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    if entity_type == "receivable":
        return active_store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 9, 3), amount_due=100.30))
    return active_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2026-09", cold_rent=100.10, service_charge=.20))


def payload(amount="40.10", key=None):
    return PaymentCreate(idempotency_key=key or str(uuid4()), amount=Decimal(amount), payment_date=date(2026, 9, 5), note="Teilzahlung")


@pytest.fixture(params=["memory", "sql"])
def payment_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'payments.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


@pytest.mark.parametrize("entity_type", ["receivable", "rent_charge"])
def test_partial_then_full_payment_and_idempotent_retry(payment_store, entity_type):
    target = seed(payment_store, entity_type)
    first = payload()
    receipt = payment_store.record_payment(entity_type, target.id, first)
    assert payment_store.record_payment(entity_type, target.id, first).id == receipt.id
    updated = getattr(payment_store, f"get_{entity_type}")(target.id)
    assert updated.amount_paid == 40.10
    assert updated.status == "partial"
    assert payment_store.list_payments(entity_type, target.id)[0].note == "Teilzahlung"
    payment_store.record_payment(entity_type, target.id, payload("60.20"))
    updated = getattr(payment_store, f"get_{entity_type}")(target.id)
    assert updated.amount_paid == 100.30
    assert updated.status == "paid"
    assert len(payment_store.list_payments(entity_type, target.id)) == 2


@pytest.mark.parametrize("entity_type", ["receivable", "rent_charge"])
def test_overpayment_and_conflicting_replay_do_not_change_balance(payment_store, entity_type):
    target = seed(payment_store, entity_type)
    first = payload()
    payment_store.record_payment(entity_type, target.id, first)
    for invalid in [payload("60.21"), payload("41.00", first.idempotency_key)]:
        with pytest.raises(ValidationError):
            payment_store.record_payment(entity_type, target.id, invalid)
    assert getattr(payment_store, f"get_{entity_type}")(target.id).amount_paid == 40.10
    assert len(payment_store.list_payments(entity_type, target.id)) == 1


def test_partial_receivable_is_included_in_aging(payment_store):
    target = seed(payment_store, "receivable")
    payment_store.record_payment("receivable", target.id, payload())
    report = compute_receivables_aging(receivables=payment_store.list_receivables(), today=date(2026, 10, 1))
    assert report["openTotal"] == pytest.approx(60.20)
    assert report["buckets"]["days1to30"] == pytest.approx(60.20)


def test_receivable_edit_preserves_paid_balance(payment_store):
    target = seed(payment_store, "receivable")
    payment_store.record_payment("receivable", target.id, payload())
    payment_store.update_receivable(target.id, ReceivableCreate(contract_id=target.contract_id, due_date=target.due_date,
                                                              amount_due=100.30, status="partial"))
    assert payment_store.get_receivable(target.id).amount_paid == 40.10


def test_sql_transaction_rolls_back_receipt_and_balance(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active_store = SQLAlchemyStore(db)
        target = seed(active_store, "receivable")
        def fail_commit():
            raise RuntimeError("Simulated commit failure")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError):
            active_store.record_payment("receivable", target.id, payload())
    with Session(engine) as db:
        assert SQLAlchemyStore(db).get_receivable(target.id).amount_paid == 0
        assert db.scalar(select(PaymentORM)) is None
    engine.dispose()


def test_payment_survives_new_sql_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'persist.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active_store = SQLAlchemyStore(db)
        target = seed(active_store, "rent_charge")
        active_store.record_payment("rent_charge", target.id, payload())
    with Session(engine) as db:
        active_store = SQLAlchemyStore(db)
        assert active_store.get_rent_charge(target.id).amount_paid == 40.10
        assert active_store.list_payments("rent_charge", target.id)[0].payment_date == date(2026, 9, 5)
    engine.dispose()


def test_existing_sqlite_database_gets_additive_upgrade(tmp_path, monkeypatch):
    from backend.db import session
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE receivables (id TEXT PRIMARY KEY, amount_due NUMERIC, status TEXT)"))
        connection.execute(text("INSERT INTO receivables VALUES ('paid', 150, 'paid'), ('open', 200, 'open')"))
    monkeypatch.setattr(session, "engine", engine)
    session.create_tables()
    session.create_tables()
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT id, amount_paid FROM receivables")).all()) == {"paid": 150, "open": 0}
    engine.dispose()


def test_export_restore_preserves_relationships_balance_and_receipts():
    store.clear_all()
    try:
        target = seed(store, "receivable")
        store.record_payment("receivable", target.id, payload())
        before_revisions = {}
        if hasattr(store, "db"):
            from backend.db.rent_batch_models import RentSourceRevisionORM
            before_revisions = {(row.entity_type, row.entity_id): row.revision for row in store.db.scalars(
                select(RentSourceRevisionORM).where(RentSourceRevisionORM.entity_id == target.contract_id))}
            assert before_revisions, "Current SQL startup installs actual source-revision triggers"
        snapshot = _export_store_data()
        result = _import_store_data(snapshot, replace_existing=True)
        assert result["errors"] == []
        restored = store.list_receivables()[0]
        assert restored.id != target.id
        assert store.get_contract(restored.contract_id).contract_number == "P-1"
        assert restored.amount_paid == 40.10
        assert store.list_payments("receivable", restored.id)[0].amount == Decimal("40.10")
        if before_revisions:
            after_revisions = {(row.entity_type, row.entity_id): row.revision for row in store.db.scalars(
                select(RentSourceRevisionORM).where(RentSourceRevisionORM.entity_id == target.contract_id))}
            assert all(after_revisions[key] >= revision for key, revision in before_revisions.items())
    finally:
        store.clear_all()


def test_partial_restore_refuses_real_saved_rental_snapshots_and_preserves_source_counters(tmp_path):
    from backend.db.rent_batch_models import RentBatchContractORM, RentSourceRevisionORM
    from backend.db.rent_batch_schema import ensure_rent_batch_schema
    from backend.services.data_transfer import TransferError
    from backend.services.rent_batch import BatchAdvance, BatchCreate, advance_batch, create_batch, get_batch

    engine = create_engine(f"sqlite:///{tmp_path / 'saved-rent-restore.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_rent_batch_schema(connection)
    try:
        with Session(engine) as db:
            active = SQLAlchemyStore(db)
            target = seed(active, "rent_charge")
            snapshot = _export_store_data(active)
            job = create_batch(active, BatchCreate(start_month="2026-10", end_month="2026-12",
                contract_ids=[target.contract_id], idempotency_key="protected-source"))
            for _ in range(10):
                if job["state"] == "ready":
                    break
                job = advance_batch(active, job["id"], BatchAdvance(cursor=job["cursor"], budget=2))
            assert job["state"] == "ready"
            assert db.scalar(select(RentBatchContractORM.contract_id).where(RentBatchContractORM.batch_id == job["id"])) == target.contract_id
            db.expire_all()
            original = active.get_rent_charge(target.id)
            counters = [(row.entity_type, row.entity_id, row.revision) for row in db.scalars(select(RentSourceRevisionORM))]
            with pytest.raises(TransferError, match="rent_generation_"):
                _import_store_data(snapshot, replace_existing=True, active_store=active)
            assert active.get_rent_charge(target.id) == original
            assert get_batch(active, job["id"])["plan_hash"] == job["plan_hash"]
            assert [(row.entity_type, row.entity_id, row.revision) for row in db.scalars(select(RentSourceRevisionORM))] == counters
    finally:
        engine.dispose()


def test_recorded_rent_payment_reaches_contract_settlement():
    from backend.services.rent_ledger import contract_ledger_inputs
    store.clear_all()
    try:
        target = seed(store, "rent_charge")
        store.record_payment("rent_charge", target.id, payload())
        _, payments = contract_ledger_inputs(store, store.get_contract(target.contract_id), date(2026, 9, 30))
        assert len(payments) == 1
        assert payments[0].amount == Decimal("40.10")
        assert payments[0].booking_date == date(2026, 9, 5)
    finally:
        store.clear_all()


@pytest.mark.parametrize("entity_type,path", [("receivable", "receivables"), ("rent_charge", "rent-charges")])
def test_payment_http_contract_and_permissions(entity_type, path):
    store.clear_all()
    clear_users()
    try:
        target = seed(store, entity_type)
        owner = register_user("payowner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
        reader = register_user("payreader", "reader@example.com", "Reader", "Secret123", "readonly")
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        reader_headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        url = f"/api/v1/{path}/{target.id}/payments"
        data = payload().model_dump(mode="json")
        with TestClient(app) as client:
            assert client.post(url, json=data).status_code == 401
            assert client.post(url, json=data, headers=reader_headers).status_code == 403
            assert client.post(url, json={**data, "amount": -1}, headers=headers).status_code == 422
            assert client.post(url, json={**data, "amount": "0.001"}, headers=headers).status_code == 422
            assert client.post(url, json=data, headers=headers).status_code == 201
            assert client.post(url, json=data, headers=headers).status_code == 201
            assert len(client.get(url, headers=reader_headers).json()) == 1
            assert client.post(url, json=payload("100").model_dump(mode="json"), headers=headers).status_code == 409
            assert client.get(f"/api/v1/{path}/missing/payments", headers=headers).status_code == 404
    finally:
        store.clear_all()
        clear_users()
