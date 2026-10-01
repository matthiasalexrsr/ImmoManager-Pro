"""Compatible offset reads, applying all filters before slicing."""
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select

from ..db.orm_models import BookingORM
from ..models import Booking

SORT_FIELDS = frozenset(BookingORM.__table__.columns.keys())


def legacy_booking_list(store, *, skip, limit, filters, sort_by, descending, date_from, date_to):
    if hasattr(store, "db"):
        statement = select(BookingORM.__table__)
        for field, value in filters.items():
            if value is not None:
                statement = statement.where(getattr(BookingORM, field) == value)
        if date_from:
            statement = statement.where(BookingORM.booking_date >= date_from)
        if date_to:
            statement = statement.where(BookingORM.booking_date <= date_to)
        if sort_by in SORT_FIELDS:
            column = getattr(BookingORM, sort_by)
            statement = statement.order_by(column.desc() if descending else column.asc())
        with store.db.no_autoflush:
            with store.db.execute(statement.offset(skip).limit(limit)) as result:
                return [Booking.model_validate(row) for row in result.mappings()]
    values: Iterable[Any] = (item for item in store.bookings.values()
        if all(value is None or getattr(item, field) == value for field, value in filters.items())
        and (date_from is None or item.booking_date >= date_from)
        and (date_to is None or item.booking_date <= date_to))
    if sort_by in SORT_FIELDS:
        values = sorted(values, key=lambda item: (getattr(item, sort_by) is None, getattr(item, sort_by)), reverse=descending)
    # Memory is a reference implementation; the persisted path performs SQL
    # WHERE/LIMIT/OFFSET and never materializes the entire database.
    from itertools import islice
    return list(islice(values, skip, skip + limit))
