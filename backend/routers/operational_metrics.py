"""Installation-admin telemetry: authenticated, uncached and PII-free."""

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import require_role
from ..dependencies import get_store
from ..services.operational_metrics import database_health, metrics, process_health
from ..services.operational_schedule import scheduler_status
from ..services.portfolio_scope import current_scope, refresh_scope, scope_from_user

router = APIRouter(prefix="/admin", tags=["Operations"])


def require_metrics_access(user=Depends(require_role("eigentuemer", "verwalter"))):
    # Also enforces scope when this router is used without the app middleware.
    actor = current_scope() or scope_from_user(user.model_dump())
    refresh_scope(actor)
    if actor.user_id != user.id or not actor.unrestricted:
        raise HTTPException(403, "Betriebsmetriken benötigen Zugriff auf alle Portfolios.")
    return actor


@router.get("/operational-metrics")
def get_operational_metrics(response: Response, actor=Depends(require_metrics_access), store=Depends(get_store)):
    database = database_health(store)
    result = {**metrics.snapshot(), "process": process_health(), "database": database, "scheduler": scheduler_status()}
    # Revocation during the probe must never publish installation-wide counters.
    refresh_scope(actor)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return result
