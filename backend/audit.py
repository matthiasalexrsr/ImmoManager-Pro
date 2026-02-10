"""Audit logging for write operations (create, update, patch, delete)."""

import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

from .models import AuditLogEntry


# In-memory audit log store
_audit_logs: list[AuditLogEntry] = []


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
    _audit_logs.append(entry)
    return entry


def list_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
) -> list[AuditLogEntry]:
    """List audit logs with optional filters."""
    results = _audit_logs
    if entity_type:
        results = [e for e in results if e.entity_type == entity_type]
    if entity_id:
        results = [e for e in results if e.entity_id == entity_id]
    if user_id:
        results = [e for e in results if e.user_id == user_id]
    if action:
        results = [e for e in results if e.action == action]
    return results


def clear_audit_logs() -> None:
    """Clear all audit logs (for testing)."""
    _audit_logs.clear()
