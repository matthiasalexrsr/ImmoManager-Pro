"""Local TEHA field, mapping and import commands. No provider writes."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError as PydanticValidationError

from ..auth import require_role
from ..config import settings
from ..db.teha_receive_schema import TehaReceiveSchemaError
from ..dependencies import get_store
from ..routers.datev import PrivateDownloadResponse
from ..services.integrations.history_types import HistoryError
from ..services.portfolio_scope import require_installation_scope
from ..services.providers import teha_receive_commands as commands
from ..services.providers.teha_command_types import (
    ConfirmMapping,
    ImportDocument,
    ImportTechnicalOrder,
    PreviewImport,
)
from ..services.providers.teha_field_manifest import manifest
from ..services.providers.teha_journal_reader import TehaReceiveError
from ..services.workflow_authority_route import WorkflowAuthorityRoute


def _require_teha_administration(
    response: Response,
    actor=Depends(require_role("eigentuemer", "verwalter")),
):
    if actor.role != "eigentuemer" and actor.portfolio_access != "all":
        raise HTTPException(403, "Installationsverwaltung erforderlich")
    require_installation_scope()
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return actor


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except HistoryError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message}) from None
    except TehaReceiveError as error:
        raise HTTPException(409, {"code": error.code, "message": "TEHA-Historienbeleg ist nicht verwendbar."}) from None
    except TehaReceiveSchemaError:
        raise commands._schema_unavailable() from None


router = APIRouter(
    prefix="/integrations/teha",
    tags=["TEHA"],
    route_class=WorkflowAuthorityRoute,
    dependencies=[Depends(_require_teha_administration)],
)


@router.get("/field-manifest")
def get_field_manifest() -> dict[str, object]:
    return manifest()


@router.put("/mappings/{kind}/{external_key}")
def confirm_mapping(
    kind: str,
    external_key: str,
    payload: ConfirmMapping,
    actor=Depends(_require_teha_administration),
    store=Depends(get_store),
):
    if payload.identity.kind != kind or payload.external_identity_hash != external_key:
        raise HTTPException(422, "Pfad und opaque Mappingidentität stimmen nicht überein.")
    return _call(commands.confirm_mapping, store, payload, actor.id)


@router.post("/imports/preview")
def preview_import(
    payload: PreviewImport,
    actor=Depends(_require_teha_administration),
    store=Depends(get_store),
):
    return _call(commands.preview_import, store, payload, actor.id)


@router.post("/imports/document")
async def import_document(
    payload: str = Form(...),
    file: UploadFile = File(...),
    actor=Depends(_require_teha_administration),
    store=Depends(get_store),
):
    try:
        command = ImportDocument.model_validate_json(payload)
    except PydanticValidationError as error:
        raise HTTPException(422, error.errors()) from None
    content = await file.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Dokument überschreitet das konfigurierte Uploadbudget.")
    return _call(commands.import_document, store, command, content, actor.id)


@router.post("/imports/technical-order")
def import_technical_order(
    payload: ImportTechnicalOrder,
    actor=Depends(_require_teha_administration),
    store=Depends(get_store),
):
    return _call(commands.import_technical_order, store, payload, actor.id)


@router.get("/imports/{receipt_id}/document")
def download_imported_document(
    receipt_id: str,
    actor=Depends(_require_teha_administration),
    store=Depends(get_store),
):
    compiled, captured = _call(
        commands.prepare_document_download,
        store,
        receipt_id,
        actor.id,
    )
    try:
        commands.refresh_scope(captured)
        filename = compiled.manifest["filename"]
        return PrivateDownloadResponse(
            compiled,
            captured,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": (
                    "attachment; filename*=UTF-8''"
                    + quote(filename, safe="")
                ),
                "Content-Length": str(compiled.manifest["size"]),
                "X-Content-SHA256": compiled.manifest["sha256"],
                "X-Content-Type-Options": "nosniff",
            },
        )
    except BaseException:
        compiled.close()
        raise
