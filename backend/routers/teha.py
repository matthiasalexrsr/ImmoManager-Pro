"""Local TEHA receipt/mapping workflow; network actions use ConnectionRuns."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services.integrations.connection_runs import ConnectionRuns
from ..services.integrations.manager import integration_manager
from ..services.teha_receive import TehaReceive
from ..services.teha_types import BatchDecision, MapItem, PrepareReturn, Publish, Stage
from .integration_connections import _body, _private

router = APIRouter(prefix="/teha", tags=["TEHA Kundenportal"])


def service():
    return TehaReceive(store, ConnectionRuns(store, integration_manager))


@router.get("/connections")
def connections(response: Response, cursor: str | None = Query(None, max_length=4096),
                limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().connections(user.id, cursor=cursor, limit=limit)


@router.get("/{connection}/choices/{kind}")
def choices(connection: str, kind: str, response: Response, cursor: str | None = Query(None, max_length=4096),
            limit: int = Query(50, ge=1, le=250), property_id: str | None = None, user: UserRead = Depends(require_auth)):
    _private(response)
    return service().choices(connection, kind, user.id, cursor=cursor, limit=limit, property_id=property_id)


@router.get("/{connection}/batches")
def batches(connection: str, response: Response, cursor: str | None = Query(None, max_length=4096),
            limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().batches(connection, user.id, cursor=cursor, limit=limit)


@router.post("/{connection}/runs/{run_id}/stage")
async def stage(connection: str, run_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    command = await _body(request, Stage)
    return await run_in_threadpool(service().stage, connection, run_id, command, user.id)


@router.get("/{connection}/runs/{run_id}/diagnostic")
def diagnostic(connection: str, run_id: str, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    return service().diagnostic(connection, run_id, user.id)


@router.get("/{connection}/batches/{batch_id}/items")
def items(connection: str, batch_id: str, response: Response, cursor: str | None = Query(None, max_length=4096),
          limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().items(connection, batch_id, user.id, cursor=cursor, limit=limit)


@router.post("/{connection}/batches/{batch_id}/decision")
async def decide(connection: str, batch_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    command = await _body(request, BatchDecision)
    return await run_in_threadpool(service().decide_batch, connection, batch_id, command, user.id)


@router.post("/{connection}/items/{item_id}/mapping")
async def mapping(connection: str, item_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    command = await _body(request, MapItem)
    return await run_in_threadpool(service().map, connection, item_id, command, user.id)


@router.get("/{connection}/items/{item_id}/preview")
def preview(connection: str, item_id: str, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    return service().preview(connection, item_id, user.id)


@router.get("/{connection}/items/{item_id}/follow-up-users")
def follow_up_users(connection: str, item_id: str, response: Response,
                    cursor: str | None = Query(None, max_length=4096),
                    limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().follow_up_users(connection, item_id, user.id, cursor=cursor, limit=limit)


@router.post("/{connection}/items/{item_id}/confirm")
async def confirm(connection: str, item_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    command = await _body(request, Publish)
    return await run_in_threadpool(service().publish, connection, item_id, command, user.id)


@router.get("/{connection}/history")
def history(connection: str, response: Response, cursor: str | None = Query(None, max_length=4096),
            limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().history(connection, user.id, cursor=cursor, limit=limit)


@router.post("/{connection}/items/{item_id}/prepare-return")
async def prepare_return(connection: str, item_id: str, request: Request, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    command = await _body(request, PrepareReturn)
    return await run_in_threadpool(service().prepare_return, connection, item_id, command, user.id)


@router.get("/{connection}/returns")
def returns(connection: str, response: Response, cursor: str | None = Query(None, max_length=4096),
            limit: int = Query(50, ge=1, le=250), user: UserRead = Depends(require_auth)):
    _private(response)
    return service().returns(connection, user.id, cursor=cursor, limit=limit)


@router.get("/{connection}/evidence")
def evidence(connection: str, response: Response, user: UserRead = Depends(require_auth)):
    _private(response)
    return service().evidence(connection, user.id)


@router.get("/{connection}/returns/{draft_id}/export")
def return_export(connection: str, draft_id: str,
                  snapshot_sha256: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
                  user: UserRead = Depends(require_auth)):
    raw, filename = service().return_export(connection, draft_id, snapshot_sha256, user.id)
    return Response(raw, media_type="application/json", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
        "X-Content-Type-Options": "nosniff"})


@router.get("/{connection}/receipts/{receipt_id}/original")
def original(connection: str, receipt_id: str, user: UserRead = Depends(require_auth)):
    raw, filename = service().original(connection, receipt_id, user.id)
    return Response(raw, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
        "X-Content-Type-Options": "nosniff"})
