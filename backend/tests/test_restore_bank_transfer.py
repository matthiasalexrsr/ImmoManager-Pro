"""Transfers preserve bank receipts/reversals without applying payments twice."""

from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import admin
from backend.storage import InMemoryStore
from backend.tests import test_restore_transfer as support
from backend.tests.test_bank_payments import bank_booking, linked_payload, reversal
from backend.tests.test_payments import payload, seed

active_store = support.active_store
http_client = support.http_client
canonical_snapshot = support.canonical_snapshot
seed_existing = support.seed_existing


def bank_snapshot(entity_type="receivable"):
    source = InMemoryStore()
    target = seed(source, entity_type)
    booking = bank_booking(source, target)
    cancelled = source.record_payment(entity_type, target.id, linked_payload(booking))
    source.reverse_payment(entity_type, target.id, cancelled.id, reversal())
    source.record_payment(entity_type, target.id, linked_payload(booking, "20.10"))
    source.record_payment(entity_type, target.id, payload("10.00"))
    snapshot = admin._export_store_data(source)
    snapshot["bookings"][0]["allocated_amount"] = 999999  # Never trust this cached counter.
    return snapshot


@pytest.mark.parametrize("entity_type", ["receivable", "rent_charge"])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_bank_and_reversal_roundtrip(active_store, entity_type, reverse_order):
    seed_existing(active_store)  # Existing protected receipt history must be replaced atomically.
    incoming = bank_snapshot(entity_type)
    if reverse_order:
        incoming["payments"].reverse()
    originals = {item["id"]: item for item in incoming["payments"]}
    admin._restore_store_data(incoming, active_store)
    target = getattr(active_store, f"list_{'receivables' if entity_type == 'receivable' else 'rent_charges'}")()[0]
    assert target.amount_paid == pytest.approx(30.10)
    assert target.status == "partial"
    bank = active_store.list_bookings()[0]
    assert bank.id != incoming["bookings"][0]["id"]
    assert bank.allocated_amount == pytest.approx(20.10)
    history = active_store.list_payments(entity_type, target.id)
    assert len(history) == 3
    assert sum((p.amount for p in history if not p.reversal), Decimal(0)) == Decimal("30.10")
    assert all(p.id not in originals for p in history)
    assert all(p.idempotency_key not in {x["idempotency_key"] for x in originals.values()} for p in history)
    restored = next(p for p in history if p.reversal)
    old = next(x for x in originals.values() if x["reversal"])
    assert restored.booking_id == bank.id
    assert restored.reversal.payment_id == restored.id
    assert restored.reversal.id != old["reversal"]["id"]
    assert restored.reversal.idempotency_key != old["reversal"]["idempotency_key"]
    assert restored.reversal.amount == restored.amount == Decimal("40.10")
    assert restored.reversal.reason == old["reversal"]["reason"]
    assert restored.reversal.reversal_date.isoformat() == old["reversal"]["reversal_date"]
    # Imported balances still permit a subsequent allocation and reversal normally.
    active_store.record_payment(entity_type, target.id, linked_payload(bank, "70.20"))
    active_receipt = next(p for p in history if p.booking_id and not p.reversal)
    active_store.reverse_payment(entity_type, target.id, active_receipt.id, reversal())
    assert getattr(active_store, f"get_{entity_type}")(target.id).amount_paid == pytest.approx(80.20)
    assert active_store.get_booking(bank.id).allocated_amount == pytest.approx(70.20)


@pytest.mark.parametrize("fault", ["missing_bank", "reversal_target", "reversal_amount",
                                     "duplicate_reversal", "unknown_reversal", "overallocated", "underpaid"])
def test_invalid_bank_snapshot_cannot_change_existing_data(active_store, fault):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming = bank_snapshot()
    cancelled = next(p for p in incoming["payments"] if p["reversal"])
    if fault == "missing_bank":
        incoming["bookings"] = []
    elif fault == "reversal_target":
        cancelled["reversal"]["payment_id"] = "wrong-receipt"
    elif fault == "reversal_amount":
        cancelled["reversal"]["amount"] = "0.01"
    elif fault == "unknown_reversal":
        cancelled["reversal"]["unrecognized"] = "must not disappear"
    elif fault == "overallocated":
        incoming["bookings"][0]["amount"] = 1
    elif fault == "underpaid":
        incoming["receivables"][0]["amount_paid"] = 1
    else:
        duplicate = deepcopy(cancelled)
        duplicate["id"], duplicate["idempotency_key"] = "another-receipt", "another-payment-key"
        duplicate["reversal"]["payment_id"] = duplicate["id"]
        incoming["payments"].append(duplicate)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)
    assert canonical_snapshot(active_store) == before


def test_bank_reversal_import_failure_rolls_back_all_tables(active_store, monkeypatch):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming = bank_snapshot()
    original = type(active_store).import_payment
    reached = []

    def fail_after_reversal(staged, receipt):
        original(staged, receipt)
        if receipt.reversal:
            reached.append(receipt.id)
            raise RuntimeError("failure after storing nested reversal")

    monkeypatch.setattr(type(active_store), "import_payment", fail_after_reversal)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)
    assert len(reached) == 1
    assert canonical_snapshot(active_store) == before
    if isinstance(active_store, SQLAlchemyStore):
        with Session(active_store.db.get_bind()) as fresh:
            assert canonical_snapshot(SQLAlchemyStore(fresh)) == before


@pytest.mark.parametrize("operation", ["restore", "import"])
def test_real_http_routes_preserve_bank_reversal(active_store, http_client, operation):
    import json
    client, headers, _, directory = http_client
    incoming = bank_snapshot()
    if operation == "restore":
        seed_existing(active_store)
        (directory / "backup_banks.json").write_text(json.dumps(incoming), encoding="utf-8")
        response = client.post("/api/v1/admin/restore/backup_banks.json", headers=headers)
    else:
        response = client.post("/api/v1/admin/import", headers=headers,
                               files={"file": ("banks.json", json.dumps(incoming), "application/json")})
    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    bank = active_store.list_bookings()[0]
    target = active_store.list_receivables()[0]
    assert bank.allocated_amount == pytest.approx(20.10)
    assert target.amount_paid == pytest.approx(30.10)
    restored = next(p for p in active_store.list_payments() if p.reversal)
    assert restored.booking_id == bank.id
    assert restored.reversal.payment_id == restored.id
