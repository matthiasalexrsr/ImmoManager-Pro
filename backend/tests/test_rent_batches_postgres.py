"""Real PostgreSQL when explicitly configured; private UUID schema only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select, text

from backend.db.rent_batch_models import RentSourceRevisionORM
from backend.db.rent_batch_schema import ensure_rent_batch_schema
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.rent_batch import BatchAdvance, BatchConfirm, BatchError, advance_batch, control_batch, get_batch
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401
from backend.tests.test_rent_batches import ready, setup_contract, start


def test_pg_persistent_revision_triggers_and_atomic_parallel_step(postgres_database):  # noqa: F811
    engine, factory, *_ = postgres_database
    with engine.begin() as connection:
        ensure_rent_batch_schema(connection)
        ensure_rent_batch_schema(connection)  # Idempotent explicit bootstrap.
    with factory() as db:
        store = SQLAlchemyStore(db)
        contract, _ = setup_contract(store)
        assert db.get(RentSourceRevisionORM, ("contract", contract.id)).revision == 1
        job = ready(store, start(store, contract))
        job = control_batch(store, job["id"], BatchConfirm(cursor=job["cursor"], plan_hash=job["plan_hash"]), "confirm")
    barrier = Barrier(2)
    def run(_):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                return advance_batch(SQLAlchemyStore(db), job["id"], BatchAdvance(cursor=job["cursor"], budget=2))["created_count"]
            except BatchError as exc:
                return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(map(str, results)) == ["2", "RENT_CURSOR_STALE"]
    with factory() as db:
        restored = get_batch(SQLAlchemyStore(db), job["id"])
        assert restored["created_count"] == 2 and restored["revision"] == job["revision"] + 1
        assert db.scalar(select(RentSourceRevisionORM.revision).where(RentSourceRevisionORM.entity_type == "contract",
            RentSourceRevisionORM.entity_id == contract.id)) == 1  # No-op lock is not a price/term edit.
    assert engine.pool.checkedout() == 0


def test_pg_non_utc_database_clock_does_not_silently_omit_fresh_contracts(postgres_database):  # noqa: F811
    engine, factory, *_ = postgres_database
    with engine.begin() as connection:
        ensure_rent_batch_schema(connection)
    with factory() as db:
        db.execute(text("SET TIME ZONE 'Pacific/Auckland'"))
        db.commit()
        store = SQLAlchemyStore(db)
        contract, _ = setup_contract(store)
        job = ready(store, start(store, contract))
        assert job["contract_count"] == 1
