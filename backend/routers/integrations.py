from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..auth import require_role
from ..services.checked_publication import CheckedPublicationRoute
from ..services.integrations.config_store import ConfigStoreError
from ..services.integrations.history_types import HistoryError
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


class IntegrationPublicationRoute(CheckedPublicationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request: Request) -> Response:
            try:
                return await handler(request)
            except HistoryError as error:
                raise HTTPException(error.status, detail={"code": error.code, "message": error.message}) from None

        return checked


router = APIRouter(prefix="/integrations", tags=["Integrationen"],
                   route_class=IntegrationPublicationRoute,
                   dependencies=[Depends(_require_integration_administration)])


class IntegrationTogglePayload(BaseModel):
    enabled: bool


class IntegrationActionPayload(BaseModel):
    payload: dict = Field(default_factory=dict)


class IntegrationConfigPayload(BaseModel):
    config: dict = Field(default_factory=dict)


class IntegrationConnectionStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    enabled: bool | None = None
    config: dict | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.enabled is None and self.config is None:
            raise ValueError("Mindestens enabled oder config muss geändert werden.")
        return self


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


@router.get("/{integration_id}/connection-state")
def get_integration_connection_state(integration_id: str) -> dict:
    try:
        return integration_manager.connection_state(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
    except ConfigStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": "Verbindungszustand nicht revisionssicher verfügbar."},
        ) from None


@router.patch("/{integration_id}/connection-state")
def patch_integration_connection_state(
    integration_id: str, body: IntegrationConnectionStatePatch
) -> dict:
    try:
        return integration_manager.update_connection_state(
            integration_id,
            expected_revision=body.expected_revision,
            enabled=body.enabled,
            config_updates=body.config,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
    except ConfigStoreError as exc:
        status_code = 412 if exc.code == "state_revision_conflict" else 503
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": (
                    "Verbindungszustand wurde parallel geändert. Aktuellen Stand neu laden."
                    if status_code == 412
                    else "Verbindungszustand konnte nicht revisionssicher geändert werden."
                ),
            },
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get("/{integration_id}/parameters")
def get_integration_parameters(integration_id: str) -> dict:
    try:
        return integration_manager.parameter_catalog(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.post("/{integration_id}/connection-test")
def test_integration_connection(integration_id: str) -> dict:
    try:
        return integration_manager.connection_test(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Der Verbindungstest verletzt den nebenwirkungsfreien Adaptervertrag.",
        ) from exc


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
    cursor: str | None = Query(None),
    state: Literal["completed", "rejected", "outcome_uncertain", "observation_failed", "pending"] | None = Query(None),
    projection: Literal["full", "summary"] = Query("full"),
) -> dict:
    try:
        return integration_manager.history_page(integration_id, limit=limit, cursor=cursor, state=state, projection=projection)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.get("/{integration_id}/history/{run_id}")
def get_integration_history_detail(integration_id: str, run_id: str) -> dict:
    try:
        return integration_manager.history_detail(integration_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc


@router.delete("/{integration_id}/history")
def clear_integration_history(integration_id: str) -> dict:
    try:
        return integration_manager.clear_history(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Integration nicht gefunden") from exc
