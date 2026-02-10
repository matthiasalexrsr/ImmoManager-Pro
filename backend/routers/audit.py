"""Audit log router: read-only access to audit trail."""

from fastapi import APIRouter, Depends, Query

from ..audit import list_audit_logs
from ..auth import require_role
from ..models import AuditLogEntry, UserRead

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("", response_model=list[AuditLogEntry])
def get_audit_logs(
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> list[AuditLogEntry]:
    """List audit log entries (admin only)."""
    results = list_audit_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
    )
    return results[skip : skip + limit]
