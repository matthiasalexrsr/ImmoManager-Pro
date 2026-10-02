"""Bank allocation and append-only reversal regression coverage for both stores."""

import logging.config
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError as ModelValidationError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base, PaymentReversalORM
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, BookingPatch, ReceivableCreate, TenantCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.payments import PaymentReversalCreate
from backend.storage import InMemoryStore, NotFoundError, ValidationError
from backend.tests.test_payments import payload, seed


@pytest.fixture(params=["memory", "sql"])
def active_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'bank-payments.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


def bank_booking(active, target, amount=100.30, **assignments):
    contract = active.get_contract(target.contract_id)
    prop = active.get_property(contract.property_id)
    account = active.create_account(AccountCreate(portfolio_id=prop.portfolio_id, name="Bank", account_type="bank"))
    return active.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 9, 5), amount=amount, **assignments))


def reversal(key=None, reason="Falsche Zuordnung"):
    return PaymentReversalCreate(idempotency_key=key or str(uuid4()), reversal_date=date(2026, 10, 1), reason=reason)


def linked_payload(booking, amount="40.10", key=None):
    return payload(amount, key).model_copy(update={"booking_id": booking.id})


@pytest.mark.parametrize("entity_type", ["receivable", "rent_charge"])
def test_reversal_reopens_paid_target_keeps_receipt_and_is_idempotent(active_store, entity_type):
    target = seed(active_store, entity_type)
    booking = bank_booking(active_store, target)
    receipt = active_store.record_payment(entity_type, target.id, linked_payload(booking, "100.30"))
    request = reversal()
    cancelled = active_store.reverse_payment(entity_type, target.id, receipt.id, request)
    assert active_store.reverse_payment(entity_type, target.id, receipt.id, request) == cancelled
    assert cancelled.payment_id == receipt.id and cancelled.amount == Decimal("100.30")
    with pytest.raises(ModelValidationError):
        cancelled.reason = "changed"
    updated = getattr(active_store, f"get_{entity_type}")(target.id)
    assert updated.amount_paid == 0 and updated.status == "open"
    assert active_store.get_booking(booking.id).allocated_amount == 0
    history = active_store.list_payments(entity_type, target.id)
    assert len(history) == 1 and history[0].reversal == cancelled
    with pytest.raises(ValidationError):
        active_store.reverse_payment(entity_type, target.id, receipt.id, reversal())
    with pytest.raises(ValidationError):
        active_store.reverse_payment(entity_type, target.id, receipt.id, reversal(request.idempotency_key, "anderer Grund"))
    active_store.record_payment(entity_type, target.id, linked_payload(booking, "100.30"))
    assert active_store.get_booking(booking.id).allocated_amount == 100.30


def test_reversal_of_partial_manual_receipt_retains_other_receipts(active_store):
    target = seed(active_store, "receivable")
    first = active_store.record_payment("receivable", target.id, payload())
    active_store.record_payment("receivable", target.id, payload("20.10"))
    active_store.reverse_payment("receivable", target.id, first.id, reversal())
    updated = active_store.get_receivable(target.id)
    assert updated.amount_paid == 20.10 and updated.status == "partial"
    assert len(active_store.list_payments("receivable", target.id)) == 2


def test_bank_amount_cannot_be_spent_across_both_ledgers_twice(active_store):
    first = seed(active_store, "rent_charge")
    second = active_store.create_receivable(ReceivableCreate(contract_id=first.contract_id, due_date=date(2026, 9, 1), amount_due=100.30))
    booking = bank_booking(active_store, first)
    receipt = active_store.record_payment("rent_charge", first.id, linked_payload(booking))
    active_store.record_payment("receivable", second.id, linked_payload(booking, "60.20"))
    assert active_store.get_booking(booking.id).allocated_amount == 100.30
    with pytest.raises(ValidationError):
        active_store.record_payment("receivable", second.id, linked_payload(booking, "0.01"))
    assert active_store.get_receivable(second.id).amount_paid == 60.20
    active_store.reverse_payment("rent_charge", first.id, receipt.id, reversal())
    assert active_store.get_booking(booking.id).allocated_amount == 60.20
    active_store.record_payment("receivable", second.id, linked_payload(booking, "40.10"))
    assert active_store.get_receivable(second.id).status == "paid"


@pytest.mark.parametrize("kind", ["negative", "tenant", "property", "unit", "missing"])
def test_foreign_negative_and_missing_bookings_leave_target_untouched(active_store, kind):
    target = seed(active_store, "receivable")
    assigned = {}
    if kind == "tenant":
        assigned["tenant_id"] = active_store.create_tenant(TenantCreate(full_name="Fremder Mieter")).id
    elif kind == "property":
        from backend.models import PropertyCreate
        contract = active_store.get_contract(target.contract_id)
        prop = active_store.get_property(contract.property_id)
        assigned["property_id"] = active_store.create_property(PropertyCreate(portfolio_id=prop.portfolio_id, name="Andere", property_type="residential")).id
    elif kind == "unit":
        from backend.models import UnitCreate
        contract = active_store.get_contract(target.contract_id)
        assigned["unit_id"] = active_store.create_unit(UnitCreate(property_id=contract.property_id, label="Andere", unit_type="apartment")).id
    booking = bank_booking(active_store, target, amount=-100 if kind == "negative" else 100.30, **assigned)
    request = linked_payload(booking).model_copy(update={"booking_id": "missing"}) if kind == "missing" else linked_payload(booking)
    with pytest.raises(NotFoundError if kind == "missing" else ValidationError):
        active_store.record_payment("receivable", target.id, request)
    assert active_store.get_receivable(target.id).amount_paid == 0
    assert active_store.get_booking(booking.id).allocated_amount == 0
    assert active_store.list_payments() == []


def test_replay_includes_bank_reference_and_reversal_key_cannot_cross_receipts(active_store):
    target = seed(active_store, "receivable")
    booking = bank_booking(active_store, target)
    request = linked_payload(booking)
    first = active_store.record_payment("receivable", target.id, request)
    assert active_store.record_payment("receivable", target.id, request).id == first.id
    with pytest.raises(ValidationError):
        active_store.record_payment("receivable", target.id, request.model_copy(update={"booking_id": None}))
    second = active_store.record_payment("receivable", target.id, payload("20.10"))
    reverse_request = reversal()
    active_store.reverse_payment("receivable", target.id, first.id, reverse_request)
    with pytest.raises(ValidationError):
        active_store.reverse_payment("receivable", target.id, second.id, reverse_request)
    with pytest.raises(NotFoundError):
        active_store.reverse_payment("receivable", target.id, "missing", reversal())


@pytest.mark.parametrize("reversed_receipt", [False, True])
def test_history_guards_bookings_targets_and_ancestors(active_store, reversed_receipt):
    target = seed(active_store, "rent_charge")
    booking = bank_booking(active_store, target)
    receipt = active_store.record_payment("rent_charge", target.id, linked_payload(booking))
    if reversed_receipt:
        active_store.reverse_payment("rent_charge", target.id, receipt.id, reversal())
    contract = active_store.get_contract(target.contract_id)
    prop = active_store.get_property(contract.property_id)
    operations = [
        ("booking", booking.id), ("rent_charge", target.id), ("contract", contract.id),
        ("tenant", contract.tenant_id), ("unit", contract.unit_id), ("property", contract.property_id),
        ("account", booking.account_id), ("portfolio", prop.portfolio_id),
    ]
    for entity, identity in operations:
        with pytest.raises(ValidationError):
            getattr(active_store, f"delete_{entity}")(identity)
    with pytest.raises(ValidationError):
        active_store._patch_entity("booking", booking.id, BookingPatch(amount=500))
    with pytest.raises(ValidationError):
        active_store.update_booking(booking.id, BookingCreate(**{**booking.model_dump(include=set(BookingCreate.model_fields)), "amount": 500}))
    active_store._patch_entity("booking", booking.id, BookingPatch(payment_text="Belegnotiz"))
    assert active_store.get_booking(booking.id).allocated_amount == (0 if reversed_receipt else 40.10)
    assert len(active_store.list_payments()) == 1


def test_receivable_history_cannot_be_deleted(active_store):
    target = seed(active_store, "receivable")
    active_store.record_payment("receivable", target.id, payload())
    with pytest.raises(ValidationError):
        active_store.delete_receivable(target.id)


def test_bank_receipt_restore_preserves_reversal_and_does_not_double_increment_balances(active_store):
    target = seed(active_store, "receivable")
    booking = bank_booking(active_store, target)
    first = active_store.record_payment("receivable", target.id, linked_payload(booking))
    active_store.reverse_payment("receivable", target.id, first.id, reversal())
    second = active_store.record_payment("receivable", target.id, linked_payload(booking, "20.10"))
    receipts = active_store.list_payments()
    for item in receipts:
        assert active_store.import_payment(item).id == item.id
    assert active_store.get_receivable(target.id).amount_paid == 20.10
    assert active_store.get_booking(booking.id).allocated_amount == 20.10
    # Restore into new parent objects as an importer does; receipt IDs remain stable.
    new_target = active_store.create_receivable(ReceivableCreate(contract_id=target.contract_id, due_date=date(2026, 10, 1), amount_due=100.30))
    new_booking = bank_booking(active_store, new_target)
    for item in receipts:
        copied = item.model_copy(update={"id": str(uuid4()), "entity_id": new_target.id, "booking_id": new_booking.id, "idempotency_key": str(uuid4())})
        if copied.reversal:
            copied = copied.model_copy(update={"reversal": copied.reversal.model_copy(update={"id": str(uuid4()), "payment_id": copied.id, "idempotency_key": str(uuid4())})})
        active_store.import_payment(copied)
    assert active_store.get_receivable(new_target.id).amount_paid == 0
    assert active_store.get_booking(new_booking.id).allocated_amount == 20.10
    assert second.amount == Decimal("20.10")


@pytest.mark.parametrize("operation", ["record", "reverse"])
def test_sql_commit_failure_rolls_back_bank_target_and_receipt(tmp_path, monkeypatch, operation):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback-bank.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        target = seed(active, "receivable")
        booking = bank_booking(active, target)
        original = active.record_payment("receivable", target.id, linked_payload(booking)) if operation == "reverse" else None
        def fail_commit():
            raise RuntimeError("commit unavailable")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError):
            if operation == "reverse":
                active.reverse_payment("receivable", target.id, original.id, reversal())
            else:
                active.record_payment("receivable", target.id, linked_payload(booking))
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        expected = 40.10 if operation == "reverse" else 0
        assert active.get_receivable(target.id).amount_paid == expected
        assert active.get_booking(booking.id).allocated_amount == expected
        assert db.scalar(select(PaymentReversalORM)) is None
        assert len(active.list_payments()) == (1 if operation == "reverse" else 0)
    engine.dispose()


def test_parallel_sql_sessions_cannot_allocate_one_bank_receipt_twice(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'parallel.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        first = seed(active, "rent_charge")
        second = active.create_receivable(ReceivableCreate(contract_id=first.contract_id, due_date=date(2026, 9, 1), amount_due=100.30))
        booking = bank_booking(active, first, amount=40.10)
    barrier = Barrier(2)
    def allocate(entity, identity):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                SQLAlchemyStore(db).record_payment(entity, identity, linked_payload(booking))
                return "recorded"
            except ValidationError:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(allocate, "rent_charge", first.id), executor.submit(allocate, "receivable", second.id)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == ["conflict", "recorded"]
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        assert active.get_booking(booking.id).allocated_amount == 40.10
        assert len(active.list_payments()) == 1
        assert active.get_rent_charge(first.id).amount_paid + active.get_receivable(second.id).amount_paid == 40.10
    engine.dispose()


def test_settlement_counts_exact_contract_allocations_once_and_ignores_reversal(monkeypatch, active_store):
    from backend.routers import contracts
    monkeypatch.setattr(contracts, "store", active_store)
    target = seed(active_store, "rent_charge")
    contract = active_store.get_contract(target.contract_id)
    booking = bank_booking(active_store, target, tenant_id=contract.tenant_id)
    receipt = active_store.record_payment("rent_charge", target.id, linked_payload(booking))
    _, lines = contracts.contract_ledger_inputs(active_store, contract, date(2026, 10, 2))
    assert sum((line.amount for line in lines), Decimal("0")) == Decimal("40.10")
    active_store.reverse_payment("rent_charge", target.id, receipt.id, reversal())
    assert contracts.contract_ledger_inputs(active_store, contract, date(2026, 10, 2))[1] == []
    manual = active_store.record_payment("rent_charge", target.id, payload("10.10"))
    assert contracts.contract_ledger_inputs(active_store, contract, date(2026, 10, 2))[1][0].amount == Decimal("10.10")
    active_store.reverse_payment("rent_charge", target.id, manual.id, reversal())
    assert contracts.contract_ledger_inputs(active_store, contract, date(2026, 10, 2))[1] == []
    bank_booking(active_store, target, amount=30.30, tenant_id=contract.tenant_id, unit_id=contract.unit_id)
    # A tenant/unit label is not an allocation; unallocated bank rows never
    # manufacture a rent receipt, including after a reversal.
    assert contracts.contract_ledger_inputs(active_store, contract, date(2026, 10, 2))[1] == []


def test_linked_bank_payment_is_not_reused_for_another_contract_of_the_same_tenant(monkeypatch, active_store):
    from backend.models import ContractCreate, UnitCreate
    from backend.routers import contracts
    monkeypatch.setattr(contracts, "store", active_store)
    target = seed(active_store, "rent_charge")
    original = active_store.get_contract(target.contract_id)
    unit = active_store.create_unit(UnitCreate(property_id=original.property_id, label="WE2", unit_type="apartment"))
    other = active_store.create_contract(ContractCreate(contract_number="P-2", property_id=original.property_id,
                                                        unit_id=unit.id, tenant_id=original.tenant_id, start_date=date(2026, 1, 1)))
    booking = bank_booking(active_store, target, tenant_id=original.tenant_id)
    active_store.record_payment("rent_charge", target.id, linked_payload(booking))
    assert contracts.contract_ledger_inputs(active_store, other, date(2026, 10, 2))[1] == []
    assert contracts.contract_ledger_inputs(active_store, original, date(2026, 10, 2))[1][0].amount == Decimal("40.10")


def test_existing_sqlite_bank_receipt_upgrade_is_repeatable_and_preserves_history(tmp_path, monkeypatch):
    from backend.db import session
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-banks.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE receivables (id TEXT PRIMARY KEY, amount_due NUMERIC, status TEXT)"))
        connection.execute(text("CREATE TABLE bookings (id TEXT PRIMARY KEY, amount NUMERIC)"))
        connection.execute(text("CREATE TABLE payments (id TEXT PRIMARY KEY, receivable_id TEXT, rent_charge_id TEXT, amount NUMERIC)"))
        connection.execute(text("INSERT INTO receivables VALUES ('original', 50, 'paid')"))
        connection.execute(text("INSERT INTO bookings VALUES ('bank', 50)"))
        connection.execute(text("INSERT INTO payments VALUES ('receipt', 'original', NULL, 50)"))
    monkeypatch.setattr(session, "engine", engine)
    session.create_tables()
    session.create_tables()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT amount_paid FROM receivables")).scalar() == 50
        assert connection.execute(text("SELECT allocated_amount FROM bookings")).scalar() == 0
        assert connection.execute(text("SELECT booking_id FROM payments")).scalar() is None
        assert "payment_reversals" in inspect(connection).get_table_names()
        with pytest.raises(Exception, match="Payment history must be preserved"):
            connection.execute(text("DELETE FROM receivables WHERE id='original'"))
    engine.dispose()


def test_alembic_fresh_upgrade_and_downgrade(tmp_path, monkeypatch):
    # CLI logging configuration must not disable application loggers in this process.
    monkeypatch.setattr(logging.config, "fileConfig", lambda *args, **kwargs: None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'alembic-bank.db'}")
    config = Config("alembic.ini")
    # Exercise the payment migration itself, independently of later feature
    # revisions that preserve security/document history through full recovery.
    command.upgrade(config, "d8e9f0a1b2c3")
    engine = create_engine(f"sqlite:///{tmp_path / 'alembic-bank.db'}")
    assert "payment_reversals" in inspect(engine).get_table_names()
    assert "allocated_amount" in {column["name"] for column in inspect(engine).get_columns("bookings")}
    assert all(fk["options"].get("ondelete") == "RESTRICT" for fk in inspect(engine).get_foreign_keys("payments"))
    command.downgrade(config, "a7b8c9d0e1f2")
    assert "payment_reversals" not in inspect(engine).get_table_names()
    command.upgrade(config, "d8e9f0a1b2c3")
    engine.dispose()


@pytest.mark.parametrize("entity_type,path", [("receivable", "receivables"), ("rent_charge", "rent-charges")])
def test_reversal_http_contract_rbac_and_conflicts(entity_type, path):
    store.clear_all()
    clear_users()
    try:
        target = seed(store, entity_type)
        receipt = store.record_payment(entity_type, target.id, payload())
        owner = register_user("reverseowner", "reverse-owner@example.com", "Owner", "Secret123", "eigentuemer")
        reader = register_user("reversereader", "reverse-reader@example.com", "Reader", "Secret123", "readonly")
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        reader_headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        url = f"/api/v1/{path}/{target.id}/payments/{receipt.id}/reversal"
        data = reversal().model_dump(mode="json")
        with TestClient(app) as client:
            assert client.post(url, json=data).status_code == 401
            assert client.post(url, json=data, headers=reader_headers).status_code == 403
            assert client.post(url, json={**data, "reason": "  "}, headers=headers).status_code == 422
            response = client.post(url, json=data, headers=headers)
            assert response.status_code == 201
            assert response.json()["payment_id"] == receipt.id
            assert client.post(url, json=data, headers=headers).json() == response.json()
            assert client.post(url, json=reversal().model_dump(mode="json"), headers=headers).status_code == 409
            assert client.post(url.replace(receipt.id, "missing"), json=data, headers=headers).status_code == 404
            history = client.get(f"/api/v1/{path}/{target.id}/payments", headers=reader_headers).json()
            assert len(history) == 1 and history[0]["reversal"]["reason"] == "Falsche Zuordnung"
    finally:
        store.clear_all()
        clear_users()


def test_reversal_reason_is_required():
    with pytest.raises(ModelValidationError):
        reversal(reason="  ")
