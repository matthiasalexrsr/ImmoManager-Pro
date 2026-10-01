"""Regression tests for receipt-backed financial balance invariants."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base
from backend.dependencies import store
from backend.models import ReceivableCreate, RentChargeCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.storage import InMemoryStore, ValidationError
from backend.tests.test_payments import payload, seed


@pytest.fixture(params=["memory", "sql"])
def financial_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'financial-integrity.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def receivable_update(target, amount_due, status="open"):
    return ReceivableCreate(
        contract_id=target.contract_id,
        due_date=target.due_date,
        amount_due=amount_due,
        dunning_level=target.dunning_level,
        status=status,
        statement_id=target.statement_id,
    )


def charge_update(target, **changes):
    values = target.model_dump(include=set(RentChargeCreate.model_fields))
    values.update(changes)
    return RentChargeCreate(**values)


def test_receivable_total_cannot_fall_below_recorded_payments(financial_store):
    target = seed(financial_store, "receivable")
    financial_store.record_payment("receivable", target.id, payload())

    with pytest.raises(ValidationError):
        financial_store.update_receivable(target.id, receivable_update(target, 1.00, "partial"))

    unchanged = financial_store.get_receivable(target.id)
    assert unchanged.amount_due == pytest.approx(100.30)
    assert unchanged.amount_paid == pytest.approx(40.10)
    assert unchanged.status == "partial"
    assert len(financial_store.list_payments("receivable", target.id)) == 1


def test_receivable_total_edits_reconcile_payment_status(financial_store):
    target = seed(financial_store, "receivable")
    financial_store.record_payment("receivable", target.id, payload())

    reduced = financial_store.update_receivable(target.id, receivable_update(target, 50.00, "open"))
    assert reduced.amount_paid == pytest.approx(40.10)
    assert reduced.status == "partial"

    exactly_paid = financial_store.update_receivable(target.id, receivable_update(target, 40.10, "open"))
    assert exactly_paid.amount_paid == pytest.approx(40.10)
    assert exactly_paid.status == "paid"

    increased = financial_store.update_receivable(target.id, receivable_update(target, 120.00, "paid"))
    assert increased.amount_paid == pytest.approx(40.10)
    assert increased.status == "partial"


def test_rent_charge_edit_cannot_overwrite_receipt_backed_balance(financial_store):
    target = seed(financial_store, "rent_charge")
    financial_store.record_payment("rent_charge", target.id, payload())

    with pytest.raises(ValidationError):
        financial_store.update_rent_charge(target.id, charge_update(target, amount_paid=0, status="open"))

    unchanged = financial_store.get_rent_charge(target.id)
    assert unchanged.amount_paid == pytest.approx(40.10)
    assert unchanged.status == "partial"
    assert sum(p.amount for p in financial_store.list_payments("rent_charge", target.id)) == Decimal("40.10")


def test_rent_charge_total_edits_reconcile_payment_status(financial_store):
    target = seed(financial_store, "rent_charge")
    financial_store.record_payment("rent_charge", target.id, payload())

    changed = financial_store.update_rent_charge(
        target.id,
        charge_update(target, cold_rent=120.10, amount_paid=40.10, status="paid"),
    )
    assert changed.amount_paid == pytest.approx(40.10)
    assert changed.status == "partial"

    with pytest.raises(ValidationError):
        financial_store.update_rent_charge(
            target.id,
            charge_update(target, cold_rent=10.00, service_charge=0, amount_paid=40.10),
        )


@pytest.mark.parametrize(
    "entity_type,path,bad_patch",
    [
        ("receivable", "receivables", {"amount_due": 1.0}),
        ("rent_charge", "rent-charges", {"amount_paid": 0, "status": "open"}),
    ],
)
def test_http_patch_rejects_edits_that_break_payment_invariants(entity_type, path, bad_patch):
    store.clear_all()
    clear_users()
    try:
        target = seed(store, entity_type)
        store.record_payment(entity_type, target.id, payload())
        owner = register_user("integrityowner", "integrity@example.com", "Owner", "Secret123", "eigentuemer")
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        with TestClient(app) as client:
            response = client.patch(f"/api/v1/{path}/{target.id}", json=bad_patch, headers=headers)
            assert response.status_code == 409
        unchanged = getattr(store, f"get_{entity_type}")(target.id)
        assert unchanged.amount_paid == pytest.approx(40.10)
        assert len(store.list_payments(entity_type, target.id)) == 1
    finally:
        store.clear_all()
        clear_users()


def test_http_patch_cannot_mark_unpaid_receivable_paid_without_receipt():
    store.clear_all()
    clear_users()
    try:
        target = seed(store, "receivable")
        owner = register_user("statusowner", "status@example.com", "Owner", "Secret123", "eigentuemer")
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/receivables/{target.id}",
                json={"status": "paid"},
                headers=headers,
            )
            assert response.status_code == 409
        unchanged = store.get_receivable(target.id)
        assert unchanged.amount_paid == 0
        assert unchanged.status == "open"
    finally:
        store.clear_all()
        clear_users()
