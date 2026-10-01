"""Real journal progress, source revisions and financial replay protection."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, ContractORM, RentAdjustmentORM, RentChargeORM
from backend.db.rent_batch_models import RentSourceRevisionORM
from backend.db.rent_batch_schema import ensure_rent_batch_schema
from backend.models import UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.rent_batch import (
    BatchAdvance,
    BatchConfirm,
    BatchCreate,
    BatchError,
    advance_batch,
    control_batch,
    create_batch,
    get_batch,
    preview_batch,
)
from backend.storage import InMemoryStore
from backend.tests.test_rent_ledger import setup_contract


@pytest.fixture(params=["memory", "sql"])
def batch_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'batch.db'}", connect_args={"timeout": 30, "check_same_thread": False})
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_rent_batch_schema(connection)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


def start(store, contract, start_month="2026-10", end_month="2026-12"):
    return create_batch(store, BatchCreate(start_month=start_month, end_month=end_month,
        contract_ids=[contract.id], idempotency_key=str(uuid4())))


def advance(store, job, budget=2):
    return advance_batch(store, job["id"], BatchAdvance(cursor=job["cursor"], budget=budget))


def ready(store, job, budget=2):
    for _ in range(1000):
        if job["state"] != "preparing":
            assert job["state"] == "ready"
            return job
        job = advance(store, job, budget)
    pytest.fail("Synthetic batch did not finish preparation")


def complete(store, job, budget=2):
    job = control_batch(store, job["id"], BatchConfirm(cursor=job["cursor"], plan_hash=job["plan_hash"]), "confirm")
    for _ in range(1000):
        if job["state"] == "done":
            return job
        job = advance(store, job, budget)
    pytest.fail("Synthetic batch did not finish generation")


def test_pause_resume_restart_journal_and_exactly_once_targets(batch_store):
    contract, existing = setup_contract(batch_store)
    job = start(batch_store, contract, "2026-09")
    first = advance(batch_store, job)
    with pytest.raises(BatchError, match="weitergeführt"):
        advance(batch_store, job)
    paused = control_batch(batch_store, first["id"], BatchAdvance(cursor=first["cursor"]), "pause")
    with pytest.raises(BatchError, match="fortsetzen"):
        advance(batch_store, paused)
    if hasattr(batch_store, "db"):
        engine = batch_store.db.get_bind()
        batch_store.db.close()
        batch_store = SQLAlchemyStore(Session(engine))  # New process/session view.
    recovered = get_batch(batch_store, paused["id"])
    resumed = control_batch(batch_store, recovered["id"], BatchAdvance(cursor=recovered["cursor"]), "resume")
    job = ready(batch_store, resumed)
    page = preview_batch(batch_store, job["id"], page_size=2)
    assert [r["month"] for r in page["items"]] == ["2026-09", "2026-10"]
    assert page["items"][0]["existing_charge_id"] == existing.id
    assert page["items"][1]["total_amount"] == 950
    assert page["next_cursor"]
    later = preview_batch(batch_store, job["id"], cursor=page["next_cursor"], page_size=2)
    assert [r["month"] for r in later["items"]] == ["2026-11", "2026-12"]
    result = complete(batch_store, job)
    assert (result["created_count"], result["existing_count"], result["examined_count"]) == (3, 1, 4)
    assert batch_store.get_rent_charge(existing.id).cold_rent == 100.10
    assert len(batch_store.list_rent_charges()) == 4
    with pytest.raises(BatchError):
        complete(batch_store, job)


def test_price_change_before_seal_requires_restart_but_after_seal_is_frozen(batch_store):
    contract, _ = setup_contract(batch_store)
    job = advance(batch_store, start(batch_store, contract))
    unit = batch_store.get_unit(contract.unit_id)
    def change(amount):
        batch_store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "cold_rent": amount}))
    change(1200)
    with pytest.raises(BatchError) as conflict:
        ready(batch_store, job)
    assert conflict.value.code == "RENT_SOURCE_CHANGED"
    current = get_batch(batch_store, job["id"])
    restarted = control_batch(batch_store, job["id"], BatchAdvance(cursor=current["cursor"]), "restart")
    job = ready(batch_store, restarted)
    change(1600)
    assert preview_batch(batch_store, job["id"])["items"][0]["total_amount"] == 1350
    complete(batch_store, job)
    assert {r.cold_rent for r in batch_store.list_rent_charges() if r.month != "2026-09"} == {1200}


def test_tampered_bound_cursor_unknown_creator_and_idempotency(batch_store):
    contract, _ = setup_contract(batch_store)
    payload = BatchCreate(start_month="2026-10", end_month="2026-12", contract_ids=[contract.id], idempotency_key="replay")
    job = create_batch(batch_store, payload)
    assert create_batch(batch_store, payload)["id"] == job["id"]
    with pytest.raises(BatchError) as error:
        advance_batch(batch_store, job["id"], BatchAdvance(cursor=job["cursor"][:-1] + "X"))
    assert error.value.code == "RENT_CURSOR_INVALID"
    assert get_batch(batch_store, job["id"])["revision"] == 0
    with pytest.raises(BatchError) as error:
        get_batch(batch_store, job["id"], actor_id="other")
    assert error.value.status == 404
    with pytest.raises(BatchError):
        create_batch(batch_store, payload.model_copy(update={"end_month": "2027-01"}))


def test_long_calendar_range_is_bounded_and_not_rejected(batch_store):
    contract, _ = setup_contract(batch_store)
    job = ready(batch_store, start(batch_store, contract, "2026-10", "2046-10"))
    result = complete(batch_store, job, budget=50)
    assert result["created_count"] == 241
    assert result["state"] == "done"


def test_sql_atomic_parallel_step_and_transaction_failure(batch_store):
    if not hasattr(batch_store, "db"):
        pytest.skip("Independent SQL transactions")
    contract, _ = setup_contract(batch_store)
    job = ready(batch_store, start(batch_store, contract))
    job = control_batch(batch_store, job["id"], BatchConfirm(cursor=job["cursor"], plan_hash=job["plan_hash"]), "confirm")
    engine = batch_store.db.get_bind()
    batch_store.db.rollback()
    barrier = Barrier(2)
    def run(_):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                return advance(SQLAlchemyStore(db), job)["created_count"]
            except BatchError as exc:
                return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, range(2)))
    assert sorted(map(str, outcomes)) == ["2", "RENT_CURSOR_STALE"]
    fresh = get_batch(batch_store, job["id"])
    before = batch_store.db.scalar(select(func.count()).select_from(RentChargeORM))
    def fail_on_result(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO rent_generation_results"):
            raise RuntimeError("Synthetic crash after target writes")
    event.listen(engine, "before_cursor_execute", fail_on_result)
    try:
        with pytest.raises(RuntimeError, match="Synthetic crash"):
            advance(batch_store, fresh)
    finally:
        event.remove(engine, "before_cursor_execute", fail_on_result)
    assert get_batch(batch_store, job["id"])["cursor"] == fresh["cursor"]
    assert batch_store.db.scalar(select(func.count()).select_from(RentChargeORM)) == before
    assert advance(batch_store, fresh)["created_count"] == 3


def test_sql_revision_triggers_detect_price_delete_move_and_ignore_lock_noop(batch_store):
    if not hasattr(batch_store, "db"):
        pytest.skip("Persistent database triggers")
    contract, _ = setup_contract(batch_store)
    db = batch_store.db
    def rev(kind, identifier):
        db.expire_all()
        return db.get(RentSourceRevisionORM, (kind, identifier)).revision
    before = rev("contract", contract.id)
    db.execute(update(ContractORM).where(ContractORM.id == contract.id).values(updated_at=ContractORM.updated_at))
    db.commit()
    assert rev("contract", contract.id) == before
    adjustment = RentAdjustmentORM(id=str(uuid4()), contract_id=contract.id, effective_date=date(2026, 11, 15),
        adjustment_type="manual", previous_rent=800, new_rent=900, status="applied")
    db.add(adjustment)
    db.commit()
    assert rev("prices", contract.id) == 1
    job = advance(batch_store, start(batch_store, contract))
    db.delete(adjustment)
    db.commit()
    assert rev("prices", contract.id) == 2
    with pytest.raises(BatchError):
        ready(batch_store, job)


def test_sql_more_than_500_contracts_are_prepared_and_generated_in_bounded_pages(batch_store):
    if not hasattr(batch_store, "db"):
        pytest.skip("Synthetic large SQL dataset")
    from sqlalchemy import insert

    from backend.db.orm_models import UnitORM
    contract, _ = setup_contract(batch_store)
    db = batch_store.db
    units, contracts = [], []
    for index in range(501):
        identifier = f"synthetic-batch-{index:04d}"
        units.append(dict(id=identifier, property_id=contract.property_id, label=identifier, unit_type="apartment", cold_rent=700,
            service_charge_advance=80, heating_advance=20))
        contracts.append(dict(id=identifier, unit_id=identifier, property_id=contract.property_id, tenant_id=contract.tenant_id,
            contract_number=identifier, start_date=date(2026, 10, 1), status="active"))
    db.execute(insert(UnitORM), units)
    db.execute(insert(ContractORM), contracts)
    db.commit()
    payload = BatchCreate(start_month="2026-10", end_month="2026-10", contract_ids=[x["id"] for x in contracts], idempotency_key="large")
    job = create_batch(batch_store, payload)
    limits = []
    def inspect_limit(conn, cursor, statement, parameters, context, many):
        if statement.startswith("SELECT") and "FROM contracts" in statement:
            assert "LIMIT" in statement  # No unbounded source materialization.
            limits.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", inspect_limit)
    try:
        job = ready(batch_store, job, budget=100)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", inspect_limit)
    assert job["contract_count"] == 501 and len(limits) < 15
    result = complete(batch_store, job, budget=100)
    assert result["created_count"] == 501


def test_sql_frozen_applied_price_history_uses_day_one_baseline_across_pages(batch_store):
    if not hasattr(batch_store, "db"):
        pytest.skip("SQL pricing snapshot chunks")
    contract, _ = setup_contract(batch_store)
    db = batch_store.db
    for index, (effective, previous, new) in enumerate([(date(2026, 11, 15), 800, 900), (date(2027, 1, 1), 900, 1000)]):
        db.add(RentAdjustmentORM(id=f"price-{index}", contract_id=contract.id, effective_date=effective,
            adjustment_type="manual", previous_rent=previous, new_rent=new, status="applied"))
    db.commit()
    job = ready(batch_store, start(batch_store, contract, "2026-10", "2027-02"), budget=1)
    assert job["price_count"] == 2
    result = complete(batch_store, job, budget=2)
    assert result["created_count"] == 5
    charges = {r.month: r.cold_rent for r in batch_store.list_rent_charges()}
    assert {month: charges[month] for month in ("2026-10", "2026-11", "2026-12", "2027-01", "2027-02")} == {
        "2026-10": 800, "2026-11": 800, "2026-12": 900, "2027-01": 1000, "2027-02": 1000}
