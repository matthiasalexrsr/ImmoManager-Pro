"""SEPA direct debit files for rents (written here, uploaded to online banking by the user)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import sepa_debit
from ..storage import NotFoundError

Actor = Annotated[UserRead, Depends(require_auth)]
router = APIRouter(prefix="/receivables/sepa-debits", tags=["SEPA-Lastschriften"])
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args):
    try:
        return operation(*args)
    except NotFoundError:
        raise HTTPException(404, "Nicht gefunden.") from None
    except IntegrityError:
        raise HTTPException(409, "Gleichzeitig geändert. Bitte die Vorschau neu laden.") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Speicherung nicht bestätigt. Bitte denselben Vorgang erneut versuchen.") from None


@router.get("/preview")
async def preview(actor: Actor, response: Response, account_id: str = Query(..., max_length=120),
                  month: str = Query(..., max_length=7), collection_date: str | None = Query(None, max_length=10)):
    """Contracts of the account's portfolio that pay by direct debit, with what is open in the month."""
    response.headers.update(_PRIVATE)
    return await run_in_threadpool(_call, sepa_debit.preview, store, actor.id, account_id, month, collection_date)


@router.post("/files")
async def create_file(payload: dict[str, Any], actor: Actor, response: Response):
    """The pain.008 file for the chosen contracts (returned as text; nothing is sent to a bank)."""
    response.headers.update(_PRIVATE)
    return await run_in_threadpool(_call, sepa_debit.create, store, actor.id, payload)
