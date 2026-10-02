import uuid
from datetime import date
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..dependencies import store
from ..models import Document, DocumentCreate, DocumentPatch
from ..routers.files import (
    SUPPORTED_OCR_EXTENSIONS,
    _perform_ocr,
    _safe_extension,
    _validate_upload,
    analyze_file,
    process_ocr,
)
from ..services.file_storage import get_file_storage
from ..services.ocr_service import OCRProcessingError
from ..services.portfolio_scope import register_upload, require_assigned_scope
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["Dokumente"])


class DocumentOcrAnalyzeRequest(BaseModel):
    file_url: str
    use_ai: bool = True


class DocumentImportResponse(Document):
    """Upload-only OCR result; the original Document schema stays unchanged."""

    ocr_status: Literal["completed", "empty", "failed", "unsupported"]
    ocr_error: dict[str, str] | None = None
    ocr_url: str | None = None


@router.get("", response_model=list[Document])
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    contract_id: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Document]:
    filters = {"property_id": property_id, "contract_id": contract_id}
    results = store._list_paginated(
        entity_type="document",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    return results


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate) -> Document:
    try:
        return store.create_document(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import", response_model=DocumentImportResponse, status_code=status.HTTP_201_CREATED)
async def import_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str | None = Form(None),
    document_date: date | None = Form(None),
    tags: str | None = Form(None),
    description: str | None = Form(None),
    property_id: str | None = Form(None),
    unit_id: str | None = Form(None),
    contract_id: str | None = Form(None),
) -> DocumentImportResponse:
    """Import a document in one step: upload + OCR + metadata persistence."""
    require_assigned_scope()
    contents = await file.read(settings.max_upload_size_bytes + 1)
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="Datei überschreitet das Upload-Größenlimit.")
    _validate_upload(file)
    storage = get_file_storage()
    ext = _safe_extension(file.filename)
    key = f"documents/{uuid.uuid4().hex}.{ext}"
    storage.save(key, BytesIO(contents), content_type=file.content_type or "application/octet-stream")
    register_upload(key)
    file_url = storage.get_url(key)

    ocr_status: Literal["completed", "empty", "failed", "unsupported"] = "unsupported"
    ocr_error = None
    ocr_url = None
    if ext in SUPPORTED_OCR_EXTENSIONS:
        try:
            ocr_text = _perform_ocr(storage, key, ext)
            ocr_status = "completed" if ocr_text else "empty"
        except OCRProcessingError as exc:
            ocr_text = None
            ocr_status = "failed"
            ocr_error = {"code": exc.code, "message": exc.message}
        if ocr_text:
            ocr_key = f"{key.rsplit('.', 1)[0]}_ocr.txt"
            storage.save(ocr_key, BytesIO(ocr_text.encode("utf-8")), content_type="text/plain")
            ocr_url = storage.get_url(ocr_key)

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
        document = store.create_document(payload)
        return DocumentImportResponse(**document.model_dump(), ocr_status=ocr_status, ocr_error=ocr_error, ocr_url=ocr_url)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/ocr-analyze", response_model=None)
def ocr_analyze_document(payload: DocumentOcrAnalyzeRequest) -> dict | JSONResponse:
    """Run OCR and structured analysis for a document upload."""
    try:
        ocr_result = process_ocr(payload.file_url)
        analysis = analyze_file(payload.file_url, use_ai=payload.use_ai)
    except HTTPException as exc:
        # Preserve only this service's typed OCR error. Authentication, scope
        # and unrelated failures still use the common application handlers.
        if isinstance(exc.detail, dict) and str(exc.detail.get("code", "")).startswith("ocr_"):
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
        raise
    result = analysis.get("result") or {}
    extracted_text = result.get("summary")

    return {
        "success": bool(analysis.get("analyzed") or ocr_result.get("has_ocr")),
        "processed": bool(ocr_result.get("processed")),
        "has_ocr": bool(ocr_result.get("has_ocr")),
        "ocr_url": ocr_result.get("ocr_url"),
        "analyzed": bool(analysis.get("analyzed")),
        "message": analysis.get("message"),
        "document_type": result.get("document_type"),
        "guessedType": result.get("document_type"),
        "extracted_text": extracted_text,
        "summary": extracted_text,
        "entities": result.get("entities"),
        "invoice_number": result.get("invoice_number"),
        "invoice_date": result.get("invoice_date"),
        "total_amount": result.get("total_amount"),
        "supplier": result.get("supplier"),
        "cost_category": result.get("cost_category"),
        "result": result,
    }


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
        return store._patch_entity("document", document_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    try:
        store.delete_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
