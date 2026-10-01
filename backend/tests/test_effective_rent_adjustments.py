"""Applied contract prices, historical snapshots and real DB arbitration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event, current_thread

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as ModelValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth
from backend.app import app
from backend.db.orm_models import Base, RentAdjustmentORM
from backend.models import ContractCreate, RentAdjustment, RentAdjustmentCreate, RentAdjustmentPatch, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import rent_adjustments, rent_charges
from backend.services.rent_adjustments import INDEX_NAME, RentAdjustmentConflict, ensure_rent_adjustment_schema
from backend.services.rent_ledger import RentGenerationRequest, generate_rent_charges, preview_generation
from backend.storage import InMemoryStore, ValidationError
from backend.tests import test_private_server_concurrency as postgres_support
from backend.tests.test_payments import seed

postgres_database = postgres_support.postgres_database


@pytest.fixture(params=["sqlite", "postgres"])
def transaction_database(request, tmp_path):
    if request.param == "postgres":
        engine, _, _, _ = request.getfixturevalue("postgres_database")
        yield engine
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'price-transactions.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(params=["memory", "sql"])
def ledger_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'applied-prices.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


def contract_setup(store):
    historical = seed(store, "rent_charge")
    contract = store.get_contract(historical.contract_id)
    unit = store.get_unit(contract.unit_id)
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "cold_rent": 500,
                                            "service_charge_advance": 100.10, "heating_advance": 50.05}))
    contract = store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
                                                                   "start_date": date(2025, 1, 1)}))
    return contract, historical


def adjustment(store, contract, **overrides):
    return store.create_rent_adjustment(RentAdjustmentCreate(**{
        "contract_id": contract.id, "adjustment_type": "stepped", "effective_date": date(2025, 2, 1),
        "previous_rent": 500, "new_rent": 600, "status": "applied", **overrides}))


def request(contract, start="2025-01", end="2025-03", **overrides):
    return RentGenerationRequest(start_month=start, end_month=end, contract_ids=[contract.id], **overrides)


def test_applied_prices_per_month_with_exact_cents_and_generated_history_preserved(ledger_store):
    contract, historical = contract_setup(ledger_store)
    adjustment(ledger_store, contract)
    adjustment(ledger_store, contract, effective_date=date(2025, 3, 1), previous_rent=600, new_rent=650.30)
    preview = preview_generation(ledger_store, request(contract))
    assert [row["cold_rent"] for row in preview["candidates"]] == [500, 600, 650.30]
    assert [row["total_amount"] for row in preview["candidates"]] == [650.15, 750.15, 800.45]
    assert preview["total_amount"] == 2200.75
    result = generate_rent_charges(ledger_store, request(contract, preview_hash=preview["preview_hash"]))
    assert result["created_count"] == 3
    original = {row.month: row.model_dump() for row in ledger_store.list_rent_charges()}
    applied = next(row for row in ledger_store.list_rent_adjustments() if row.new_rent == 650.30)
    ledger_store.update_rent_adjustment(applied.id, RentAdjustmentCreate(**{
        **applied.model_dump(include=set(RentAdjustmentCreate.model_fields)), "new_rent": 900}))
    assert generate_rent_charges(ledger_store, request(contract))["created_count"] == 0
    assert {row.month: row.model_dump() for row in ledger_store.list_rent_charges()} == original
    assert ledger_store.get_rent_charge(historical.id).cold_rent == historical.cold_rent


def test_pending_rejected_and_another_contract_do_not_change_prices_or_hash(ledger_store):
    contract, _ = contract_setup(ledger_store)
    original = preview_generation(ledger_store, request(contract))
    adjustment(ledger_store, contract, status="pending", new_rent=850)
    adjustment(ledger_store, contract, status="rejected", new_rent=950)
    other = ledger_store.create_contract(ContractCreate(**{
        **contract.model_dump(include=set(ContractCreate.model_fields)), "contract_number": "other-synthetic-contract"}))
    adjustment(ledger_store, other, new_rent=700)
    current = preview_generation(ledger_store, request(contract))
    assert current["preview_hash"] == original["preview_hash"]
    assert [row["cold_rent"] for row in current["candidates"]] == [500, 500, 500]


def test_first_previous_rent_anchors_history_after_unit_price_changes(ledger_store):
    contract, _ = contract_setup(ledger_store)
    adjustment(ledger_store, contract)
    original = preview_generation(ledger_store, request(contract))
    unit = ledger_store.get_unit(contract.unit_id)
    ledger_store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "cold_rent": 999}))
    current = preview_generation(ledger_store, request(contract))
    assert [row["cold_rent"] for row in current["candidates"]] == [500, 600, 600]
    assert current["preview_hash"] == original["preview_hash"]


def test_midmonth_rule_waits_for_next_full_month(ledger_store):
    contract, _ = contract_setup(ledger_store)
    adjustment(ledger_store, contract, effective_date=date(2025, 2, 15))
    preview = preview_generation(ledger_store, request(contract))
    assert [row["cold_rent"] for row in preview["candidates"]] == [500, 500, 600]
    assert "Untermonatliche" in preview["policy_description"]


def test_effective_rule_change_invalidates_hash_even_when_monthly_amount_is_equal(ledger_store):
    contract, _ = contract_setup(ledger_store)
    rule = adjustment(ledger_store, contract)
    preview = preview_generation(ledger_store, request(contract, "2025-03", "2025-03"))
    ledger_store.update_rent_adjustment(rule.id, RentAdjustmentCreate(**{
        **rule.model_dump(include=set(RentAdjustmentCreate.model_fields)), "effective_date": date(2025, 1, 1)}))
    current = preview_generation(ledger_store, request(contract, "2025-03", "2025-03"))
    assert current["total_amount"] == preview["total_amount"] and current["preview_hash"] != preview["preview_hash"]
    with pytest.raises(ValidationError, match="Vorschau"):
        generate_rent_charges(ledger_store, request(contract, "2025-03", "2025-03", preview_hash=preview["preview_hash"]))
    assert len(ledger_store.list_rent_charges()) == 1
    assert generate_rent_charges(ledger_store, request(contract, "2025-03", "2025-03", preview_hash=current["preview_hash"]))["created_count"] == 1


def test_status_application_and_notes_hash_behavior(ledger_store):
    contract, _ = contract_setup(ledger_store)
    rule = adjustment(ledger_store, contract, status="pending")
    before = preview_generation(ledger_store, request(contract))
    ledger_store._patch_entity("rent_adjustment", rule.id, RentAdjustmentPatch(status="applied"))
    after = preview_generation(ledger_store, request(contract))
    assert after["preview_hash"] != before["preview_hash"]
    ledger_store._patch_entity("rent_adjustment", rule.id, RentAdjustmentPatch(notes="synthetic administrative note"))
    assert preview_generation(ledger_store, request(contract))["preview_hash"] == after["preview_hash"]


def test_duplicate_applied_date_is_rejected_on_create_and_patch_without_changes(ledger_store):
    contract, _ = contract_setup(ledger_store)
    adjustment(ledger_store, contract)
    with pytest.raises(RentAdjustmentConflict):
        adjustment(ledger_store, contract, new_rent=700)
    pending = adjustment(ledger_store, contract, status="pending", new_rent=750)
    with pytest.raises(RentAdjustmentConflict):
        ledger_store._patch_entity("rent_adjustment", pending.id, RentAdjustmentPatch(status="applied"))
    assert ledger_store.get_rent_adjustment(pending.id).status == "pending"
    assert len(ledger_store.list_rent_adjustments()) == 2


def test_legacy_ambiguous_applied_rules_fail_closed_without_new_charges(ledger_store):
    contract, _ = contract_setup(ledger_store)
    first = adjustment(ledger_store, contract)
    values = first.model_dump(include=set(RentAdjustmentCreate.model_fields))
    if hasattr(ledger_store, "db"):
        ledger_store.db.execute(text(f"DROP INDEX {INDEX_NAME}"))
        ledger_store.db.add(RentAdjustmentORM(id="synthetic-ambiguous", **values))
        ledger_store.db.commit()
    else:
        ledger_store.rent_adjustments["synthetic-ambiguous"] = RentAdjustment(id="synthetic-ambiguous", **values)
    with pytest.raises(RentAdjustmentConflict, match="nicht eindeutig"):
        generate_rent_charges(ledger_store, request(contract))
    assert len(ledger_store.list_rent_charges()) == 1
    assert len(ledger_store.list_rent_adjustments()) == 2


@pytest.mark.parametrize("value", [-1, 500.001, "NaN", "Infinity", True, None, "1e100"])
def test_rent_money_invalid_create_and_patch_are_validation_errors(value):
    for model in (RentAdjustmentCreate, RentAdjustmentPatch):
        payload = {"contract_id": "synthetic", "adjustment_type": "index", "effective_date": "2025-02-01", "previous_rent": 500, "new_rent": value}
        with pytest.raises(ModelValidationError):
            model(**payload)


@pytest.mark.parametrize("field,value", [("contract_id", None), ("effective_date", None), ("status", None),
                                       ("status", "unknown"), ("adjustment_type", "unsupported")])
def test_patch_required_fields_and_status_rules(field, value):
    with pytest.raises(ModelValidationError):
        RentAdjustmentPatch(**{field: value})


def test_http_money_422_duplicate_409_and_readonly_403(ledger_store, monkeypatch):
    contract, _ = contract_setup(ledger_store)
    monkeypatch.setattr(rent_adjustments, "store", ledger_store)
    monkeypatch.setattr(rent_charges, "store", ledger_store)
    auth.clear_users()
    owner = auth.register_user(username="synthetic-owner", email="owner@example.test", full_name="Synthetic", password="Strong123", role="eigentuemer")
    viewer = auth.register_user(username="synthetic-viewer", email="viewer@example.test", full_name="Synthetic", password="Strong123", role="readonly")
    headers = {"Authorization": "Bearer " + auth.create_access_token(owner.id)}
    data = {"contract_id": contract.id, "adjustment_type": "stepped", "effective_date": "2025-02-01", "previous_rent": 500, "new_rent": 600, "status": "applied"}
    with TestClient(app) as client:
        assert client.post("/api/v1/rent-adjustments", json={**data, "new_rent": 600.001}, headers=headers).status_code == 422
        created = client.post("/api/v1/rent-adjustments", json=data, headers=headers)
        assert created.status_code == 201
        assert client.post("/api/v1/rent-adjustments", json=data, headers=headers).status_code == 409
        pending = client.post("/api/v1/rent-adjustments", json={**data, "status": "pending"}, headers=headers).json()
        assert client.put("/api/v1/rent-adjustments/" + pending["id"], json=data, headers=headers).status_code == 409
        assert client.patch("/api/v1/rent-adjustments/" + pending["id"], json={"status": "applied"}, headers=headers).status_code == 409
        assert client.put("/api/v1/rent-adjustments/" + pending["id"], json={**data, "contract_id": "missing"}, headers=headers).status_code == 400
        assert client.patch("/api/v1/rent-adjustments/" + created.json()["id"], json={"new_rent": None}, headers=headers).status_code == 422
        readonly = {"Authorization": "Bearer " + auth.create_access_token(viewer.id)}
        assert client.post("/api/v1/rent-adjustments", json={**data, "effective_date": "2025-04-01"}, headers=readonly).status_code == 403
        preview = client.post("/api/v1/rent-charges/preview", json=request(contract).model_dump(mode="json"), headers=headers)
        assert preview.status_code == 200 and preview.json()["candidates"][2]["cold_rent"] == 600


def test_two_memory_writers_accept_only_one_applied_rule():
    store = InMemoryStore()
    contract, _ = contract_setup(store)
    barrier = Barrier(2)
    def create(index):
        barrier.wait(timeout=5)
        try:
            adjustment(store, contract, new_rent=600 + index)
            return "accepted"
        except RentAdjustmentConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, [0, 1])) == ["accepted", "conflict"]
    assert len(store.list_rent_adjustments()) == 1


def test_two_sql_sessions_accept_only_one_applied_rule(transaction_database):
    engine = transaction_database
    with Session(engine) as session:
        contract, _ = contract_setup(SQLAlchemyStore(session))
    barrier = Barrier(2)
    def create(index):
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            barrier.wait(timeout=5)
            try:
                adjustment(store, contract, new_rent=600 + index)
                return "accepted"
            except RentAdjustmentConflict:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, [0, 1])) == ["accepted", "conflict"]
    with Session(engine) as session:
        assert len(SQLAlchemyStore(session).list_rent_adjustments()) == 1


def test_schema_upgrade_preserves_conflicting_rows_and_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-prices.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE rent_adjustments(id TEXT,contract_id TEXT,effective_date DATE,status TEXT)"))
            connection.execute(text("INSERT INTO rent_adjustments VALUES ('a','synthetic','2025-02-01','applied'),('b','synthetic','2025-02-01','applied')"))
            with pytest.raises(RuntimeError, match="keine Einträge gelöscht"):
                ensure_rent_adjustment_schema(connection)
            assert connection.execute(text("SELECT COUNT(*) FROM rent_adjustments")).scalar_one() == 2
            connection.execute(text("UPDATE rent_adjustments SET status='pending' WHERE id='b'"))
            ensure_rent_adjustment_schema(connection)
            ensure_rent_adjustment_schema(connection)
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE rent_adjustments SET status='applied' WHERE id='b'"))
    finally:
        engine.dispose()


def test_generation_snapshot_holds_database_price_lock_until_batch_commit(transaction_database, monkeypatch):
    """A second SQL session cannot change a rule halfway through confirmed generation."""
    engine = transaction_database
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        contract, _ = contract_setup(store)
        rule = adjustment(store, contract)
        confirmed = preview_generation(store, request(contract, "2025-03", "2025-03"))["preview_hash"]
        original_contract_stamp = contract.updated_at
    snapshot_ready, attempted_write, release_generation, writer_done = Event(), Event(), Event(), Event()

    @event.listens_for(engine, "before_cursor_execute")
    def detect_writer(_connection, _cursor, statement, _parameters, _context, _executemany):
        if current_thread().name.startswith("price-writer") and statement.startswith("UPDATE contracts"):
            attempted_write.set()

    def generate():
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            read_rules = store.list_rent_adjustments
            def capture_snapshot():
                rows = read_rules()
                snapshot_ready.set()
                assert release_generation.wait(timeout=10)
                return rows
            monkeypatch.setattr(store, "list_rent_adjustments", capture_snapshot)
            return generate_rent_charges(store, request(contract, "2025-03", "2025-03", preview_hash=confirmed))

    def edit():
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            result = store.update_rent_adjustment(rule.id, RentAdjustmentCreate(**{
                **rule.model_dump(include=set(RentAdjustmentCreate.model_fields)), "new_rent": 700}))
            writer_done.set()
            return result
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="price-generator") as generator, \
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="price-writer") as writer:
            generated = generator.submit(generate)
            assert snapshot_ready.wait(timeout=10)
            changed = writer.submit(edit)
            try:
                assert attempted_write.wait(timeout=10)
                assert not writer_done.wait(timeout=0.1)
            finally:
                release_generation.set()
            assert generated.result(timeout=10)["created"][0]["cold_rent"] == 600
            assert changed.result(timeout=10).new_rent == 700
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            assert next(row for row in store.list_rent_charges() if row.month == "2025-03").cold_rent == 600
            assert preview_generation(store, request(contract, "2025-04", "2025-04"))["candidates"][0]["cold_rent"] == 700
            assert store.get_contract(contract.id).updated_at.replace(tzinfo=None) == original_contract_stamp.replace(tzinfo=None)
    finally:
        release_generation.set()


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_moved_adjustment_cannot_be_changed_under_an_old_parent_lock(transaction_database, operation):
    engine = transaction_database
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        contract, _ = contract_setup(store)
        rule = adjustment(store, contract)
        another = store.create_contract(ContractCreate(**{
            **contract.model_dump(include=set(ContractCreate.model_fields)), "contract_number": "V-Moved"}))
    has_read_parent, release_writer = Event(), Event()

    @event.listens_for(engine, "before_cursor_execute")
    def pause_stale_parent(_connection, _cursor, statement, _parameters, _context, _executemany):
        if current_thread().name.startswith("stale-price") and statement.startswith("UPDATE contracts"):
            has_read_parent.set()
            assert release_writer.wait(timeout=10)

    def stale_write():
        with Session(engine) as session, pytest.raises(RentAdjustmentConflict, match="zwischenzeitlich geändert"):
            store = SQLAlchemyStore(session)
            if operation == "delete":
                store.delete_rent_adjustment(rule.id)
            else:
                store.update_rent_adjustment(rule.id, RentAdjustmentCreate(**{
                    **rule.model_dump(include=set(RentAdjustmentCreate.model_fields)), "new_rent": 900}))
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-price") as executor:
            blocked = executor.submit(stale_write)
            try:
                assert has_read_parent.wait(timeout=10)
                with Session(engine) as session:
                    store = SQLAlchemyStore(session)
                    moved = store.update_rent_adjustment(rule.id, RentAdjustmentCreate(**{
                        **rule.model_dump(include=set(RentAdjustmentCreate.model_fields)), "contract_id": another.id}))
                    assert moved.contract_id == another.id
            finally:
                release_writer.set()
            blocked.result(timeout=10)
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            current = store.get_rent_adjustment(rule.id)
            assert current.contract_id == another.id and current.new_rent == 600
            assert preview_generation(store, request(another, "2025-03", "2025-03"))["candidates"][0]["cold_rent"] == 600
    finally:
        release_writer.set()
