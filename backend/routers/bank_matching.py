"""Explicit suggestions and confirmation for already persisted bank bookings."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..dependencies import get_store
from ..services.bank_matching import (
    MatchConfirm,
    MatchError,
    SuggestionPage,
    SuggestionQuery,
    confirm_match,
    suggestions,
)
from ..services.payment_history import PaymentHistoryPage, PaymentHistoryQuery, payment_history
from ..services.payments import Payment
from ..storage import NotFoundError, ValidationError
from .bank_imports import actor, writer

router = APIRouter(prefix="/bookings", tags=["Bankzuordnung"])


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except (MatchError, ValidationError, NotFoundError) as error:
        status = error.status if isinstance(error, MatchError) else 404 if isinstance(error, NotFoundError) else 409
        code = error.code if isinstance(error, MatchError) else "MATCH_NOT_FOUND" if status == 404 else "MATCH_CONFLICT"
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": str(error),
            "details": [{"clear_code": code, "recovery": "review_again"}]}})


@router.get("/{booking_id}/suggestions", response_model=SuggestionPage)
def list_suggestions(booking_id: str, query: Annotated[SuggestionQuery, Query()], store=Depends(get_store), scope=Depends(actor)):
    return call(suggestions, store, booking_id, query, scope=scope)


@router.post("/{booking_id}/matching", status_code=201, response_model=Payment)
def match(booking_id: str, command: MatchConfirm, store=Depends(get_store), scope=Depends(writer)):
    return call(confirm_match, store, booking_id, command, scope=scope)


@router.get("/{booking_id}/allocations", response_model=PaymentHistoryPage)
def allocations(booking_id: str, query: Annotated[PaymentHistoryQuery, Query()], store=Depends(get_store), scope=Depends(actor)):
    return call(payment_history, store, "booking", booking_id, query, scope=scope)
