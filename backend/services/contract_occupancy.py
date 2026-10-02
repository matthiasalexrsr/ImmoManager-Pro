"""Shared transaction locks and inclusive active-tenancy date conflicts.

Draft contracts are non-reserving. Legacy metadata-only edits do not reinterpret
existing overlapping history. A terminated tenancy retains its rental end day.
"""

from contextlib import contextmanager
from datetime import date

from sqlalchemy import or_, select

from ..db.orm_models import ContractORM, PropertyORM, UnitORM
from ..storage import ValidationError
from .payments import _memory_lock

BLOCKED = frozenset({"inactive", "archived", "maintenance", "unavailable"})


def begin_writer(db):
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def lock_location(store, property_id, unit_id):
    if hasattr(store, "db"):
        begin_writer(store.db)
        # Native row locks serialize normal creates, wizard publication and
        # relocation edits across processes; SELECT also keeps scopes applied.
        for model, identifier in ((PropertyORM, property_id), (UnitORM, unit_id)):
            if store.db.scalar(select(model.id).where(model.id == identifier).with_for_update()) is None:
                raise ValidationError("Immobilie oder Einheit nicht gefunden.")
    property = store.get_property(property_id)
    unit = store.get_unit(unit_id)
    if unit.property_id != property_id:
        raise ValidationError("Einheit gehört nicht zur ausgewählten Immobilie.")
    return property, unit


def assert_occupancy(store, data, *, exclude_id=None):
    property, unit = lock_location(store, data.property_id, data.unit_id)
    if data.end_date and data.end_date < data.start_date:
        raise ValidationError("Das Enddatum liegt vor dem Mietbeginn.")
    if data.status not in {"active", "terminated"}:
        return
    if data.status == "active" and (property.status in BLOCKED or unit.status in BLOCKED):
        raise ValidationError("Immobilie oder Einheit ist für eine aktive Vermietung gesperrt.")
    if hasattr(store, "db"):
        # Occupancy is a safety condition, including any already existing
        # tenancy of this exact accessible unit. No full getAll collection.
        query = select(ContractORM.id).where(ContractORM.unit_id == data.unit_id,
            ContractORM.status.in_(("active", "terminated")),
            ContractORM.start_date <= (data.end_date or date.max),
            or_(ContractORM.end_date.is_(None), ContractORM.end_date >= data.start_date))
        if exclude_id:
            query = query.where(ContractORM.id != exclude_id)
        conflict = store.db.scalar(query.limit(1)) is not None
    else:
        conflict = any(row.id != exclude_id and row.unit_id == data.unit_id
            and row.status in {"active", "terminated"}
            and row.start_date <= (data.end_date or date.max)
            and (row.end_date is None or row.end_date >= data.start_date)
            for row in store.contracts.values())
    if conflict:
        raise ValidationError("Der Mietzeitraum überschneidet sich mit einem aktiven oder noch laufenden gekündigten Vertrag. Entwurf bleibt möglich.")


@contextmanager
def creation_guard(store, data, *, exclude_id=None, previous=None):
    # All normal create/activation/date relocation paths use the same boundary.
    fields = ("property_id", "unit_id", "start_date", "end_date", "status")
    check = previous is None or any(getattr(previous, key) != getattr(data, key) for key in fields)
    with _memory_lock if not hasattr(store, "db") else _null():
        try:
            if check:
                assert_occupancy(store, data, exclude_id=exclude_id)
            yield
        except Exception:
            if hasattr(store, "db"):
                store.db.rollback()
            raise


@contextmanager
def _null():
    yield
