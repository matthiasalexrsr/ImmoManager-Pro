"""Additive router. Application registration belongs to the integration owner."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import operational_jobs as service
from ..services.operational_job_types import JobCommand, JobContinue, JobCreate


class SafeDatabaseRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request: Request):
            try:
                header = request.headers.get("authorization", "")
                with service.request_token(header[7:] if header.lower().startswith("bearer ") else None):
                    return await handler(request)
            except service.AuthorizationUnavailable:
                return JSONResponse(status_code=503, content={"code": "authorization_unavailable",
                    "detail": "Die Sitzungsprüfung ist vorübergehend nicht verfügbar. Arbeitslauf später erneut laden."},
                    headers={"Retry-After": "2"})
            except DBAPIError:
                # A complete outage can also prevent recording failure metadata.
                # Persisted work remains protected by expiry/fencing on restart.
                return JSONResponse(status_code=503, content={"code": "database_unavailable",
                    "detail": "Die Datenbank ist vorübergehend nicht verfügbar. Gespeicherten Arbeitslauf erneut laden und fortsetzen."},
                    headers={"Retry-After": "2"})
        return guarded


router = APIRouter(prefix="/tasks/operational-jobs", tags=["Fortsetzbare Arbeitslisten"], route_class=SafeDatabaseRoute)
Actor = Annotated[UserRead, Depends(require_auth)]


@router.post("", status_code=201)
def create(payload: JobCreate, actor: Actor, store=Depends(get_store)):
    return service.create_job(store, payload, actor.id)


@router.get("/{job_id}")
def read(job_id: str, actor: Actor, store=Depends(get_store)):
    return service.read_job(store, job_id, actor.id)


@router.post("/{job_id}/continue")
def continuation(job_id: str, payload: JobContinue, actor: Actor, store=Depends(get_store)):
    try:
        return service.continue_job(store, job_id, payload, actor.id)
    except service.ClaimLost:
        raise HTTPException(409, "Die Verarbeitung wurde bereits von einem anderen Worker übernommen. Aktuellen Stand laden.") from None


@router.post("/{job_id}/cancel")
def cancel(job_id: str, payload: JobCommand, actor: Actor, store=Depends(get_store)):
    return service.cancel_job(store, job_id, payload, actor.id)


@router.post("/{job_id}/items/{item_id}/retry")
def retry(job_id: str, item_id: str, payload: JobCommand, actor: Actor, store=Depends(get_store)):
    return service.retry_item(store, job_id, item_id, payload, actor.id)


@router.post("/{job_id}/lanes/{lane_id}/retry")
def retry_lane(job_id: str, lane_id: str, payload: JobCommand, actor: Actor, store=Depends(get_store)):
    return service.retry_lane(store, job_id, lane_id, payload, actor.id)


@router.get("/{job_id}/items")
def items(job_id: str, actor: Actor, after: str | None = None, page_size: int = Query(64, ge=1), store=Depends(get_store)):
    return service.item_page(store, job_id, after=after, page_size=page_size, actor_id=actor.id)
