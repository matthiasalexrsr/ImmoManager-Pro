"""Dedicated UUID PostgreSQL schemas only; no fallback pretending to be PG."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from backend.db.bank_import_models import BankImportReceiptORM
from backend.db.bank_import_schema import ensure_bank_import_schema
from backend.db.orm_models import BookingORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.tests.test_bank_imports import account, confirm, stage
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def test_pg_parallel_replay_publishes_one_complete_import(postgres_database):  # noqa: F811
    engine, factory, _, _ = postgres_database
    with engine.begin() as connection:
        ensure_bank_import_schema(connection)
    with factory() as db:
        store = SQLAlchemyStore(db)
        selected = account(store)
        job = stage(store, selected.id, "date;amount;text\n2026-01-01;1.01;Equal\n2026-01-01;1.01;Equal\n")
    barrier = Barrier(2)
    def worker():
        with factory() as db:
            barrier.wait(timeout=10)
            return confirm(SQLAlchemyStore(db), job)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert sorted(result["replay"] for result in results) == [False, True]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BookingORM)) == 2
        assert db.scalar(select(func.count()).select_from(BankImportReceiptORM)) == 2
