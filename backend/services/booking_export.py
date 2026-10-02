"""All matching bookings as CSV, using a read snapshot and bounded SQL batches."""
import csv
import io
from contextlib import contextmanager
from datetime import date, datetime

import anyio
from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from ..db.orm_models import BookingORM
from .booking_query import booking_key, booking_statement, memory_page
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scope_context, scoped_clause

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


def _check_live_sql_rows(engine, rows, scope):
    """Check current ownership outside the export's immutable read snapshot."""
    if scope is None or scope.unrestricted or not rows:
        return
    table = BookingORM.__table__
    identifiers = {row["id"] for row in rows}
    with engine.connect() as live:
        visible = set(live.execute(select(table.c.id).where(
            table.c.id.in_(identifiers), scoped_clause(table, scope=scope))).scalars())
    if visible != identifiers:
        raise HTTPException(403, "Die Portfoliozuordnung wurde geändert. Bitte den Export erneut starten.")


def _sql_chunks(engine, filters, chunk_size, scope):
    # Captured scope, rather than the iterator worker's ambient ContextVar.
    with scope_context(scope):
        refresh_scope(scope)
    with _snapshot(engine) as connection:
        after = None
        # Establish the snapshot before yielding the CSV header, not after the
        # client has started receiving the file.
        with scope_context(scope):
            rows = connection.execute(booking_statement(filters, limit=chunk_size, scope=scope)).mappings().all()
            refresh_scope(scope)
            _check_live_sql_rows(engine, rows, scope)
        yield _header()
        while rows:
            with scope_context(scope):
                refresh_scope(scope)
                _check_live_sql_rows(engine, rows, scope)
            yield _csv_rows(rows)
            last = rows[-1]
            after = last["booking_date"], last["id"]
            with scope_context(scope):
                rows = connection.execute(booking_statement(filters, after=after, limit=chunk_size, scope=scope)).mappings().all()
        with scope_context(scope):
            refresh_scope(scope)


def _memory_chunks(store, filters, chunk_size, scope):
    # Memory is an explicitly transient reference backend. A shallow snapshot
    # retains immutable models, while CSV buffers remain bounded to one batch.
    with _memory_lock, scope_context(scope):
        refresh_scope(scope)
        snapshot = tuple(store.bookings.values())
    after = None
    yield _header()
    while True:
        rows = memory_page(snapshot, filters, after=after, limit=chunk_size)
        if not rows:
            break
        with _memory_lock, scope_context(scope):
            refresh_scope(scope)
            if scope is not None and not scope.unrestricted and any(
                (live := store.bookings.get(row.id)) is None
                or not memory_visible(store, "bookings", live, scope=scope) for row in rows
            ):
                raise HTTPException(403, "Die Portfoliozuordnung wurde geändert. Bitte den Export erneut starten.")
        yield _csv_rows(row.model_dump() for row in rows)
        after = booking_key(rows[-1])
    with scope_context(scope):
        refresh_scope(scope)


def booking_csv_chunks(store, filters, *, chunk_size=CSV_CHUNK_SIZE):
    if type(chunk_size) is not int or not 1 <= chunk_size <= 5000:
        raise ValueError("CSV transfer chunk size must be from 1 through 5000")
    scope = current_scope()
    if hasattr(store, "db"):
        return _sql_chunks(store.db.get_bind(), filters, chunk_size, scope)
    return _memory_chunks(store, filters, chunk_size, scope)


async def closing_chunks(iterator):
    """Close private snapshot connections on completion or client cancellation."""
    try:
        async for chunk in iterate_in_threadpool(iterator):
            yield chunk
    finally:
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(iterator.close)
