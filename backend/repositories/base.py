"""Generic base repository for CRUD operations.

All database operations are wrapped with error handling via
safe_db_operation to catch SQLAlchemy errors and convert them
to DatabaseOperationError with proper logging.
"""

import logging
from typing import Any, NoReturn, cast
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import String, delete, exists, or_, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from ..db.orm_models import Base
from ..error_helpers import safe_db_operation
from ..safe_diagnostics import exception_diagnostic
from ..services.concurrency import conflict, expected_revision, next_updated_at
from ..storage import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

def _generate_id() -> str:
    return str(uuid4())


def _orm_to_dict(orm_obj: Base) -> dict[str, Any]:
    """Extract column values from an ORM object as a dict."""
    try:
        return {c.key: getattr(orm_obj, c.key) for c in orm_obj.__table__.columns}
    except Exception:
        logger.error("Failed to convert ORM object to dict: %s", type(orm_obj).__name__)
        raise


class BaseRepository:
    """Generic CRUD repository for a single entity type.

    Error handling strategy:
    - NotFoundError is raised for missing entities (caught by global handler → 404)
    - SQLAlchemy errors are caught by @safe_db_operation → DatabaseOperationError → 500
    - Pydantic validation errors in _to_pydantic propagate naturally → 422
    """

    def __init__(
        self,
        db: Session,
        orm_class: type[Base],
        read_class: type[PydanticBaseModel],
        not_found_msg: str,
    ):
        self.db = db
        self.orm_class = orm_class
        self.read_class = read_class
        self.not_found_msg = not_found_msg

    def _to_pydantic(self, orm_obj: Base) -> Any:
        try:
            return self.read_class.model_validate(_orm_to_dict(orm_obj))
        except Exception as exc:
            logger.error(
                "Failed to validate %s from ORM %s: diagnostic=%s",
                self.read_class.__name__,
                type(orm_obj).__name__,
                exception_diagnostic(exc),
            )
            raise

    def _booking_condition(self, orm_obj, updates):
        if self.orm_class.__tablename__ != "bookings":
            return None
        from ..db.credit_models import CreditReceiptORM
        from ..db.orm_models import PaymentORM
        from ..services.payment_integrity import BOOKING_FIELDS, guard_booking_edit
        has_receipts = self.db.scalar(select(PaymentORM.id).where(PaymentORM.booking_id == orm_obj.id).limit(1)) is not None
        has_receipts = has_receipts or self.db.scalar(select(CreditReceiptORM.id)
            .where(CreditReceiptORM.booking_id == orm_obj.id).limit(1)) is not None
        guard_booking_edit(orm_obj, updates, has_receipts)
        if not any(key in updates and updates[key] != getattr(orm_obj, key) for key in BOOKING_FIELDS):
            return None
        # Allocation may race a booking edit. Both writes arbitrate on the booking row.
        return (~exists(select(PaymentORM.id).where(PaymentORM.booking_id == orm_obj.id)) &
            ~exists(select(CreditReceiptORM.id).where(CreditReceiptORM.booking_id == orm_obj.id)))

    def _revision_condition(self, entity_id):
        try:
            expected = expected_revision(self.orm_class.__tablename__, entity_id)
        except HTTPException:
            self.db.rollback()
            raise
        if expected is None:
            return None
        column = getattr(self.orm_class, "updated_at", None)
        if column is None:
            self.db.rollback()
            raise conflict()
        # Existing DateTime columns are UTC without timezone on SQLite/PostgreSQL.
        stamp = expected.updated_at if column.type.timezone else expected.updated_at.replace(tzinfo=None)
        if self.db.get_bind().dialect.name == "sqlite" and stamp.microsecond == 0:
            # SQLite CURRENT_TIMESTAMP stores seconds without a fraction, while
            # SQLAlchemy's DateTime bind always includes .000000. Keep exact
            # equality for both existing representations, without truncating
            # microseconds or changing historical rows just to create a token.
            return or_(column == stamp, sql_cast(column, String) == stamp.strftime("%Y-%m-%d %H:%M:%S"))
        return column == stamp

    def _missing(self, entity_id) -> NoReturn:
        if self._revision_condition(entity_id) is not None:
            self.db.rollback()
            raise conflict()
        raise NotFoundError(self.not_found_msg)

    def _write(self, entity_id, updates):
        orm_obj = self.db.get(self.orm_class, entity_id, populate_existing=True)
        if orm_obj is None:
            self._missing(entity_id)
        from ..services.portfolio_scope import guard_sql_write
        guard_sql_write(self.db, self.orm_class.__table__, {**_orm_to_dict(orm_obj), **updates}, entity_id=entity_id)
        self._guard_contract_update(orm_obj, updates)
        booking_condition = self._booking_condition(orm_obj, updates)
        revision_condition = self._revision_condition(entity_id)
        conditions = [getattr(self.orm_class, "id") == entity_id]
        if booking_condition is not None:
            conditions.append(booking_condition)
        if revision_condition is not None:
            conditions.append(revision_condition)
        if hasattr(self.orm_class, "updated_at"):
            stamp = next_updated_at(getattr(orm_obj, "updated_at", None))
            column = getattr(self.orm_class, "updated_at")
            updates = {**updates, "updated_at": stamp if column.type.timezone else stamp.replace(tzinfo=None)}
        result = self.db.execute(update(self.orm_class).where(*conditions).values(**updates)
                                 .execution_options(synchronize_session=False))
        if cast(CursorResult, result).rowcount != 1:
            self.db.rollback()
            if revision_condition is not None:
                raise conflict()
            raise ValidationError("Die Bankbuchung wurde zwischenzeitlich zugeordnet. Bitte neu laden.")
        self.db.expire(orm_obj)
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    def _guard_contract_update(self, orm_obj, updates) -> None:
        if self.orm_class.__tablename__ == "contracts" and any(
                field in updates and updates[field] != getattr(orm_obj, field)
                for field in ("tenant_id", "property_id", "unit_id")):
            from ..services.payment_integrity import guard_sql_delete
            guard_sql_delete(self.db, "contracts", orm_obj.id)

    @safe_db_operation("list_all")
    def list_all(self) -> list[Any]:
        objs = self.db.query(self.orm_class).populate_existing().all()
        return [self._to_pydantic(o) for o in objs]

    @safe_db_operation("get")
    def get(self, entity_id: str) -> Any:
        obj = self.db.get(self.orm_class, entity_id, populate_existing=True)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return self._to_pydantic(obj)

    @safe_db_operation("get_orm")
    def get_orm(self, entity_id: str) -> Base:
        obj = self.db.get(self.orm_class, entity_id, populate_existing=True)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return obj

    @safe_db_operation("exists")
    def exists(self, entity_id: str) -> bool:
        return self.db.get(self.orm_class, entity_id, populate_existing=True) is not None

    @safe_db_operation("create")
    def create(self, data: PydanticBaseModel) -> Any:
        orm_obj = self.orm_class(id=_generate_id(), **data.model_dump())
        self.db.add(orm_obj)
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    @safe_db_operation("update")
    def update(self, entity_id: str, data: PydanticBaseModel) -> Any:
        return self._write(entity_id, data.model_dump())

    @safe_db_operation("patch")
    def patch(self, entity_id: str, data: PydanticBaseModel) -> Any:
        return self._write(entity_id, data.model_dump(exclude_unset=True))

    @safe_db_operation("delete")
    def delete(self, entity_id: str) -> None:
        orm_obj = self.db.get(self.orm_class, entity_id, populate_existing=True)
        if orm_obj is None:
            self._missing(entity_id)
        from ..services.payment_integrity import guard_sql_delete
        guard_sql_delete(self.db, self.orm_class.__tablename__, entity_id)
        revision_condition = self._revision_condition(entity_id)
        if revision_condition is None:
            self.db.delete(orm_obj)
        else:
            result = self.db.execute(delete(self.orm_class).where(
                getattr(self.orm_class, "id") == entity_id, revision_condition,
            ).execution_options(synchronize_session=False))
            if cast(CursorResult, result).rowcount != 1:
                self.db.rollback()
                raise conflict()
            # Database cascades also invalidate already-loaded child objects.
            self.db.expire_all()
        self.db.flush()

    @safe_db_operation("list_paginated")
    def list_paginated(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list[Any]:
        """List entities with DB-level pagination, filtering, and ordering.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            filters: Column-value pairs to filter by (None values are skipped).
            order_by: Column name to order by.
            order_desc: If True, order descending.
        """
        query = self.db.query(self.orm_class).populate_existing()
        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(self.orm_class, key):
                    query = query.filter(getattr(self.orm_class, key) == value)
        if order_by and hasattr(self.orm_class, order_by):
            col = getattr(self.orm_class, order_by)
            query = query.order_by(col.desc() if order_desc else col.asc())
        query = query.offset(skip).limit(limit)
        return [self._to_pydantic(o) for o in query.all()]

    @safe_db_operation("count")
    def count(self, filters: dict[str, Any] | None = None) -> int:
        """Count entities matching the given filters."""
        query = self.db.query(self.orm_class)
        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(self.orm_class, key):
                    query = query.filter(getattr(self.orm_class, key) == value)
        return query.count()

    @safe_db_operation("filter_by")
    def filter_by(self, **kwargs) -> list[Any]:
        """Filter entities by column values. None values are skipped."""
        query = self.db.query(self.orm_class).populate_existing()
        for key, value in kwargs.items():
            if value is not None:
                query = query.filter(getattr(self.orm_class, key) == value)
        return [self._to_pydantic(o) for o in query.all()]
