"""Carry an accepted edit revision to the atomic write point of that request."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import String, case, func, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import CursorResult


@dataclass(frozen=True)
class ExpectedRevision:
    table: str
    record_id: str
    updated_at: datetime


_expected: ContextVar[dict[tuple[str, str], datetime] | None] = ContextVar("expected_record_revisions", default=None)


@contextmanager
def revision_scope(expected: ExpectedRevision | None) -> Iterator[None]:
    # Worker contexts share this request's dictionary, so consuming a revision
    # remains visible when FastAPI schedules the next call on another worker.
    values = {} if expected is None else {(expected.table, expected.record_id): expected.updated_at}
    token = _expected.set(values)
    try:
        yield
    finally:
        _expected.reset(token)


def expected_revision(table: str, record_id: str) -> datetime | None:
    return (_expected.get() or {}).get((table, record_id))


def consume_expected(table: str, record_id: str) -> None:
    values = _expected.get()
    if values is not None:
        values.pop((table, record_id), None)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def conflict() -> HTTPException:
    return HTTPException(409, "Der Datensatz wurde inzwischen geändert. Bitte neu laden und die Änderung "
                             "noch einmal eintragen, damit nichts überschrieben wird.")


def assert_expected(table: str, record_id: str, current_updated_at: datetime | None) -> None:
    expected = expected_revision(table, record_id)
    if expected is not None and (current_updated_at is None or _utc(current_updated_at) != _utc(expected)):
        raise conflict()


def compare_sql_revision(db: Any, orm: Any, record_id: str) -> None:
    """Compare and hold the row at its existing write point, after any parent locks."""
    table = orm.__table__
    expected = expected_revision(table.name, record_id)
    if expected is None:
        return
    matches = table.c.updated_at == expected
    if db.get_bind().dialect.name == "sqlite":
        # SQLite's CURRENT_TIMESTAMP omits fractional zeroes; SQLAlchemy binds
        # six digits. Normalize only trailing fractional zeroes, retaining the
        # full microsecond value instead of rounding it through julianday.
        raw = sql_cast(table.c.updated_at, String)
        canonical = case((func.instr(raw, ".") > 0, func.rtrim(func.rtrim(raw, "0"), ".")), else_=raw)
        value = expected.replace(tzinfo=None).isoformat(" ", timespec="microseconds").rstrip("0").rstrip(".")
        matches = canonical == value
    # The accepted database timestamp is exact, even when the submitted token
    # was rounded to milliseconds. The ORM update retains portfolio filters.
    with db.no_autoflush:
        result = cast(CursorResult[Any], db.execute(update(orm).where(
            table.c.id == record_id, matches,
        ).values(updated_at=table.c.updated_at).execution_options(synchronize_session=False)))
    if result.rowcount != 1:
        raise conflict()


def collection_table(collection: str) -> str:
    aliases = {"/maintenance": "maintenance_cases", "/calendar": "calendar_events",
               "/viewings": "viewing_appointments", "/billing/periods": "billing_periods",
               "/notifications/templates": "notification_templates", "/escalation/rules": "escalation_rules"}
    return aliases.get(collection, collection.rsplit("/", 1)[-1].replace("-", "_"))
