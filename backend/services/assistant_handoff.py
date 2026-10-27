"""Human-confirmed domain completion, atomically bound to a private proposal.

The model cannot call this module. The authenticated form save supplies the
final values; creating the record, archiving a selected private receipt and
recording the result share one transaction and one replay receipt.
"""
from __future__ import annotations

import hashlib
import mimetypes
from contextlib import nullcontext
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..business_qol_models import ConversationNote
from ..db.access_models import UploadAccessORM
from ..db.document_version_models import CHUNK_BYTES, DocumentVersionORM
from ..db.orm_models import DocumentORM, InvoiceORM, TaskORM
from ..models import Document, Invoice, InvoiceCreate, Task, TaskCreate
from . import assistant_storage as db
from . import business_qol as office
from . import document_versions as archive
from . import workspace_contexts as contexts


class ProposalSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)
    values: dict


def attachment_evidence(store, actor_id, identifier, *, allowed_attachment_ids=None, unit=None):
    from . import assistant as service
    if allowed_attachment_ids is not None and identifier not in allowed_attachment_ids:
        raise HTTPException(422, "Dieser Anhang gehört nicht zu den Quellen dieses Auftrags.")
    with nullcontext(unit) if unit is not None else db.work(store, actor_id) as current:
        row = db.owned_child(current, service.Attachment, identifier)
        _, data = service.verified_attachment(row)
        return {"kind": "attachment", "id": row.id, "revision": str(row.revision),
                "sha256": data["sha256"], "title": data["name"],
                "href": f"/api/v1/assistant/attachments/{row.id}/download",
                "mime": data["mime"], "byte_length": data["byte_length"]}


def get_proposal(store, actor_id, identifier):
    from .assistant import Proposal
    with db.work(store, actor_id) as unit:
        return db.public(db.owned_child(unit, Proposal, identifier))


def _insert(unit, collection, model, orm):
    if unit.db is None:
        unit.insert(getattr(unit.store, collection), model.id, model)
    else:
        values = model.model_dump()
        for name, value in values.items():
            if isinstance(value, datetime):
                values[name] = office.utc(value).replace(tzinfo=None)
        unit.db.add(orm(**values))
        unit.db.flush()


def _strict_values(values, allowed):
    if set(values) - set(allowed):
        raise HTTPException(422, "Das Fachformular enthält nicht unterstützte Felder.")
    return {key: (None if value == "" else value) for key, value in values.items()}


def _archive_receipt(unit, attachment_id, property_id, actor_id, proposal_id):
    from . import assistant as service
    if not property_id:
        raise HTTPException(422, "Bitte die Immobilie für die Rechnung und ihren Originalbeleg auswählen.")
    archive.check_account(unit.user, write_areas=("/documents",))
    context = contexts.resolve_context(unit.store, "property", property_id, actor_id, lock=True)
    row = db.owned_child(unit, service.Attachment, attachment_id, lock=True)
    raw, data = service.verified_attachment(row)
    identifier = str(uuid4())
    name = archive.filename(data["name"])
    # A user filename is display metadata, never a URL/key component: percent
    # escapes and URL delimiters must not change its identity on later reads.
    suffix = mimetypes.guess_extension(data["mime"]) or ".bin"
    key = f"assistant-archive/{identifier}/original{suffix}"
    # The original lives in immutable database blocks. Authorize its virtual
    # upload identity before the document association is flushed; both grant
    # and document must roll back together if the final form save fails.
    portfolio_id = context["values"]["portfolio_id"]
    if unit.db is None:
        raw_store = object.__getattribute__(unit.store, "__dict__")
        unit.add_set_entry(raw_store.setdefault("_upload_grants", set()), (key, portfolio_id))
    else:
        unit.db.add(UploadAccessORM(storage_key=key, portfolio_id=portfolio_id, uploaded_by=actor_id))
        unit.db.flush()
    document = Document(id=identifier, property_id=property_id, title=name, document_type="invoice",
                        file_url=f"/uploads/{key}",
                        description="Nach Prüfung aus einer persönlichen Assistenten-Unterhaltung übernommen.")
    unit.store.validate_document_associations(document)
    _insert(unit, "documents", document, DocumentORM)
    _, binding = archive.bind_document(unit, document.id)
    _publish_receipt(unit, document, binding, raw, name, data["mime"], proposal_id,
                     {"proposal_id": proposal_id, "attachment_id": attachment_id})
    return document.id


def _publish_receipt(unit, document, binding, raw, name, media_type, proposal_id, origin):
    digest = hashlib.sha256(raw).hexdigest()
    manifest = DocumentVersionORM(id=str(uuid4()), document_id=document.id, **binding,
        number=1, predecessor_id=None, restored_from_id=None, actor_id=unit.actor_id,
        idempotency_key="assistant-receipt-" + proposal_id,
        request_sha256=hashlib.sha256((proposal_id + ":" + digest).encode()).hexdigest(),
        operation="archive_original", comment="Geprüfter Originalbeleg aus dem Assistenten",
        filename=name, media_type=media_type, sha256=digest, size_bytes=len(raw),
        metadata_snapshot={**document.model_dump(mode="json"),
                           "assistant_origin": origin},
        created_at=archive.now())
    archive.validate_manifest(manifest)
    archive.persist_version_bytes(unit, manifest, (raw[offset:offset + CHUNK_BYTES]
                                                 for offset in range(0, len(raw), CHUNK_BYTES)))


def _existing_receipt(unit, document_id, property_id, proposal_id, evidence):
    from . import assistant_context, business_documents
    resolved = contexts.resolve_context(unit.store, "document", document_id, unit.actor_id, lock=True)
    if not property_id or resolved["property_id"] != property_id:
        raise HTTPException(422, "Rechnung und Originalbeleg müssen derselben zugeordneten Immobilie angehören.")
    current = assistant_context._source(unit.store, "document", document_id, unit.actor_id)
    if current["revision"] != evidence["revision"] or current["sha256"] != evidence["sha256"]:
        raise HTTPException(409, "Der Dokumentbeleg wurde geändert. Bitte erneut prüfen.")
    if archive.head(unit, document_id) is not None:
        # _source verifies the authoritative original and its immutable blocks.
        return document_id
    archive.check_account(unit.user, write_areas=("/documents",))
    document, binding = archive.bind_document(unit, document_id, lock=True)
    raw = business_documents._file(document.file_url)
    if hashlib.sha256(raw).hexdigest() != current["file_sha256"]:
        raise HTTPException(409, "Der Originalbeleg wurde während der Prüfung geändert.")
    name = archive.filename(document.file_url)
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    _publish_receipt(unit, document, binding, raw, name, media_type, proposal_id,
                     {"proposal_id": proposal_id, "document_id": document_id})
    return document_id


def save_proposal(store, actor_id, identifier, command: ProposalSave):
    from . import assistant as service
    from .assistant_proposals import InvoiceValues, NoteValues, validate_proposal
    operation = "proposal.save:" + identifier
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = db.owned_child(unit, service.Proposal, identifier, lock=True)
        if db.replay(unit, operation, command):
            result = db.public(row)
            return {"proposal": result, "record": result.get("record"), "replayed": True}
        data = db.payload(row)
        if command.expected_revision > row.revision:
            raise HTTPException(409, "Der übermittelte Bearbeitungsstand liegt in der Zukunft. Bitte neu laden.")
        # The proposal itself is a second durable replay fence. A new browser
        # command after a lost success must never create the domain record twice.
        if row.state == "saved":
            if data.get("_saved_values") != command.values:
                raise HTTPException(409, "Dieser Vorschlag wurde bereits mit anderen Angaben gespeichert.")
            db.receipt(unit, operation, command, row)
            return {"proposal": db.public(row), "record": data["record"], "replayed": True}
        db.revision(row, command.expected_revision)
        if row.state != "applied":
            raise HTTPException(409, "Bitte den Vorschlag zunächst prüfen und den Entwurf übernehmen.")
        proposed = data["payload"]
        kind = proposed["kind"]
        archive.check_account(unit.user, write_areas=({"task": "/tasks", "note": "/tasks", "invoice": "/invoices"}[kind],))
        run = db.owned_child(unit, service.Run, data["run_id"], lock=True)
        run_data = db.payload(run)
        refs = {(source["kind"], source["id"]) for source in run_data["_bundle"]["sources"]}
        refs.update((source["kind"], source["id"]) for source in proposed.get("evidence", []))
        for field, source_kind in (("property_id", "property"), ("unit_id", "unit")):
            source_id = command.values.get(field)
            if isinstance(source_id, str) and source_id.strip():
                refs.add((source_kind, source_id))
        for source_kind, source_id in sorted(refs):
            if source_kind == "attachment":
                attachment_evidence(unit.store, actor_id, source_id,
                                    allowed_attachment_ids=run_data.get("attachment_ids", []), unit=unit)
            else:
                contexts.resolve_context(unit.store, source_kind, source_id, actor_id, lock=True)
        service.require_current_analysis(unit, run)
        validate_proposal(unit.store, proposed, actor_id, context_bundle=run_data["_bundle"],
                          allowed_attachment_ids=run_data.get("attachment_ids", []))
        stamp = office.timestamp()
        created: Any
        payload: Any
        checked: Any
        if kind == "task":
            values = _strict_values(command.values, TaskCreate.model_fields)
            payload = TaskCreate.model_validate(values)
            if payload.parent_task_id:
                raise HTTPException(422, "Serienkinder werden durch den vorhandenen Aufgabenplan erzeugt.")
            if not payload.title.strip() or payload.status not in {"open", "in_progress", "completed", "cancelled"}:
                raise HTTPException(422, "Bitte Titel und gültigen Aufgabenstatus angeben.")
            if payload.priority not in {"low", "medium", "high", "urgent"}:
                raise HTTPException(422, "Ungültige Priorität.")
            contexts.validate_values(unit.store, "tasks", payload.model_dump(mode="json"), actor_id)
            validator = unit.store.communication if unit.db is not None else unit.store
            validator.validate_task(payload)
            created = Task(id=str(uuid4()), **payload.model_dump(), created_at=stamp, updated_at=stamp)
            _insert(unit, "tasks", created, TaskORM)
            record = {"kind": "task", "id": created.id, "title": created.title,
                      "href": f"/tasks?focus_id={created.id}"}
        elif kind == "invoice":
            values = _strict_values(command.values, InvoiceCreate.model_fields)
            checked = InvoiceValues.model_validate(values)
            payload = InvoiceCreate.model_validate(checked.model_dump(mode="json"))
            contexts.validate_values(unit.store, "invoices", payload.model_dump(mode="json"), actor_id)
            document_refs = [ref for ref in proposed["evidence"] if ref["kind"] == "document"]
            attachment_refs = [ref for ref in proposed["evidence"] if ref["kind"] == "attachment"]
            if len(document_refs) + len(attachment_refs) != 1:
                raise HTTPException(422, "Für die Rechnung bitte genau einen maßgeblichen Originalbeleg auswählen.")
            if document_refs:
                document_id = _existing_receipt(unit, document_refs[0]["id"], payload.property_id,
                                                identifier, document_refs[0])
            else:
                document_id = _archive_receipt(unit, attachment_refs[0]["id"], payload.property_id, actor_id, identifier)
            created = Invoice(id=str(uuid4()), **payload.model_dump(), source_document_id=document_id,
                              created_at=stamp, updated_at=stamp)
            _insert(unit, "invoices", created, InvoiceORM)
            record = {"kind": "invoice", "id": created.id, "title": created.supplier,
                      "href": f"/invoice-review/{created.id}", "document_id": document_id}
        else:
            values = _strict_values(command.values, NoteValues.model_fields)
            checked = NoteValues.model_validate(values)
            anchor = proposed["anchor"]
            context = contexts.resolve_context(unit.store, anchor["kind"], anchor["id"], actor_id, lock=True)
            created = ConversationNote(id=str(uuid4()), entity_type=context["kind"], entity_id=context["entity_id"],
                property_id=office._context_property(context), body=checked.body, conversation_kind=checked.conversation_kind,
                occurred_at=stamp, actor_id=actor_id, created_at=stamp, updated_at=stamp)
            office.put_record(unit, "business_conversation_notes", created)
            record = {"kind": "note", "id": created.id, "title": context["title"], "href": context["href"]}
        data.update(record=record, _saved_values=command.values,
                    completion={"actor_id": actor_id, "at": stamp.isoformat()})
        data["handoff"] = {**data.get("handoff", {}), "record": record}
        row = db.put(unit, service.Proposal, data, row=row, state="saved")
        db.receipt(unit, operation, command, row)
        return {"proposal": db.public(row), "record": record, "replayed": False}
