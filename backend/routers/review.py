"""Review list: rents and payments that need a decision."""

from datetime import date

from fastapi import APIRouter, Query

from ..concurrency import shared_portfolio_result
from ..dependencies import store
from ..domain.clock import local_today
from ..services.review import review_items

router = APIRouter(prefix="/review", tags=["Prüfliste"])


@router.get("")
@shared_portfolio_result
def get_review_list(as_of: date | None = Query(None)) -> dict:
    items = review_items(store, as_of or local_today())
    return {"count": len(items), "items": items}
