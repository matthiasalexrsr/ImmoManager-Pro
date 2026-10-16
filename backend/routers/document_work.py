"""Authenticated document tools; all writes recheck the actor in their transaction."""
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import store
from ..document_work_models import (
    AnnotationSave,
    Command,
    EvidenceRequest,
    EvidenceUpload,
    ExportRequest,
    InvoiceTakeover,
    OpenSession,
    SessionRebase,
)
from ..models import UserRead
from ..services import document_pdf
from ..services import document_work as service
from ..services.document_formats import decode
from ..services.upload_policy import read_limited
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/documents/{document_id}/work", tags=["Dokumentwerkzeuge"])
evidence_router = APIRouter(prefix="/handover-protocols/{protocol_id}/evidence", tags=["Übergabenachweise"])
Actor = Annotated[UserRead, Depends(require_auth)]


class SaveDocx(Command):
    content_base64: str = Field(min_length=1)
    session_revision: int = Field(ge=1)
    autosave: bool = False


class SaveText(Command):
    text: str
    session_revision: int = Field(ge=1)
    autosave: bool = False


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Dokument oder zugehöriger Vorgang nicht gefunden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Gleichzeitige Änderung. Bitte den Stand neu laden; denselben Auftrag mit demselben Schlüssel wiederholen.") from None


@router.get("/source")
def source(document_id: str, actor: Actor):
    return call(service.source, store, document_id, actor.id)


@router.get("/capabilities")
def capabilities(document_id: str, actor: Actor):
    call(service.source, store, document_id, actor.id)
    return {"pdf_engine": document_pdf.available(), "docx_storage": True,
            "docx_editor": "optional_local_component", "docx_pdf_conversion": "requires_local_libreoffice",
            "ocr_pdf_layer": "requires_local_tesseract", "cryptographic_signature_verification": False,
            "redaction_mode": "remove_content_then_rasterize_all_pages"}


@router.post("/archive")
def archive(document_id: str, payload: Command, actor: Actor):
    return call(service.archive_upload, store, document_id, payload, actor.id)


@router.get("/versions")
def versions(document_id: str, actor: Actor, before: int | None = None, limit: int = Query(25, ge=1, le=100)):
    # Use fresh scope even when the service is called independently of middleware.
    with service.work(store, actor.id) as unit:
        return call(service.archive.history, unit.store, document_id, actor.id, before=before, limit=limit)


@router.get("/versions/{version_id}/download")
def download(document_id: str, version_id: str, actor: Actor):
    content, row = call(service.download, store, document_id, version_id, actor.id)
    return Response(content, media_type=row["media_type"], headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox", "X-Content-SHA256": row["sha256"],
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row["filename"], safe="")})


@router.post("/sessions")
def open_session(document_id: str, payload: OpenSession, actor: Actor):
    return call(service.open_session, store, document_id, payload, actor.id)


@router.get("/sessions/{session_id}")
def session(document_id: str, session_id: str, actor: Actor):
    return call(service.read_session, store, document_id, session_id, actor.id)


@router.post("/sessions/{session_id}/rebase")
def rebase(document_id: str, session_id: str, payload: SessionRebase, actor: Actor):
    return call(service.rebase_session, store, document_id, session_id, payload, actor.id)


@router.post("/sessions/{session_id}/docx")
def save_docx(document_id: str, session_id: str, payload: SaveDocx, actor: Actor):
    command = Command.model_validate(payload.model_dump(include=set(Command.model_fields)))
    return call(service.save_docx, store, document_id, session_id, command, decode(payload.content_base64),
                payload.session_revision, actor.id, autosave=payload.autosave)


@router.post("/sessions/{session_id}/text")
def save_text(document_id: str, session_id: str, payload: SaveText, actor: Actor):
    command = Command.model_validate(payload.model_dump(include=set(Command.model_fields)))
    return call(service.save_docx, store, document_id, session_id, command, payload.text.encode("utf-8"),
                payload.session_revision, actor.id, autosave=payload.autosave, native_format="text")


@router.post("/sessions/{session_id}/annotations")
def annotations(document_id: str, session_id: str, payload: AnnotationSave, actor: Actor):
    return call(service.save_annotations, store, document_id, session_id, payload, actor.id)


@router.get("/pdf-inspection")
def inspect(document_id: str, actor: Actor, start_page: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    with service.work(store, actor.id) as unit:
        _, _, _, content, _ = call(service.read_source, unit, document_id)
        return call(document_pdf.isolated, content, "inspect", {"start_page": start_page, "limit": limit})


@router.post("/exports")
def export(document_id: str, payload: ExportRequest, actor: Actor):
    return call(service.queue_export, store, document_id, payload, actor.id)


@router.get("/exports/{job_id}")
def export_status(document_id: str, job_id: str, actor: Actor):
    return call(service.job_status, store, document_id, job_id, actor.id)


@router.post("/exports/{job_id}/run")
def export_run(document_id: str, job_id: str, actor: Actor):
    return call(service.run_export, store, document_id, job_id, actor.id)


@router.post("/invoice-proposal")
def propose_invoice(document_id: str, payload: Command, actor: Actor):
    return call(service.propose_invoice, store, document_id, payload, actor.id)


@router.post("/analysis")
def queue_analysis(document_id: str, payload: Command, actor: Actor):
    return call(service.queue_analysis, store, document_id, payload, actor.id)


@router.post("/analysis/{job_id}/run")
def run_analysis(document_id: str, job_id: str, actor: Actor):
    return call(service.run_analysis, store, document_id, job_id, actor.id)


@router.post("/invoice-takeover")
def take_invoice(document_id: str, payload: InvoiceTakeover, actor: Actor):
    return call(service.take_invoice, store, document_id, payload, actor.id)


@router.post("/evidence")
def attach_evidence(document_id: str, payload: EvidenceRequest, actor: Actor):
    return call(service.attach_evidence, store, document_id, payload, actor.id)


@router.get("/evidence-protocol/{protocol_id}")
def evidence_protocol(document_id: str, protocol_id: str, actor: Actor):
    return call(service.evidence_protocol, store, document_id, protocol_id, actor.id)


@router.get("/choices/{kind}")
def choices(document_id: str, kind: Literal["protocols", "pdfs"], actor: Actor,
            after: str | None = None, limit: int = Query(25, ge=1, le=100)):
    return call(service.source_choices, store, document_id, actor.id, kind, after=after, limit=limit)


@router.get("/history")
def history(document_id: str, actor: Actor, after: str | None = None, limit: int = Query(25, ge=1, le=100)):
    return call(service.history, store, document_id, actor.id, after=after, limit=limit)


@evidence_router.get("/source")
def protocol_source(protocol_id: str, actor: Actor):
    return call(service.protocol_source, store, protocol_id, actor.id)


@evidence_router.get("")
def evidence_list(protocol_id: str, actor: Actor, after: str | None = None, limit: int = Query(25, ge=1, le=100)):
    return call(service.protocol_evidence, store, protocol_id, actor.id, after=after, limit=limit)


@evidence_router.post("")
async def evidence_upload(protocol_id: str, actor: Actor, file: UploadFile = File(...),
    command_key: str = Form(..., min_length=1, max_length=100), expected_protocol_revision: str = Form(...),
    expected_sha256: str = Form(...), purpose: Literal["original_photo", "signed_return"] = Form(...)):
    from pydantic import ValidationError as PayloadError
    from starlette.concurrency import run_in_threadpool
    try:
        command = EvidenceUpload(command_key=command_key, expected_protocol_revision=expected_protocol_revision,
            expected_sha256=expected_sha256, purpose=purpose)
    except PayloadError:
        raise HTTPException(422, "Bitte Nachweisart, Quellrevision und Datei prüfen.") from None
    content = await read_limited(file)
    return await run_in_threadpool(call, service.upload_evidence, store, protocol_id, command, content,
                                   file.filename or "Nachweis", actor.id)
