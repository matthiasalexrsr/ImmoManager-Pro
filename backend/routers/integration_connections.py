"""Connection configuration and explicit action commands; no implicit dispatch on GET."""

from __future__ import annotations

import json
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..config import settings
from ..dependencies import store
from ..models import UserRead
from ..services.integrations.connection_runs import ConnectionRuns
from ..services.integrations.connection_types import (
    ConnectionCreate,
    ConnectionUpdate,
    LegacyAdoption,
    MappingDecision,
    RunCancellation,
    RunDispatch,
    RunPreparation,
    SourceObservation,
)
from ..services.integrations.manager import integration_manager

router = APIRouter(prefix="/integration-connections", tags=["Verbindungen und Vorgänge"])
Command = TypeVar("Command", bound=BaseModel)


def _schema(model: type[BaseModel]) -> dict:
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": model.model_json_schema()}}}}


def _service() -> ConnectionRuns:
    return ConnectionRuns(store, integration_manager)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


async def _body(request: Request, model: type[Command]) -> Command:
    # Read a bounded command without echoing submitted credentials in validation
    # errors. Large collections use cursors/chunks, not an unbounded POST body.
    body = bytearray()
    maximum = settings.integration_step_max_bytes
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(413, "Dieser Arbeitsschritt ist zu groß. Bitte die Quelle in fortsetzbaren Abschnitten übernehmen.")
    try:
        value = json.loads(body.decode("utf-8"))
        return model.model_validate(value)
    except ValidationError as error:
        raise HTTPException(422, {"code": "invalid_command", "message": "Bitte die eingegebenen Felder prüfen.",
                                  "errors": error.errors(include_input=False, include_context=False, include_url=False)}) from None
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "Die Anfrage muss ein gültiges JSON-Objekt enthalten.") from None


@router.get("/catalog")
def catalog(response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return {"providers": _service().catalog(user.id)}


@router.get("")
def connections(response: Response, cursor: str | None = Query(None, max_length=4096),
                limit: int = Query(50, ge=1, le=250), include_archived: bool = False,
                user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().list(user.id, cursor=cursor, limit=limit, include_archived=include_archived)


@router.post("", status_code=201, openapi_extra=_schema(ConnectionCreate))
async def create(request: Request, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, ConnectionCreate)
    return await run_in_threadpool(_service().create, payload, user.id)


@router.get("/legacy/{provider_id}")
def legacy_preview(provider_id: str, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().legacy_preview(provider_id, user.id)


@router.post("/legacy/adopt", openapi_extra=_schema(LegacyAdoption))
async def adopt(request: Request, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, LegacyAdoption)
    return await run_in_threadpool(_service().adopt_legacy, payload, user.id)


@router.get("/{connection_id}")
def get(connection_id: str, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().get(connection_id, user.id)


@router.patch("/{connection_id}", openapi_extra=_schema(ConnectionUpdate))
async def update(connection_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, ConnectionUpdate)
    return await run_in_threadpool(_service().update, connection_id, payload, user.id)


@router.get("/{connection_id}/events")
def events(connection_id: str, response: Response, cursor: str | None = Query(None, max_length=4096),
           limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().events(connection_id, user.id, cursor=cursor, limit=limit)


@router.get("/{connection_id}/mappings")
def mappings(connection_id: str, response: Response, cursor: str | None = Query(None, max_length=4096),
             limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().mappings(connection_id, user.id, cursor=cursor, limit=limit)


@router.post("/{connection_id}/observations", status_code=201, openapi_extra=_schema(SourceObservation))
async def observe(connection_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, SourceObservation)
    return await run_in_threadpool(_service().observe, connection_id, payload, user.id)


@router.post("/{connection_id}/mappings/{mapping_id}/decide", openapi_extra=_schema(MappingDecision))
async def decide_mapping(connection_id: str, mapping_id: str, request: Request, response: Response,
                         user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, MappingDecision)
    return await run_in_threadpool(_service().decide_mapping, connection_id, mapping_id, payload, user.id)


@router.get("/{connection_id}/runs")
def runs(connection_id: str, response: Response, cursor: str | None = Query(None, max_length=4096),
         limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().runs(connection_id, user.id, cursor=cursor, limit=limit)


@router.post("/{connection_id}/runs", status_code=201, openapi_extra=_schema(RunPreparation))
async def prepare(connection_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, RunPreparation)
    return await run_in_threadpool(_service().prepare, connection_id, payload, user.id)


@router.get("/{connection_id}/runs/{run_id}")
def run(connection_id: str, run_id: str, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().get_run(connection_id, run_id, user.id)


@router.post("/{connection_id}/runs/{run_id}/dispatch", openapi_extra=_schema(RunDispatch))
async def dispatch(connection_id: str, run_id: str, request: Request, response: Response,
                   user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, RunDispatch)
    return await run_in_threadpool(_service().dispatch, connection_id, run_id, payload, user.id)


@router.post("/{connection_id}/runs/{run_id}/cancel", openapi_extra=_schema(RunCancellation))
async def cancel(connection_id: str, run_id: str, request: Request, response: Response,
                 user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    payload = await _body(request, RunCancellation)
    return await run_in_threadpool(_service().cancel, connection_id, run_id, payload, user.id)


@router.get("/{connection_id}/runs/{run_id}/preview")
def preview(connection_id: str, run_id: str, response: Response, user: UserRead = Depends(require_auth)) -> dict:
    _private(response)
    return _service().preview(connection_id, run_id, user.id)
