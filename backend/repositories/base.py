"""Generic base repository for CRUD operations."""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from ..db.orm_models import Base
from ..storage import NotFoundError

ORM = TypeVar("ORM", bound=Base)
ReadModel = TypeVar("ReadModel", bound=PydanticBaseModel)
CreateModel = TypeVar("CreateModel", bound=PydanticBaseModel)


def _generate_id() -> str:
    return str(uuid4())


def _orm_to_dict(orm_obj: Base) -> dict[str, Any]:
    """Extract column values from an ORM object as a dict."""
    return {c.key: getattr(orm_obj, c.key) for c in orm_obj.__table__.columns}


class BaseRepository(Generic[ORM, ReadModel, CreateModel]):
    """Generic CRUD repository for a single entity type."""

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
        return self.read_class.model_validate(_orm_to_dict(orm_obj))

    def list_all(self) -> list[ReadModel]:
        objs = self.db.query(self.orm_class).all()
        return [self._to_pydantic(o) for o in objs]

    def get(self, entity_id: str) -> ReadModel:
        obj = self.db.get(self.orm_class, entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return self._to_pydantic(obj)

    def get_orm(self, entity_id: str) -> ORM:
        obj = self.db.get(self.orm_class, entity_id)
        if obj is None:
            raise NotFoundError(self.not_found_msg)
        return obj

    def exists(self, entity_id: str) -> bool:
        return self.db.get(self.orm_class, entity_id) is not None

    def create(self, data: CreateModel) -> ReadModel:
        orm_obj = self.orm_class(id=_generate_id(), **data.model_dump())
        self.db.add(orm_obj)
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    def update(self, entity_id: str, data: CreateModel) -> ReadModel:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        for key, value in data.model_dump().items():
            setattr(orm_obj, key, value)
        orm_obj.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    def patch(self, entity_id: str, data: PydanticBaseModel) -> ReadModel:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(orm_obj, key, value)
        orm_obj.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(orm_obj)
        return self._to_pydantic(orm_obj)

    def delete(self, entity_id: str) -> None:
        orm_obj = self.db.get(self.orm_class, entity_id)
        if orm_obj is None:
            raise NotFoundError(self.not_found_msg)
        self.db.delete(orm_obj)
        self.db.flush()

    def filter_by(self, **kwargs) -> list[ReadModel]:
        """Filter entities by column values. None values are skipped."""
        query = self.db.query(self.orm_class)
        for key, value in kwargs.items():
            if value is not None:
                query = query.filter(getattr(self.orm_class, key) == value)
        return [self._to_pydantic(o) for o in query.all()]
