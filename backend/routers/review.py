"""Review list: rents and payments that need a decision."""

from datetime import date

from fastapi import APIRouter, Query

from ..dependencies import store
from ..services.review import review_items

router = APIRouter(prefix="/review", tags=["Prüfliste"])


@router.get("")
def get_review_list(as_of: date | None = Query(None)) -> dict:
    items = review_items(store, as_of or date.today())
    return {"count": len(items), "items": items}
