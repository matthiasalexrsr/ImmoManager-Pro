"""Manual durable SMTP outbox; reads and writes retain existing communication roles."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..auth import UserRead, require_auth, require_role
from ..dependencies import store
from ..outbox_models import OutboxCommand, OutboxCreate, OutboxDecision
from ..services import outbox

router = APIRouter(prefix="/messages/outbox", tags=["SMTP-Ausgang"])
Reader = Annotated[UserRead, Depends(require_auth)]
Writer = Annotated[UserRead, Depends(require_role("eigentuemer", "verwalter", "buchhaltung", "techniker"))]


@router.get("/configuration")
def configuration(actor: Reader):
    return outbox.public_configuration(actor.id)


@router.get("")
def messages(portfolio_id: str, actor: Reader, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000)):
    return outbox.list_messages(store, portfolio_id, actor.id, offset, limit)


@router.post("", status_code=201)
def create(command: OutboxCreate, actor: Writer):
    return outbox.create_message(store, command, actor.id)


@router.get("/{identifier}")
def message(identifier: str, actor: Reader):
    return outbox.get_message(store, identifier, actor.id)


@router.get("/{identifier}/events")
def events(identifier: str, actor: Reader, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return outbox.list_events(store, identifier, actor.id, offset, limit)


@router.post("/{identifier}/send")
def send(identifier: str, command: OutboxCommand, actor: Writer):
    return outbox.send_message(store, identifier, command, actor.id)


@router.post("/{identifier}/decision")
def decision(identifier: str, command: OutboxDecision, actor: Writer):
    return outbox.decide(store, identifier, command, actor.id)


@router.post("/{identifier}/recover")
def recover(identifier: str, command: OutboxCommand, actor: Writer):
    return outbox.decide(store, identifier, command, actor.id, recover=True)
