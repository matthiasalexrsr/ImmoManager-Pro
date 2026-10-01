"""Actual monthly generation, historical pricing and uniqueness regressions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base, RentChargeORM
from backend.domain.lease_engine import ChargeConfig, LeaseEngine
from backend.models import ContractCreate, RentChargeCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.rent_ledger import (
    RentGenerationRequest,
    contract_ledger_inputs,
    ensure_unique_month_schema,
    generate_rent_charges,
    list_open_items,
    preview_generation,
    ungenerated_contract_preview,
)
from backend.storage import InMemoryStore, ValidationError
from backend.tests.test_payments import payload, seed


@pytest.fixture(params=["memory", "sql"])
def ledger_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


def setup_contract(store):
    existing = seed(store, "rent_charge")
    contract = store.get_contract(existing.contract_id)
    unit = store.get_unit(contract.unit_id)
    data = unit.model_dump(include=set(UnitCreate.model_fields))
    store.update_unit(unit.id, UnitCreate(**{**data, "cold_rent": 800, "service_charge_advance": 100, "heating_advance": 50}))
    return contract, existing


def request_range(contract, start="2026-09", end="2026-12"):
    return RentGenerationRequest(start_month=start, end_month=end, contract_ids=[contract.id])


def test_preview_and_inclusive_generation_replay(ledger_store):
    contract, existing = setup_contract(ledger_store)
    request = request_range(contract)
    preview = preview_generation(ledger_store, request)
    assert preview["policy"] == "full_month"
    assert [p["month"] for p in preview["candidates"]] == ["2026-10", "2026-11", "2026-12"]
    assert preview["total_amount"] == 2850
    assert len(ledger_store.list_rent_charges()) == 1
    created = generate_rent_charges(ledger_store, request)
    assert created["created_count"] == 3
    assert created["skipped_count"] == 1
    assert generate_rent_charges(ledger_store, request)["created_count"] == 0
    assert len(ledger_store.list_rent_charges()) == 4
    assert ledger_store.get_rent_charge(existing.id).cold_rent == 100.10
    assert ledger_store.list_receivables() == []


def test_active_contract_intersection_and_explicit_partial_month_policy(ledger_store):
    contract, _ = setup_contract(ledger_store)
    values = contract.model_dump(include=set(ContractCreate.model_fields))
    contract = ledger_store.update_contract(contract.id, ContractCreate(**{**values,
        "start_date": date(2026, 10, 15), "end_date": date(2026, 11, 10)}))
    preview = preview_generation(ledger_store, request_range(contract))
    assert [row["month"] for row in preview["candidates"]] == ["2026-10", "2026-11"]
    assert all(row["partial_month"] for row in preview["candidates"])
    assert preview["total_amount"] == 1900
    draft = ledger_store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)), "status": "draft"}))
    result = generate_rent_charges(ledger_store, request_range(draft))
    assert result["created_count"] == 0
    assert result["skipped_contracts"][0]["reason"] == "inactive_contract"


def test_unknown_selected_contract_cannot_partially_generate(ledger_store):
    contract, _ = setup_contract(ledger_store)
    request = RentGenerationRequest(start_month="2026-10", end_month="2026-11", contract_ids=[contract.id, "missing"])
    with pytest.raises(ValidationError):
        generate_rent_charges(ledger_store, request)
    assert len(ledger_store.list_rent_charges()) == 1


def test_changed_prices_invalidate_confirmation_but_completed_replay_is_safe(ledger_store):
    contract, _ = setup_contract(ledger_store)
    request = request_range(contract, "2026-10", "2026-10")
    preview = preview_generation(ledger_store, request)
    confirmed = request.model_copy(update={"preview_hash": preview["preview_hash"]})
    unit = ledger_store.get_unit(contract.unit_id)
    ledger_store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "cold_rent": 1200}))
    with pytest.raises(ValidationError, match="Vorschau"):
        generate_rent_charges(ledger_store, confirmed)
    assert len(ledger_store.list_rent_charges()) == 1
    current_preview = preview_generation(ledger_store, request)
    confirmed = request.model_copy(update={"preview_hash": current_preview["preview_hash"]})
    assert generate_rent_charges(ledger_store, confirmed)["created_count"] == 1
    assert generate_rent_charges(ledger_store, confirmed)["created_count"] == 0


def test_paid_month_cannot_move_its_history_to_another_month(ledger_store):
    _, target = setup_contract(ledger_store)
    ledger_store.record_payment("rent_charge", target.id, payload())
    with pytest.raises(ValidationError, match="Zahlungshistorie"):
        ledger_store.update_rent_charge(target.id, RentChargeCreate(**{
            **ledger_store.get_rent_charge(target.id).model_dump(include=set(RentChargeCreate.model_fields)), "month": "2026-10"}))
    assert ledger_store.get_rent_charge(target.id).month == "2026-09"


@pytest.mark.parametrize("changes", [{"month": "2026-13"}, {"month": "2026-1"}, {"month": "0000-01"},
    {"cold_rent": -1}, {"cold_rent": "NaN"}, {"heating_charge": "Infinity"}, {"amount_paid": -1},
    {"service_charge": "0.001"}, {"status": "made_up"}])
def test_invalid_month_money_and_status_rejected(changes):
    with pytest.raises(PydanticValidationError):
        RentChargeCreate(**{"contract_id": "c", "month": "2026-10", "cold_rent": 10, **changes})


@pytest.mark.parametrize("start,end", [("2026-13", "2026-14"), ("2026-11", "2026-10"), ("2000-01", "2020-01")])
def test_invalid_generation_ranges(start, end):
    with pytest.raises(PydanticValidationError):
        RentGenerationRequest(start_month=start, end_month=end)


def test_single_crud_rejects_duplicate_and_missing_contract(ledger_store):
    contract, existing = setup_contract(ledger_store)
    with pytest.raises(ValidationError):
        ledger_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month=existing.month))
    with pytest.raises((ValidationError, KeyError)):
        ledger_store.create_rent_charge(RentChargeCreate(contract_id="missing", month="2026-10"))
    second = ledger_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2026-10", cold_rent=20))
    with pytest.raises(ValidationError):
        ledger_store.update_rent_charge(second.id, RentChargeCreate(contract_id=contract.id, month=existing.month, cold_rent=20))
    assert ledger_store.get_rent_charge(second.id).month == "2026-10"


def test_snapshots_and_targeted_payments_survive_current_unit_price_changes(ledger_store):
    contract, september = setup_contract(ledger_store)
    generate_rent_charges(ledger_store, request_range(contract, "2026-10", "2026-10"))
    october = next(c for c in ledger_store.list_rent_charges() if c.month == "2026-10")
    ledger_store.record_payment("rent_charge", october.id, payload("50.00"))
    unit = ledger_store.get_unit(contract.unit_id)
    ledger_store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "cold_rent": 1200}))
    lines, payments = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 15))
    dashboard = LeaseEngine.build_dashboard(contract_start=contract.start_date, contract_end=contract.end_date,
        charge=ChargeConfig(Decimal("9999")), payments=payments, today=date(2026, 10, 15), charge_lines=lines)
    assert dashboard.summary.total_expected == Decimal("1050.30")
    assert dashboard.settlement_lines[0].paid_amount == 0
    assert dashboard.settlement_lines[1].paid_amount == 50
    assert dashboard.summary.total_outstanding == Decimal("1000.30")
    preview = ungenerated_contract_preview(ledger_store, contract, date(2026, 11, 15))
    assert next(row for row in preview["candidates"] if row["month"] == "2026-11")["cold_rent"] == 1200
    assert ledger_store.get_rent_charge(september.id).cold_rent == 100.10


def test_other_charges_legacy_balances_and_payment_cutoff(ledger_store):
    contract, existing = setup_contract(ledger_store)
    ledger_store.delete_rent_charge(existing.id)
    target = ledger_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2026-10",
        cold_rent=800, other_charges=25, amount_paid=100, status="partial"))
    ledger_store.record_payment("rent_charge", target.id, payload("50.00").model_copy(update={"payment_date": date(2026, 10, 5)}))
    lines, payments = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 1))
    assert lines[0].total_amount == 825
    assert lines[0].other_charges == 25
    # Old balance survives; the future dated receipt is excluded from as-of October 1.
    assert sum(p.amount for p in payments) == 100
    _, later_payments = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 10))
    assert sum(p.amount for p in later_payments) == 150
    earlier_lines, _ = contract_ledger_inputs(ledger_store, contract, date(2026, 9, 30))
    assert earlier_lines == []
    assert list_open_items(ledger_store)["total_outstanding"] == 675


def test_concurrent_generation_is_idempotent_memory():
    store = InMemoryStore()
    contract, _ = setup_contract(store)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: generate_rent_charges(store, request_range(contract)), range(4)))
    assert sum(r["created_count"] for r in results) == 3
    assert len(store.list_rent_charges()) == 4


def test_sql_unique_guard_across_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"timeout": 15})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        contract, _ = setup_contract(SQLAlchemyStore(db))
    barrier = Barrier(2)
    def create_one(_):
        with Session(engine) as db:
            barrier.wait()
            try:
                SQLAlchemyStore(db).create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2026-10", cold_rent=10))
                return "created"
            except ValidationError:
                return "duplicate"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create_one, range(2)))
    assert sorted(results) == ["created", "duplicate"]
    with Session(engine) as db:
        assert len(list(db.scalars(select(RentChargeORM).where(RentChargeORM.month == "2026-10")))) == 1
    engine.dispose()


def test_sql_generation_commit_failure_rolls_back_whole_batch(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        contract, _ = setup_contract(store)
        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError):
            generate_rent_charges(store, request_range(contract))
    with Session(engine) as db:
        assert len(SQLAlchemyStore(db).list_rent_charges()) == 1
    engine.dispose()


def test_legacy_unique_migration_refuses_duplicates_without_losing_financial_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-duplicate.db'}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE rent_charges (id TEXT PRIMARY KEY, contract_id TEXT, month TEXT, amount_paid NUMERIC)"))
        db.execute(text("INSERT INTO rent_charges VALUES ('a', 'c', '2026-10', 30), ('b', 'c', '2026-10', 20)"))
        with pytest.raises(RuntimeError, match="Keine Zahlungsbelege löschen"):
            ensure_unique_month_schema(db)
        assert db.execute(text("SELECT COUNT(*), SUM(amount_paid) FROM rent_charges")).one() == (2, 50)
    engine.dispose()


def test_legacy_unique_migration_is_repeatable_and_enforces_database_constraint(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-unique.db'}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE rent_charges (id TEXT PRIMARY KEY, contract_id TEXT, month TEXT)"))
        db.execute(text("INSERT INTO rent_charges VALUES ('a', 'c', '2026-10')"))
        ensure_unique_month_schema(db)
        ensure_unique_month_schema(db)
        assert any(index["unique"] for index in __import__("sqlalchemy").inspect(db).get_indexes("rent_charges"))
    engine.dispose()


def test_http_generation_and_booked_account_contract(ledger_store, monkeypatch):
    from backend.routers import contracts, rent_charges
    clear_users()
    contract, existing = setup_contract(ledger_store)
    monkeypatch.setattr(contracts, "store", ledger_store)
    monkeypatch.setattr(rent_charges, "store", ledger_store)
    try:
        owner = register_user("ledger-owner", "ledger@example.com", "Owner", "Secret123", "eigentuemer")
        reader = register_user("ledger-reader", "reader@example.com", "Reader", "Secret123", "readonly")
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        read_headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        request = request_range(contract, "2026-09", "2026-10").model_dump()
        with TestClient(app) as client:
            assert client.post("/api/v1/rent-charges/generate", json=request).status_code == 401
            assert client.post("/api/v1/rent-charges/generate", json=request, headers=read_headers).status_code == 403
            invalid = client.post("/api/v1/rent-charges/preview", json={**request, "end_month": "2026-13"}, headers=headers)
            assert invalid.status_code == 422
            preview = client.post("/api/v1/rent-charges/preview", json=request, headers=headers).json()
            assert preview["candidates"][0]["due_date"] == "2026-10-03"
            assert preview["candidates"][0]["contract_number"] == "P-1"
            generated = client.post("/api/v1/rent-charges/generate", json=request, headers=headers)
            assert generated.status_code == 200
            assert generated.json()["created_count"] == 1
            assert client.post("/api/v1/rent-charges/generate", json=request, headers=headers).json()["created_count"] == 0
            account = client.get(f"/api/v1/contracts/{contract.id}/settlement?as_of=2026-10-15", headers=headers).json()
            assert account["source"] == "booked_rent_charges"
            assert account["balance"]["expected_total"] == 1050.30
            assert len(account["receivables"]) == 2
            assert account["ungenerated_preview"]["created_count"] == 0
            report = client.get("/api/v1/rent-charges/open-items", headers=read_headers).json()
            assert report["total_outstanding"] == 1050.30
            assert ledger_store.get_rent_charge(existing.id).cold_rent == 100.10
    finally:
        clear_users()


def test_empty_booked_account_never_duns_estimated_months(ledger_store, monkeypatch):
    from backend.routers import contracts
    contract, existing = setup_contract(ledger_store)
    ledger_store.delete_rent_charge(existing.id)
    monkeypatch.setattr(contracts, "store", ledger_store)
    account = contracts.get_contract_settlement(contract.id, as_of=date(2026, 10, 15))
    assert account["balance"]["expected_total"] == 0
    assert account["settlement_lines"] == []
    assert len(account["ungenerated_preview"]["candidates"]) == 10
    assert contracts.create_dunning_campaign(contract.id, as_of=date(2026, 10, 15))["total_cases"] == 0
