"""Reading a document into a form ("Lesevorgang"): local rules or the AI of the person's own account,
then a conversation about it.

A reading starts at a surface (`ai_surfaces`): the document goes to the reader with the task of that
surface, the house rules of the office and what is known about the property. The answer becomes
checked values with their evidence; records that probably stem from the same document are listed so
the person can decide. In the conversation the person says what should happen with the document; the
AI answers and changes values. Nothing is written to the business data: the person checks the values
in the form and saves it there. Readings are the person's own records, kept encrypted with the
assistant's conversations (state "reading") and deleted after the days set in the settings.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..db.assistant_models import AssistantConversationORM as Conversation
from ..db.assistant_models import AssistantMessageORM as Message
from ..domain.clock import local_today
from ..permissions import may_write
from ..storage import NotFoundError
from . import ai_surfaces as surfaces
from . import assistant_storage as db
from .assistant_provider_protocol import ProviderError

STATE = "reading"
READERS = {"local": "Lokale Regeln", "claude": "Claude", "codex": "ChatGPT"}
MAX_TEXT = 120_000
MAX_TURNS = 30
MAX_MESSAGE = 4000
BLOCK = re.compile(r"```(?:immomanager-reading|immomanager-meter-extract|json)\s*\n(.*?)\n```", re.DOTALL)
CONFIRM_MODES = ("confirm", "mark")

# AI calls per person: a reading or a chat message each. Generous for real work, a stop for loops and scripts.
_calls: dict[str, list[float]] = {}
_calls_lock = threading.Lock()
CALLS_PER_WINDOW, WINDOW_SECONDS = 40, 600


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: Optional[str] = Field(default=None, max_length=120)
    unit_id: Optional[str] = Field(default=None, max_length=120)
    contract_id: Optional[str] = Field(default=None, max_length=120)
    tenant_id: Optional[str] = Field(default=None, max_length=120)
    billing_period_id: Optional[str] = Field(default=None, max_length=120)


class StartCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: str = Field(min_length=1, max_length=40)
    document_id: Optional[str] = Field(default=None, max_length=120)
    file_url: Optional[str] = Field(default=None, max_length=1000)
    params: Params = Field(default_factory=Params)
    reader: Literal["auto", "local", "claude", "codex"] = "auto"
    model: Optional[str] = Field(default=None, max_length=80)
    instruction: Optional[str] = Field(default=None, max_length=MAX_MESSAGE)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_MESSAGE)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["use_existing", "update_existing", "create_new", "cancel"]
    record_kind: Optional[str] = Field(default=None, max_length=40)
    record_id: Optional[str] = Field(default=None, max_length=120)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class FinishCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["taken_over", "cancelled"]
    record_kind: Optional[str] = Field(default=None, max_length=40)
    record_id: Optional[str] = Field(default=None, max_length=120)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


# ─── Settings, readers, permissions ─────────────────────────────────────────

def settings(store: Any, actor_id: str) -> dict:
    from .settings_catalogue import effective_values
    return {key: value for key, value in effective_values(store, actor_id).items() if key.startswith("ai_")}


def readers(actor_id: str) -> list[dict]:
    """The local rules always; Claude or ChatGPT once connected in the assistant."""
    from . import assistant_providers
    found = [{"id": "local", "label": READERS["local"], "available": True, "ai": False}]
    for provider in ("claude", "codex"):
        try:
            status = assistant_providers.connection_status(actor_id, provider)
            connected = bool(status.get("connected")) and status.get("client_available", True) is not False
        except Exception:                    # an unreadable account vault means "not connected", never a failed page
            connected = False
        found.append({"id": provider, "label": READERS[provider], "available": connected, "ai": True})
    return found


def _surface(surface_id: str) -> surfaces.Surface:
    found = surfaces.SURFACES.get(surface_id)
    if found is None:
        raise HTTPException(404, "Diese Einlesestelle gibt es nicht.")
    return found


def _ai_allowed(surface: surfaces.Surface, values: dict) -> Optional[str]:
    """Why the AI may not read here, or None."""
    if not values.get("ai_reading_enabled", True):
        return "Die KI-Auswertung von Dokumenten ist in den Einstellungen ausgeschaltet (Einstellungen → KI-Verarbeitung)."
    if not values.get(f"ai_surface_{surface.id}", True):
        return f"Die KI-Auswertung ist für „{surface.label}“ in den Einstellungen ausgeschaltet."
    return None


def _check_role(actor: Any, surface: surfaces.Surface) -> None:
    if not may_write(actor.role, surface.area):
        raise HTTPException(403, f"„{surface.label}“ einlesen darf, wer die Werte dort auch speichern darf.")


def _choose_reader(requested: str, surface: surfaces.Surface, values: dict, available: list[dict]) -> str:
    ready = [reader["id"] for reader in available if reader["available"] and reader["ai"]]
    if requested == "auto":
        preferred = values.get("ai_default_reader", "auto")
        if preferred in ("claude", "codex") and preferred in ready:
            requested = preferred
        elif preferred == "local" and not surface.needs_ai:
            requested = "local"
        else:
            requested = ready[0] if ready and _ai_allowed(surface, values) is None else "local"
    if requested == "local":
        if surface.needs_ai:
            raise HTTPException(422, f"„{surface.label}“ braucht die KI (Claude oder ChatGPT): dafür gibt es keine lokalen Regeln. "
                                     "Bitte im Bereich Assistent ein Konto verbinden.")
        return "local"
    reason = _ai_allowed(surface, values)
    if reason:
        raise HTTPException(409, reason)
    if requested not in ready:
        raise HTTPException(409, f"{READERS[requested]} ist nicht verbunden. Im Bereich Assistent verbinden oder die lokalen Regeln wählen.")
    return requested


def _count_call(actor_id: str) -> None:
    import time
    now = time.monotonic()
    with _calls_lock:
        recent = [moment for moment in _calls.get(actor_id, []) if now - moment < WINDOW_SECONDS]
        if len(recent) >= CALLS_PER_WINDOW:
            _calls[actor_id] = recent
            raise HTTPException(429, "Zu viele KI-Anfragen in kurzer Zeit. Bitte in einigen Minuten erneut versuchen.")
        recent.append(now)
        _calls[actor_id] = recent
        if len(_calls) > 5000:
            for key in [key for key, moments in _calls.items() if not moments or now - moments[-1] >= WINDOW_SECONDS]:
                _calls.pop(key, None)


# ─── The document ────────────────────────────────────────────────────────────

@dataclass
class Source:
    content: bytes
    filename: str
    media_type: str
    sha256: str
    text: str
    text_source: str
    document: Any = None
    file_url: Optional[str] = None
    source_ref: Optional[str] = None


def _source(store: Any, command: StartCommand) -> Source:
    from . import document_share, document_text
    from .privacy.storage import ensure_available, ensure_file_available, ensure_restore_reviewed
    ensure_restore_reviewed(store)
    if bool(command.document_id) == bool(command.file_url):
        raise HTTPException(422, "Bitte genau ein Dokument oder eine hochgeladene Datei angeben.")
    document = None
    reference = None
    if command.document_id:
        ensure_available(store, "document", command.document_id)
        try:
            document = store.get_document(command.document_id)
        except NotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        file = document_share.current_file(store, document)
        content, filename, media_type = file.content, file.filename, file.media_type
        reference = file.source_ref
    else:
        from ..routers.files import _file_url_to_key
        from .business_documents import _file
        key = _file_url_to_key(command.file_url or "")
        if not key:
            raise HTTPException(422, "Ungültige Datei-URL.")
        ensure_file_available(store, command.file_url)
        content = _file(command.file_url or "")
        filename = document_share.shown_name(key.rsplit("/", 1)[-1])
        media_type = mimetypes.guess_type(filename)[0] or ("application/pdf" if content.startswith(b"%PDF-") else "application/octet-stream")
        reference = "file:" + (command.file_url or "")
    text, text_source = document_text.extract(content, filename)
    return Source(content, filename, media_type, hashlib.sha256(content).hexdigest(), text or "", text_source,
                  document, command.file_url, reference)


def _version(source):
    return source.source_ref.partition(":")[2] if source.source_ref and source.source_ref.startswith("version:") else None


def _citations(found, source, reader):
    from .source_citations import annotate_values
    # An AI can cite only the excerpt actually sent. Local rules use their full
    # extracted input. Image-only observations are visibly unverified text quotes.
    text = source.text if reader == "local" else source.text[:MAX_TEXT]
    return annotate_values(found, text, version_id=_version(source), file_sha256=source.sha256)


def _current_source_proof(unit, data):
    from . import document_share
    document_id = (data.get("document") or {}).get("id")
    if document_id:
        file = document_share.current_file(unit.store, unit.store.get_document(document_id))
        raw, reference = file.content, file.source_ref
    else:
        from .business_documents import _file
        url = (data.get("file") or {}).get("file_url") or ""
        raw, reference = _file(url), "file:" + url
    saved = data.get("file") or {}
    if hashlib.sha256(raw).hexdigest() != saved.get("sha256") or (saved.get("source_ref") and reference != saved["source_ref"]):
        raise HTTPException(409, "Die Quelldatei oder Originalversion wurde seit dem Einlesen geändert. Bitte erneut einlesen.")


def _params(store: Any, surface: surfaces.Surface, params: Params, document: Any) -> dict:
    """The ids the reading was started with, checked against what the person may see, with the property filled in."""
    chosen = {key: value for key, value in params.model_dump().items() if value}
    try:
        if chosen.get("billing_period_id"):
            period = store.get_billing_period(chosen["billing_period_id"])
            if chosen.get("property_id") and chosen["property_id"] != period.property_id:
                raise HTTPException(422, "Die Abrechnungsperiode gehört zu einer anderen Immobilie.")
            chosen["property_id"] = period.property_id
        if chosen.get("unit_id"):
            unit = store.get_unit(chosen["unit_id"])
            chosen.setdefault("property_id", unit.property_id)
        if chosen.get("contract_id"):
            contract = store.get_contract(chosen["contract_id"])
            chosen.setdefault("property_id", contract.property_id)
        if chosen.get("tenant_id"):
            store.get_tenant(chosen["tenant_id"])
        if document is not None and not chosen.get("property_id") and document.property_id:
            chosen["property_id"] = document.property_id
        if chosen.get("property_id"):
            store.get_property(chosen["property_id"])
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if surface.id == "meter_document":
        if document is None:
            raise HTTPException(422, "Ein Dokument des Messdienstes wird zuerst abgelegt und dann gelesen.")
        if not chosen.get("property_id"):
            raise HTTPException(422, "Bitte die Immobilie wählen, zu der das Dokument gehört.")
    if surface.id == "cost_item" and not chosen.get("billing_period_id"):
        raise HTTPException(422, "Eine Kostenposition gehört zu einer Abrechnungsperiode. Bitte die Abrechnung wählen.")
    return chosen


def _images(source: Source, max_pages: int) -> list[dict]:
    """Page images for a scan without text layer (needs PyMuPDF), or the photo itself."""
    if source.media_type in ("image/png", "image/jpeg", "image/webp"):
        return [{"name": source.filename, "mime": source.media_type, "data_base64": base64.b64encode(source.content).decode("ascii")}]
    if source.media_type != "application/pdf":
        return []
    try:
        import fitz  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        return []
    pages = []
    with fitz.open(stream=source.content, filetype="pdf") as pdf:
        for number, page in enumerate(pdf):
            if number >= max_pages:
                break
            pages.append({"name": f"{source.filename} Seite {number + 1}.png", "mime": "image/png",
                          "data_base64": base64.b64encode(page.get_pixmap(dpi=150).tobytes("png")).decode("ascii")})
    return pages


# ─── Asking the reader ───────────────────────────────────────────────────────

def _schema(surface: surfaces.Surface) -> str:
    if surface.rows:
        from .meter_documents_ai import SCHEMA
        return (SCHEMA + "\n\nIm Block steht das Objekt unter dem Schlüssel \"extraction\": "
                '{"extraction": {…}, "questions": [], "notes": []}. Bei Änderungen im Gespräch die vollständige extraction erneut angeben.')
    lines = []
    for field in surface.fields:
        kind = {"date": "JJJJ-MM-TT", "money": "Dezimalzahl mit Punkt", "percent": "Zahl 0–100", "number": "Zahl",
                "long_text": "Text", "text": "Text", "iban": "IBAN", "unit": "Bezeichnung einer bekannten Einheit",
                "tenant": "Name eines bekannten Mieters"}.get(field.kind, "Text")
        if field.kind == "choice":
            kind = "eins von: " + ", ".join(field.choices)
        lines.append(f'- {field.name} ({field.label}): {kind}' + (f" – {field.hint}" if field.hint else ""))
    return ('Block: {"values": {"feld": {"value": …, "evidence": "Zitat", "confidence": "high|medium|low"}}, '
            '"questions": ["Rückfrage"], "notes": ["Hinweis"]}\nFelder:\n' + "\n".join(lines)
            + "\nEinen Wert entfernen: {\"feld\": {\"value\": null}}.")


def _request(surface: surfaces.Surface, source: Source, known: dict, values: dict, *, model: Optional[str],
             conversation: list[dict], current: dict) -> tuple[dict, int]:
    from .meter_documents_ai import TASK
    level = values.get("ai_context", "standard")
    rules = (values.get(f"ai_rules_{surface.id}") or "").strip()
    task = (TASK if surface.rows else surface.instructions) + "\n\n" + _schema(surface)
    messages = [{"role": "user", "content": "task: " + task + (("\n\nhouse_rules:\n" + rules) if rules else "")}]
    messages += conversation
    text = source.text[:MAX_TEXT]
    attachment = {"name": source.filename, "mime": source.media_type, "text": text,
                  "text_truncated": len(source.text) > MAX_TEXT,
                  "version_id": _version(source), "sha256": source.sha256,
                  "omissions": ["Text auf 120.000 Zeichen begrenzt."] if len(source.text) > MAX_TEXT else []}
    images = []
    if values.get("ai_send_images", True) and (len(text.strip()) < 200 or source.media_type.startswith("image/")):
        images = _images(source, int(values.get("ai_max_pages") or 4))
    if not text.strip() and not images:
        raise HTTPException(422, "Aus dieser Datei ließ sich kein Text lesen, und Bilder werden nicht gesendet "
                                 "(Einstellung oder fehlendes PyMuPDF für gescannte PDFs). Bitte eine PDF mit Textebene "
                                 "oder ein Foto (JPG/PNG) verwenden.")
    request = {"_task": "document_reading", "messages": messages,
               "context": {"surface": surface.label, "known": surfaces.for_model(known, level), "current_values": current},
               "attachments": [attachment, *images],
               "application_clock": {"date": local_today().isoformat(), "timezone": "Europe/Berlin"},
               "data_scope": "selected", "web_research": False, "local_analysis": {}, "omissions": [],
               "model": model or None, "effort": None}
    return request, len(images)


def _ask(actor_id: str, reader: str, request: dict) -> tuple[str, Optional[dict]]:
    from . import assistant_providers
    _count_call(actor_id)
    try:
        answer = assistant_providers.execute(actor_id, reader, request, lambda event: None, lambda: False)
    except ProviderError as error:
        raise HTTPException(409 if error.code in ("authentication_required", "client_unavailable") else 502, str(error)) from error
    return split_answer(answer.get("text") or "")


def split_answer(text: str) -> tuple[str, Optional[dict]]:
    """The words to the person and the values block of an answer."""
    found = BLOCK.search(text)
    words = (text[:found.start()] + text[found.end():]).strip() if found else text.strip()
    data = None
    if found:
        try:
            data = json.loads(found.group(1))
        except (ValueError, RecursionError):
            data = None
        if not isinstance(data, dict):
            data = None
    return words[:MAX_MESSAGE], data


def _strings(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (surfaces._text(item, 300) for item in value[:limit]) if text]


def _extraction_dict(extraction: Any) -> dict:
    def plain(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, list):
            return [plain(item) for item in value]
        return value
    return plain(dict(extraction.__dict__))


def _extraction(data: dict) -> Any:
    from .meter_documents import Extraction

    def day(value: Any) -> Optional[date]:
        return date.fromisoformat(value) if isinstance(value, str) and value else None

    def number(value: Any) -> Any:
        return Decimal(value) if isinstance(value, str) else value
    result = Extraction(company=data.get("company"), kind=data.get("kind") or "other", period_start=day(data.get("period_start")),
                        period_end=day(data.get("period_end")), reading_date=day(data.get("reading_date")))
    result.consumption_share = data.get("consumption_share")
    result.total = number(data.get("total"))
    result.costs = [{**row, "amount": number(row["amount"])} for row in data.get("costs") or []]
    result.readings = [{**row, "value": number(row["value"]), "previous": number(row.get("previous")),
                        "consumption": number(row.get("consumption")), "date": day(row.get("date"))}
                       for row in data.get("readings") or []]
    result.unit_results = [{**row, "amount": number(row["amount"])} for row in data.get("unit_results") or []]
    result.notes = list(data.get("notes") or [])
    return result


def _read(store: Any, actor: Any, surface: surfaces.Surface, source: Source, params: dict, values: dict, reader: str, *,
          model: Optional[str], instruction: Optional[str]) -> dict:
    """The first answer: values (or the metering extraction), questions, notes and the words to the person."""
    known = surfaces.facts(store, surface, params, level=values.get("ai_context", "standard"))
    if reader == "local":
        if not source.text.strip():
            raise HTTPException(422, "Aus dieser Datei ließ sich kein Text lesen (Scan oder Foto ohne Texterkennung). "
                                     "Mit der KI (Claude oder ChatGPT) lassen sich auch Scans und Fotos lesen.")
        if surface.rows:
            from . import meter_documents
            facts = meter_documents.property_facts(store, params["property_id"])
            known_serials = {key for meter in facts.meters for key in meter_documents.serial_keys(meter.serial_number)}
            extraction = meter_documents.extract_local(source.text, known_serials)
            return {"extraction": _extraction_dict(extraction), "questions": [], "notes": [],
                    "answer": "Mit den lokalen Regeln gelesen. Bitte die Werte mit dem Dokument vergleichen.",
                    "known": known, "images": 0, "dropped": []}
        raw = surfaces.local_values(surface, source.text, filename=source.filename, known=known)
        found, dropped = surfaces.clean_values(surface, raw, known, source="local")
        _citations(found, source, reader)
        return {"values": found, "questions": [], "notes": [], "dropped": dropped, "known": known, "images": 0,
                "answer": f"Mit den lokalen Regeln {len(found)} Werte gefunden. Ein Gespräch über das Dokument ist mit "
                          "Claude oder ChatGPT möglich."}
    conversation = [{"role": "user", "content": instruction}] if instruction else []
    request, images = _request(surface, source, known, values, model=model, conversation=conversation, current={})
    words, data = _ask(actor.id, reader, request)
    result: dict = {"answer": words or "Die Werte stehen in der Maske.", "known": known, "images": images,
                    "questions": _strings((data or {}).get("questions")), "notes": _strings((data or {}).get("notes")),
                    "dropped": []}
    if data is None:
        result["notes"].append("Die KI hat keine lesbaren Werte geliefert. Bitte erneut fragen oder die lokalen Regeln nutzen.")
    if surface.rows:
        from .meter_documents_ai import parse_data
        offered = (data or {}).get("extraction")
        extraction = parse_data(offered if isinstance(offered, dict) else {})
        result["extraction"] = _extraction_dict(extraction)
    else:
        result["values"], result["dropped"] = surfaces.clean_values(surface, (data or {}).get("values"), known, source=reader)
        _citations(result["values"], source, reader)
    return result


# ─── Readings as records ─────────────────────────────────────────────────────

def _row(unit: Any, identifier: str, *, lock: bool = False) -> Any:
    row = db.get(unit, Conversation, identifier, lock=lock)
    if row.state != STATE:
        raise HTTPException(404, "Lesevorgang nicht gefunden.")
    _check_source_access(unit, db.payload(row))
    return row


def _check_source_access(unit: Any, data: dict) -> None:
    from .privacy.storage import ensure_available, ensure_file_available, ensure_restore_reviewed
    ensure_restore_reviewed(unit.store)
    if (data.get("document") or {}).get("id"):
        ensure_available(unit.store, "document", data["document"]["id"])
    # Receipts retain identifiers only: every read, replay and mutation must
    # resolve both the original source and all context anchors with today's rights.
    try:
        # Cached duplicate titles and AI answers may include context beyond the
        # source document. An old scope must never survive a grant change.
        if data.get('_access_scope') != _access_scope(unit.user):
            raise HTTPException(404, 'Berechtigungen geändert; Dokument bitte neu einlesen.')
        document_id = (data.get("document") or {}).get("id")
        document = unit.store.get_document(document_id) if document_id else None
        if not document_id:
            from ..routers.files import _file_url_to_key
            from .portfolio_scope import require_file_access
            file_key = _file_url_to_key((data.get("file") or {}).get("file_url") or "")
            if not file_key:
                raise HTTPException(404, "Quelldatei nicht gefunden.")
            ensure_file_available(unit.store, (data.get("file") or {}).get("file_url") or "")
            require_file_access(file_key)
        _params(unit.store, _surface(data["surface"]), Params(**(data.get("params") or {})), document)
        getters = {'document': unit.store.get_document, 'invoice': unit.store.get_invoice,
                   'cost_item': unit.store.get_cost_item, 'meter_reading': unit.store.get_standalone_meter_reading}
        for candidate in data.get('duplicates') or []:
            if candidate['kind'] == 'document':
                ensure_available(unit.store, 'document', candidate['id'])
            getter = getters.get(candidate['kind'])
            if getter is None:
                raise HTTPException(404, 'Unbekannter Quellenbezug.')
            getter(candidate['id'])
        for field, getter in (('known_units', unit.store.get_unit), ('known_tenants', unit.store.get_tenant)):
            for reference in data.get(field) or []:
                getter(reference['id'])
    except (NotFoundError, HTTPException):
        raise HTTPException(404, "Lesevorgang aufgrund geänderter Quellenrechte nicht verfügbar.") from None


def _access_scope(user: dict) -> dict:
    from .portfolio_scope import scope_from_user
    scope = scope_from_user(user)
    return {'user': scope.user_id, 'role': scope.role, 'all': scope.unrestricted,
            'portfolios': list(scope.portfolio_ids)}


def _messages(unit: Any, identifier: str) -> list[dict]:
    from sqlalchemy import select
    if unit.db is None:
        rows = [row for row in db.dbs.memory(unit, Message).values()
                if row.owner_id == unit.actor_id and row.conversation_id == identifier]
    else:
        rows = list(unit.db.scalars(select(Message).where(Message.owner_id == unit.actor_id, Message.conversation_id == identifier)))
    return [{**db.payload(row), "id": row.id, "at": db.dbs.stamp(row.created_at)}
            for row in sorted(rows, key=lambda row: (row.created_at, row.id))]


def _purge(unit: Any, keep_days: int) -> None:
    """The person's readings untouched for longer than the settings keep them, with their messages."""
    from sqlalchemy import delete, select
    cutoff = db.dbs.now() - timedelta(days=max(1, int(keep_days)))
    if unit.db is None:
        conversations = db.dbs.memory(unit, Conversation)
        stale = [row.id for row in conversations.values() if row.owner_id == unit.actor_id and row.state == STATE and row.updated_at < cutoff]
        messages = db.dbs.memory(unit, Message)
        for key in [key for key, row in messages.items() if row.conversation_id in stale]:
            unit.remove(messages, key)
        for key in stale:
            unit.remove(conversations, key)
        return
    stale = list(unit.db.scalars(select(Conversation.id).where(Conversation.owner_id == unit.actor_id, Conversation.state == STATE,
                                                                Conversation.updated_at < cutoff)))
    if stale:
        unit.db.execute(delete(Message).where(Message.conversation_id.in_(stale)))
        unit.db.execute(delete(Conversation).where(Conversation.id.in_(stale)))
        unit.db.flush()


def public(store: Any, unit: Any, row: Any, confirm_mode: str = "confirm") -> dict:
    data = db.payload(row)
    # The account is reloaded by the write transaction after an external reader
    # returns. A newly created reading must also honour a revocation during that call.
    _check_source_access(unit, data)
    _current_source_proof(unit, data)
    surface = surfaces.SURFACES[data["surface"]]
    result = {key: data.get(key) for key in ("surface", "reader", "model", "params", "values", "duplicates", "decision",
                                              "questions", "notes", "dropped", "status", "record", "file", "document",
                                              "chat", "changed", "known_units", "known_tenants")}
    result.update(id=row.id, revision=row.revision, created_at=db.dbs.stamp(row.created_at),
                  surface_label=surface.label, reader_label=READERS.get(data["reader"], data["reader"]),
                  confirm_mode=confirm_mode if confirm_mode in CONFIRM_MODES else "confirm",
                  messages=[{key: message.get(key) for key in ("id", "role", "text", "changed", "at")} for message in _messages(unit, row.id)])
    if surface.id == "meter_photo":                     # the meter the read device number belongs to, for the form
        serial = ((data.get("values") or {}).get("serial") or {}).get("value")
        meter = surfaces.match_meter(store, data.get("params") or {}, str(serial)) if serial else None
        result["meter"] = {"id": meter.id, "label": meter.serial_number or meter.id} if meter is not None else None
    if surface.rows and data.get("extraction") is not None:
        from . import meter_documents
        try:
            document = store.get_document(data["document"]["id"])
            period = store.get_billing_period(data["params"]["billing_period_id"]) if data["params"].get("billing_period_id") else None
        except NotFoundError:
            result["proposal"] = None
            result["notes"] = [*(result.get("notes") or []), "Das Dokument oder die Abrechnung ist nicht mehr vorhanden."]
            return result
        proposal = meter_documents.proposal(store, document, _extraction(data["extraction"]),
                                            property_id=data["params"]["property_id"], period=period, reader=data["reader"])
        proposal.update(property_id=data["params"]["property_id"], billing_period_id=period.id if period is not None else None,
                        reader_label=result["reader_label"], text_source=(data.get("file") or {}).get("text_source"))
        result["proposal"] = proposal
    return result


def _duplicates(store: Any, surface: surfaces.Surface, params: dict, values: dict, source_info: dict, document_id: Optional[str],
                text: str, check: bool) -> list[dict]:
    if not check:
        return []
    return surfaces.duplicates(store, surface, params, values, sha256=source_info["sha256"], text=text, document_id=document_id,
                               size=source_info.get("size"))


def options(store: Any, actor: Any, surface_id: Optional[str] = None) -> dict:
    """Who can read, what is switched on and how values appear in the form, for one surface or all."""
    values = settings(store, actor.id)
    available = readers(actor.id)
    if surface_id and surface_id not in surfaces.SURFACES:
        raise HTTPException(404, "Diese Einlesestelle gibt es nicht.")
    shown = [surfaces.SURFACES[surface_id]] if surface_id else list(surfaces.SURFACES.values())
    return {"readers": available, "confirm_mode": values.get("ai_confirm_mode", "confirm"),
            "default_reader": values.get("ai_default_reader", "auto"),
            "chat": bool(values.get("ai_chat_enabled", True)) and bool(values.get("ai_reading_enabled", True)),
            "ai_enabled": bool(values.get("ai_reading_enabled", True)),
            # what goes to the AI and how long readings stay, for the explanation in the settings
            "policy": {"send_images": bool(values.get("ai_send_images", True)), "max_pages": values.get("ai_max_pages", 4),
                       "context": values.get("ai_context", "standard"), "keep_days": values.get("ai_keep_days", 30),
                       "check_duplicates": bool(values.get("ai_check_duplicates", True)), "calls_per_window": CALLS_PER_WINDOW,
                       "window_minutes": WINDOW_SECONDS // 60},
            "surfaces": [{"id": surface.id, "label": surface.label, "entry": surface.entry, "purpose": surface.purpose,
                          "needs_ai": surface.needs_ai, "may_use": may_write(actor.role, surface.area),
                          "ai_allowed": _ai_allowed(surface, values) is None, "ai_reason": _ai_allowed(surface, values),
                          "fields": [{"name": field.name, "label": field.label, "kind": field.kind,
                                      "choices": list(field.choices)} for field in surface.fields]}
                         for surface in shown]}


def start(store: Any, actor: Any, command: StartCommand) -> dict:
    surface = _surface(command.surface)
    _check_role(actor, surface)
    values = settings(store, actor.id)
    with db.work(store, actor.id) as unit:
        access_scope = _access_scope(unit.user)
        replayed = db.replay(unit, "reading:start", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
    reader = _choose_reader(command.reader, surface, values, readers(actor.id) if command.reader != "local" else [])
    source = _source(store, command)
    params = _params(store, surface, command.params, source.document)
    model = (command.model or values.get(f"ai_model_{reader}") or None) if reader != "local" else None
    if model:
        from .assistant_provider_prompt import checked_model
        try:
            model = checked_model(model)
        except ProviderError as error:
            raise HTTPException(422, str(error)) from error
    read = _read(store, actor, surface, source, params, values, reader, model=model, instruction=command.instruction)
    file_info = {"name": source.filename, "media_type": source.media_type, "sha256": source.sha256, "size": len(source.content),
                 "characters": len(source.text), "text_source": source.text_source, "file_url": source.file_url,
                 "source_ref": source.source_ref, "version_id": _version(source),
                 "read_characters": len(source.text) if reader == "local" else min(len(source.text), MAX_TEXT),
                 "text_truncated": len(source.text) >= 500_000 or (reader != "local" and len(source.text) > MAX_TEXT),
                 "text_available": bool(source.text.strip())}
    found_values = read.get("values") or {}
    duplicates = _duplicates(store, surface, params, found_values, file_info, source.document.id if source.document else None,
                             source.text, bool(values.get("ai_check_duplicates", True)))
    known = read["known"]
    data = {"kind": "reading", "surface": surface.id, "reader": reader, "model": model, "params": params,
            "_access_scope": access_scope,
            "document": {"id": source.document.id, "title": source.document.title, "href": f"/documents/{source.document.id}"}
            if source.document is not None else None,
            "file": file_info, "values": found_values if not surface.rows else None, "extraction": read.get("extraction"),
            "duplicates": duplicates, "decision": None, "questions": read["questions"], "notes": read["notes"],
            "dropped": read["dropped"], "status": "open", "record": None, "turns": 0 if reader == "local" else 1,
            "changed": sorted(found_values), "known_units": known.get("units") or [], "known_tenants": known.get("tenants") or [],
            "chat": reader != "local" and bool(values.get("ai_chat_enabled", True))}
    with db.work(store, actor.id, write=True, key=command.idempotency_key) as unit:
        replayed = db.replay(unit, "reading:start", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
        _purge(unit, values.get("ai_keep_days", 30))
        row = db.put(unit, Conversation, data, state=STATE)
        if command.instruction:
            db.put(unit, Message, {"role": "user", "text": command.instruction.strip()}, conversation_id=row.id)
        db.put(unit, Message, {"role": "assistant", "text": read["answer"], "changed": sorted(found_values)}, conversation_id=row.id)
        db.receipt(unit, "reading:start", command, row)
        result = public(store, unit, row, values.get("ai_confirm_mode", "confirm"))
    _audit(actor, "AI_READ", row.id, {"surface": surface.id, "reader": reader, "model": model,
                                      "document_id": source.document.id if source.document else None,
                                      "characters": len(source.text), "page_images": read["images"],
                                      "values": len(found_values), "duplicates": len(duplicates)})
    return result


def say(store: Any, actor: Any, identifier: str, command: MessageCommand) -> dict:
    """A message of the person about the document; the AI answers and may change values."""
    values = settings(store, actor.id)
    with db.work(store, actor.id) as unit:
        replayed = db.replay(unit, "reading:say", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
        row = _row(unit, identifier)
        db.revision(row, command.expected_revision)
        data = db.payload(row)
        history = _messages(unit, identifier)
    surface = _surface(data["surface"])
    _check_role(actor, surface)
    if data["reader"] == "local" or not data.get("chat"):
        raise HTTPException(409, "Ein Gespräch über das Dokument ist mit Claude oder ChatGPT möglich. Bitte das Dokument mit der KI neu einlesen.")
    if not values.get("ai_chat_enabled", True):
        raise HTTPException(409, "Das Gespräch mit der KI ist in den Einstellungen ausgeschaltet.")
    reason = _ai_allowed(surface, values)
    if reason:
        raise HTTPException(409, reason)
    if data.get("status") != "open":
        raise HTTPException(409, "Dieser Lesevorgang ist abgeschlossen. Für weitere Fragen das Dokument neu einlesen.")
    if data.get("turns", 0) >= MAX_TURNS:
        raise HTTPException(409, f"Nach {MAX_TURNS} Fragen ist dieser Lesevorgang voll. Bitte das Dokument neu einlesen.")
    if data["reader"] not in [reader["id"] for reader in readers(actor.id) if reader["available"]]:
        raise HTTPException(409, f"{READERS[data['reader']]} ist nicht mehr verbunden. Im Bereich Assistent neu verbinden.")
    document_id = (data.get("document") or {}).get("id")
    source = _source(store, StartCommand(surface=surface.id, document_id=document_id,
                                         file_url=None if document_id else (data.get("file") or {}).get("file_url"),
                                         idempotency_key="reading-chat-source"))
    if source.sha256 != (data.get("file") or {}).get("sha256"):
        raise HTTPException(409, "Die Datei wurde seit dem Einlesen geändert. Bitte das Dokument neu einlesen.")
    known = surfaces.facts(store, surface, data["params"], level=values.get("ai_context", "standard"))
    conversation = [{"role": message["role"], "content": message["text"]} for message in history
                    if message.get("role") in ("user", "assistant") and message.get("text")][-20:]
    conversation.append({"role": "user", "content": command.text.strip()})
    current = data["extraction"] if surface.rows else {name: item["value"] for name, item in (data.get("values") or {}).items()}
    request, images = _request(surface, source, known, values, model=data.get("model"), conversation=conversation, current=current)
    words, answer = _ask(actor.id, data["reader"], request)
    changed: list[str] = []
    if surface.rows:
        if answer and isinstance(answer.get("extraction"), dict):
            from .meter_documents_ai import parse_data
            data["extraction"] = _extraction_dict(parse_data(answer["extraction"]))
            changed = ["extraction"]
    else:
        offered = (answer or {}).get("values")
        incoming: dict = offered if isinstance(offered, dict) else {}
        cleaned, dropped = surfaces.clean_values(surface, incoming, known, source=data["reader"])
        _citations(cleaned, source, data["reader"])
        merged = dict(data.get("values") or {})
        for name, item in incoming.items():
            entry = item if isinstance(item, dict) else {"value": item}
            if surface.field(str(name)) and entry.get("value") is None and name in merged:
                merged.pop(name)
                changed.append(name)
        for name, item in cleaned.items():
            if (merged.get(name) or {}).get("value") != item["value"]:
                changed.append(name)
            merged[name] = item
        data["values"], data["dropped"] = merged, dropped
        data["duplicates"] = _duplicates(store, surface, data["params"], merged, data["file"], document_id, source.text,
                                         bool(values.get("ai_check_duplicates", True)))
    data["questions"] = _strings((answer or {}).get("questions"))
    data["notes"] = _strings((answer or {}).get("notes"))
    data["changed"] = sorted(set(changed))
    data["turns"] = data.get("turns", 0) + 1
    with db.work(store, actor.id, write=True, key=command.idempotency_key) as unit:
        replayed = db.replay(unit, "reading:say", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
        row = _row(unit, identifier, lock=True)
        db.revision(row, command.expected_revision)
        db.put(unit, Message, {"role": "user", "text": command.text.strip()}, conversation_id=row.id)
        db.put(unit, Message, {"role": "assistant", "text": words or "Die Werte sind angepasst.", "changed": data["changed"]},
               conversation_id=row.id)
        row = db.put(unit, Conversation, data, row=row)
        db.receipt(unit, "reading:say", command, row)
        result = public(store, unit, row, values.get("ai_confirm_mode", "confirm"))
    _audit(actor, "AI_CHAT", identifier, {"surface": surface.id, "reader": data["reader"], "changed": data["changed"],
                                          "page_images": images, "characters": len(command.text)})
    return result


def decide(store: Any, actor: Any, identifier: str, command: DecisionCommand) -> dict:
    """What the person does about a record that already exists for the document."""
    values = settings(store, actor.id)
    with db.work(store, actor.id, write=True, key=command.idempotency_key) as unit:
        replayed = db.replay(unit, "reading:decide", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
        row = _row(unit, identifier, lock=True)
        db.revision(row, command.expected_revision)
        data = db.payload(row)
        _check_role(actor, _surface(data["surface"]))
        if command.action in ("use_existing", "update_existing"):
            match = next((item for item in data.get("duplicates") or [] if item["kind"] == command.record_kind
                          and item["id"] == command.record_id), None)
            if match is None:
                raise HTTPException(422, "Dieser Datensatz gehört nicht zu den gefundenen vorhandenen Einträgen.")
            if command.action == "update_existing" and not match.get("can_update"):
                raise HTTPException(422, "Dieser vorhandene Eintrag lässt sich nicht aus dem Dokument aktualisieren; bitte öffnen.")
        data["decision"] = {"action": command.action, "record_kind": command.record_kind, "record_id": command.record_id,
                            "at": db.dbs.stamp(db.dbs.now())}
        if command.action == "cancel":
            data["status"] = "cancelled"
        row = db.put(unit, Conversation, data, row=row)
        db.receipt(unit, "reading:decide", command, row)
        result = public(store, unit, row, values.get("ai_confirm_mode", "confirm"))
    _audit(actor, "AI_DECIDE", identifier, {"action": command.action, "record_kind": command.record_kind, "record_id": command.record_id})
    return result


def finish(store: Any, actor: Any, identifier: str, command: FinishCommand) -> dict:
    """The values were saved in the form (with the record that came of it), or the reading is dropped."""
    values = settings(store, actor.id)
    with db.work(store, actor.id, write=True, key=command.idempotency_key) as unit:
        replayed = db.replay(unit, "reading:finish", command)
        if replayed:
            return public(store, unit, _row(unit, replayed), values.get("ai_confirm_mode", "confirm"))
        row = _row(unit, identifier, lock=True)
        db.revision(row, command.expected_revision)
        data = db.payload(row)
        if data.get("status") != "open":
            raise HTTPException(409, "Dieser Lesevorgang ist bereits abgeschlossen.")
        data["status"] = command.outcome
        data["record"] = {"kind": command.record_kind, "id": command.record_id} if command.record_id else None
        row = db.put(unit, Conversation, data, row=row)
        db.receipt(unit, "reading:finish", command, row)
        result = public(store, unit, row, values.get("ai_confirm_mode", "confirm"))
    _audit(actor, "AI_TAKEOVER" if command.outcome == "taken_over" else "AI_DISCARD", identifier,
           {"surface": data["surface"], "record_kind": command.record_kind, "record_id": command.record_id})
    return result


def read(store: Any, actor: Any, identifier: str) -> dict:
    values = settings(store, actor.id)
    with db.work(store, actor.id) as unit:
        return public(store, unit, _row(unit, identifier), values.get("ai_confirm_mode", "confirm"))


def _audit(actor: Any, action: str, identifier: str, changes: dict) -> None:
    """What was read, by whom and with which reader; never document content or values."""
    from ..audit import log_action
    log_action(action, "ai_reading", identifier, user_id=actor.id, username=actor.username, changes=changes)
