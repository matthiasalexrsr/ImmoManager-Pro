"""Owned synthetic SQLite only; never opens a supplied/user database.

python scripts/benchmark_booking_pages.py --rows 100000 --output work/booking-scale.json
An optional --rows 1000000 run is explicit and is never part of default pytest.
"""
import argparse
import hashlib
import json
import statistics
import sys
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.db.booking_indexes import BOOKING_INDEXES  # noqa: F401
from backend.db.orm_models import AccountORM, Base, BookingORM, PortfolioORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.booking_export import booking_csv_chunks
from backend.services.booking_query import BookingFilters, BookingPageQuery, booking_statement, get_booking_page


def measure(rows):
    with TemporaryDirectory(prefix="immo-synthetic-bookings-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'benchmark.db'}")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                connection.execute(PortfolioORM.__table__.insert(), dict(id="synthetic", name="Synthetic benchmark"))
                connection.execute(AccountORM.__table__.insert(), [dict(id=f"account-{n}", portfolio_id="synthetic", name=f"Synthetic {n}", account_type="bank") for n in range(2)])
                days_per_row = max(1, (rows + 7304) // 7305)
                for start in range(0, rows, 1000):
                    connection.execute(BookingORM.__table__.insert(), [{"id": f"booking-{n:012d}", "account_id": f"account-{n % 2}",
                        "booking_date": date(2006, 10, 1) + timedelta(days=n // days_per_row), "amount": 12.50 if n % 2 else -9.50,
                        "status": "open", "payment_text": f"Synthetic rental-note-{n:012d}"} for n in range(start, min(rows, start + 1000))])
                connection.exec_driver_sql("ANALYZE")
            with Session(engine) as db:
                active = SQLAlchemyStore(db)
                query = BookingPageQuery(page_size=100)
                times, cursor = [], None
                tracemalloc.start()
                for _ in range(min(50, (rows + 99) // 100)):
                    start = perf_counter()
                    result = get_booking_page(active, query.model_copy(update={"cursor": cursor}))
                    times.append((perf_counter() - start) * 1000)
                    cursor = result.next_cursor
                    if cursor is None:
                        break
                _, page_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                boundary = db.execute(select(BookingORM.booking_date, BookingORM.id).where(BookingORM.id == f"booking-{rows // 2:012d}")).one()
                plans = {}
                for name, filters in (("all", BookingFilters()), ("account", BookingFilters(account_id="account-1"))):
                    statement = booking_statement(filters, after=tuple(boundary), limit=101)
                    compiled = statement.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
                    plans[name] = [value[3] for value in db.execute(text("EXPLAIN QUERY PLAN " + str(compiled)))]
                tracemalloc.start()
                start = perf_counter()
                digest, byte_count, chunks, lines = hashlib.sha256(), 0, 0, 0
                for chunk in booking_csv_chunks(active, BookingFilters()):
                    digest.update(chunk)
                    byte_count += len(chunk)
                    chunks += 1
                    lines += chunk.count(b"\n")  # synthetic fields contain no embedded newlines
                csv_seconds = perf_counter() - start
                _, csv_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            return {"rows": rows, "database": "owned synthetic SQLite", "page_size": 100,
                "measured_pages": len(times), "page_median_ms": statistics.median(times), "page_max_ms": max(times),
                "page_python_peak_bytes": page_peak, "query_plans": plans,
                "csv_rows": lines - 1, "csv_chunks": chunks, "csv_bytes": byte_count, "csv_sha256": digest.hexdigest(),
                "csv_seconds": csv_seconds, "csv_python_peak_bytes": csv_peak,
                "memory_measurement": "tracemalloc Python allocations; excludes database/native driver/OS memory"}
        finally:
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("--rows must be positive")
    result = measure(args.rows)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
