"""Audit logging for write operations (create, update, patch, delete).

Supports two storage backends:
  - InMemoryAuditStore (default, for tests)
  - SQLAuditStore (when enable_sql_audit() is called with a session factory)
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import uuid4

from .models import AuditLogEntry

logger = logging.getLogger(__name__)


class AuditStore(ABC):
    @abstractmethod
    def add(self, entry: AuditLogEntry) -> None:
        ...

    @abstractmethod
    def list_all(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[AuditLogEntry]:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...


class InMemoryAuditStore(AuditStore):
    def __init__(self):
        self._logs: list[AuditLogEntry] = []

    def add(self, entry: AuditLogEntry) -> None:
        self._logs.append(entry)

    def list_all(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[AuditLogEntry]:
        results = self._logs
        if entity_type:
            results = [e for e in results if e.entity_type == entity_type]
        if entity_id:
            results = [e for e in results if e.entity_id == entity_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action:
            results = [e for e in results if e.action == action]
        return results

    def clear(self) -> None:
        self._logs.clear()


class SQLAuditStore(AuditStore):
    """SQLAlchemy-backed audit log persistence."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def add(self, entry: AuditLogEntry) -> None:
        from .db.orm_models import AuditLogORM

        session = self._session_factory()
        try:
            obj = AuditLogORM(
                id=entry.id,
                user_id=entry.user_id,
                username=entry.username,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                changes=entry.changes,
                timestamp=entry.timestamp,
            )
            session.add(obj)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to persist audit log entry")
        finally:
            session.close()

    def list_all(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[AuditLogEntry]:
        from .db.orm_models import AuditLogORM

        session = self._session_factory()
        try:
            query = session.query(AuditLogORM)
            if entity_type:
                query = query.filter(AuditLogORM.entity_type == entity_type)
            if entity_id:
                query = query.filter(AuditLogORM.entity_id == entity_id)
            if user_id:
                query = query.filter(AuditLogORM.user_id == user_id)
            if action:
                query = query.filter(AuditLogORM.action == action)
            return [
                AuditLogEntry(
                    id=obj.id,
                    user_id=obj.user_id,
                    username=obj.username,
                    action=obj.action,
                    entity_type=obj.entity_type,
                    entity_id=obj.entity_id,
                    changes=obj.changes,
                    timestamp=obj.timestamp,
                )
                for obj in query.order_by(AuditLogORM.timestamp.desc()).all()
            ]
        finally:
            session.close()

    def clear(self) -> None:
        from .db.orm_models import AuditLogORM

        session = self._session_factory()
        try:
            session.query(AuditLogORM).delete()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Default: in-memory store
_audit_store: AuditStore = InMemoryAuditStore()


def enable_sql_audit(session_factory) -> None:
    """Switch audit storage to SQLAlchemy-backed persistence."""
    global _audit_store
    _audit_store = SQLAuditStore(session_factory)


def log_action(
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    changes: Optional[dict] = None,
) -> AuditLogEntry:
    """Record an audit log entry."""
    entry = AuditLogEntry(
        id=str(uuid4()),
        user_id=user_id,
        username=username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=json.dumps(changes, default=str) if changes else None,
        timestamp=datetime.utcnow(),
    )
    _audit_store.add(entry)
    return entry


def list_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
) -> list[AuditLogEntry]:
    """List audit logs with optional filters."""
    return _audit_store.list_all(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
    )


def clear_audit_logs() -> None:
    """Clear all audit logs (for testing)."""
    _audit_store.clear()
