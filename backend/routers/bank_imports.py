"""Private bank previews and originals; GET never initiates a bank connection."""
from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services.bank_fints import CancelFinTS, FinTS, FinTSStep, StartFinTS
from ..services.bank_imports import BankImports, ConfirmImport, StageImport
from ..services.bank_matching import BankAssignment, BankMatching
from .integration_connections import _body


def _private(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


router = APIRouter(prefix="/bank-imports", tags=["Bankimporte"], dependencies=[Depends(_private)])


@router.get('/matching/{booking_id}')
def matching(booking_id: str, response: Response, user: UserRead = Depends(require_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    return BankMatching(store).proposals(booking_id, user.id)


@router.post('/matching/{booking_id}')
def assign(booking_id: str, payload: BankAssignment, user: UserRead = Depends(require_auth)):
    return BankMatching(store).assign(booking_id, payload, user.id)


@router.post('/fints/sessions')
async def fints_start(request: Request, user: UserRead = Depends(require_auth)):
    payload = await _body(request, StartFinTS)
    return await run_in_threadpool(FinTS(store).start, payload, user.id)


@router.get('/fints/sessions/{identifier}')
def fints_get(identifier: str, response: Response, user: UserRead = Depends(require_auth)):
    response.headers['Cache-Control'] = 'private, no-store'
    return FinTS(store).get(identifier, user.id)


@router.post('/fints/sessions/{identifier}/step')
async def fints_step(identifier: str, request: Request, user: UserRead = Depends(require_auth)):
    payload = await _body(request, FinTSStep)
    return await run_in_threadpool(FinTS(store).advance, identifier, payload, user.id)


@router.post('/fints/sessions/{identifier}/cancel')
async def fints_cancel(identifier: str, request: Request, user: UserRead = Depends(require_auth)):
    payload = await _body(request, CancelFinTS)
    return await run_in_threadpool(FinTS(store).cancel, identifier, payload, user.id)


@router.post('/fints/sessions/{identifier}/stage')
async def fints_stage(identifier: str, request: Request, user: UserRead = Depends(require_auth)):
    payload = await _body(request, CancelFinTS)
    return await run_in_threadpool(FinTS(store).stage_received, identifier, payload, user.id)


@router.post("")
def stage(payload: StageImport, response: Response, user: UserRead = Depends(require_auth)):
    response.headers["Cache-Control"] = "private, no-store"
    return BankImports(store).stage(payload, user.id)


@router.get('')
def imports(account_id: str, cursor: str | None = Query(None, max_length=4096), limit: int = Query(50, ge=1, le=250),
            user: UserRead = Depends(require_auth)):
    return BankImports(store).list(account_id, user.id, cursor, limit)


@router.get("/{identifier}")
def preview(identifier: str, response: Response, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=250),
            user: UserRead = Depends(require_auth)):
    response.headers["Cache-Control"] = "private, no-store"
    return BankImports(store).preview(identifier, user.id, offset, limit)


@router.get("/{identifier}/original")
def original(identifier: str, user: UserRead = Depends(require_auth)):
    return Response(BankImports(store).original(identifier, user.id), media_type="application/octet-stream",
                    headers={"Cache-Control": "private, no-store", "Content-Disposition": 'attachment; filename="Bankoriginal.bin"'})


@router.post("/{identifier}/confirm")
def confirm(identifier: str, payload: ConfirmImport, response: Response, user: UserRead = Depends(require_auth)):
    response.headers["Cache-Control"] = "private, no-store"
    return BankImports(store).confirm(identifier, payload, user.id)
