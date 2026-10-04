"""Explicit reviewed JSON commands and private dispute original reads."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..auth import require_auth
from ..dependencies import get_store
from ..services import billing_disputes as disputes
from ..services.billing_dispute_types import AppendDisputeEvent, OpenDispute
from ..services.billing_dispute_validation import DisputeIntegrityError
from ..services.request_authority import request_authority


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/disputes", tags=["Widerspruchsjournal"], dependencies=[Depends(private_response)])


def call(operation, request, store, user, *args, **kwargs):
    try:
        with request_authority(request.headers.get("authorization", "")[7:]):
            return operation(store, *args, actor_id=user.id, **kwargs)
    except DisputeIntegrityError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/preview")
def preview(command: OpenDispute, request: Request, store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.preview_open, request, store, user, command)


@router.post("", status_code=201)
def open_case(command: OpenDispute, request: Request, store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.open_case, request, store, user, command)


@router.get("")
def list_cases(request: Request, property_id: str | None = None, period_id: str | None = None,
               tenant_id: str | None = None, state: str | None = None, after_id: str = "",
               page_size: int = Query(50, ge=1), store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.list_cases, request, store, user, property_id=property_id, period_id=period_id,
                tenant_id=tenant_id, state=state, after_id=after_id, page_size=page_size)


@router.get("/periods/{period_id}/status")
def period_status(period_id: str, request: Request, store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.period_status, request, store, user, period_id)


@router.get("/{case_id}")
def case(case_id: str, request: Request, store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.read_case, request, store, user, case_id)


@router.get("/{case_id}/journal")
def journal(case_id: str, request: Request, after: int = Query(0, ge=0), page_size: int = Query(50, ge=1),
            store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.journal, request, store, user, case_id, after=after, page_size=page_size)


@router.get("/{case_id}/events/{event_id}")
def original(case_id: str, event_id: str, request: Request, store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.original_event, request, store, user, case_id, event_id)


@router.post("/{case_id}/preview")
def preview_event(case_id: str, command: AppendDisputeEvent, request: Request,
                  store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.preview_append, request, store, user, case_id, command)


@router.post("/{case_id}/events")
def append(case_id: str, command: AppendDisputeEvent, request: Request,
           store=Depends(get_store), user=Depends(require_auth)):
    return call(disputes.append_event, request, store, user, case_id, command)
