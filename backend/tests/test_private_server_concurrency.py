"""Dedicated PostgreSQL service only: TEST_SERVER_DATABASE_URL activates tests.

Every test owns a random schema; public/application schemas are never modified.
Independent engines/sessions and generation processes exercise database locks,
receipt budgets and permanent uniqueness rather than a shared Python lock.
"""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.auth_models import AuthSetupORM
from backend.db.orm_models import Base, PaymentORM, PaymentReversalORM, RentChargeORM
from backend.models import ReceivableCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.rent_ledger import RentGenerationRequest, generate_rent_charges
from backend.storage import ValidationError
from backend.tests.test_bank_payments import bank_booking, linked_payload, reversal
from backend.tests.test_payments import seed


@pytest.fixture
def postgres_database():
    raw_url = os.environ.get("TEST_SERVER_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set TEST_SERVER_DATABASE_URL to a dedicated disposable PostgreSQL service")
    if make_url(raw_url).get_backend_name() != "postgresql":
        pytest.fail("Private-server concurrency tests require PostgreSQL")
    schema = "immo_private_" + uuid4().hex
    admin_engine = create_engine(raw_url, hide_parameters=True, pool_pre_ping=True)
    engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(raw_url, hide_parameters=True, pool_pre_ping=True,
                               connect_args={"options": f"-csearch_path={schema}"})
        Base.metadata.create_all(engine)
        yield engine, sessionmaker(bind=engine), raw_url, schema
    finally:
        if engine:
            engine.dispose()
        # Exact generated identifier, never an inherited database/table name.
        assert schema.startswith("immo_private_") and len(schema) == 45
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _parallel(operation, arguments):
    barrier = Barrier(len(arguments))
    def run(argument):
        barrier.wait(timeout=15)
        return operation(argument)
    with ThreadPoolExecutor(max_workers=len(arguments)) as pool:
        return list(pool.map(run, arguments))


def test_pg_independent_sessions_read_multiple_users_and_release_connections(postgres_database, monkeypatch):
    engine, factory, _, _ = postgres_database
    store = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    roles = ["eigentuemer", "verwalter", "buchhaltung", "readonly"]
    users = [auth.register_user(f"user{index}", f"user{index}@example.com", "Synthetic", "Strong123", role) for index, role in enumerate(roles)]
    def read_user(user):
        for _ in range(5):
            assert auth.authenticate_user(user.username, "Strong123")["id"] == user.id
            assert store.get_by_id(user.id)["role"] == user.role
        return user.id
    assert set(_parallel(read_user, users)) == {user.id for user in users}
    assert engine.pool.checkedout() == 0


def test_pg_setup_marker_contends_across_user_store_instances(postgres_database, monkeypatch):
    engine, factory, _, _ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    payloads = [auth._new_user_data(f"owner{index}", f"owner{index}@example.com", "Synthetic", "a synthetic private passphrase", "eigentuemer", server_password=True) for index in range(2)]
    def create(data):
        try:
            auth.SQLUserStore(factory).create_initial_owner(data)
            return 201
        except HTTPException as error:
            return error.status_code
    assert sorted(_parallel(create, payloads)) == [201, 409]
    assert len(auth.SQLUserStore(factory).list_all()) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthSetupORM)) == 1
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("action", ["disable", "downgrade", "delete"])
def test_pg_final_two_owners_are_serialized_across_independent_store_instances(postgres_database, monkeypatch, action):
    engine, factory, _, _ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    users = [auth.register_user(f"owner{index}", f"owner{index}@example.com", "Synthetic", "Strong123", "eigentuemer") for index in range(2)]
    def remove(user):
        store = auth.SQLUserStore(factory)
        try:
            if action == "delete":
                store.delete(user.id)
            else:
                store.update(user.id, {"is_active": False} if action == "disable" else {"role": "readonly"})
            return 200
        except HTTPException as error:
            return error.status_code
    assert sorted(_parallel(remove, users)) == [200, 409]
    assert sum(user["is_active"] and user["role"] == "eigentuemer" for user in auth.SQLUserStore(factory).list_all()) == 1
    assert engine.pool.checkedout() == 0


def test_pg_one_bank_budget_cannot_be_allocated_twice_across_ledgers_then_reversal_releases_it(postgres_database):
    engine, factory, _, _ = postgres_database
    with factory() as db:
        store = SQLAlchemyStore(db)
        first = seed(store, "rent_charge")
        second = store.create_receivable(ReceivableCreate(contract_id=first.contract_id, due_date=date(2026, 9, 1), amount_due=100.30))
        booking = bank_booking(store, first)
    def allocate(target):
        with factory() as db:
            try:
                receipt = SQLAlchemyStore(db).record_payment(target[0], target[1], linked_payload(booking, "60.20"))
                return receipt
            except ValidationError:
                return None
    results = _parallel(allocate, [("rent_charge", first.id), ("receivable", second.id)])
    receipts = [result for result in results if result is not None]
    assert len(receipts) == 1
    receipt = receipts[0]
    with factory() as db:
        store = SQLAlchemyStore(db)
        assert Decimal(str(store.get_booking(booking.id).allocated_amount)) == Decimal("60.20")
        assert Decimal(str(store.get_rent_charge(first.id).amount_paid)) + Decimal(str(store.get_receivable(second.id).amount_paid)) == Decimal("60.20")
    request = reversal()
    def reverse(_):
        with factory() as db:
            return SQLAlchemyStore(db).reverse_payment(receipt.entity_type, receipt.entity_id, receipt.id, request)
    reversals = _parallel(reverse, range(2))
    assert reversals[0].id == reversals[1].id
    with factory() as db:
        store = SQLAlchemyStore(db)
        assert store.get_booking(booking.id).allocated_amount == 0
        assert db.scalar(select(func.count()).select_from(PaymentORM)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentReversalORM)) == 1
        assert store.list_payments()[0].reversal.id == reversals[0].id
        target = ("receivable", second.id) if receipt.entity_type == "rent_charge" else ("rent_charge", first.id)
        store.record_payment(*target, linked_payload(booking, "100.30"))
        assert store.get_booking(booking.id).allocated_amount == 100.30
    assert engine.pool.checkedout() == 0


def _generate_in_process(raw_url, schema, contract_id, barrier, output):
    """Spawned process has its own generation lock, engine and SQL transaction."""
    engine = create_engine(raw_url, hide_parameters=True, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with Session(engine) as db:
            barrier.wait(timeout=20)
            result = generate_rent_charges(SQLAlchemyStore(db), RentGenerationRequest(start_month="2026-10", end_month="2026-10", contract_ids=[contract_id]))
            output.put({"created_count": result["created_count"], "skipped_count": result["skipped_count"]})
    except Exception as error:
        output.put({"error_type": type(error).__name__})
    finally:
        engine.dispose()


def test_pg_monthly_generation_is_idempotent_across_processes(postgres_database):
    engine, factory, raw_url, schema = postgres_database
    with factory() as db:
        target = seed(SQLAlchemyStore(db), "rent_charge")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    output = context.Queue()
    processes = [context.Process(target=_generate_in_process, args=(raw_url, schema, target.contract_id, barrier, output)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        results = [output.get(timeout=40) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(result.get("created_count", -1) for result in results) == [0, 1], results
        assert sorted(result["skipped_count"] for result in results) == [0, 1]
        with factory() as db:
            rows = db.scalars(select(RentChargeORM).where(RentChargeORM.contract_id == target.contract_id, RentChargeORM.month == "2026-10")).all()
            assert len(rows) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)
        output.close()
        output.join_thread()
    assert engine.pool.checkedout() == 0
