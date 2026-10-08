"""One way to read and write the project tables on both stores, inside one unit of work.

SQL: ORM rows of the unit's session, so the portfolio boundary (services.portfolio_scope)
applies to every read and write and nothing commits before the unit ends. Memory: the
store's collections (bounded the same way for restricted accounts); every change is
recorded in the unit's undo list, so a failing unit leaves the store as it was.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from .. import maintenance_models as mm
from ..db import maintenance_project_models as pm
from ..db.orm_models import (
    BookingORM,
    CalendarEventORM,
    ChangeHistoryORM,
    DocumentORM,
    EntityPhotoORM,
    InvoiceORM,
    MaintenanceCaseORM,
)
from ..storage import NotFoundError
from . import memory_cascade

PROJECT = frozenset(pm.PROJECT_TABLES)


@lru_cache(maxsize=1)
def registry() -> dict[str, tuple[Any, type[BaseModel]]]:
    from .. import models   # the UI contract fields extend some models at import time

    return {
        "maintenance_work_packages": (pm.MaintenanceWorkPackageORM, mm.MaintenanceWorkPackage),
        "maintenance_dependencies": (pm.MaintenanceDependencyORM, mm.MaintenanceDependency),
        "maintenance_participants": (pm.MaintenanceParticipantORM, mm.MaintenanceParticipant),
        "maintenance_quotes": (pm.MaintenanceQuoteORM, mm.MaintenanceQuote),
        "maintenance_orders": (pm.MaintenanceOrderORM, mm.MaintenanceOrder),
        "maintenance_change_orders": (pm.MaintenanceChangeOrderORM, mm.MaintenanceChangeOrder),
        "maintenance_order_invoices": (pm.MaintenanceOrderInvoiceORM, mm.MaintenanceOrderInvoice),
        "invoice_payments": (pm.InvoicePaymentORM, mm.InvoicePayment),
        "maintenance_protocols": (pm.MaintenanceProtocolORM, mm.MaintenanceProtocol),
        "maintenance_appointments": (pm.MaintenanceAppointmentORM, mm.MaintenanceAppointment),
        "maintenance_case_documents": (pm.MaintenanceCaseDocumentORM, mm.MaintenanceCaseDocument),
        "maintenance_cases": (MaintenanceCaseORM, models.MaintenanceCase),
        "invoices": (InvoiceORM, models.Invoice),
        "bookings": (BookingORM, models.Booking),
        "calendar_events": (CalendarEventORM, models.CalendarEvent),
        "documents": (DocumentORM, models.Document),
        "change_history": (ChangeHistoryORM, models.ChangeHistoryEntry),
        "entity_photos": (EntityPhotoORM, models.EntityPhoto),
    }


def stamp(table: str) -> datetime:
    """Now, as the table's records keep it: naive UTC in project tables, UTC-aware elsewhere."""
    now = datetime.now(timezone.utc)
    return now.replace(tzinfo=None) if table in PROJECT else now


class Rows:
    def __init__(self, store: Any, db: Any = None, undo: list | None = None):
        self.store, self.db = store, db
        self.undo = undo if undo is not None else []

    @classmethod
    def of(cls, unit: Any) -> Rows:
        return cls(unit.store, unit.db, unit._undo)

    @classmethod
    def reading(cls, store: Any) -> Rows:
        return cls(store, getattr(store, "db", None))

    # ─── reading ─────────────────────────────────────────────────────────
    def _model(self, table: str, obj: Any) -> Any:
        orm, model = registry()[table]
        return model.model_validate({column.key: getattr(obj, column.key) for column in orm.__table__.columns})

    def _collection(self, table: str) -> Any:
        return getattr(self.store, table)        # bounded for a restricted account

    def _raw(self) -> dict[str, Any]:
        return object.__getattribute__(self.store, "__dict__")

    def get(self, table: str, key: str | None) -> Any:
        if not key:
            return None
        if self.db is not None:
            obj = self.db.get(registry()[table][0], key)
            return None if obj is None else self._model(table, obj)
        return self._collection(table).get(key)

    def require(self, table: str, key: str | None, message: str) -> Any:
        found = self.get(table, key)
        if found is None:
            raise NotFoundError(message)
        return found

    def find(self, table: str, **criteria: Any) -> list[Any]:
        """Rows whose columns equal the criteria; a list, tuple or set value means "one of"."""
        lists = {k: list(v) for k, v in criteria.items() if isinstance(v, (list, tuple, set, frozenset))}
        if any(not values for values in lists.values()):
            return []
        if self.db is not None:
            orm = registry()[table][0]
            query = select(orm)
            for key, value in criteria.items():
                if key not in lists:
                    column = getattr(orm, key)
                    query = query.where(column.is_(None) if value is None else column == value)
            found: list[Any] = []
            if not lists:
                found = list(self.db.scalars(query))
            else:
                (key, values), *others = lists.items()
                for other, other_values in others:
                    query = query.where(getattr(orm, other).in_(other_values))
                for start in range(0, len(values), 500):
                    found += self.db.scalars(query.where(getattr(orm, key).in_(values[start:start + 500])))
            result = [self._model(table, obj) for obj in found]
        else:
            result = [row for row in self._collection(table).values()
                      if all(getattr(row, k, None) in lists[k] if k in lists else getattr(row, k, None) == v
                             for k, v in criteria.items())]
        return sorted(result, key=lambda row: (str(getattr(row, "created_at", "")), row.id))

    def lock(self, table: str, key: str) -> bool:
        """Hold the row until the unit ends (PostgreSQL; SQLite and memory hold the whole store)."""
        if self.db is not None:
            orm = registry()[table][0]
            return self.db.scalar(select(orm.id).where(orm.id == key).with_for_update()) is not None
        return key in self._collection(table)

    # ─── writing ─────────────────────────────────────────────────────────
    def add(self, table: str, record: Any) -> Any:
        if self.db is not None:
            orm = registry()[table][0]
            values = {column.key: getattr(record, column.key) for column in orm.__table__.columns
                      if hasattr(record, column.key)}
            self.db.add(orm(**values))
            self.db.flush()
            return record
        self.undo.append((self._raw()[table], record.id, False, None))
        self._collection(table)[record.id] = record
        return record

    def update(self, table: str, key: str, **changes: Any) -> Any:
        model = registry()[table][1]
        if "updated_at" in model.model_fields and "updated_at" not in changes:
            changes["updated_at"] = stamp(table)
        if self.db is not None:
            obj = self.db.get(registry()[table][0], key)
            if obj is None:
                raise NotFoundError("Datensatz nicht gefunden")
            for name, value in changes.items():
                setattr(obj, name, value)
            self.db.flush()
            return self._model(table, obj)
        collection = self._collection(table)
        old = collection.get(key)
        if old is None:
            raise NotFoundError("Datensatz nicht gefunden")
        new = model.model_validate({**old.model_dump(), **changes})
        self.undo.append((self._raw()[table], key, True, old))
        collection[key] = new
        return new

    def delete(self, table: str, key: str) -> None:
        if self.db is not None:
            obj = self.db.get(registry()[table][0], key)
            if obj is None:
                raise NotFoundError("Datensatz nicht gefunden")
            self.db.delete(obj)
            self.db.flush()
            self.db.expire_all()        # the database's ON DELETE rules changed other rows
            return
        collection = self._collection(table)
        if key not in collection:
            raise NotFoundError("Datensatz nicht gefunden")
        raw = self._raw()
        memory_cascade.apply(raw, memory_cascade.plan(raw, table, key), self.undo)
        self.undo.append((raw[table], key, True, dict.__getitem__(raw[table], key)))
        del collection[key]
