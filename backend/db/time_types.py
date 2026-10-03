"""Explicit UTC binds for physical timestamps without a timezone."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import TypeDecorator


class UTCNaiveDateTime(TypeDecorator[datetime]):
    """Normalize aware inputs; retain naive/legacy values and existing DDL."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value.tzinfo is None:
            return value
        try:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        except OverflowError:
            raise ValueError("Der UTC-Zeitpunkt liegt außerhalb des darstellbaren Bereichs.") from None


class UTCNaiveNow(FunctionElement[datetime]):
    """Database transaction time in UTC; no physical server-default change."""

    type = DateTime()
    inherit_cache = True


@compiles(UTCNaiveNow)
def _compile_utc_now(element, compiler, **kwargs):
    if compiler.dialect.name not in {"sqlite", "default"}:
        raise ValueError("UTC-Zeitpunkte unterstützen SQLite und PostgreSQL.")
    # Preserve SQLite's native second-resolution legacy representation.
    return "CURRENT_TIMESTAMP"


@compiles(UTCNaiveNow, "postgresql")
def _compile_postgres_utc_now(element, compiler, **kwargs):
    # now() keeps the existing transaction-start instant. Explicit conversion
    # prevents a session TimeZone cast when inserted into timestamp-without-zone.
    return "timezone('UTC', now())"
