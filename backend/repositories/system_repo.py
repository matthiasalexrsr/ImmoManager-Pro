"""System domain repository — change history."""

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from ..db.orm_models import ChangeHistoryORM
from ..models import ChangeHistoryEntry
from .base import BaseRepository

logger = logging.getLogger(__name__)


class SystemRepository:
    """Change history tracking."""

    def __init__(self, db: Session):
        self.db = db
        self._change_history = BaseRepository(
            db, ChangeHistoryORM, ChangeHistoryEntry, "Änderungshistorie nicht gefunden",
        )

    def _commit(self):
        self.db.commit()

    def list_change_history(self) -> list[ChangeHistoryEntry]:
        return self._change_history.list_all()

    def add_change_history(
        self,
        entity_type: str,
        entity_id: str,
        field_name: str,
        old_value: str | None,
        new_value: str | None,
        changed_by: str | None = None,
        reason: str | None = None,
    ) -> ChangeHistoryEntry:
        entry = ChangeHistoryORM(
            id=str(uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            reason=reason,
        )
        self.db.add(entry)
        self.db.flush()
        self.db.refresh(entry)
        self._commit()
        return self._change_history.get(entry.id)

    def get_entity_history(self, entity_type: str, entity_id: str) -> list[ChangeHistoryEntry]:
        return self._change_history.filter_by(entity_type=entity_type, entity_id=entity_id)
