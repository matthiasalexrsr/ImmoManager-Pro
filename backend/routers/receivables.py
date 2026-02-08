from fastapi import APIRouter, HTTPException, status

from ..models import Receivable, ReceivableCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/receivables", tags=["Forderungen"])


@router.get("", response_model=list[Receivable])
def list_receivables() -> list[Receivable]:
    return store.list_receivables()


@router.post("", response_model=Receivable, status_code=status.HTTP_201_CREATED)
def create_receivable(payload: ReceivableCreate) -> Receivable:
    try:
        return store.create_receivable(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{receivable_id}", response_model=Receivable)
def get_receivable(receivable_id: str) -> Receivable:
    try:
        return store.get_receivable(receivable_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{receivable_id}", response_model=Receivable)
def update_receivable(receivable_id: str, payload: ReceivableCreate) -> Receivable:
    try:
        return store.update_receivable(receivable_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{receivable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receivable(receivable_id: str) -> None:
    try:
        store.delete_receivable(receivable_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
