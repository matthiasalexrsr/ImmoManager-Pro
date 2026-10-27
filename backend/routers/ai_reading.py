"""Reading documents into forms with local rules or the AI of the person's account (services/ai_reading)."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..dependencies import store
from ..models import UserRead
from ..services import ai_reading as service

router = APIRouter(prefix="/ai", tags=["KI-Einlesen"])
Actor = Annotated[UserRead, Depends(get_current_user)]


@router.get("/readings/options")
def reading_options(actor: Actor, surface: Optional[str] = None) -> dict:
    """Readers (local rules, connected accounts), what the settings switch on, and the fields of the surfaces."""
    return service.options(store, actor, surface)


@router.post("/readings", status_code=201)
def start_reading(payload: service.StartCommand, actor: Actor) -> dict:
    """Reads a document or an upload for a surface; values, questions and records that may already exist."""
    return service.start(store, actor, payload)


@router.get("/readings/{reading_id}")
def get_reading(reading_id: str, actor: Actor) -> dict:
    return service.read(store, actor, reading_id)


@router.post("/readings/{reading_id}/messages")
def reading_message(reading_id: str, payload: service.MessageCommand, actor: Actor) -> dict:
    """What should happen with the document, in the person's words; the AI answers and adjusts the values."""
    return service.say(store, actor, reading_id, payload)


@router.post("/readings/{reading_id}/decision")
def reading_decision(reading_id: str, payload: service.DecisionCommand, actor: Actor) -> dict:
    """Open or update an existing record for the same document, create a new one anyway, or stop."""
    return service.decide(store, actor, reading_id, payload)


@router.post("/readings/{reading_id}/finish")
def finish_reading(reading_id: str, payload: service.FinishCommand, actor: Actor) -> dict:
    """The form was saved with the values (and the record it created), or the reading is dropped."""
    return service.finish(store, actor, reading_id, payload)
