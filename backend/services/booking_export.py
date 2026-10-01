"""All matching bookings as CSV, using a read snapshot and bounded SQL batches."""
import csv
import io
from contextlib import contextmanager
from datetime import date, datetime

import anyio
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .booking_query import booking_key, booking_statement, memory_page
from .payments import _memory_lock

CSV_CHUNK_SIZE = 1000
CSV_FIELDS = ("id", "booking_date", "account_id", "category_id", "property_id", "unit_id", "tenant_id",
              "amount", "allocated_amount", "status", "payment_text", "receipt_url", "created_at", "updated_at")


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if not isinstance(value, str):
        return value
    # Protect text cells, including whitespace-prefixed formulas. Numeric money
    # columns remain numbers; a legitimate negative expense is not rewritten.
    if value[:1] in ("\t", "\r", "\n", "\0") or value.lstrip(" \t\r\n\0").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@contextmanager
def _snapshot(engine):
    connection = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            transaction = connection.begin()
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        elif engine.dialect.name == "sqlite":
            # Python's SQLite legacy mode otherwise does not BEGIN on SELECT.
            connection.exec_driver_sql("BEGIN")
            transaction = connection.get_transaction()
        else:
            raise RuntimeError("Booking snapshots support SQLite and PostgreSQL")
        try:
            yield connection
        finally:
            transaction.rollback()
    finally:
        connection.close()


def _csv_rows(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key in CSV_FIELDS])
    return output.getvalue().encode("utf-8")


def _header():
    output = io.StringIO(newline="")
    csv.writer(output, delimiter=";", lineterminator="\r\n").writerow(CSV_FIELDS)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def _sql_chunks(engine, filters, chunk_size):
    with _snapshot(engine) as connection:
        after = None
        # Establish the snapshot before yielding the CSV header, not after the
        # client has started receiving the file.
        rows = connection.execute(booking_statement(filters, limit=chunk_size)).mappings().all()
        yield _header()
        while rows:
            yield _csv_rows(rows)
            last = rows[-1]
            after = last["booking_date"], last["id"]
            rows = connection.execute(booking_statement(filters, after=after, limit=chunk_size)).mappings().all()


def _memory_chunks(store, filters, chunk_size):
    # Memory is an explicitly transient reference backend. A shallow snapshot
    # retains immutable models, while CSV buffers remain bounded to one batch.
    with _memory_lock:
        snapshot = tuple(store.bookings.values())
    after = None
    yield _header()
    while True:
        rows = memory_page(snapshot, filters, after=after, limit=chunk_size)
        if not rows:
            break
        yield _csv_rows(row.model_dump() for row in rows)
        after = booking_key(rows[-1])


def booking_csv_chunks(store, filters, *, chunk_size=CSV_CHUNK_SIZE):
    if type(chunk_size) is not int or not 1 <= chunk_size <= 5000:
        raise ValueError("CSV transfer chunk size must be from 1 through 5000")
    if hasattr(store, "db"):
        return _sql_chunks(store.db.get_bind(), filters, chunk_size)
    return _memory_chunks(store, filters, chunk_size)


async def closing_chunks(iterator):
    """Close private snapshot connections on completion or client cancellation."""
    try:
        async for chunk in iterate_in_threadpool(iterator):
            yield chunk
    finally:
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(iterator.close)
