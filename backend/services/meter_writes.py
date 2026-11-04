"""Serialize reading validation with normal writes, handovers and imports."""
from contextlib import contextmanager
from decimal import Decimal
from itertools import groupby
from types import SimpleNamespace

from sqlalchemy import text

from .billing_writes import billing_write

METER_LOCK = 0x494D4D4F4D455452


def lock_meter_readings(db):
    if db is not None and db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": METER_LOCK})


@contextmanager
def meter_write(store, period_ids=()):
    # Import transactions take this same key before locking their target tables.
    # Keep the order also for document imports that touch both periods/readings.
    with billing_write(store, period_ids, before_locks=lock_meter_readings):
        yield


def validate_reading(store, data, reading_id=None):
    from .meter_history import _readings
    from .plausibility import meter_reading

    store.get_meter(data.meter_id)
    values = data.model_dump()
    if reading_id:
        values["id"] = reading_id
    meter_reading(values, SimpleNamespace(list_standalone_meter_readings=lambda: _readings(store, data.meter_id)))


def snapshot_problems(readings):
    """Every later day's lowest value is at least the preceding day's maximum."""
    errors = []
    ordered = sorted(readings, key=lambda r: (r.meter_id, r.reading_date))
    for meter_id, group in groupby(ordered, key=lambda r: r.meter_id):
        previous = None
        for day, daily in groupby(group, key=lambda r: r.reading_date):
            values = [Decimal(str(r.value)) for r in daily]
            if min(values) < 0 or (previous is not None and min(values) < previous):
                errors.append(f"Zähler {meter_id}: rückläufiger oder negativer Stand am {day:%d.%m.%Y}.")
                break
            previous = max(values)
    return errors
