"""Synthetic disposable SQLite bank-import evidence; no customer inputs.

Run `python scripts/bank_import_benchmark.py --rows 100000 --output report.json`.
The record count is an evidence parameter, never a product import limit.
"""
import argparse
import json
import sys
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.db.bank_import_models import BankImportReceiptORM, BankImportRowORM
from backend.db.bank_import_schema import ensure_bank_import_schema
from backend.db.orm_models import Base, BookingORM
from backend.models import AccountCreate, PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.bank_import import BankConfirm, commit_import, preview_import, stage_import
from backend.services.bank_import_parser import BankMapping


def run(count):
    with tempfile.TemporaryDirectory(prefix="immo-synthetic-bank-import-") as directory:
        root = Path(directory)
        source = root / "synthetic.csv"
        with source.open("wb") as handle:
            handle.write(b"date;amount;text\n")
            for ordinal in range(count):
                amount = "1.01" if ordinal % 2 == 0 else "-0.01"
                handle.write(f"2026-01-01;{amount};Synthetic {ordinal}\n".encode())
        engine = create_engine(f"sqlite:///{root / 'synthetic.db'}", hide_parameters=True)
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_bank_import_schema(connection)
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            portfolio = store.create_portfolio(PortfolioCreate(name="SYNTHETIC BENCHMARK"))
            account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Synthetic bank", account_type="bank"))
            tracemalloc.start()
            start = perf_counter()
            with source.open("rb") as handle:
                job = stage_import(store, handle, account.id, BankMapping())
            staging_seconds = perf_counter() - start
            assert job["row_count"] == count and job["state"] == "ready"
            _, staging_peak = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            plan = db.execute(text("EXPLAIN QUERY PLAN SELECT ordinal FROM bank_import_rows "
                "WHERE import_id=:id AND ordinal>:after ORDER BY ordinal LIMIT 501"), {"id": job["id"], "after": count // 2}).all()
            assert any("INDEX" in str(row) for row in plan)
            first = preview_import(store, job["id"], page_size=100)
            assert len(first["items"]) == min(100, count)
            start = perf_counter()
            result = commit_import(store, job["id"], BankConfirm(revision=job["revision"], preview_hash=job["preview_hash"]))
            publish_seconds = perf_counter() - start
            _, publish_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert result["published_count"] == count
            assert db.scalar(select(func.count()).select_from(BookingORM)) == count
            assert db.scalar(select(func.count()).select_from(BankImportReceiptORM)) == count
            cents = db.scalar(select(func.sum(BankImportRowORM.amount_cents)).where(BankImportRowORM.import_id == job["id"]))
            assert cents == ((count + 1) // 2) * 101 - (count // 2)
            with source.open("rb") as handle:
                replay = stage_import(store, handle, account.id, BankMapping())
            assert replay["replay"] and replay["id"] == job["id"]
            report = {"synthetic": True, "database": "disposable SQLite", "rows": count,
                "file_bytes": source.stat().st_size, "row_sum_cents": cents,
                "staging_seconds": staging_seconds, "publication_seconds": publish_seconds,
                "staging_python_peak_bytes": staging_peak, "publication_python_peak_bytes": publish_peak,
                "memory_measurement": "tracemalloc Python allocations, not total process RSS",
                "paged_explain": [list(row) for row in plan], "replay_published_again": False}
        engine.dispose()
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.rows < 1:
        parser.error("--rows must be positive")
    result = run(arguments.rows)
    serialized = json.dumps(result, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(serialized, encoding="utf-8")
    print(serialized)
