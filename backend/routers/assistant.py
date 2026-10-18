"""Personal assistant API. Local analysis is available independently of a provider."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from ..assistant_models import (
    ConversationCreate,
    ConversationEdit,
    ProposalApply,
    ProposalPreview,
    ProposalReject,
    RevisionCommand,
    RunCreate,
)
from ..auth import require_auth
from ..dependencies import store
from ..finance_models import ReportDefinition
from ..models import UserRead
from ..services import assistant as service
from ..services.assistant import Attachment, Message, Proposal, Run
from ..services.assistant_context import ContextSelection, local_analysis
from ..services.assistant_handoff import ProposalSave
from ..services.private_file_response import private_bytes


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(prefix="/assistant", tags=["Persönlicher KI-Assistent"], dependencies=[Depends(private)])
Actor = Annotated[UserRead, Depends(require_auth)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=2048)]


class LocalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: ContextSelection = Field(default_factory=ContextSelection)
    report: ReportDefinition | None = None
    extract_documents: bool = False


class LoginCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str = Field(min_length=1, max_length=120)


class LoginComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=4096, repr=False)


def provider_call(operation, actor_id, provider, *args):
    if provider not in ("local", "codex", "claude"):
        raise HTTPException(404, "KI-Anbieter nicht gefunden.")
    from ..services import assistant_providers
    try:
        return getattr(assistant_providers, operation)(actor_id, provider, *args)
    except assistant_providers.ProviderError as exc:
        raise HTTPException(409, {"code": exc.code, "message": "KI-Verbindung konnte nicht abgeschlossen werden. Bitte Verbindungsstatus prüfen."}) from None


@router.get("/capabilities")
def capabilities(actor: Actor):
    return service.capabilities(actor.id)


@router.get("/connections/{provider}")
def connection(provider: str, actor: Actor):
    return provider_call("connection_status", actor.id, provider)


@router.post("/connections/{provider}/login")
def login(provider: str, actor: Actor):
    return provider_call("start_login", actor.id, provider)


@router.post("/connections/{provider}/login/cancel")
def cancel_login(provider: str, payload: LoginCancel, actor: Actor):
    return provider_call("cancel_login", actor.id, provider, payload.login_id)


@router.post("/connections/{provider}/disconnect")
def disconnect(provider: str, actor: Actor):
    return provider_call("disconnect", actor.id, provider)


@router.post("/connections/{provider}/probe")
def probe_connection(provider: str, actor: Actor):
    return provider_call("probe_connection", actor.id, provider)


@router.post("/connections/{provider}/login/{login_id}/complete")
def complete_login(provider: str, login_id: str, payload: LoginComplete, actor: Actor):
    if provider != "claude":
        raise HTTPException(422, "Diesen Anmeldecode bitte ausschließlich auf der Anbieterseite eingeben.")
    return provider_call("complete_login", actor.id, provider, login_id, payload.code)


@router.post("/context/preview")
def context_preview(payload: LocalRequest, actor: Actor):
    return local_analysis(store, payload.selection, actor.id, report=payload.report,
                          extract_documents=payload.extract_documents)


@router.get("/conversations")
def conversations(actor: Actor, cursor: Cursor = None, limit: Limit = 50):
    return service.list_records(store, actor.id, cursor=cursor, limit=limit)


@router.post("/conversations")
def create_conversation(payload: ConversationCreate, actor: Actor):
    return service.create_conversation(store, actor.id, payload)


@router.get("/conversations/{identifier}")
def get_conversation(identifier: str, actor: Actor):
    return service.get_conversation(store, actor.id, identifier)


@router.patch("/conversations/{identifier}")
def edit_conversation(identifier: str, payload: ConversationEdit, actor: Actor):
    return service.edit_conversation(store, actor.id, identifier, payload)


@router.get("/conversations/{identifier}/messages")
def messages(identifier: str, actor: Actor, cursor: Cursor = None, limit: Limit = 50):
    return service.list_records(store, actor.id, Message, conversation_id=identifier, cursor=cursor, limit=limit)


@router.get("/conversations/{identifier}/runs")
def runs(identifier: str, actor: Actor, cursor: Cursor = None, limit: Limit = 50):
    return service.list_records(store, actor.id, Run, conversation_id=identifier, cursor=cursor, limit=limit)


@router.post("/conversations/{identifier}/runs")
def submit(identifier: str, payload: RunCreate, actor: Actor):
    return service.submit(store, actor.id, identifier, payload)


@router.get("/runs/{identifier}")
def run_status(identifier: str, actor: Actor):
    return service.get_run(store, actor.id, identifier)


@router.post("/runs/{identifier}/cancel")
def cancel_run(identifier: str, payload: RevisionCommand, actor: Actor):
    return service.cancel(store, actor.id, identifier, payload)


@router.post("/runs/{identifier}/retry")
def retry_run(identifier: str, payload: RevisionCommand, actor: Actor):
    return service.retry(store, actor.id, identifier, payload)


@router.get("/conversations/{identifier}/attachments")
def attachments(identifier: str, actor: Actor, cursor: Cursor = None, limit: Limit = 50):
    return service.list_records(store, actor.id, Attachment, conversation_id=identifier, cursor=cursor, limit=limit)


@router.post("/conversations/{identifier}/attachments")
async def upload(identifier: str, actor: Actor, file: UploadFile = File(...)):
    raw = await file.read(service.attachment_limit() + 1)
    return await run_in_threadpool(service.add_attachment, store, actor.id, identifier, raw, file.filename or "Anhang")


@router.get("/attachments/{identifier}/download")
def download(identifier: str, actor: Actor):
    raw, data = service.download(store, actor.id, identifier)
    from urllib.parse import quote
    return private_bytes(raw, media_type=data["mime"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(data["name"], safe=""),
        "Content-Security-Policy": "sandbox", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/conversations/{identifier}/proposals")
def proposals(identifier: str, actor: Actor, cursor: Cursor = None, limit: Limit = 50):
    return service.list_records(store, actor.id, Proposal, conversation_id=identifier, cursor=cursor, limit=limit)


@router.post("/proposals/{identifier}/preview")
def preview(identifier: str, payload: ProposalPreview, actor: Actor):
    return service.proposal_preview(store, actor.id, identifier, payload)


@router.post("/proposals/{identifier}/apply")
def apply(identifier: str, payload: ProposalApply, actor: Actor):
    return service.decide_proposal(store, actor.id, identifier, payload)


@router.post("/proposals/{identifier}/reject")
def reject(identifier: str, payload: ProposalReject, actor: Actor):
    return service.decide_proposal(store, actor.id, identifier, payload, reject=True)


@router.get("/proposals/{identifier}")
def get_proposal(identifier: str, actor: Actor):
    from ..services.assistant_handoff import get_proposal as operation
    return operation(store, actor.id, identifier)


@router.post("/proposals/{identifier}/save")
def save_proposal(identifier: str, payload: ProposalSave, actor: Actor):
    from ..services.assistant_handoff import save_proposal as operation
    try:
        return operation(store, actor.id, identifier, payload)
    except ValidationError:
        raise HTTPException(422, "Bitte Pflichtangaben, Beträge und Datumsangaben im Fachformular prüfen.") from None
