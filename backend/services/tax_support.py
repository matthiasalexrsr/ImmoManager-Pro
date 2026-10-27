"""Local tax export resources; no provider calls or money mutations."""
import threading
from contextlib import contextmanager, nullcontext
from datetime import date, datetime

_memory_lock = threading.RLock()

@contextmanager
def private_workspace(parent=None):
    from .tax_temp import tax_workspace
    with tax_workspace(parent) as directory:
        yield directory, None

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




def finance_write(function):
    """Bind writes to the live actor; hold the existing account lock through commit."""
    from functools import wraps

    @wraps(function)
    def guarded(store, command, actor_id):
        from .. import auth
        from .document_versions import begin_writer, check_account, memory_archive
        from .portfolio_scope import current_scope, refresh_scope
        captured = current_scope()
        try:
            if hasattr(store, "db"):
                begin_writer(store.db)
                if store.db.get_bind().dialect.name == "postgresql" and hasattr(command, "profile_version_id"):
                    # Fence source edits and phantoms through publication; the
                    # independent repeatable read alone cannot prevent them.
                    store.db.connection().exec_driver_sql(
                        "LOCK TABLE bookings, accounts, categories, properties IN SHARE MODE")
            with (auth.locked_account(actor_id, store.db if hasattr(store, "db") else None)
                  if captured is not None else nullcontext(None)) as user:
                if captured is not None:
                    if captured.user_id != actor_id:
                        from fastapi import HTTPException
                        raise HTTPException(403, "Die Sitzung stimmt nicht mit dem Auftrag überein.")
                    check_account(user, write_areas=("/reports",))
                    refresh_scope(captured)
                with (memory_archive(store).lock if not hasattr(store, "db") else nullcontext()):
                    return function(store, command, actor_id)
        except BaseException:
            if hasattr(store, "db"):
                store.db.rollback()
            raise
    return guarded


def check_saved_booking(store, identifier):
    """Retain deleted sources, but deny a surviving source moved outside today's scope."""
    from sqlalchemy import select

    from ..db.orm_models import BookingORM
    from .portfolio_scope import current_scope

    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    if hasattr(store, "db"):
        # Core existence check contains no disclosed fields and deliberately does
        # not confuse a deleted original with an existing but unauthorized one.
        with store.db.get_bind().connect() as connection:
            exists = connection.scalar(select(BookingORM.__table__.c.id).where(BookingORM.__table__.c.id == identifier))
    else:
        exists = identifier in object.__getattribute__(store, "__dict__")["bookings"]
    if exists:
        store.get_booking(identifier)
