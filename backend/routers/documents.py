from fastapi import APIRouter, HTTPException, status

from ..models import Document, DocumentCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["Dokumente"])


@router.get("", response_model=list[Document])
def list_documents() -> list[Document]:
    return store.list_documents()


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
