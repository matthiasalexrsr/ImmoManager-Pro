"""Additive indexes for fixed booking keyset ordering; no data rewrites."""
from sqlalchemy import Index, inspect

from .booking_order import bytewise_id
from .orm_models import BookingORM

BOOKING_INDEXES = (
    Index("idx_bookings_date_id", BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()),
    Index("idx_bookings_account_date_id", BookingORM.account_id, BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()),
    Index("idx_bookings_property_date_id", BookingORM.property_id, BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()),
    Index("idx_bookings_tenant_date_id", BookingORM.tenant_id, BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()),
    Index("idx_bookings_status_date_id", BookingORM.status, BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()),
)


def ensure_booking_indexes(connection):
    inspector = inspect(connection)
    if not inspector.has_table("bookings"):
        return
    available = {column["name"] for column in inspector.get_columns("bookings")}
    for index in BOOKING_INDEXES:
        # Historical upgrade probes and partial legacy schemas may not yet
        # contain date/relationship columns. Never rewrite them to add an index.
        required = {column.name for column in index.columns}
        if required <= available:
            index.create(connection, checkfirst=True)
