"""Generic base repository for CRUD operations.

All database operations are wrapped with error handling via
safe_db_operation to catch SQLAlchemy errors and convert them
to DatabaseOperationError with proper logging.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from ..db.orm_models import Base
from ..error_helpers import safe_db_operation
from ..storage import NotFoundError

logger = logging.getLogger(__name__)

ORM = TypeVar("ORM", bound=Base)
ReadModel = TypeVar("ReadModel", bound=PydanticBaseModel)
CreateModel = TypeVar("CreateModel", bound=PydanticBaseModel)


def _generate_id() -> str:
    return str(uuid4())


def _orm_to_dict(orm_obj: Base) -> dict[str, Any]:
    """Extract column values from an ORM object as a dict."""
    try:
        return {c.key: getattr(orm_obj, c.key) for c in orm_obj.__table__.columns}
    except Exception:
        logger.error("Failed to convert ORM object to dict: %s", type(orm_obj).__name__)
        raise


class BaseRepository(Generic[ORM, ReadModel, CreateModel]):
    """Generic CRUD repository for a single entity type.

    Error handling strategy:
    - NotFoundError is raised for missing entities (caught by global handler → 404)
    - SQLAlchemy errors are caught by @safe_db_operation → DatabaseOperationError → 500
    - Pydantic validation errors in _to_pydantic propagate naturally → 422
    """

    def __init__(
        self,
        db: Session,
        orm_class: type[ORM],
        read_class: type[ReadModel],
        not_found_msg: str,
    ):
        self.db = db
        self.orm_class = orm_class
        self.read_class = read_class
        self.not_found_msg = not_found_msg

    def _to_pydantic(self, orm_obj: ORM) -> ReadModel:
        try:
            return self.read_class.model_validate(_orm_to_dict(orm_obj))
        except Exception as exc:
            logger.error(
                "Failed to validate %s from ORM %s: %s",
                self.read_class.__name__,
                type(orm_obj).__name__,
                exc,
            )
            raise

    @safe_db_operation("list_all")
    def list_all(self) -> list[ReadModel]:
        objs = self.db.query(self.orm_class).all()
        return [self._to_pydantic(o) for o in objs]

    @safe_db_operation("get")
    def get(self, entity_id: str) -> ReadModel:
        obj = self.db.get(self.orm_class, entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return self._to_pydantic(obj)

    @safe_db_operation("get_orm")
    def get_orm(self, entity_id: str) -> ORM:
        obj = self.db.get(self.orm_class, entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return obj

    @safe_db_operation("exists")
    def exists(self, entity_id: str) -> bool:
        return self.db.get(self.orm_class, entity_id) is not None

    @safe_db_operation("create")
    def create(self, data: CreateModel) -> ReadModel:
        orm_obj = self.orm_class(id=_generate_id(), **data.model_dump())
        self.db.add(orm_obj)
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    @safe_db_operation("update")
    def update(self, entity_id: str, data: CreateModel) -> ReadModel:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        for key, value in data.model_dump().items():
            setattr(orm_obj, key, value)
        orm_obj.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    @safe_db_operation("patch")
    def patch(self, entity_id: str, data: PydanticBaseModel) -> ReadModel:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(orm_obj, key, value)
        orm_obj.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    @safe_db_operation("delete")
    def delete(self, entity_id: str) -> None:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        self.db.delete(orm_obj)
        self.db.flush()

    @safe_db_operation("list_paginated")
    def list_paginated(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list[ReadModel]:
        """List entities with DB-level pagination, filtering, and ordering.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            filters: Column-value pairs to filter by (None values are skipped).
            order_by: Column name to order by.
            order_desc: If True, order descending.
        """
        query = self.db.query(self.orm_class)
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
    def filter_by(self, **kwargs) -> list[ReadModel]:
        """Filter entities by column values. None values are skipped."""
        query = self.db.query(self.orm_class)
        for key, value in kwargs.items():
            if value is not None:
                query = query.filter(getattr(self.orm_class, key) == value)
        return [self._to_pydantic(o) for o in query.all()]
