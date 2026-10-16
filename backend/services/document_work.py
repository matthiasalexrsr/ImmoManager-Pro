"""Document workflows on the existing transaction, scope, archive and invoice contracts.

Commands append immutable application states. An interrupted export remains queued;
its deterministic local computation may be repeated and publication is atomic. No
external service or financial action is invoked by this module.
"""
from __future__ import annotations

import base64
import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..db.document_version_models import CHUNK_BYTES, DocumentVersionORM
from ..db.document_work_models import DocumentWorkEventORM
from ..document_work_models import DocumentWorkEvent
from ..models import Document, DocumentCreate
from . import document_formats as formats
from . import document_versions as archive
from .maintenance_rows import Rows
from .portfolio_scope import require_file_access, scope_context, scope_from_user

AREA = ("/documents",)


def digest(value) -> str:
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()


@contextmanager
def work(store, actor_id, areas=()):
    with archive.work(store, actor_id, write_areas=areas) as unit:
        # Also protects direct service calls and sessions reopened after grant changes.
        with scope_context(scope_from_user(unit.user)):
            yield unit


def events(unit, **criteria):
    if unit.db is not None:
        query = select(DocumentWorkEventORM).filter_by(**criteria)
        return [DocumentWorkEvent.model_validate({column.name: getattr(row, column.name)
                for column in DocumentWorkEventORM.__table__.columns}) for row in unit.db.scalars(query)]
    return [row for row in unit.store.document_work_events.values()
            if all(getattr(row, key) == value for key, value in criteria.items())]


def latest(unit, resource):
    if unit.db is not None:
        row = unit.db.scalar(select(DocumentWorkEventORM).where(DocumentWorkEventORM.resource_id == resource)
                             .order_by(DocumentWorkEventORM.revision.desc()).limit(1))
        return None if row is None else DocumentWorkEvent.model_validate({
            column.name: getattr(row, column.name) for column in DocumentWorkEventORM.__table__.columns})
    return max(events(unit, resource_id=resource), key=lambda row: row.revision, default=None)


def append(unit, document_id, binding, kind, resource, key, fingerprint, payload):
    previous = latest(unit, resource)
    row = DocumentWorkEvent(id=str(uuid4()), document_id=document_id, portfolio_id=binding["portfolio_id"],
        protocol_id=payload.get("protocol_id") if kind == "evidence" else None,
        actor_id=unit.actor_id, kind=kind, resource_id=resource, revision=previous.revision + 1 if previous else 1,
        command_key=key, fingerprint=fingerprint, payload=deepcopy(payload), created_at=archive.now())
    if unit.db is not None:
        unit.db.add(DocumentWorkEventORM(**row.model_dump()))
        unit.db.flush()
    else:
        unit.insert(unit.store.document_work_events, row.id, row)
    return row


def replay(unit, document_id, key, fingerprint):
    found = events(unit, actor_id=unit.actor_id, command_key=key)
    if not found:
        return None
    row = found[0]
    if row.document_id != document_id or row.fingerprint != fingerprint:
        archive.fail("Dieser Wiederholungsschlüssel gehört zu einem anderen Auftrag.")
    return deepcopy(row.payload)


def fingerprint(action, document_id, payload):
    return digest({"action": action, "document_id": document_id, "payload": payload})


def document_revision(document):
    return digest(document.model_dump(mode="json"))


def read_source(unit, document_id, *, lock=False):
    document, binding = archive.bind_document(unit, document_id, lock=lock)
    row = archive.head(unit, document_id)
    if row:
        archive.authorized_version(unit, document_id, row.id, binding)
        content = archive.original_bytes(unit, row)
        name = row.filename
    else:
        from ..routers.files import _file_url_to_key
        from .file_storage import get_file_storage
        key = _file_url_to_key(document.file_url)
        if not key:
            archive.fail("Nur eine zugeordnete lokale Uploaddatei kann übernommen werden.", 422)
        require_file_access(key)
        uploaded = get_file_storage().get(key)
        if uploaded is None:
            archive.fail("Die Quelldatei ist nicht verfügbar.", 404)
        content = uploaded
        name = archive.filename(key)
    return document, binding, row, content, name


def check_source(document, row, content, command):
    if (command.expected_version != (row.id if row else None)
            or command.expected_sha256 != digest(content)
            or command.expected_document_revision != document_revision(document)):
        archive.fail("Die Quelle wurde geändert. Eingaben bleiben erhalten; bitte Quelle neu laden und vergleichen.")


def publish(unit, document, binding, content, name, media, key, request_hash, *, extra=None):
    previous = archive.head(unit, document.id)
    row = DocumentVersionORM(id=str(uuid4()), document_id=document.id, **binding,
        number=previous.number + 1 if previous else 1, predecessor_id=previous.id if previous else None,
        restored_from_id=None, actor_id=unit.actor_id, idempotency_key=key,
        request_sha256=request_hash, operation="upload" if previous else "archive_original",
        comment="Bearbeitete Fassung" if previous else "Unveränderliches Eingangsoriginal",
        filename=archive.filename(name), media_type=media, sha256=digest(content), size_bytes=len(content),
        metadata_snapshot=document.model_dump(mode="json") | ({"document_work": extra} if extra else {}),
        created_at=archive.now())
    archive.validate_manifest(row)
    return archive.persist_version_bytes(unit, row,
        (content[offset:offset + CHUNK_BYTES] for offset in range(0, len(content), CHUNK_BYTES)))


def source(store, document_id, actor_id):
    with work(store, actor_id) as unit:
        doc, _, row, content, name = read_source(unit, document_id)
        info = formats.inspect_file(content, name)
        layer = latest(unit, "layer:" + document_id + ":" + (row.id if row else "upload"))
        return {"document": doc.model_dump(mode="json"), "document_revision": document_revision(doc),
            "version": archive.public(row) if row else None, "sha256": digest(content), "filename": name,
            "inspection": info, "layer_revision": layer.revision if layer else 0,
            "annotations": deepcopy(layer.payload["annotations"]) if layer else [],
            "signature_validity": "not_verified", "original_unchanged": True}


def archive_upload(store, document_id, command, actor_id):
    request = command.model_dump(mode="json")
    hashed = fingerprint("archive", document_id, request)
    with work(store, actor_id, AREA) as unit:
        doc, binding, row, content, name = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        if row:
            archive.fail("Das Original wurde bereits archiviert. Bitte den aktuellen Stand laden.")
        info = formats.inspect_file(content, name)
        row = publish(unit, doc, binding, content, name, info["media_type"], command.command_key, hashed,
                      extra={"inspection": info, "origin": "ordinary_upload"})
        result = {"version": archive.public(row)}
        append(unit, document_id, binding, "archive", str(uuid4()), command.command_key, hashed, result)
        return result


def open_session(store, document_id, command, actor_id):
    hashed = fingerprint("open_session", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, AREA) as unit:
        doc, binding, row, content, name = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        if row is None:
            archive.fail("Bitte zuerst das Eingangsoriginal archivieren.")
        if command.mode == "docx":
            formats.validate_docx(content)
        elif command.mode == "text":
            if row.media_type != "text/plain":
                archive.fail("Die Textbearbeitung benötigt eine UTF-8-Textdatei.", 422)
        elif row.media_type != "application/pdf":
            archive.fail("Anmerkungen benötigen ein PDF.", 422)
        identifier = str(uuid4())
        result = {"session_id": identifier, "mode": command.mode, "revision": 1, "version_id": row.id,
            "sha256": row.sha256, "document_revision": document_revision(doc), "draft_base64": None,
            "state": "open", "filename": name, "owner_id": actor_id}
        append(unit, document_id, binding, "session", identifier, command.command_key, hashed, result)
        return result


def session(unit, document_id, session_id):
    current = latest(unit, session_id)
    if (current is None or current.document_id != document_id or current.kind != "session"
            or current.actor_id != unit.actor_id):
        archive.fail("Bearbeitungssitzung nicht gefunden.", 404)
    return current


def read_session(store, document_id, session_id, actor_id):
    with work(store, actor_id) as unit:
        archive.check_account(unit.user, write_areas=AREA)
        archive.bind_document(unit, document_id)
        return deepcopy(session(unit, document_id, session_id).payload)


def rebase_session(store, document_id, session_id, command, actor_id):
    hashed = fingerprint("rebase_session", document_id, command.model_dump(mode="json") | {"session_id": session_id})
    with work(store, actor_id, AREA) as unit:
        doc, binding, row, content, _ = read_source(unit, document_id, lock=True)
        current = session(unit, document_id, session_id)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        if current.revision != command.session_revision or row is None:
            archive.fail("Sitzung oder Quelle wurde geändert. Bitte den Vergleich erneut prüfen.")
        if current.payload["mode"] not in {"docx", "text"}:
            archive.fail("Diese Sitzung unterstützt keine Inhaltsübernahme.", 422)
        formats.inspect_file(content, current.payload["filename"])
        result = deepcopy(current.payload) | {"version_id": row.id, "sha256": row.sha256,
            "document_revision": document_revision(doc), "revision": current.revision + 1,
            "rebased_from": {"version_id": current.payload["version_id"], "sha256": current.payload["sha256"]},
            "state": "recovery"}
        append(unit, document_id, binding, "session", session_id, command.command_key, hashed, result)
        return result


def save_docx(store, document_id, session_id, command, content, revision, actor_id, *, autosave=False, native_format="docx"):
    hashed = fingerprint("autosave" if autosave else "save_docx", document_id,
        command.model_dump(mode="json") | {"session": session_id, "revision": revision, "content": digest(content), "format": native_format})
    if native_format == "docx":
        formats.validate_docx(content)
    elif native_format == "text":
        if content:
            formats.inspect_file(content, "Zwischenstand.txt")
    else:
        archive.fail("Ungültiges Bearbeitungsformat.", 422)
    with work(store, actor_id, AREA) as unit:
        doc, binding, head, source_bytes, _ = read_source(unit, document_id, lock=True)
        current = session(unit, document_id, session_id)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        if current.revision != revision or current.payload["mode"] != native_format:
            archive.fail("Der Zwischenstand wurde in einem anderen Fenster geändert. Bitte vergleichen.")
        # Autosave may keep a stale editor's private work for recovery, but it
        # cannot publish it over the current source. No changes are discarded.
        if not autosave:
            check_source(doc, head, source_bytes, command)
            if current.payload["version_id"] != command.expected_version:
                archive.fail("Die Sitzung gehört zu einer anderen Ausgangsfassung.")
        elif (command.expected_version != current.payload["version_id"]
              or command.expected_sha256 != current.payload["sha256"]
              or command.expected_document_revision != current.payload["document_revision"]):
            archive.fail("Der Zwischenstand gehört zu einer anderen Ausgangsquelle.")
        result = deepcopy(current.payload)
        result.update(revision=current.revision + 1, draft_base64=base64.b64encode(content).decode(), state="recovery")
        if not autosave:
            row = publish(unit, doc, binding, content, current.payload["filename"], formats.DOCX if native_format == "docx" else "text/plain",
                          command.command_key, hashed, extra={"session_id": session_id, "source_sha256": head.sha256,
                            "signature_validity": "not_verified" if digest(content) == head.sha256 else "modified_bytes"})
            result.update(version_id=row.id, sha256=row.sha256, document_revision=document_revision(doc),
                          draft_base64=None, state="saved")
        append(unit, document_id, binding, "session", session_id, command.command_key, hashed, result)
        return result


def save_annotations(store, document_id, session_id, command, actor_id):
    hashed = fingerprint("annotations", document_id, command.model_dump(mode="json") | {"session": session_id})
    # Native engine startup/validation may take seconds. Snapshot authorized
    # bytes before computing; never hold the database writer for native work.
    # The publication transaction below rechecks every source/session/layer
    # precondition and current authorization after the worker returns.
    with work(store, actor_id, AREA) as unit:
        doc, _, head, content, _ = read_source(unit, document_id)
        current = session(unit, document_id, session_id)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, head, content, command)
        if current.payload["mode"] != "annotations" or current.payload["version_id"] != head.id:
            archive.fail("Die Sitzung gehört nicht zu dieser PDF-Fassung.")
    from .document_pdf import isolated
    isolated(content, "validate_annotations", annotations=[item.model_dump(mode="json") for item in command.annotations])
    with work(store, actor_id, AREA) as unit:
        doc, binding, head, content, _ = read_source(unit, document_id, lock=True)
        current = session(unit, document_id, session_id)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, head, content, command)
        if current.payload["mode"] != "annotations" or current.payload["version_id"] != head.id:
            archive.fail("Die Sitzung gehört nicht zu dieser PDF-Fassung.")
        resource = "layer:" + document_id + ":" + head.id
        previous = latest(unit, resource)
        if command.session_revision != (previous.revision if previous else 0):
            archive.fail("Die Anmerkungsebene wurde gleichzeitig geändert. Bitte vergleichen.")
        old_items = {item["id"]: item for item in previous.payload["annotations"]} if previous else {}
        annotations = []
        for item in command.annotations:
            identifier = item.id or str(uuid4())
            prior = old_items.get(identifier)
            annotations.append(item.model_dump(mode="json") | {"id": identifier,
                "author_id": prior["author_id"] if prior else actor_id,
                "created_at": prior["created_at"] if prior else archive.now().isoformat(),
                "modified_by": actor_id, "modified_at": archive.now().isoformat()})
        if len({item["id"] for item in annotations}) != len(annotations):
            archive.fail("Anmerkungen besitzen doppelte Identitäten.", 422)
        result = {"annotations": annotations, "layer_revision": command.session_revision + 1,
                  "source_version": head.id, "source_sha256": head.sha256, "signature_validity": "not_verified"}
        append(unit, document_id, binding, "annotations", resource, command.command_key, hashed, result)
        return result


def download(store, document_id, version_id, actor_id):
    with work(store, actor_id) as unit:
        _, binding = archive.bind_document(unit, document_id)
        row = archive.authorized_version(unit, document_id, version_id, binding)
        return archive.original_bytes(unit, row), archive.public(row)


def queue_export(store, document_id, command, actor_id):
    hashed = fingerprint("export", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, AREA) as unit:
        doc, binding, head, content, _ = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            # Return the current job, even after completion/lost reply.
            return deepcopy(latest(unit, repeated["job_id"]).payload)
        check_source(doc, head, content, command)
        if head is None:
            archive.fail("Bitte zuerst das Original archivieren.")
        sources = []
        for item in command.sources:
            if set(item) != {"document_id", "version_id", "sha256"}:
                archive.fail("Zusatzquelle benötigt Dokument, Fassung und Prüfsumme.", 422)
            _, extra_binding = archive.bind_document(unit, item["document_id"], lock=True)
            extra = archive.authorized_version(unit, item["document_id"], item["version_id"], extra_binding)
            if extra.sha256 != item["sha256"]:
                archive.fail("Eine Zusatzquelle wurde geändert.")
            sources.append(item)
        layer = latest(unit, "layer:" + document_id + ":" + head.id)
        identifier = str(uuid4())
        result = {"job_id": identifier, "state": "queued", "revision": 1, "source_version": head.id,
            "source_sha256": head.sha256, "document_revision": document_revision(doc),
            "operation": command.operation, "options": command.options, "sources": sources,
            "annotations": layer.payload["annotations"] if layer else [], "outputs": [], "error": None}
        append(unit, document_id, binding, "export", identifier, command.command_key, hashed, result)
        return result


def _job(unit, document_id, job_id):
    row = latest(unit, job_id)
    if row is None or row.document_id != document_id or row.kind != "export" or row.actor_id != unit.actor_id:
        archive.fail("Exportauftrag nicht gefunden.", 404)
    return row


def job_status(store, document_id, job_id, actor_id):
    with work(store, actor_id) as unit:
        archive.bind_document(unit, document_id)
        return deepcopy(_job(unit, document_id, job_id).payload)


def run_export(store, document_id, job_id, actor_id):
    # Compute outside the writer lock. A crash here leaves the durable queued
    # command. Concurrent workers may compute twice but publish once.
    with work(store, actor_id, AREA) as unit:
        doc, binding = archive.bind_document(unit, document_id)
        job = _job(unit, document_id, job_id)
        if job.payload["state"] == "completed":
            return job.payload
        data = deepcopy(job.payload)
        source = archive.authorized_version(unit, document_id, data["source_version"], binding)
        content = archive.original_bytes(unit, source)
        extras = []
        for item in data["sources"]:
            _, location = archive.bind_document(unit, item["document_id"])
            extra = archive.authorized_version(unit, item["document_id"], item["version_id"], location)
            extras.append(archive.original_bytes(unit, extra))
    try:
        if data["operation"] == "copy":
            outputs = [(source.filename, source.media_type, content)]
        elif data["operation"] == "docx_pdf":
            from .document_conversion import docx_pdf
            outputs = [("Ausgabe.pdf", "application/pdf", docx_pdf(content))]
        else:
            from .document_pdf import isolated
            outputs = isolated(content, data["operation"], data["options"], extras, data["annotations"])
    except HTTPException as error:
        with work(store, actor_id, AREA) as unit:
            _, binding = archive.bind_document(unit, document_id, lock=True)
            current = _job(unit, document_id, job_id)
            if current.payload["state"] == "completed":
                return current.payload
            result = deepcopy(current.payload) | {"state": "failed", "error": str(error.detail),
                                                   "revision": current.revision + 1}
            append(unit, document_id, binding, "export", job_id, str(uuid4()), digest(result), result)
            return result
    with work(store, actor_id, AREA) as unit:
        doc, binding = archive.bind_document(unit, document_id, lock=True)
        current = _job(unit, document_id, job_id)
        if current.payload["state"] == "completed":
            return current.payload
        # Metadata or rights changes cannot silently repurpose the export.
        if document_revision(doc) != data["document_revision"]:
            archive.fail("Die Dokumentzuordnung wurde geändert. Bitte einen neuen Export prüfen.")
        archive.authorized_version(unit, document_id, data["source_version"], binding)
        for item in data["sources"]:
            _, location = archive.bind_document(unit, item["document_id"], lock=True)
            archive.authorized_version(unit, item["document_id"], item["version_id"], location)
        published = []
        for index, (name, media, output) in enumerate(outputs):
            identifier = str(uuid4())
            new = Document(**DocumentCreate(title=doc.title + " – Ausgabe", property_id=doc.property_id,
                unit_id=doc.unit_id, contract_id=doc.contract_id, tenant_id=doc.tenant_id,
                document_type=doc.document_type, file_url=f"/uploads/document-outputs/{identifier}/{name}").model_dump(),
                id=identifier)
            Rows.of(unit).add("documents", new)
            _, new_binding = archive.bind_document(unit, new.id)
            row = publish(unit, new, new_binding, output, name, media, "export-" + job_id + "-" + str(index),
                digest(output), extra={"source_document_id": document_id, "source_version": source.id,
                    "source_sha256": source.sha256, "job_id": job_id, "operation": data["operation"],
                    "signature_validity": "not_verified" if data["operation"] == "copy" else "modified_bytes"})
            published.append({"document_id": new.id, "version_id": row.id, "sha256": row.sha256, "filename": name})
        result = data | {"state": "completed", "outputs": published, "error": None, "revision": current.revision + 1}
        append(unit, document_id, binding, "export", job_id, str(uuid4()), digest(result), result)
        return result


def propose_invoice(store, document_id, command, actor_id):
    """Capture the observed suggestions, never treat them as approved facts."""
    hashed = fingerprint("invoice_proposal", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, AREA) as unit:
        doc, binding, row, content, _ = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        if row is None:
            archive.fail("Bitte zuerst den Eingangsbeleg archivieren.")
        # Existing analysis is stored on Document and intake; no cloud/provider
        # is invoked here. Unknown fields are retained in the observation.
        observed: dict[str, Any] = {}
        if doc.ai_entities_json:
            try:
                parsed = json.loads(doc.ai_entities_json)
                observed = parsed if isinstance(parsed, dict) else {"raw": parsed}
            except (ValueError, TypeError):
                observed = {"unparsed": doc.ai_entities_json}
        from .business_documents import _intake
        intake = _intake(unit, document_id)
        if intake is not None:
            observed["intake"] = intake.model_dump(mode="json")
        if unit.db is not None:
            recognized = unit.db.scalar(select(DocumentWorkEventORM).where(
                DocumentWorkEventORM.document_id == document_id, DocumentWorkEventORM.kind == "analysis",
                DocumentWorkEventORM.payload["state"].as_string() == "completed",
                DocumentWorkEventORM.payload["source_version"].as_string() == row.id)
                .order_by(DocumentWorkEventORM.created_at.desc(), DocumentWorkEventORM.id.desc()).limit(1))
        else:
            analyses = [event for event in events(unit, document_id=document_id, kind="analysis")
                if event.payload.get("state") == "completed" and event.payload.get("source_version") == row.id]
            recognized = max(analyses, key=lambda event: (event.created_at, event.id), default=None)
        if recognized is not None:
            observed = deepcopy(recognized.payload["result"])
        identifier = str(uuid4())
        result = {"proposal_id": identifier, "source_version": row.id, "source_sha256": row.sha256,
                  "observed": observed, "summary": doc.ai_summary, "status": "unreviewed",
                  "observation_state": "current" if recognized or intake and intake.sha256 == row.sha256 else "stale" if intake else "unbound"}
        append(unit, document_id, binding, "invoice_proposal", identifier, command.command_key, hashed, result)
        return result


def queue_analysis(store, document_id, command, actor_id):
    hashed = fingerprint("analysis", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, AREA) as unit:
        doc, binding, row, content, name = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return latest(unit, repeated["job_id"]).payload
        check_source(doc, row, content, command)
        if row is None:
            archive.fail("Bitte zuerst das Eingangsoriginal archivieren.")
        identifier = str(uuid4())
        result = {"job_id": identifier, "state": "queued", "revision": 1, "source_version": row.id,
            "source_sha256": row.sha256, "document_revision": document_revision(doc), "filename": name,
            "result": None, "error": None}
        append(unit, document_id, binding, "analysis", identifier, command.command_key, hashed, result)
        return result


def run_analysis(store, document_id, job_id, actor_id):
    with work(store, actor_id) as unit:
        archive.check_account(unit.user, write_areas=AREA)
        _, binding = archive.bind_document(unit, document_id)
        job = latest(unit, job_id)
        if job is None or job.kind != "analysis" or job.document_id != document_id:
            archive.fail("Erkennungsauftrag nicht gefunden.", 404)
        if job.payload["state"] == "completed":
            return job.payload
        row = archive.authorized_version(unit, document_id, job.payload["source_version"], binding)
        content = archive.original_bytes(unit, row)
        data = deepcopy(job.payload)
    from .business_documents import analyze_bytes
    try:
        # Existing parser/OCR, explicitly local. No AI/provider business action.
        result = analyze_bytes(content, data["filename"], use_ai=False)
        error = None
    except Exception:
        result = None
        error = "Die lokale Erkennung lieferte keinen Text. Bitte OCR-Komponente prüfen oder Rechnungsangaben manuell erfassen."
    with work(store, actor_id, AREA) as unit:
        doc, binding, current, _, _ = read_source(unit, document_id, lock=True)
        latest_job = latest(unit, job_id)
        if latest_job.payload["state"] == "completed":
            return latest_job.payload
        if current.id != data["source_version"] or document_revision(doc) != data["document_revision"]:
            error = "Die Quelle wurde geändert. Bitte einen neuen Erkennungsauftrag anlegen."
            result = None
        output = data | {"state": "completed" if result is not None else "failed", "result": result,
                         "error": error, "revision": latest_job.revision + 1}
        append(unit, document_id, binding, "analysis", job_id, str(uuid4()), digest(output), output)
        return output


def take_invoice(store, document_id, command, actor_id):
    from decimal import Decimal

    from ..invoice_review_models import ReceiptRequest
    from . import invoice_review

    hashed = fingerprint("take_invoice", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, (*AREA, "/invoices", "/invoice-review/receipts")) as unit:
        doc, binding, row, content, _ = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        proposal = latest(unit, command.proposal_id)
        if (not proposal or proposal.kind != "invoice_proposal" or proposal.document_id != document_id
                or proposal.payload["source_version"] != command.expected_version):
            archive.fail("Der Erkennungsvorschlag gehört nicht zur aktuellen Quelle.")
        existing = events(unit, document_id=document_id, kind="invoice_taken")
        if existing:
            archive.fail("Für diesen Beleg wurde bereits eine Rechnung übernommen.")
        from decimal import InvalidOperation

        from pydantic import ValidationError as PayloadError
        try:
            raw_invoice = command.receipt.get("invoice") or {}
            for field in ("net_amount", "vat_amount", "gross_amount", "vat_rate"):
                value = Decimal(str(raw_invoice.get(field, "")))
                if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")):
                    raise ValueError()
            payload = ReceiptRequest.model_validate(command.receipt)
            if payload.invoice is not None:
                for field in ("net_amount", "vat_amount", "gross_amount", "vat_rate"):
                    if Decimal(str(getattr(payload.invoice, field))) != Decimal(str(raw_invoice[field])):
                        raise ValueError()
            for line in command.receipt.get("vat_lines") or []:
                for field in ("rate", "net", "vat"):
                    value = Decimal(str(line[field]))
                    if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")):
                        raise ValueError()
        except (PayloadError, ValueError, InvalidOperation, TypeError, AttributeError):
            archive.fail("Die Rechnungsangaben sind unvollständig oder mehrdeutig. Bitte Beträge und Datumsfelder prüfen.", 422)
        if payload.invoice is None or payload.kind != "invoice" or payload.document_id not in (None, document_id):
            archive.fail("Bitte einen Rechnungsentwurf für diesen Beleg bestätigen.", 422)
        if payload.invoice.property_id not in (None, binding["property_id"]):
            archive.fail("Rechnungsobjekt und Belegobjekt stimmen nicht überein.", 422)
        required = {"supplier", "invoice_number", "invoice_date", "net_amount", "vat_rate", "vat_amount", "gross_amount"}
        if not required <= command.field_sources.keys() or any(
                value not in {"reviewed_ocr", "manual_correction"} for value in command.field_sources.values()):
            archive.fail("Bitte jede Rechnungsangabe prüfen und ihre Herkunft bestätigen.", 422)
        draft = payload.invoice
        if Decimal(str(draft.net_amount)) + Decimal(str(draft.vat_amount)) != Decimal(str(draft.gross_amount)):
            archive.fail("Netto plus Umsatzsteuer muss dem Bruttobetrag entsprechen.", 422)
        payload = payload.model_copy(update={"document_id": document_id,
            "invoice": draft.model_copy(update={"property_id": binding["property_id"]})})
        result = invoice_review.start_review(unit.store, None, payload, actor_id, _unit=unit)
        output = {"invoice_id": result["invoice"]["id"], "source_version": row.id, "source_sha256": row.sha256,
                  "field_sources": command.field_sources, "review": result}
        append(unit, document_id, binding, "invoice_taken", str(uuid4()), command.command_key, hashed, output)
        return output


def evidence_protocol(store, document_id, protocol_id, actor_id):
    with work(store, actor_id) as unit:
        document, binding = archive.bind_document(unit, document_id)
        protocol = unit.store.get_handover_protocol(protocol_id)
        if protocol.contract_id != document.contract_id or protocol.unit_id != binding["unit_id"] or not document.contract_id:
            archive.fail("Übergabeprotokoll nicht gefunden.", 404)
        return {"protocol": protocol.model_dump(mode="json"), "revision": digest(protocol.model_dump(mode="json"))}


def source_choices(store, document_id, actor_id, kind, *, after=None, limit=25):
    """Bounded keyset choices with human titles, using the current source scopes."""
    from sqlalchemy import exists

    from ..db.orm_models import DocumentORM, HandoverProtocolORM
    with work(store, actor_id) as unit:
        document, binding = archive.bind_document(unit, document_id)
        if kind == "protocols":
            if not document.contract_id:
                return {"items": [], "next_after": None}
            if unit.db is not None:
                protocol_query = select(HandoverProtocolORM).where(HandoverProtocolORM.contract_id == document.contract_id,
                                                         HandoverProtocolORM.unit_id == binding["unit_id"])
                if after:
                    protocol_query = protocol_query.where(HandoverProtocolORM.id > after)
                records = list(unit.db.scalars(protocol_query.order_by(HandoverProtocolORM.id).limit(limit + 1)))
            else:
                records = sorted((row for row in unit.store.handover_protocols.values()
                    if row.contract_id == document.contract_id and row.unit_id == binding["unit_id"]
                    and (after is None or row.id > after)), key=lambda row: row.id)[:limit + 1]
            items = [{"id": row.id, "label": ("Einzug" if row.protocol_type == "move_in" else "Auszug")
                       + " · " + row.protocol_date.isoformat()} for row in records[:limit]]
        else:
            if unit.db is not None:
                document_query = select(DocumentORM).where(DocumentORM.id != document_id, exists(select(DocumentVersionORM.id)
                    .where(DocumentVersionORM.document_id == DocumentORM.id, DocumentVersionORM.media_type == "application/pdf")))
                if after:
                    document_query = document_query.where(DocumentORM.id > after)
                records = list(unit.db.scalars(document_query.order_by(DocumentORM.id).limit(limit + 1)))
            else:
                records = sorted((row for row in unit.store.documents.values() if row.id != document_id
                    and (after is None or row.id > after) and any(version.document_id == row.id
                    and version.media_type == "application/pdf" for version in unit.archive.versions.values())),
                    key=lambda row: row.id)[:limit + 1]
            items = [{"id": row.id, "label": row.title} for row in records[:limit]]
        return {"items": items, "next_after": records[limit - 1].id if len(records) > limit else None}


def attach_evidence(store, document_id, command, actor_id):
    hashed = fingerprint("evidence", document_id, command.model_dump(mode="json"))
    with work(store, actor_id, (*AREA, "/handover-protocols")) as unit:
        doc, binding, row, content, name = read_source(unit, document_id, lock=True)
        repeated = replay(unit, document_id, command.command_key, hashed)
        if repeated is not None:
            return repeated
        check_source(doc, row, content, command)
        protocol = unit.store.get_handover_protocol(command.protocol_id)
        if unit.db is not None:
            from ..db.orm_models import HandoverProtocolORM
            unit.db.scalar(select(HandoverProtocolORM).where(HandoverProtocolORM.id == protocol.id).with_for_update())
            unit.db.expire_all()
            protocol = unit.store.get_handover_protocol(command.protocol_id)
        if digest(protocol.model_dump(mode="json")) != command.expected_protocol_revision:
            archive.fail("Das Übergabeprotokoll wurde geändert. Bitte neu prüfen.")
        if protocol.contract_id != doc.contract_id or protocol.unit_id != binding["unit_id"] or not doc.contract_id:
            archive.fail("Nachweis und Übergabeprotokoll gehören nicht zum selben Vertrag und derselben Einheit.", 404)
        if row is None:
            archive.fail("Bitte den Nachweis zuerst als Original archivieren.")
        info = formats.inspect_file(content, name)
        if command.purpose == "original_photo" and info["format"] != "image":
            archive.fail("Ein Originalfoto benötigt eine Bilddatei.", 422)
        if command.purpose == "signed_return" and info["format"] not in {"image", "pdf"}:
            archive.fail("Eine Rückfassung benötigt einen Scan oder ein PDF.", 422)
        result = {"document_id": document_id, "version_id": row.id, "sha256": row.sha256,
            "protocol_id": protocol.id, "protocol_revision": command.expected_protocol_revision,
            "purpose": command.purpose, "signature_validity": "not_verified", "filename": name}
        append(unit, document_id, binding, "evidence", str(uuid4()), command.command_key, hashed, result)
        return result


def protocol_source(store, protocol_id, actor_id):
    with work(store, actor_id) as unit:
        protocol = unit.store.get_handover_protocol(protocol_id)
        unit.store.get_contract(protocol.contract_id)
        return {"protocol": protocol.model_dump(mode="json"), "revision": digest(protocol.model_dump(mode="json"))}


def upload_evidence(store, protocol_id, command, content, filename, actor_id):
    name = archive.filename(filename)
    info = formats.inspect_file(content, name)
    if command.expected_sha256 != digest(content):
        archive.fail("Die Nachweisdatei wurde seit der Auswahl geändert.")
    if command.purpose == "original_photo" and info["format"] != "image":
        archive.fail("Ein Originalfoto benötigt eine Bilddatei.", 422)
    if command.purpose == "signed_return" and info["format"] not in {"pdf", "image"}:
        archive.fail("Eine Rückfassung benötigt ein PDF oder einen Bildscan.", 422)
    hashed = digest({"protocol": protocol_id, "request": command.model_dump(mode="json"), "filename": name})
    with work(store, actor_id, (*AREA, "/handover-protocols")) as unit:
        protocol = unit.store.get_handover_protocol(protocol_id)
        # Take parent locks in the same order as existing handover finalization.
        from .handover_protocol import _parents
        contract, prop, location, _, _ = _parents(unit, protocol.contract_id, lock=True, protocol_id=protocol.id)
        protocol = unit.store.get_handover_protocol(protocol_id)
        repeated = events(unit, actor_id=actor_id, command_key=command.command_key)
        if repeated:
            if repeated[0].fingerprint != hashed or repeated[0].protocol_id != protocol_id:
                archive.fail("Dieser Wiederholungsschlüssel gehört zu einem anderen Nachweis.")
            return repeated[0].payload
        if digest(protocol.model_dump(mode="json")) != command.expected_protocol_revision:
            archive.fail("Das Protokoll wurde geändert. Bitte neu prüfen; die ausgewählte Datei bleibt erhalten.")
        identifier = str(uuid4())
        document = Document(id=identifier, title=("Originalfoto" if command.purpose == "original_photo" else "Unterschriebene Rückfassung")
            + " – " + protocol.protocol_date.isoformat(), property_id=prop.id, unit_id=location.id,
            contract_id=contract.id, tenant_id=contract.tenant_id, document_type="Übergabenachweis",
            file_url=f"/uploads/document-evidence/{identifier}/{name}")
        Rows.of(unit).add("documents", document)
        _, binding = archive.bind_document(unit, identifier)
        row = publish(unit, document, binding, content, name, info["media_type"], command.command_key, hashed,
            extra={"protocol_id": protocol_id, "protocol_revision": command.expected_protocol_revision,
                   "purpose": command.purpose, "signature_validity": "not_verified"})
        result = {"protocol_id": protocol_id, "protocol_revision": command.expected_protocol_revision,
            "document_id": identifier, "version_id": row.id, "sha256": row.sha256, "filename": name,
            "purpose": command.purpose, "signature_validity": "not_verified"}
        append(unit, identifier, binding, "evidence", str(uuid4()), command.command_key, hashed, result)
        return result


def ensure_protocol_evidence_kept(store, protocol_id, changes=None, *, deleting=False):
    """Guard legacy mutation paths as well as the new evidence UI."""
    if hasattr(store, "db"):
        found = store.db.scalar(select(DocumentWorkEventORM.id).where(
            DocumentWorkEventORM.protocol_id == protocol_id).limit(1)) is not None
    else:
        found = any(row.protocol_id == protocol_id for row in store.document_work_events.values())
    if found:
        old = store.get_handover_protocol(protocol_id)
        changes = changes or {}
        if deleting or any(field in changes and changes[field] != getattr(old, field) for field in ("contract_id", "unit_id")):
            archive.fail("Das Protokoll besitzt unveränderliche Originalnachweise. Zuordnung und Nachweise bleiben erhalten.")


def protocol_evidence(store, protocol_id, actor_id, *, after=None, limit=25):
    with work(store, actor_id) as unit:
        protocol = unit.store.get_handover_protocol(protocol_id)
        if unit.db is not None:
            query = select(DocumentWorkEventORM).where(DocumentWorkEventORM.protocol_id == protocol_id)
            if after:
                query = query.where(DocumentWorkEventORM.id > after)
            found = list(unit.db.scalars(query.order_by(DocumentWorkEventORM.id).limit(limit + 1)))
        else:
            found = sorted((row for row in events(unit, protocol_id=protocol_id)
                            if after is None or row.id > after), key=lambda row: row.id)[:limit + 1]
        items = []
        for event in found[:limit]:
            document, binding = archive.bind_document(unit, event.document_id)
            if document.contract_id != protocol.contract_id or binding["unit_id"] != protocol.unit_id:
                archive.fail("Der Nachweis stimmt nicht mehr mit der Protokollzuordnung überein.")
            version = archive.authorized_version(unit, document.id, event.payload["version_id"], binding)
            for _ in archive.verified_blocks(unit, version):
                pass
            items.append(deepcopy(event.payload))
        return {"items": items, "next_after": found[limit - 1].id if len(found) > limit else None}


def history(store, document_id, actor_id, *, after=None, limit=25):
    """Complete keyset history; private sessions/jobs remain private to their actor."""
    from sqlalchemy import and_, or_
    with work(store, actor_id) as unit:
        archive.bind_document(unit, document_id)
        if unit.db is not None:
            query = select(DocumentWorkEventORM).where(DocumentWorkEventORM.document_id == document_id,
                or_(DocumentWorkEventORM.kind.not_in(("session", "export")), DocumentWorkEventORM.actor_id == actor_id))
            if after:
                anchor = unit.db.get(DocumentWorkEventORM, after)
                if anchor is None or anchor.document_id != document_id or (
                        anchor.kind in {"session", "export"} and anchor.actor_id != actor_id):
                    archive.fail("Ungültige Verlaufsposition.", 422)
                query = query.where(or_(DocumentWorkEventORM.created_at > anchor.created_at,
                    and_(DocumentWorkEventORM.created_at == anchor.created_at, DocumentWorkEventORM.id > anchor.id)))
            found = [DocumentWorkEvent.model_validate({col.name: getattr(row, col.name)
                for col in DocumentWorkEventORM.__table__.columns}) for row in unit.db.scalars(
                    query.order_by(DocumentWorkEventORM.created_at, DocumentWorkEventORM.id).limit(limit + 1))]
        else:
            found = sorted((row for row in events(unit, document_id=document_id)
                if row.kind not in {"session", "export"} or row.actor_id == actor_id),
                key=lambda row: (row.created_at, row.id))
            if after:
                anchors = [row for row in found if row.id == after]
                if not anchors:
                    archive.fail("Ungültige Verlaufsposition.", 422)
                anchor = anchors[0]
                found = [row for row in found if (row.created_at, row.id) > (anchor.created_at, anchor.id)]
            found = found[:limit + 1]
        # Recovery bytes are returned only through the own-session endpoint.
        items = [row.model_dump(mode="json") for row in found[:limit]]
        for item in items:
            item["payload"].pop("draft_base64", None)
        return {"items": items, "next_after": found[limit - 1].id if len(found) > limit else None}


def archived_upload(store, key, actor_id):
    """Resolve ordinary archived upload URLs to FIRST original bytes, never disk.

    The viewer remains an original viewer. New versions have explicit downloads.
    """
    from ..db.orm_models import DocumentORM
    with work(store, actor_id) as unit:
        url = "/uploads/" + key
        if unit.db is not None:
            ids = list(unit.db.scalars(select(DocumentORM.id).where(DocumentORM.file_url == url)))
        else:
            ids = [doc.id for doc in unit.store.documents.values() if doc.file_url == url]
        selected = None
        for identifier in ids:
            if unit.db is not None:
                row = unit.db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.document_id == identifier,
                                                                      DocumentVersionORM.number == 1))
            else:
                row = next((row for row in unit.archive.versions.values()
                            if row.document_id == identifier and row.number == 1), None)
            if row is not None:
                _, binding = archive.bind_document(unit, identifier)
                archive.authorized_version(unit, identifier, row.id, binding)
                content = archive.original_bytes(unit, row)
                if selected is not None and selected[0] != content:
                    archive.fail("Mehrere Originale besitzen dieselbe Dateiadresse. Bitte die Fassung direkt öffnen.")
                selected = content, row.media_type
        return selected
