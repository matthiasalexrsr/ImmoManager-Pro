from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.integration_service import integration_service

router = APIRouter(prefix="/integrations", tags=["Integrationen"])


class IntegrationTogglePayload(BaseModel):
    enabled: bool


class IntegrationActionPayload(BaseModel):
    payload: dict = {}


@router.get("/status")
def list_integration_status() -> dict:
    return {"integrations": integration_service.list_status()}


@router.patch("/{integration_id}")
def toggle_integration(integration_id: str, body: IntegrationTogglePayload) -> dict:
    try:
        return integration_service.toggle(integration_id, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.post("/{integration_id}/run")
def run_integration_action(integration_id: str, body: IntegrationActionPayload) -> dict:
    return integration_service.run_action(integration_id, body.payload)
