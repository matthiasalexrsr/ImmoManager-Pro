"""Explicit archived budgets, offline proof and shared retained-history fences."""

import sqlite3
import time
from collections.abc import Mapping
from contextlib import ExitStack, closing, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from ..db.integration_history_models import TABLES
from ..db.integration_history_schema import ensure_history_schema
from .integrations.history_restore import mark_restored_unconfirmed
from .integrations.history_store import configured_history, history_fence, lock_history_fence
from .integrations.history_types import HistoryError, HistoryLimits
from .integrations.history_validation import validate_history_journal
from .recovery_archive import RecoveryError

FACT_TABLES = frozenset(TABLES[1:4])
TECHNICAL_TABLES = frozenset((TABLES[0], TABLES[4]))
_memory_connection: ContextVar[Connection | None] = ContextVar("retained_history_memory_connection", default=None)
RETENTION_MESSAGE = "Gespeicherte Integrationsläufe und Ergebnisnachweise benötigen eine vollständige Offline-Sicherung/Wiederherstellung. Teilimport oder Geschäftsreset wurde vor Datenänderung abgebrochen."


def history_limits_from_configuration(configuration: Mapping[str, object]) -> HistoryLimits:
    """Never instantiate Settings, read an environment file or resolve keys."""
    defaults = HistoryLimits()
    values: list[int] = []
    for name, default in (("INTEGRATION_HISTORY_ARTIFACT_BYTES", defaults.artifact_bytes),
                          ("INTEGRATION_HISTORY_PAGE_BYTES", defaults.page_bytes),
                          ("INTEGRATION_HISTORY_TEMP_BYTES", defaults.temp_bytes)):
        value = configuration.get(name, default)
        if isinstance(value, str):
            value = value.strip()
            if not value.isascii() or not value.isdecimal():
                raise ValueError("integration_history_budget_invalid: positive integer bytes required")
            value = int(value)
        if type(value) is not int:
            raise ValueError("integration_history_budget_invalid: positive integer bytes required")
        values.append(cast(int, value))
    timeout = configuration.get("INTEGRATION_HISTORY_TIMEOUT_SECONDS", defaults.timeout_seconds)
    if isinstance(timeout, str):
        try:
            timeout = float(timeout)
        except ValueError:
            raise ValueError("integration_history_budget_invalid: positive finite time required") from None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("integration_history_budget_invalid: positive finite time required")
    return HistoryLimits(artifact_bytes=values[0], page_bytes=values[1], temp_bytes=values[2], timeout_seconds=timeout)


def _proof_deadline(limits, deadline):
    local = time.monotonic() + limits.timeout_seconds
    return local if deadline is None else min(local, deadline)


def validate_configured_history(connection, configuration, *, deadline=None) -> bool:
    # Entire old images remain compatible before both budget and key lookup.
    if not ensure_history_schema(connection):
        return False
    limits = history_limits_from_configuration(configuration)
    return validate_history_journal(connection, configuration, deadline=_proof_deadline(limits, deadline), limits=limits)


def normalize_restored_history(connection, configuration, *, deadline=None) -> int:
    if not ensure_history_schema(connection):
        return 0
    limits = history_limits_from_configuration(configuration)
    return mark_restored_unconfirmed(connection, configuration, deadline=_proof_deadline(limits, deadline), limits=limits)


def verify_history(database: Path, configuration: Mapping[str, object], *, deadline=None) -> bool:
    """Proof of the unchanged archive image; no factory/auth/DML or publication."""
    try:
        remaining = 300.0 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise HistoryError("HISTORY_BUDGET_EXCEEDED")
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=min(0.2, remaining))) as connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
            if deadline is not None:
                connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            connection.execute("BEGIN")
            return validate_configured_history(connection, configuration, deadline=deadline)
    except (HistoryError, ValueError, sqlite3.Error):
        raise RecoveryError("Integrationshistorie konnte mit der gesicherten Schlüssel- und Budgetkonfiguration nicht vollständig geprüft werden. Unveränderte vollständige Sicherung verwenden; das Ziel wurde nicht freigegeben.") from None


def _guard_facts(connection):
    from ..storage import ValidationError

    if ensure_history_schema(connection) and any(
            connection.execute(text('SELECT 1 FROM "' + name + '" LIMIT 1')).first() is not None
            for name in sorted(FACT_TABLES)):
        raise ValidationError(RETENTION_MESSAGE)


def guard_history_retention(store, *, serialized=False):
    """Bounded actual journal facts; technical heads/clear audits do not block."""
    from ..storage import ValidationError

    try:
        if hasattr(store, "db"):
            db = store.db
            with db.no_autoflush:
                if any(getattr(getattr(row, "__table__", None), "name", None) in TABLES
                       for row in db.new | db.dirty | db.deleted):
                    raise ValidationError("Ungespeicherte Integrationshistorie: Reset/Teiloperation vor Datenänderung abgebrochen.")
                connection = db.connection()
                if serialized:
                    # Call only after the caller's existing account/domain fence.
                    # NOWAIT plus a savepoint preserves its pending transaction.
                    with connection.begin_nested():
                        lock_history_fence(connection, nowait=True)
                _guard_facts(connection)
            return
        current = _memory_connection.get()
        if current is not None:
            _guard_facts(current)
        else:
            with configured_history().connection() as connection:
                _guard_facts(connection)
    except HistoryError:
        raise ValidationError("Die dauerhafte Integrationshistorie ist nicht vollständig verfügbar. Teiloperation vor Datenänderung abgebrochen.") from None
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) != "55P03":
            raise
        raise ValidationError("Ein laufender Integrationsschreibvorgang verhindert den sicheren Reset/Teilimport. Nach dessen Abschluss erneut versuchen.") from None


@contextmanager
def _memory_fenced_connection():
    from .correspondence_calendar import account_lock
    from .payments import _memory_lock

    with configured_history().factory() as session:
        sqlite = session.get_bind().dialect.name == "sqlite"
    if sqlite:
        # The versioned core must obtain BEGIN IMMEDIATE before MemoryAuth.
        # Transfer its cleanup inside the domain/account contexts so SQL commit
        # finishes while those outer authority locks still remain held.
        with ExitStack() as reservation:
            connection = reservation.enter_context(history_fence())
            with account_lock(), _memory_lock, reservation.pop_all():
                yield connection
    else:
        with account_lock(), _memory_lock, history_fence() as connection:
            yield connection


@contextmanager
def memory_history_boundary():
    """Shared journal through publication; SQLite writer precedes MemoryAuth."""
    current = _memory_connection.get()
    if current is not None:
        yield current
        return
    with _memory_fenced_connection() as connection:
        token = _memory_connection.set(connection)
        try:
            yield connection
        finally:
            _memory_connection.reset(token)
