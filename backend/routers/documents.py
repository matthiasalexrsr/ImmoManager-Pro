import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from ..dependencies import store
from ..models import Document, DocumentCreate, DocumentPatch
from ..routers.files import _perform_ocr
from ..services.file_storage import get_file_storage
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/documents", tags=["Dokumente"])


@router.get("", response_model=list[Document])
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    contract_id: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Document]:
    results = store.list_documents()
    if property_id:
        results = [d for d in results if d.property_id == property_id]
    if contract_id:
        results = [d for d in results if d.contract_id == contract_id]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate) -> Document:
    try:
        return store.create_document(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import", response_model=Document, status_code=status.HTTP_201_CREATED)
async def import_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str | None = Form(None),
    document_date: str | None = Form(None),
    tags: str | None = Form(None),
    description: str | None = Form(None),
    property_id: str | None = Form(None),
    unit_id: str | None = Form(None),
    contract_id: str | None = Form(None),
) -> Document:
    """Import a document in one step: upload + OCR + metadata persistence."""
    storage = get_file_storage()
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower()
    key = f"documents/{uuid.uuid4().hex}_{(file.filename or 'file').replace(' ', '_')}"
    storage.save(key, file.file, content_type=file.content_type or "application/octet-stream")
    file_url = storage.get_url(key)

    if ext in {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp"}:
        ocr_text = _perform_ocr(storage, key, ext)
        if ocr_text:
            from io import BytesIO

            ocr_key = f"{key.rsplit('.', 1)[0]}_ocr.txt"
            storage.save(ocr_key, BytesIO(ocr_text.encode("utf-8")), content_type="text/plain")

    payload = DocumentCreate(
        title=title,
        document_type=document_type,
        document_date=document_date,
        tags=tags,
        description=description,
        property_id=property_id,
        unit_id=unit_id,
        contract_id=contract_id,
        file_url=file_url,
    )
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


@router.patch("/{document_id}", response_model=Document)
def patch_document(document_id: str, payload: DocumentPatch) -> Document:
    try:
        return store._patch_entity(None, document_id, payload, "Dokument nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    try:
        store.delete_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
