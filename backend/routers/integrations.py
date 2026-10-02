from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..auth import require_role
from ..services.checked_publication import CheckedPublicationRoute
from ..services.integrations.manager import integration_manager
from ..services.portfolio_scope import require_installation_scope


def _require_integration_administration(
    response: Response, _actor=Depends(require_role("eigentuemer", "verwalter")),
):
    # The legacy manager stores global configuration/history. A read is not a
    # scoped property lookup and must not inherit general business read access.
    if _actor.role != "eigentuemer" and _actor.portfolio_access != "all":
        raise HTTPException(403, "Installationsverwaltung erforderlich")
    require_installation_scope()
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


router = APIRouter(prefix="/integrations", tags=["Integrationen"],
                   route_class=CheckedPublicationRoute,
                   dependencies=[Depends(_require_integration_administration)])


class IntegrationTogglePayload(BaseModel):
    enabled: bool


class IntegrationActionPayload(BaseModel):
    payload: dict = Field(default_factory=dict)


class IntegrationConfigPayload(BaseModel):
    config: dict = Field(default_factory=dict)


@router.get("")
def list_integrations() -> dict:
    return {"integrations": integration_manager.list_integrations()}


@router.get("/status")
def list_integration_status() -> dict:
    return {"integrations": integration_manager.list_integrations()}


@router.get("/metrics")
def get_integration_metrics() -> dict:
    return integration_manager.get_metrics()


@router.get("/{integration_id}")
def get_integration(integration_id: str) -> dict:
    try:
        return integration_manager.get_integration(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.get("/{integration_id}/schema")
def get_integration_schema(integration_id: str) -> dict:
    try:
        return integration_manager.get_schema(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.post("/{integration_id}/validate")
def validate_integration_config(integration_id: str, body: IntegrationConfigPayload) -> dict:
    try:
        return integration_manager.validate_config(integration_id, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.patch("/{integration_id}")
def toggle_integration(integration_id: str, body: IntegrationTogglePayload) -> dict:
    try:
        return integration_manager.set_enabled(integration_id, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.put("/{integration_id}/config")
def update_integration_config(integration_id: str, body: IntegrationConfigPayload) -> dict:
    try:
        return integration_manager.update_config(integration_id, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{integration_id}/run")
def run_integration_action(integration_id: str, body: IntegrationActionPayload) -> dict:
    try:
        return integration_manager.run(integration_id, body.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.get("/{integration_id}/history")
def get_integration_history(
    integration_id: str,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    try:
        return {"items": integration_manager.list_history(integration_id, limit=limit)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.delete("/{integration_id}/history")
def clear_integration_history(integration_id: str) -> dict:
    try:
        return integration_manager.clear_history(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
