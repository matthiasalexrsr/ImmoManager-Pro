"""Explicitly confirmed historical sources, under billing authorization."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import require_auth
from ..dependencies import get_store
from ..services import measurement_history as history
from ..services.measurement_history_types import MeasurementCommand
from ..services.measurement_history_validation import MeasurementIntegrityError
from ..services.request_authority import request_authority
from ..storage import NotFoundError

router = APIRouter(prefix="/measurement-history", tags=["Historische Abrechnungsgrundlagen"])


def call(operation, request, store, user, *args, **kwargs):
    try:
        with request_authority(request.headers.get("authorization", "")[7:]):
            return operation(store, *args, actor_id=user.id, **kwargs)
    except NotFoundError as error:
        raise HTTPException(404, "Quellenobjekt nicht verfügbar.") from error
    except MeasurementIntegrityError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/units/{unit_id}")
def sources(unit_id: str, request: Request, start: date, end: date,
            store=Depends(get_store), user=Depends(require_auth)):
    return call(history.sources, request, store, user, unit_id, start=start, end=end)


@router.get("/units/{unit_id}/journal")
def journal(unit_id: str, request: Request, after: int = Query(0, ge=0), page_size: int = Query(50, ge=1),
            store=Depends(get_store), user=Depends(require_auth)):
    return call(history.journal, request, store, user, unit_id, after=after, page_size=page_size)


@router.post("/units/{unit_id}/confirm")
def confirm(unit_id: str, command: MeasurementCommand, request: Request,
            store=Depends(get_store), user=Depends(require_auth)):
    return call(history.confirm, request, store, user, unit_id, command)
