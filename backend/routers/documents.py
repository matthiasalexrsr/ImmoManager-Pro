import uuid
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..auth import get_current_user
from ..dependencies import store
from ..models import Document, DocumentCreate, DocumentPatch, UserRead
from ..routers.files import _perform_ocr, analyze_file, process_ocr
from ..services import document_retention, document_text
from ..services.document_versions import ensure_binding_kept, ensure_no_originals
from ..services.file_storage import get_file_storage
from ..services.upload_policy import DOCUMENT_EXTENSIONS, read_limited, require_allowed_extension
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["Dokumente"])


class DocumentOcrAnalyzeRequest(BaseModel):
    file_url: str
    use_ai: bool = True


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
        document = store.create_document(payload)
        document_text.schedule(f"created:{document.id}")
        return document
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
    tenant_id: str | None = Form(None),
) -> Document:
    """Import a document in one step: upload + OCR + metadata persistence."""
    storage = get_file_storage()
    ext = require_allowed_extension(file.filename, DOCUMENT_EXTENSIONS)
    key = f"documents/{uuid.uuid4().hex}_{(file.filename or 'file').replace(' ', '_')}"
    file_url = storage.get_url(key)
    payload = DocumentCreate(
        title=title,
        document_type=document_type,
        document_date=document_date,  # type: ignore[arg-type]  # pydantic parses ISO date strings
        tags=tags,
        description=description,
        property_id=property_id,
        unit_id=unit_id,
        contract_id=contract_id,
        tenant_id=tenant_id,
        file_url=file_url,
    )
    try:
        await run_in_threadpool(store.validate_document_associations, payload)
        contents = await read_limited(file)
        storage.save(key, BytesIO(contents), content_type=file.content_type or "application/octet-stream")
        if ext in {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp"}:
            ocr_text = _perform_ocr(storage, key, ext)
            if ocr_text:
                ocr_key = f"{key.rsplit('.', 1)[0]}_ocr.txt"
                storage.save(ocr_key, BytesIO(ocr_text.encode("utf-8")), content_type="text/plain")
        document = await run_in_threadpool(store.create_document, payload)
        await run_in_threadpool(document_text.schedule, f"created:{document.id}")
        return document
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/ocr-analyze")
def ocr_analyze_document(payload: DocumentOcrAnalyzeRequest) -> dict:
    """Run OCR and structured analysis for a document upload."""
    ocr_result = process_ocr(payload.file_url)
    analysis = analyze_file(payload.file_url, use_ai=payload.use_ai)
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


@router.get("/search")
def search_documents(q: str = Query(..., min_length=2, max_length=200),
                     limit: int = Query(25, ge=1, le=100)) -> dict:
    """Documents whose text contains `q` (literal, case-insensitive), with a snippet around the hit."""
    return document_text.search(store, q, limit=limit)


@router.get("/text-index")
def text_index_status() -> dict:
    """How many of the visible documents are searchable by their content."""
    return document_text.status(store)


@router.post("/text-index", status_code=status.HTTP_202_ACCEPTED)
def text_index_now() -> dict:
    """Index new and changed documents now (in the background)."""
    document_text.schedule("manual:" + uuid.uuid4().hex)
    return document_text.status(store)


@router.get("/retention")
def retention_of_documents() -> dict:
    """Retention class, period and deletion lock of every visible document, and the rules."""
    return {"rules": document_retention.rules(store), "items": document_retention.assess_all(store)}


@router.get("/{document_id}/details")
def document_details(document_id: str, actor: Annotated[UserRead | None, Depends(get_current_user)] = None) -> dict:
    """Everything the document page shows: the record, its places by name, retention, the text read
    for the full-text search and the first archived versions."""
    try:
        document = store.get_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def name(getter, identifier, field):
        if not identifier:
            return None
        try:
            return getattr(getter(identifier), field)
        except NotFoundError:
            return None
    places = {"property": name(store.get_property, document.property_id, "name"),
              "unit": name(store.get_unit, document.unit_id, "label"),
              "contract": name(store.get_contract, document.contract_id, "contract_number"),
              "tenant": name(store.get_tenant, document.tenant_id, "full_name")}
    text = document_text.get(store, document.id)
    versions: dict = {"items": [], "next_before": None, "unavailable": None}
    if actor is not None:
        from ..services import document_versions
        try:
            versions = {**document_versions.history(store, document.id, actor.id, limit=10), "unavailable": None}
        except ValidationError as exc:           # versions need a property or contract the document belongs to
            versions["unavailable"] = str(exc)
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            versions["unavailable"] = str(exc.detail)
    return {"document": document.model_dump(mode="json"), "places": places,
            "retention": document_retention.assess_all(store, [document])[document.id],
            "text": None if text is None else {"source": text.source, "characters": text.characters,
                                               "indexed_at": text.indexed_at.isoformat(), "excerpt": text.text[:3000],
                                               "source_ref": text.source_ref},
            "versions": versions}


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str) -> Document:
    try:
        return store.get_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{document_id}", response_model=Document)
def update_document(document_id: str, payload: DocumentCreate) -> Document:
    try:
        ensure_binding_kept(store, "document", document_id, store.get_document(document_id), payload.model_dump())
        document = store.update_document(document_id, payload)
        document_text.schedule(f"changed:{document.id}:{document.updated_at.isoformat()}")
        return document
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{document_id}", response_model=Document)
def patch_document(document_id: str, payload: DocumentPatch) -> Document:
    try:
        ensure_binding_kept(store, "document", document_id, store.get_document(document_id),
                            payload.model_dump(exclude_unset=True))
        document = store._patch_entity("document", document_id, payload)
        if "file_url" in payload.model_fields_set:
            document_text.schedule(f"changed:{document.id}:{document.updated_at.isoformat()}")
        return document
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str,
                    retention_override: Annotated[str | None, Query(max_length=600)] = None,
                    actor: Annotated[UserRead | None, Depends(get_current_user)] = None) -> None:
    """Delete a document; refused (409) while its retention period runs, unless an owner or
    manager gives `retention_override` (a reason, kept in the audit journal)."""
    try:
        ensure_no_originals(store, "document", document_id)
        user = actor.model_dump() if actor is not None else None
        retention = document_retention.ensure_deletable(store, document_id, actor=user, override_reason=retention_override)
        if retention.get("override") and user is not None:
            document_retention.record_override(store, user, store.get_document(document_id), retention)
        store.delete_document(document_id)
        document_text.forget(store, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
