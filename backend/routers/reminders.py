"""Authenticated personal reminder plans; no external send endpoint."""
from fastapi import APIRouter, Depends, Query

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import reminders

router = APIRouter(prefix='/reminders', tags=['Persönliche Erinnerungen'])


@router.get('')
def reminder_list(status: str | None = Query('active'), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), actor: UserRead = Depends(require_auth)):
    return reminders.page(store, actor.id, status=status, offset=offset, limit=limit)


@router.post('', status_code=201)
def reminder_create(payload: reminders.Plan, actor: UserRead = Depends(require_auth)):
    return reminders.create(store, actor.id, payload)


@router.post('/{identifier}/command')
def reminder_change(identifier: str, payload: reminders.Command, actor: UserRead = Depends(require_auth)):
    return reminders.change(store, actor.id, identifier, payload)
