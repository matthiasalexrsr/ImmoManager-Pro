"""Lossless export / import / restore of the business data (memory and SQL store)."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    BookingCreate,
    ContractCreate,
    CostItemCreate,
    DepositCreate,
    MessageCreate,
    MessageThreadCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    RentAdjustmentCreate,
    StandaloneMeterReadingCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementCreate,
)
from backend.routers import admin_runtime
from backend.services.data_snapshot import (
    SnapshotError,
    clear_business_data,
    entity_specs,
    export_snapshot,
    import_snapshot,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    yield
    clear_business_data(store)


def _seed() -> dict:
    """A small but complete portfolio: lease, money, billing, meters, tasks, messages."""
    pf = store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="MFH", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 1", unit_type="residential",
                                        area_sqm=60, cold_rent=600, service_charge_advance=150))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = store.create_contract(ContractCreate(contract_number="V-1", property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2024, 1, 1)))
    account = store.create_account(AccountCreate(portfolio_id=pf.id, name="Mietkonto", account_type="bank",
                                                 iban="DE89370400440532013000"))
    store.create_booking(BookingCreate(account_id=account.id, tenant_id=tenant.id, property_id=prop.id,
                                       booking_date=date(2025, 1, 3), amount=750))
    store.create_deposit(DepositCreate(contract_id=contract.id, amount=1800))
    store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2025, 2, 1), amount_due=750))
    store.create_rent_adjustment(RentAdjustmentCreate(contract_id=contract.id, adjustment_type="index",
                                                      effective_date=date(2025, 1, 1), previous_rent=600, new_rent=620))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="BK 2024",
                                                             start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
                                                             status="finalized"))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Fläche", key_type="area_sqm"))
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Grundsteuer", amount=400,
                                          allocation_key_id=key.id))
    store.create_utility_statement(UtilityStatementCreate(billing_period_id=period.id, contract_id=contract.id,
                                                          unit_id=unit.id, total_cost=400, advance_paid=1800,
                                                          balance=-1400, line_items=[{"description": "Grundsteuer",
                                                                                      "allocated_amount": 400}]))
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="water"))
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter.id, reading_date=date(2024, 12, 31),
                                                                       value=123.4))
    parent = store.create_task(TaskCreate(title="Wartung", property_id=prop.id))
    store.create_task(TaskCreate(title="Wartung Januar", parent_task_id=parent.id))
    thread = store.create_message_thread(MessageThreadCreate(subject="Heizung", contract_id=contract.id))
    store.create_message(MessageCreate(thread_id=thread.id, body="Heizung fällt aus"))
    return {"contract": contract, "tenant": tenant, "period": period}


def _content(snapshot: dict) -> dict:
    return {key: sorted(value, key=lambda r: r["id"]) for key, value in snapshot.items() if isinstance(value, list)}


def test_snapshot_covers_every_business_table():
    keys = {spec.key for spec in entity_specs()}
    # Previously missing from exports, so a restore silently dropped them.
    assert {"billing_periods", "cost_items", "utility_statements", "rent_adjustments",
            "meters", "standalone_meter_readings", "message_threads", "messages"} <= keys
    assert not keys & {"users", "user_preferences", "audit_logs"}


def test_replace_restores_exact_state():
    """Regression: restore re-created records with new IDs, so all children were dropped."""
    _seed()
    snapshot = json.loads(json.dumps(export_snapshot(store)))
    store.create_tenant(TenantCreate(full_name="Nach dem Backup"))

    import_snapshot(store, snapshot, replace=True)

    assert _content(export_snapshot(store)) == _content(snapshot)
    period = next(p for p in store.list_billing_periods())
    assert period.status == "finalized"


def test_import_into_empty_installation_keeps_references():
    seeded = _seed()
    snapshot = json.loads(json.dumps(export_snapshot(store)))
    clear_business_data(store)

    result = import_snapshot(store, snapshot, replace=False)

    assert result["imported"]["contracts"] == 1
    assert store.get_contract(seeded["contract"].id).tenant_id == seeded["tenant"].id
    assert _content(export_snapshot(store)) == _content(snapshot)


def test_reimporting_own_export_changes_nothing():
    """Regression: importing the export again duplicated portfolios, units, bookings, …"""
    _seed()
    snapshot = json.loads(json.dumps(export_snapshot(store)))

    result = import_snapshot(store, snapshot, replace=False)

    assert result["imported"] == {}
    assert result["skipped_existing"]["bookings"] == 1
    assert _content(export_snapshot(store)) == _content(snapshot)


def test_dangling_reference_aborts_without_writing():
    _seed()
    before = _content(export_snapshot(store))
    snapshot = json.loads(json.dumps(export_snapshot(store)))
    snapshot["contracts"][0]["tenant_id"] = "does-not-exist"

    with pytest.raises(SnapshotError, match="tenant_id"):
        import_snapshot(store, snapshot, replace=True)

    assert _content(export_snapshot(store)) == before


def test_unique_conflict_aborts_merge_without_writing():
    _seed()
    before = _content(export_snapshot(store))
    snapshot = json.loads(json.dumps(export_snapshot(store)))
    clash = dict(snapshot["contracts"][0], id="other-contract")  # same contract number, new ID
    snapshot["contracts"].append(clash)

    with pytest.raises(SnapshotError, match="contract_number"):
        import_snapshot(store, snapshot, replace=False)

    assert _content(export_snapshot(store)) == before


def test_restore_refuses_legacy_export():
    """Old exports lack billing, meters, …: replacing with them would delete data."""
    _seed()
    legacy = {k: v for k, v in export_snapshot(store).items() if k not in ("format", "format_version")}

    with pytest.raises(SnapshotError, match="älteren Version"):
        import_snapshot(store, legacy, replace=True)


def test_merge_accepts_legacy_keys_and_records_without_id():
    import_snapshot(store, {"tenants": [{"full_name": "Ohne ID"}], "viewings": []}, replace=False)

    assert [t.full_name for t in store.list_tenants()] == ["Ohne ID"]


def test_subtasks_listed_before_their_parent_are_imported():
    _seed()
    snapshot = json.loads(json.dumps(export_snapshot(store)))
    snapshot["tasks"].sort(key=lambda t: t["parent_task_id"] is None)  # child first
    clear_business_data(store)

    import_snapshot(store, snapshot, replace=True)

    assert len(store.list_tasks()) == 2


def test_invalid_record_is_reported_with_its_position():
    with pytest.raises(SnapshotError, match=r"tenants\[0\] full_name"):
        import_snapshot(store, {"tenants": [{"id": "t1"}]}, replace=False)


# --- API level -------------------------------------------------------------


@pytest.fixture
def client():
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()


def test_settings_export_import_round_trip(client):
    _seed()
    exported = client.get("/api/v1/data/export").content

    resp = client.post("/api/v1/data/import", files={"file": ("export.json", exported, "application/json")})

    assert resp.status_code == 200
    assert resp.json()["imported"] == {}
    assert len(store.list_bookings()) == 1


def test_settings_import_reports_problems(client):
    resp = client.post("/api/v1/data/import",
                       files={"file": ("x.json", b'{"contracts": [{"id": "c1"}]}', "application/json")})

    assert resp.status_code == 400
    assert "Import abgebrochen" in resp.json()["error"]["message"]


def test_json_restore_validates_before_touching_data(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_runtime, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(admin_runtime, "_live_sqlite_path", lambda: None)
    _seed()
    snapshot = export_snapshot(store)
    snapshot["bookings"][0]["account_id"] = "gone"
    (tmp_path / "backup_broken.json").write_text(json.dumps(snapshot), encoding="utf-8")
    before = _content(export_snapshot(store))

    with pytest.raises(Exception) as exc:
        admin_runtime.restore_backup("backup_broken.json")

    assert getattr(exc.value, "status_code", None) == 400
    assert _content(export_snapshot(store)) == before
    assert not list(tmp_path.glob("pre_restore_*"))


def test_json_restore_keeps_safety_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_runtime, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(admin_runtime, "_live_sqlite_path", lambda: None)
    _seed()
    (tmp_path / "backup_empty.json").write_text(json.dumps({"format": "immomanager-snapshot"}), encoding="utf-8")

    result = admin_runtime.restore_backup("backup_empty.json")

    assert store.list_contracts() == []
    safety = json.loads((tmp_path / result["safety_backup"]).read_text(encoding="utf-8"))
    import_snapshot(store, safety, replace=True)
    assert len(store.list_contracts()) == 1


def test_pre_update_backup_is_a_full_snapshot(tmp_path, monkeypatch):
    from backend import updater

    monkeypatch.setattr(updater, "_BACKUP_DIR", tmp_path)
    _seed()

    name = updater._create_pre_update_backup()

    assert name is not None
    data = json.loads((tmp_path / name).read_text(encoding="utf-8"))
    assert data["format"] == "immomanager-snapshot"
    assert len(data["utility_statements"]) == 1
