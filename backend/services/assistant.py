"""Private assistant domain. Providers never receive a store or a live file path."""
import base64
import hashlib
import io
from pathlib import PurePath
from uuid import uuid4

from fastapi import HTTPException

from ..assistant_models import ConversationCreate, ConversationEdit, RunCreate
from ..config import settings
from ..db.assistant_models import AssistantAttachmentORM as Attachment
from ..db.assistant_models import AssistantConversationORM as Conversation
from ..db.assistant_models import AssistantMessageORM as Message
from ..db.assistant_models import AssistantProposalORM as Proposal
from ..db.assistant_models import AssistantRunORM as Run
from . import assistant_storage as db
from .file_storage import get_file_storage
from .integrations import connection_storage as dbs

MAX_TEXT = 64000
ACTIVE = ("queued", "running")
MIME = {"txt": "text/plain", "csv": "text/csv", "pdf": "application/pdf", "png": "image/png",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def attachment_limit():
    return settings.assistant_max_attachment_bytes or settings.max_upload_size_bytes


def capabilities(actor_id):
    from .assistant_providers import capabilities as provider_capabilities
    return {**provider_capabilities(actor_id), "attachment_max_bytes": attachment_limit(),
            "request_attachment_max_bytes": settings.assistant_request_attachment_bytes,
            "allowed_mime_types": sorted(set(MIME.values())), "allowed_extensions": sorted(MIME),
            "max_attachments": 12, "max_message_length": 32000}


def create_conversation(store, actor_id: str, command: ConversationCreate):
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        prior = db.replay(unit, "conversation.create", command)
        if prior:
            return db.public(db.conversation(unit, prior))
        row = db.put(unit, Conversation, dict(title=command.title.strip(), provider=command.provider,
            model=command.model, effort=command.effort, data_scope=command.data_scope,
            attachment_ids=[], context={}, context_sources=[], archived=False, active_run_id=None, _contexts=[]))
        db.receipt(unit, "conversation.create", command, row)
        return db.public(row)


def get_conversation(store, actor_id, identifier):
    with db.work(store, actor_id) as unit:
        return db.conversation_public(unit, db.conversation(unit, identifier))


def edit_conversation(store, actor_id, identifier, command: ConversationEdit):
    operation = "conversation.edit:" + identifier
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = db.conversation(unit, identifier, lock=True)
        if db.replay(unit, operation, command):
            return db.public(row)
        db.revision(row, command.expected_revision)
        data = db.payload(row)
        transport_fields = {"provider", "model", "effort", "data_scope"}.intersection(command.model_fields_set)
        if transport_fields and data.get("active_run_id") and db.get(unit, Run, data["active_run_id"]).state in ACTIVE:
            raise HTTPException(409, "Bitte den laufenden Auftrag vor dem Konto- oder Modellwechsel beenden.")
        for field in transport_fields:
            value = getattr(command, field)
            if value is not None or field == "model":
                data[field] = value
        if command.archived and data.get("active_run_id"):
            raise HTTPException(409, "Bitte den laufenden Auftrag zuerst beenden.")
        if command.title is not None:
            if not command.title.strip():
                raise HTTPException(422, "Gesprächstitel fehlt.")
            data["title"] = command.title.strip()
        if command.archived is not None:
            data["archived"] = command.archived
        row = db.put(unit, Conversation, data, row=row)
        db.receipt(unit, operation, command, row)
        return db.public(row)


def list_records(store, actor_id, model=Conversation, *, conversation_id=None, cursor=None, limit=50):
    with db.work(store, actor_id) as unit:
        conversation = db.conversation(unit, conversation_id) if conversation_id else None
        result = db.page(unit, model, conversation_id=conversation_id, cursor=cursor, limit=limit)
        if model is Message:
            result["items"].reverse()
            result["conversation"] = db.conversation_public(unit, conversation)
        elif model is Run:
            result["items"] = [run_summary(item) for item in result["items"]]
        return result


def run_summary(data):
    from .assistant_findings import collected
    data["findings"] = collected(data)
    from .assistant_tools import MAX_CALLS
    used = min(len(data.get("tool_calls", [])), MAX_CALLS)
    data["tool_budget"] = {"used": used, "limit": MAX_CALLS, "exhausted": used >= MAX_CALLS,
                           "continuation": "followup" if used >= MAX_CALLS else None}
    return data


def run_public(unit, row):
    data = run_summary(db.public(row))
    data["sources"] = source_cards(db.payload(row)["_bundle"])
    if row.state in ("blocked", "unknown") and not data.get("error"):
        data["error"] = {"code": row.state, "message": "Quellen oder Berechtigungen wurden geändert." if row.state == "blocked"
                         else "Ausgang nach Verbindungsabbruch unklar. Ein erneuter Versuch startet einen neuen Auftrag."}
    proposal_ids = db.payload(row).get("_proposal_ids", [])
    data["proposals"] = [db.public(db.owned_child(unit, Proposal, identifier)) for identifier in proposal_ids]
    return data


def source_cards(bundle):
    allowed = ("kind", "id", "title", "revision", "sha256", "href", "file_sha256")
    return [{key: source[key] for key in allowed if key in source} for source in bundle.get("sources", [])]


def get_run(store, actor_id, identifier):
    with db.work(store, actor_id) as unit:
        return run_public(unit, db.owned_child(unit, Run, identifier))


def submit(store, actor_id, identifier, command: RunCreate, *, retry_of=None):
    from .assistant_context import ContextSelection, build_context
    operation = "run.create:" + identifier
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        conversation = db.conversation(unit, identifier, lock=True)
        prior = db.replay(unit, operation, command)
        if prior:
            return run_public(unit, db.owned_child(unit, Run, prior))
        db.revision(conversation, command.expected_revision)
        data = db.payload(conversation)
        if data["archived"]:
            raise HTTPException(409, "Archivierte Gespräche können keine neuen Aufträge erhalten.")
        if data.get("active_run_id"):
            active = db.get(unit, Run, data["active_run_id"])
            if active.state in ACTIVE:
                raise HTTPException(409, "In diesem Gespräch läuft bereits ein Auftrag.")
            data["active_run_id"] = None
        if command.web_research and data["provider"] == "local":
            raise HTTPException(422, "Webrecherche benötigt einen ausdrücklich ausgewählten Cloudanbieter.")
        if len(set(command.attachment_ids)) != len(command.attachment_ids):
            raise HTTPException(422, "Ein Anhang wurde mehrfach ausgewählt.")
        if set(command.attachment_ids).intersection(command.excluded_attachment_ids):
            raise HTTPException(422, "Eine Datei kann nicht gleichzeitig ausgewählt und ausgeschlossen sein.")
        attachment_ids = sorted((set(data.get("attachment_ids", [])) | set(command.attachment_ids))
                                - set(command.excluded_attachment_ids))
        for excluded_id in set(command.excluded_attachment_ids):
            excluded = db.owned_child(unit, Attachment, excluded_id)
            if excluded.conversation_id != identifier:
                raise HTTPException(404, "Anhang gehört nicht zu diesem Gespräch.")
        if len(attachment_ids) > 12:
            raise HTTPException(413, "Mehr als 12 Arbeitsdateien. Bitte bisherige Dateien ausdrücklich abwählen.")
        attachment_bytes = 0
        for attachment_id in attachment_ids:
            attachment = db.owned_child(unit, Attachment, attachment_id)
            if attachment.conversation_id != identifier:
                raise HTTPException(404, "Anhang gehört nicht zu diesem Gespräch.")
            verified_attachment(attachment)
            attachment_bytes += db.payload(attachment)["byte_length"]
        if attachment_bytes > settings.assistant_request_attachment_bytes:
            raise HTTPException(413, f"Die ausgewählten Anhänge überschreiten zusammen {settings.assistant_request_attachment_bytes} Byte.")
        selected_context = command.context if "context" in command.model_fields_set else data.get("context", {})
        if command.data_scope == "none" and "context" not in command.model_fields_set:
            selected_context = {}
        selection = ContextSelection.model_validate(selected_context)
        if command.data_scope == "none" and (any(getattr(selection, key) for key in ContextSelection.model_fields) or command.report is not None):
            raise HTTPException(422, "Ohne Fachaktenzugriff bitte Aktenauswahl und Finanzbericht entfernen.")
        if command.report is not None:
            report = command.report
            if (report.unit_id and report.unit_id not in selection.unit_ids) or (
                    not report.unit_id and (not report.property_id or report.property_id not in selection.property_ids)):
                raise HTTPException(422, "Der Bericht muss ausdrücklich auf eine ausgewählte Immobilie oder Einheit begrenzt sein.")
        bundle = build_context(unit.store, selection, actor_id)
        run = db.put(unit, Run, dict(content=command.content, attachment_ids=attachment_ids,
            effective_attachment_ids=attachment_ids, data_scope=command.data_scope, _grant_selection=selection.model_dump(mode="json"),
            provider=data["provider"], model=data["model"], effort=data["effort"], activity=[], tool_calls=[],
            context=selection.model_dump(mode="json"), web_research=command.web_research,
            report=command.report.model_dump(mode="json") if command.report is not None else None,
            verification_status="pending",
            response="", events=[], error=None, retry_of=retry_of,
            _bundle=bundle, _proposal_ids=[]), conversation_id=identifier, state="queued")
        db.put(unit, Message, {"role": "user", "content": command.content, "run_id": run.id,
            "attachment_ids": attachment_ids}, conversation_id=identifier)
        # Keep source guards for every historical answer, including provider session context.
        if bundle.get("sources"):
            # Historical guards need identities, not repeated copies of source text.
            sources = {(source["kind"], source["id"]) for guard in data["_contexts"] for source in guard["sources"]}
            sources.update((source["kind"], source["id"]) for source in bundle["sources"])
            from .assistant_context import SELECTIONS
            data["_contexts"] = [{"format": bundle["format"],
                "selection": {field: sorted(identifier for kind, identifier in sources if kind == target)
                              for field, target in SELECTIONS.items()},
                "sources": [{"kind": kind, "id": source_id} for kind, source_id in sorted(sources)]}]
        data["active_run_id"] = run.id
        data["attachment_ids"] = attachment_ids
        data["context"] = selection.model_dump(mode="json")
        data["context_sources"] = source_cards(bundle)
        db.put(unit, Conversation, data, row=conversation)
        db.receipt(unit, operation, command, run)
        result = run_public(unit, run)
    wake(run.id, actor_id)
    return result


def wake(identifier, actor_id):
    # The authoritative queued row survives a failed wakeup. Recovery will enqueue it again.
    from .jobs.scheduler import get_job_store, request_wakeup
    try:
        jobs = get_job_store()
        jobs.enqueue("assistant.run", "assistant:" + identifier, {"run_id": identifier, "actor_id": actor_id}, max_attempts=1)
        request_wakeup()
    except Exception:
        pass


def cancel(store, actor_id, identifier, command):
    operation = "run.cancel:" + identifier
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = db.owned_child(unit, Run, identifier, lock=True)
        if db.replay(unit, operation, command):
            return run_public(unit, row)
        # Cancel targets this immutable run ID. Streaming may have advanced its
        # revision since the last poll; only an impossible future stand conflicts.
        # owned_child(lock=True) holds both the run and conversation locks.
        if command.expected_revision > row.revision:
            db.revision(row, command.expected_revision)
        if row.state not in ACTIVE:
            raise HTTPException(409, "Dieser Auftrag ist bereits beendet.")
        data = db.payload(row)
        data["error"] = {"code": "cancelled", "message": "Auftrag ausdrücklich abgebrochen."}
        row = db.put(unit, Run, data, row=row, state="cancelled")
        release_conversation(unit, row)
        db.receipt(unit, operation, command, row)
        return run_public(unit, row)


def retry(store, actor_id, identifier, command):
    operation = "run.retry:" + identifier
    # Serialize the old run and new submission inside one transaction.
    from .assistant_context import revalidate_context
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        old = db.owned_child(unit, Run, identifier, lock=True)
        prior = db.replay(unit, operation, command)
        if prior:
            return run_public(unit, db.owned_child(unit, Run, prior))
        db.revision(old, command.expected_revision)
        if old.state not in ("failed", "cancelled", "unknown", "blocked"):
            raise HTTPException(409, "Nur beendete fehlgeschlagene oder abgebrochene Aufträge können neu gestartet werden.")
        old_data = db.payload(old)
        revalidate_context(unit.store, old_data["_bundle"], actor_id)
        conversation = db.conversation(unit, old.conversation_id, lock=True)
        conversation_data = db.payload(conversation)
        if conversation_data.get("active_run_id") and db.get(unit, Run, conversation_data["active_run_id"]).state not in ACTIVE:
            conversation_data["active_run_id"] = None
        if conversation_data.get("active_run_id") or conversation_data["archived"]:
            raise HTTPException(409, "Gespräch ist archiviert oder enthält einen laufenden Auftrag.")
        for attachment_id in old_data["attachment_ids"]:
            verified_attachment(db.owned_child(unit, Attachment, attachment_id))
        data = {**old_data, "response": "", "events": [], "error": None, "retry_of": old.id, "_proposal_ids": []}
        data.update(provider=conversation_data["provider"], model=conversation_data["model"], effort=conversation_data["effort"], activity=[], tool_calls=[])
        for key in ("_tool_reports", "_tool_results", "_tool_timelines", "_tool_investigations", "_tool_actor",
                    "local_findings", "local_checks", "finding_proposals"):
            data.pop(key, None)
        data["verification_status"] = "pending"
        for key in ("usage", "provider_session_id", "provider_turn_id", "_lease", "_submitted", "financial_summary", "_report_hash"):
            data.pop(key, None)
        row = db.put(unit, Run, data, conversation_id=old.conversation_id, state="queued")
        latest = db.page(unit, Message, conversation_id=old.conversation_id, limit=1)["items"]
        if (not latest or latest[0].get("role") != "user" or latest[0].get("content") != data["content"]
                or latest[0].get("attachment_ids", []) != data["attachment_ids"]):
            # A retry after later turns must restore its own question as the
            # final prompt. Immediate retries reuse the existing user bubble.
            db.put(unit, Message, {"role": "user", "content": data["content"], "run_id": row.id,
                "attachment_ids": data["attachment_ids"]}, conversation_id=old.conversation_id)
        conversation_data["active_run_id"] = row.id
        db.put(unit, Conversation, conversation_data, row=conversation)
        db.receipt(unit, operation, command, row)
        result = run_public(unit, row)
    wake(row.id, actor_id)
    return result


def release_conversation(unit, run):
    conversation = db.get(unit, Conversation, run.conversation_id, lock=True)
    data = db.payload(conversation)
    if data.get("active_run_id") == run.id:
        data["active_run_id"] = None
        db.put(unit, Conversation, data, row=conversation)


def inspect_attachment(raw, name):
    name = PurePath(name.replace("\\", "/")).name[:200]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in MIME:
        raise HTTPException(415, "Erlaubt sind PDF, DOCX, UTF-8-Text/CSV und PNG/JPEG/WebP.")
    if not raw or len(raw) > attachment_limit():
        raise HTTPException(413, f"Anhang ist leer oder größer als {attachment_limit()} Byte.")
    mime, text, omissions = MIME[ext], "", []
    if ext in ("txt", "csv"):
        try:
            text = raw.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError
        except (UnicodeError, ValueError):
            raise HTTPException(415, "Textanhänge benötigen gültiges UTF-8 ohne Binärdaten.") from None
    elif ext == "docx":
        import zipfile
        from xml.etree import ElementTree as ET

        from .document_formats import validate_docx
        validate_docx(raw)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        parts, length = [], 0
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            selected = ["word/document.xml"] + sorted(name for name in package.namelist()
                if name.startswith(("word/header", "word/footer")) and name.endswith(".xml"))
            for part in selected:
                root = ET.fromstring(package.read(part))
                for paragraph in root.iter(namespace + "p"):
                    chunk = "".join(node.text or "" if node.tag == namespace + "t" else
                                    "\t" if node.tag == namespace + "tab" else "\n"
                                    for node in paragraph.iter() if node.tag in (
                                        namespace + "t", namespace + "tab", namespace + "br")) + "\n"
                    remaining = MAX_TEXT + 1 - length
                    parts.append(chunk[:remaining])
                    length += len(chunk)
                    if length > MAX_TEXT:
                        break
                if length > MAX_TEXT:
                    break
        text = "".join(parts)
        if not text.strip():
            omissions.append("DOCX enthält keinen extrahierbaren Text.")
    elif ext == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise HTTPException(415, "Datei enthält kein gültiges PDF.")
        try:
            import fitz
            with fitz.open(stream=raw, filetype="pdf") as document:
                if document.needs_pass:
                    raise HTTPException(422, "Passwortgeschützte PDFs können nicht analysiert werden.")
                parts, length = [], 0
                for index, page in enumerate(document):
                    if index >= 100 or length >= MAX_TEXT:
                        omissions.append("PDF-Auszug auf 100 Seiten / 64.000 Zeichen begrenzt.")
                        break
                    chunk = page.get_text()
                    parts.append(chunk)
                    length += len(chunk)
                text = "\n".join(parts)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "PDF konnte nicht gelesen werden.") from None
        if not text.strip():
            omissions.append("PDF enthält keinen extrahierbaren Text; keine automatische OCR durchgeführt.")
    else:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                expected = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}[ext]
                if image.format != expected or image.width * image.height > 25_000_000:
                    raise ValueError
                image.verify()
        except Exception:
            raise HTTPException(415, "Bildformat ist ungültig oder das Bild ist zu groß.") from None
        omissions.append("Bild wird nur an bildfähige Modelle übergeben; lokal keine automatische OCR.")
    if len(text) > MAX_TEXT:
        omissions.append("Textauszug auf 64.000 Zeichen begrenzt.")
    return dict(name=name, mime=mime, byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                text=text[:MAX_TEXT], text_truncated=len(text) > MAX_TEXT, omissions=omissions, status="ready")


def add_attachment(store, actor_id, identifier, raw, name):
    data = inspect_attachment(raw, name)
    storage = get_file_storage()
    # Nonpublic owner-specific keys, covered by the existing uploads/full-backup layout.
    key = "assistant-private/files/" + hashlib.sha256(actor_id.encode()).hexdigest() + "/" + uuid4().hex
    with db.work(store, actor_id, write=True) as unit:
        conversation = db.conversation(unit, identifier, lock=True)
        if db.payload(conversation)["archived"]:
            raise HTTPException(409, "Gespräch ist archiviert.")
        storage.save(key, io.BytesIO(raw), content_type=data["mime"])
        try:
            row = db.put(unit, Attachment, {**data, "_storage_key": key}, conversation_id=identifier)
            result = db.public(row)
            result.pop("text", None)
            return result
        except BaseException:
            storage.delete(key)
            raise


def verified_attachment(row):
    data = db.payload(row)
    raw = get_file_storage().get(data["_storage_key"])
    if raw is None or len(raw) != data["byte_length"] or hashlib.sha256(raw).hexdigest() != data["sha256"]:
        raise HTTPException(409, "Anhang fehlt oder wurde verändert. Bitte erneut hochladen.")
    return raw, data


def download(store, actor_id, identifier):
    with db.work(store, actor_id) as unit:
        row = db.owned_child(unit, Attachment, identifier)
        return verified_attachment(row)


def attachment_request(row):
    raw, data = verified_attachment(row)
    result = {key: data[key] for key in ("name", "mime", "sha256", "text", "text_truncated", "omissions")}
    if data["mime"].startswith("image/"):
        result["data_base64"] = base64.b64encode(raw).decode("ascii")
    return {"id": row.id, "revision": str(row.revision), **result}


def proposal_preview(store, actor_id, identifier, command):
    from .assistant_proposals import validate_proposal
    with db.work(store, actor_id) as unit:
        row = db.owned_child(unit, Proposal, identifier)
        db.revision(row, command.expected_revision)
        if row.state != "proposed":
            raise HTTPException(409, "Dieser Vorschlag wurde bereits entschieden.")
        data = db.payload(row)
        proposal = {**data["payload"], **({"values": command.values} if command.values is not None else {})}
        run = db.get(unit, Run, data["run_id"])
        require_current_analysis(unit, run)
        review = validate_proposal(unit.store, proposal, actor_id, context_bundle=db.payload(run)["_bundle"],
                                   allowed_attachment_ids=db.payload(run).get("attachment_ids", []))
        return {"proposal": db.public(row), "review": review}


def decide_proposal(store, actor_id, identifier, command, *, reject=False):
    from .assistant_proposals import handoff_proposal, validate_proposal
    operation = ("proposal.reject:" if reject else "proposal.apply:") + identifier
    with db.work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = db.owned_child(unit, Proposal, identifier, lock=True)
        if db.replay(unit, operation, command):
            data = db.public(row)
            return {"proposal": data, "handoff": data.get("handoff")}
        db.revision(row, command.expected_revision)
        if row.state != "proposed":
            raise HTTPException(409, "Dieser Vorschlag wurde bereits entschieden.")
        data = db.payload(row)
        if reject:
            if not command.reason.strip():
                raise HTTPException(422, "Bitte einen Entscheidungsgrund angeben.")
            data["decision"] = dict(actor_id=actor_id, at=dbs.stamp(dbs.now()), reason=command.reason.strip())
            row = db.put(unit, Proposal, data, row=row, state="rejected")
        else:
            proposed = {**data["payload"], **({"values": command.values} if command.values is not None else {})}
            run = db.get(unit, Run, data["run_id"])
            require_current_analysis(unit, run)
            review = validate_proposal(unit.store, proposed, actor_id, context_bundle=db.payload(run)["_bundle"],
                                       allowed_attachment_ids=db.payload(run).get("attachment_ids", []))
            if review["review_hash"] != command.review_hash or not review["allowed"]:
                raise HTTPException(409, "Vorschlagsprüfung hat sich geändert. Bitte erneut prüfen.")
            # The context agent uses the supplied unit for atomic draft+decision+receipt.
            handoff = handoff_proposal(unit.store, proposed, actor_id, draft_id=row.id,
                                      base_revision=0, idempotency_key=command.idempotency_key, unit=unit,
                                      review_hash=command.review_hash, context_bundle=db.payload(run)["_bundle"],
                                      allowed_attachment_ids=db.payload(run).get("attachment_ids", []))
            data.update(payload=proposed, handoff=handoff,
                        decision=dict(actor_id=actor_id, at=dbs.stamp(dbs.now()), reason="Geprüften Entwurf übernommen"))
            row = db.put(unit, Proposal, data, row=row, state="applied")
        db.receipt(unit, operation, command, row)
        return {"proposal": db.public(row), "handoff": data.get("handoff")}


def require_current_analysis(unit, run):
    data = db.payload(run)
    from .assistant_tools import validate_reports
    validate_reports(unit.store, data)
    if data.get("verification_status") == "stale":
        raise HTTPException(409, "Die Auswertungszahlen dieses Vorschlags sind veraltet. Bitte mit aktuellem Stand erneut prüfen.")
    if data.get("report") and data.get("_report_hash"):
        from ..finance_models import ReportDefinition
        from .finance_reports import compute
        current = compute(unit.store, ReportDefinition.model_validate(data["report"]))
        if current["result_hash"] != data["_report_hash"]:
            raise HTTPException(409, "Auswertungszahlen wurden geändert. Bitte mit aktuellem Stand erneut prüfen.")
