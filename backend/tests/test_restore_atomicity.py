"""Atomic JSON restore and relationship-preservation regressions."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.orm_models import Base
from backend.models import (
    ContactCreate,
    LeadCreate,
    ListingCreate,
    NotificationCreate,
    RentAdjustmentCreate,
    TaskCreate,
)
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
    parent_task = source.create_task(TaskCreate(title="Parent restore task"))
    source.create_task(
        TaskCreate(title="Child restore task", parent_task_id=parent_task.id)
    )
    source.create_notification(
        NotificationCreate(
            notification_type="overdue_payment",
            title="Restore notification",
            content="Payment reminder",
            entity_type="receivable",
            entity_id=receivable.id,
        )
    )
    snapshot = admin._export_store_data(source)
    snapshot["tasks"].reverse()  # child-first input must still restore parent-first
    return snapshot, receivable.id


def seed_existing(active_store):
    receivable = seed(active_store, "receivable")
    active_store.record_payment("receivable", receivable.id, payload("10.00"))
    return receivable


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

    tasks = {task.title: task for task in active_store.list_tasks()}
    assert tasks["Child restore task"].parent_task_id == tasks["Parent restore task"].id

    notification = active_store.list_notifications()[0]
    assert notification.entity_type == "receivable"
    assert notification.entity_id == restored.id


def test_restore_rolls_back_when_middle_entity_import_fails(active_store, monkeypatch):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()

    def fail_tenant(staged, _payload):
        raise RuntimeError("injected tenant import failure")

    monkeypatch.setattr(type(active_store), "create_tenant", fail_tenant)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert canonical_snapshot(active_store) == before


def test_restore_rolls_back_when_payment_import_fails(active_store, monkeypatch):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()

    def fail_payment(staged, _payment):
        raise RuntimeError("injected payment import failure")

    monkeypatch.setattr(type(active_store), "import_payment", fail_payment)
    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert canonical_snapshot(active_store) == before


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


def test_restore_rejects_receipts_that_exceed_stored_paid_balance(active_store):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    incoming["receivables"][0]["amount_paid"] = 1.00

    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert canonical_snapshot(active_store) == before


def test_restore_rejects_cyclic_task_relationships(active_store):
    seed_existing(active_store)
    before = canonical_snapshot(active_store)
    incoming, _ = build_snapshot()
    first, second = incoming["tasks"]
    first["parent_task_id"] = second["id"]
    second["parent_task_id"] = first["id"]

    with pytest.raises(admin.TransferError):
        admin._restore_store_data(incoming, active_store)

    assert canonical_snapshot(active_store) == before
