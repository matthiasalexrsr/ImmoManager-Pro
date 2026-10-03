"""Complete filtered CSV in bounded SQL snapshot batches, with live read fences."""

import csv
import io

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import decode_token
from .booking_export import _snapshot, csv_cell
from .portfolio_scope import current_scope, refresh_scope, scope_context


def encode_rows(rows, fields, *, header=False):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    if header:
        writer.writerow(fields)
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key in fields])
    return (b"\xef\xbb\xbf" if header else b"") + output.getvalue().encode("utf-8")


def check_access(scope, token):
    refresh_scope(scope)
    if token is not None and decode_token(token).type != "access":
        raise HTTPException(401, "Bitte erneut anmelden.")


def csv_chunks(store, query, *, inventory, fields, token=None, chunk_size=100):
    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("Positive transfer batch required")
    if query.cursor is not None:
        raise HTTPException(422, "Der vollständige Export benötigt Filter, keinen Seitencursor.")
    scope = current_scope()
    check_access(scope, token)
    engine = store.db.get_bind() if hasattr(store, "db") else None

    def generate():
        if engine is None:
            from .payments import _memory_lock
            after, first = None, True
            while True:
                with _memory_lock, scope_context(scope):
                    check_access(scope, token)
                    rows = inventory.memory_page(store, query, scope, after, chunk_size)
                    chunk = encode_rows(rows, fields, header=first)
                yield chunk
                if len(rows) < chunk_size:
                    break
                after, first = (rows[-1][query.sort_by], rows[-1]["id"]), False
            return
        with _snapshot(engine) as connection, Session(bind=connection, autoflush=False) as snapshot:
            if query.search:
                inventory.ensure_sqlite_casefold(snapshot)
            after, first = None, True
            while True:
                with scope_context(scope):
                    check_access(scope, token)
                    rows = [dict(row) for row in snapshot.execute(inventory.ordered(
                        inventory.statement(query, scope), query, after, chunk_size)).mappings()]
                    # Names and related ownership can change independently of the
                    # record. Compare the current authorized projection before each
                    # batch instead of trusting access at export start forever.
                    if rows:
                        with Session(engine, autoflush=False) as live:
                            if query.search:
                                inventory.ensure_sqlite_casefold(live)
                            source = inventory.statement(query, scope).subquery()
                            current = {row["id"]: inventory.item(dict(row)).model_dump(mode="json") for row in
                                       live.execute(select(source).where(source.c.id.in_([row["id"] for row in rows]))).mappings()}
                        if any(current.get(row["id"]) != inventory.item(row).model_dump(mode="json") for row in rows):
                            raise HTTPException(409, "Daten oder Zuordnungen wurden geändert. Bitte den Export erneut starten.")
                    check_access(scope, token)
                    chunk = encode_rows(rows, fields, header=first)
                yield chunk
                if len(rows) < chunk_size:
                    break
                after, first = (rows[-1][query.sort_by], rows[-1]["id"]), False
    return generate()

