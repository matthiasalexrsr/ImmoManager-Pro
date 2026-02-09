from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Document, DocumentCreate
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["Dokumente"])


@router.get("", response_model=list[Document])
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    contract_id: str | None = Query(None),
) -> list[Document]:
    results = store.list_documents()
    if property_id:
        results = [d for d in results if d.property_id == property_id]
    if contract_id:
        results = [d for d in results if d.contract_id == contract_id]
    return results[skip : skip + limit]


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate) -> Document:
    try:
        return store.create_document(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str) -> Document:
    try:
        return store.get_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{document_id}", response_model=Document)
def update_document(document_id: str, payload: DocumentCreate) -> Document:
    try:
        return store.update_document(document_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    try:
        store.delete_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
