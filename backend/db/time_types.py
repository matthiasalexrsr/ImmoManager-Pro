"""Explicit UTC binds for physical timestamps without a timezone."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
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
