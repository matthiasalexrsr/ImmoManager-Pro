"""Read-only, freshly authorized application tools; no provider or arbitrary SQL."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from ..db.assistant_models import AssistantAttachmentORM as Attachment
from ..db.assistant_models import AssistantConversationORM as Conversation
from ..db.assistant_models import AssistantRunORM as Run
from ..db.orm_models import Base
from ..finance_models import ReportDefinition
from . import assistant_context as context
from . import assistant_storage as db
from . import workspace_contexts as contexts
from .integrations import connection_storage as dbs
from .portfolio_scope import RESOURCE_ALIASES

MAX_CALLS = 64
SCAN_LIMIT = 500


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Search(Strict):
    kind: context.SourceKind | None = None
    query: str = Field(default="", max_length=200)
    cursor: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=20, ge=1, le=100)


class Read(Strict):
    kind: context.SourceKind
    id: str = Field(min_length=1, max_length=120)


class Related(Read):
    target_kinds: list[context.SourceKind] = Field(default_factory=list, max_length=30)
    cursor: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=20, ge=1, le=100)


class Timeline(Related):
    date_from: date | None = None
    date_to: date | None = None


class Report(Strict):
    definition: ReportDefinition
    cursor: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=50, ge=1, le=100)


class Document(Strict):
    kind: Literal["document", "attachment"] = "document"
    id: str = Field(min_length=1, max_length=120)
    cursor: str | None = Field(default=None, max_length=4000)
    limit_chars: int = Field(default=16000, ge=100, le=32000)


class Investigate(Strict):
    anchor: Read | None = None
    kinds: list[Literal["task", "invoice", "contract", "receivable", "unit", "document"]] = Field(default_factory=list, max_length=6)
    checks: list[Literal["deadlines", "missing_data", "consistency", "invoice_arithmetic", "invoice_payments"]] = Field(default_factory=list, max_length=5)
    as_of: date | None = None
    cursor: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=20, ge=1, le=100)


TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "immo_search": (Search, "Berechtigte Akten suchen; Typ und Suchtext eingrenzen. Jede Seite nennt has_more/next_cursor; keine Treffer beweisen keine vollständige Aktenlage."),
    "immo_read": (Read, "Eine aktuelle Fachakte mit freigegebenen Feldern, Revision und Hash lesen. Keine Kontozugänge oder IBAN."),
    "immo_related": (Related, "Objektgebundene verwandte Akten einer Quelle seitenweise lesen, z.B. Verträge, Forderungen, Aufgaben, Rechnungen, Zähler und Schäden."),
    "immo_timeline": (Timeline, "Datierte Angaben verwandter Akten im Zeitraum lesen. Fehlende Datierung ist ausdrücklich ausgewiesen; keine freie Ereignisinferenz."),
    "immo_report": (Report, "Geprüfte lokale Finanzrechnung. Gesamt-/Monatswerte vollständig, Belege seitenweise. result_hash, Währung, Zeitraum und Berechnungsbasis beachten."),
    "immo_document": (Document, "Originaltext eines Dokuments oder einer verfügbaren Chatdatei vollständig per Cursor lesen. OCR/fehlende Texterkennung bleibt sichtbar, kein Inhalt wird still abgeschnitten."),
    "immo_investigate": (Investigate, "Freigegebene Akten automatisch auf überfällige Aufgaben, fehlende Daten, Vertragsstatus sowie Rechnungs- und Zahlungswidersprüche prüfen; optional auf eine Akte begrenzen. Deterministische Befunde mit Quellen und Folgeaktion. Alle Seiten lesen; Prüfgrenzen/skipped_checks beachten. Keine Fachänderungen."),
}


def descriptors() -> list[dict]:
    return [{"name": name, "description": description, "inputSchema": model.model_json_schema(),
             "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}}
            for name, (model, description) in TOOLS.items()]


def merge_bundle(bundle: dict, sources: list[dict]) -> dict:
    known = {(source["kind"], source["id"]): source for source in bundle["sources"]}
    known.update({(source["kind"], source["id"]): source for source in sources})
    selected = {field: sorted(identifier for kind, identifier in known if kind == target)
                for field, target in context.SELECTIONS.items()}
    selected = {key: value for key, value in selected.items() if value or key in (
        "property_ids", "unit_ids", "tenant_ids", "contact_ids", "document_ids")}
    ordered = [known[(kind, identifier)] for field, kind in context.SELECTIONS.items()
               for identifier in selected.get(field, [])]
    result = {"format": context.FORMAT, "selection": selected, "sources": ordered,
              "warnings": [], "automatic_related_records": False}
    result["sha256"] = context.content_hash(result)
    return result


def _roots(store, kind: str, identifier: str) -> tuple[set[str], set[str], dict]:
    table = RESOURCE_ALIASES[kind]
    values = contexts._row(store, table, identifier)
    properties: set[str] = set()
    contexts._portfolios(store, table, values, set(), properties)
    units: set[str] = set()
    if kind == "tenant":
        if hasattr(store, "db"):
            contracts = Base.metadata.tables["contracts"]
            units.update(value for value in store.db.scalars(select(contracts.c.unit_id).where(contracts.c.tenant_id == identifier)) if value)
        else:
            units.update(contract.unit_id for contract in store.list_contracts() if contract.tenant_id == identifier)
    pending = [(kind, identifier, values)]
    seen: set[tuple[str, str]] = set()
    # Only approved parent paths, never neighboring records or users/accounts.
    parents = {"unit_id": "unit", "contract_id": "contract", "meter_id": "meter",
               "billing_period_id": "billing_period", "statement_id": "utility_statement"}
    while pending:
        current_kind, current_id, current = pending.pop()
        if (current_kind, current_id) in seen:
            continue
        seen.add((current_kind, current_id))
        if current_kind == "unit":
            units.add(current_id)
        for field, parent in parents.items():
            if current.get(field):
                try:
                    pending.append((parent, current[field], contexts._row(store, RESOURCE_ALIASES[parent], current[field])))
                except HTTPException:
                    pass
    return properties, units, values


def _permitted(unit, data, kind: str, identifier: str) -> dict:
    if data.get("data_scope", "selected") == "none":
        raise HTTPException(404, "Diese Fachquelle ist für den Auftrag nicht freigegeben.")
    source = context._source(unit.store, kind, identifier, unit.actor_id)
    if data.get("data_scope") == "authorized":
        return source
    selected = context.ContextSelection.model_validate(data.get("_grant_selection", data["context"]))
    exact = {(target, value) for field, target in context.SELECTIONS.items() for value in getattr(selected, field)}
    if (kind, identifier) in exact:
        return source
    properties, units, values = _roots(unit.store, kind, identifier)
    if properties.intersection(selected.property_ids) or units.intersection(selected.unit_ids):
        return source
    if kind == "property" and any(contexts._row(unit.store, "units", unit_id).get("property_id") == identifier
                                   for unit_id in selected.unit_ids):
        # Parent metadata does not authorize that property's other units.
        return source
    if any(values.get(field) in getattr(selected, field.replace("_id", "_ids"), [])
           for field in ("tenant_id", "contract_id", "meter_id", "billing_period_id")):
        return source
    raise HTTPException(404, "Diese Fachquelle ist für den Auftrag nicht freigegeben.")


def _cursor(unit, run_id: str, tool: str, fingerprint: str, value=None, token=None):
    aad = "assistant-tool-cursor:" + unit.actor_id + ":" + run_id + ":" + tool
    if token:
        try:
            data = json.loads(dbs.unseal(token, aad))
            if data["fingerprint"] != fingerprint:
                raise ValueError
            return data["position"]
        except Exception:
            raise HTTPException(409, "Fortsetzung ist ungültig oder die Quelle wurde geändert. Bitte neu beginnen.") from None
    return dbs.seal(json.dumps({"fingerprint": fingerprint, "position": value}), aad)


def _ids(unit, kind: str, after: str) -> list[str]:
    table = RESOURCE_ALIASES[kind]
    if unit.db is not None:
        model = Base.metadata.tables[table]
        return list(unit.db.scalars(select(model.c.id).where(model.c.id > after).order_by(model.c.id).limit(SCAN_LIMIT + 1)))
    collection = getattr(unit.store, table, {})
    return sorted(identifier for identifier in collection if identifier > after)[:SCAN_LIMIT + 1]


def _listing(unit, row, data, tool, args, *, kinds_override=None, fingerprint_override=None):
    fingerprint = fingerprint_override or context.content_hash(args.model_dump(mode="json", exclude={"cursor", "limit"}))
    after = _cursor(unit, row.id, tool, fingerprint, token=args.cursor) if args.cursor else ["", ""]
    kinds = [args.kind] if isinstance(args, Search) and args.kind else sorted(context.FIELDS)
    anchor = None
    if isinstance(args, Related):
        anchor = _permitted(unit, data, args.kind, args.id)
        anchor_properties, anchor_units, _ = _roots(unit.store, args.kind, args.id)
        kinds = sorted(set(args.target_kinds or context.FIELDS))
    if kinds_override is not None:
        kinds = sorted(set(kinds_override))
    candidates = [(kind, identifier) for kind in kinds if kind >= after[0]
                  for identifier in _ids(unit, kind, after[1] if kind == after[0] else "")]
    items: list[dict] = []
    sources = [anchor] if anchor else []
    last = after
    consumed = 0
    for kind, identifier in candidates:
        if consumed >= SCAN_LIMIT or len(items) >= args.limit:
            break
        consumed += 1
        last = [kind, identifier]
        try:
            source = _permitted(unit, data, kind, identifier)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        if isinstance(args, Search):
            if args.query.casefold() not in json.dumps(source["values"], ensure_ascii=False).casefold():
                continue
        else:
            properties, units, values = _roots(unit.store, kind, identifier)
            linked = (kind, identifier) == (args.kind, args.id) or values.get(args.kind + "_id") == args.id
            if args.kind == "property":
                linked |= bool(properties.intersection(anchor_properties))
            elif args.kind == "unit":
                linked |= bool(units.intersection(anchor_units))
            elif args.kind == "contract":
                linked |= values.get("contract_id") == args.id
            elif args.kind == "document" and kind == "invoice":
                linked |= any(values.get(field) == args.id for field in ("document_id", "source_document_id"))
            elif args.kind == "invoice" and kind == "document" and anchor:
                linked |= any(anchor["values"].get(field) == identifier for field in ("document_id", "source_document_id"))
            if not linked:
                continue
        if isinstance(args, Timeline):
            dated = {key: value for key, value in source["values"].items() if value and
                     (key.endswith("_date") or key in ("due_date", "installation_date", "removal_date", "start_datetime", "end_datetime"))}
            if args.date_from and args.date_to and args.date_from > args.date_to:
                raise HTTPException(422, "Der Zeitraum ist widersprüchlich.")
            matches = {key: value for key, value in dated.items() if
                       (not args.date_from or str(value)[:10] >= args.date_from.isoformat()) and
                       (not args.date_to or str(value)[:10] <= args.date_to.isoformat())}
            if dated and not matches:
                continue
            source = {**source, "dates": matches, "date_missing": not dated}
        items.append(source)
        sources.append({key: value for key, value in source.items() if key not in ("dates", "date_missing")})
    more = consumed < len(candidates)
    return {"ok": True, "items": items, "sources": sources,
            "coverage": {"returned": len(items), "has_more": more, "truncated": False,
                         "total": len(items) if not more and not args.cursor else None,
                         "total_known": not more and not args.cursor,
                         "next_cursor": _cursor(unit, row.id, tool, fingerprint, value=last) if more else None,
                         "scope": data.get("data_scope", "selected"), "complete": not more,
                         "meaning": "Nur aktuell freigegebene, passende Akten. Kein Treffer ist kein Nachweis vollständiger Datenhaltung."}}


def _investigate(unit, row, data, args, *, persist=True):
    from . import assistant_checks as checks
    from . import invoice_review
    from .maintenance_rows import Rows

    # Freeze the effective day in proofs and cursors, including across midnight.
    as_of = args.as_of or datetime.now(ZoneInfo("Europe/Berlin")).date()
    effective = args.model_copy(update={"as_of": as_of})
    fingerprint = context.content_hash(effective.model_dump(mode="json", exclude={"cursor", "limit"}))
    kinds = sorted(set(args.kinds or checks.KINDS))
    enabled = sorted(set(args.checks or checks.CHECKS))
    listing_args = (Related(**args.anchor.model_dump(), target_kinds=kinds, cursor=args.cursor, limit=args.limit)
                    if args.anchor else Search(cursor=args.cursor, limit=args.limit))
    page = _listing(unit, row, data, "immo_investigate", listing_args,
                    kinds_override=kinds, fingerprint_override=fingerprint)
    found, calculations, skipped = [], [], []
    rows = Rows.reading(unit.store)
    for source in page["items"]:
        found.extend(checks.findings_for_source(source, as_of, enabled))
        if source["kind"] != "invoice":
            continue
        first_derived_finding = len(found)
        invoice = rows.require("invoices", source["id"], "Rechnung nicht gefunden")
        derived: dict[str, object] = {}
        if "invoice_arithmetic" in enabled:
            # Use the application's real per-rate breakdown; a single-rate
            # approximation would flag perfectly valid mixed-rate invoices.
            review = invoice_review.review_of(rows, invoice.id)
            arithmetic = invoice_review._arithmetic(invoice, review)
            derived["arithmetic"] = arithmetic
            for item in arithmetic:
                found.append(checks.finding(source, "invoice_" + item["code"], item["message"],
                    severity=item["severity"], next_step="Beträge und Steuersätze im Originalbeleg und in der Rechnungsprüfung abgleichen."))
        if "invoice_payments" in enabled:
            if data.get("data_scope", "selected") != "authorized":
                skipped.append({"check": "invoice_payments", "source": checks.evidence(source),
                    "reason": "Die Zahlungsprüfung benötigt berechtigten Gesamtzugriff auf verknüpfte Zahlungs- und Gutschriftakten; ausgewählte Akten erweitern diese Freigabe nicht."})
            else:
                settlement = invoice_review.settlements(rows, [invoice], as_of)[invoice.id]
                derived["settlement"] = settlement.as_json()
                for item in settlement.findings:
                    found.append(checks.finding(source, "invoice_" + item["code"], item["message"],
                        severity=item["severity"], next_step="Zahlungszuordnungen und Freigabe in der Rechnungsprüfung abgleichen."))
                if invoice.status == "paid" and settlement.open > 0:
                    found.append(checks.finding(source, "invoice_paid_without_full_allocation",
                        "Die Rechnung ist als bezahlt erfasst, aber die lokale Zahlungsprüfung weist noch einen offenen Betrag aus.",
                        next_step="Zahlung zuordnen oder den erfassten Rechnungsstatus berichtigen."))
                if settlement.overdue and invoice.status not in ("cancelled", "rejected"):
                    found.append(checks.finding(source, "invoice_payment_overdue",
                        "Die lokale Rechnungsprüfung weist am Prüftag einen überfälligen offenen Betrag aus.",
                        next_step="Freigabe, Zahlungszuordnung und gegebenenfalls Rückfrage prüfen."))
        if derived:
            calculations.append({"kind": "invoice", "id": invoice.id,
                "engine": "invoice_review", "sha256": context.content_hash(derived)})
            for item in found[first_derived_finding:]:
                item["calculation_sha256"] = calculations[-1]["sha256"]
                item["as_of"] = as_of.isoformat()
    coverage = {**page["coverage"], "scanned": len(page["items"]), "findings": len(found),
                "as_of": as_of.isoformat(), "checks": enabled, "kinds": kinds, "skipped_checks": skipped,
                "meaning": "Seitenweise Prüfung erfasster, aktuell freigegebener Akten; fehlende Akten oder nicht angelegte Aufgaben sind damit nicht bewiesen. Offene Statusangaben allein belegen keine Restschuld."}
    result = {"ok": True, "items": page["items"], "sources": page["sources"], "findings": found,
              "calculations": calculations, "coverage": coverage}
    result["result_hash"] = context.content_hash({"sources": page["sources"], "findings": found,
        "calculations": calculations, "coverage": {key: value for key, value in coverage.items() if key != "next_cursor"}})
    if persist:
        key = context.content_hash([fingerprint, args.cursor, args.limit])
        data.setdefault("_tool_investigations", {})[key] = {"run_id": row.id,
            "arguments": effective.model_dump(mode="json"), "hash": result["result_hash"]}
    return result


def _timeline(unit, row, data, args):
    from . import business_qol as office
    anchor = _permitted(unit, data, args.kind, args.id)
    if data.get("data_scope", "selected") == "selected":
        selected = context.ContextSelection.model_validate(data.get("_grant_selection", data["context"]))
        exact = {(target, value) for field, target in context.SELECTIONS.items() for value in getattr(selected, field)}
        properties, units, _ = _roots(unit.store, args.kind, args.id)
        if ((args.kind, args.id) not in exact and not (
                properties and properties.issubset(set(selected.property_ids)) or
                units and units.issubset(set(selected.unit_ids)))):
            raise HTTPException(404, "Die vollständige Chronik dieser übergeordneten Akte ist nicht freigegeben.")
    if args.date_from and args.date_to and args.date_from > args.date_to:
        raise HTTPException(422, "Der Zeitraum ist widersprüchlich.")
    fingerprint = context.content_hash(args.model_dump(mode="json", exclude={"cursor", "limit"}))
    native_cursor = _cursor(unit, row.id, "immo_timeline", fingerprint, token=args.cursor) if args.cursor else None
    if not native_cursor and args.date_to:
        boundary = datetime.combine(args.date_to + timedelta(days=1), time(), tzinfo=ZoneInfo("Europe/Berlin"))
        native_cursor = office.cursor_encode(["timeline", unit.actor_id, args.kind, args.id],
                                             [boundary.astimezone(timezone.utc).isoformat(), ""])
    page = office.timeline(unit.store, args.kind, args.id, unit.actor_id, cursor=native_cursor, limit=args.limit)
    items, sources = [], [anchor]
    reached_start = False
    for event in page["items"]:
        day = datetime.fromisoformat(event["occurred_at"]).astimezone(ZoneInfo("Europe/Berlin")).date()
        if args.date_from and day < args.date_from:
            reached_start = True
            continue
        if args.date_to and day > args.date_to:
            continue
        entity = event.get("entity", {})
        kind, identifier = entity.get("type"), entity.get("id")
        if kind not in context.FIELDS or not identifier:
            continue
        field = event.get("field_name")
        if field and (field not in context.FIELDS[kind] or contexts.SENSITIVE.search(field)):
            continue
        try:
            source = _permitted(unit, data, kind, identifier)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        # Keep an explicit scalar event schema; never serialize arbitrary old
        # record dictionaries from change history or account data.
        public = {key: event[key] for key in ("id", "occurred_at", "kind", "title", "body", "actor", "field_name")
                  if key in event and isinstance(event[key], str | int | float | bool | type(None))}
        if field:
            for key in ("old_value", "new_value"):
                if isinstance(event.get(key), str | int | float | bool | type(None)):
                    public[key] = event.get(key)
        public["source"] = {key: source[key] for key in ("kind", "id", "revision", "sha256", "title", "href")}
        public["event_sha256"] = context.content_hash(public)
        items.append(public)
        sources.append(source)
    more = page["has_more"] and not reached_start
    proof_key = context.content_hash([fingerprint, native_cursor, args.limit])
    data.setdefault("_tool_timelines", {})[proof_key] = {"kind": args.kind, "id": args.id, "cursor": native_cursor,
        "limit": args.limit, "hash": context.content_hash(page)}
    return {"ok": True, "items": items, "sources": sources, "coverage": {
        "returned": len(items), "total": None, "total_known": False, "has_more": more, "truncated": False,
        "complete": not more, "timezone": "Europe/Berlin",
        "next_cursor": _cursor(unit, row.id, "immo_timeline", fingerprint, value=page["next_cursor"]) if more else None}}


def _full_text(raw: bytes, name: str) -> tuple[str, list[str]]:
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "csv"):
        return raw.decode("utf-8-sig"), []
    if ext == "docx":
        import zipfile
        from xml.etree import ElementTree as ET

        from .document_formats import validate_docx
        validate_docx(raw)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            parts = ["word/document.xml"] + sorted(key for key in package.namelist()
                if key.startswith(("word/header", "word/footer")) and key.endswith(".xml"))
            return "\n".join("".join(node.text or "" for node in paragraph.iter(namespace + "t"))
                             for part in parts for paragraph in ET.fromstring(package.read(part)).iter(namespace + "p")), []
    if ext == "pdf":
        import fitz
        with fitz.open(stream=raw, filetype="pdf") as document:
            if document.needs_pass:
                raise HTTPException(422, "Das PDF ist passwortgeschützt.")
            text = "\n".join(f"\n[Seite {index + 1}]\n" + page.get_text() for index, page in enumerate(document))
            return text, ["Es wurde nur vorhandener PDF-Text gelesen; Bildseiten benötigen separate Texterkennung."]
    return "", ["Kein lokal extrahierbarer Text. Das Original bleibt erhalten; Bilder benötigen visuelle Prüfung."]


def _document(unit, row, data, args):
    from . import assistant
    if args.kind == "attachment":
        if args.id not in data.get("attachment_ids", []):
            raise HTTPException(404, "Datei ist für diesen Auftrag nicht freigegeben.")
        attached = db.owned_child(unit, Attachment, args.id)
        if attached.conversation_id != row.conversation_id:
            raise HTTPException(404, "Datei nicht gefunden.")
        raw, saved = assistant.verified_attachment(attached)
        source = {"kind": "attachment", "id": attached.id, "revision": str(attached.revision),
                  "sha256": saved["sha256"], "file_sha256": saved["sha256"], "title": saved["name"]}
        name = saved["name"]
    else:
        source = _permitted(unit, data, "document", args.id)
        from . import business_documents, document_versions
        original = document_versions.head(unit, args.id)
        if original:
            _, binding = document_versions.bind_document(unit, args.id)
            original = document_versions.authorized_version(unit, args.id, original.id, binding)
            raw, name = document_versions.original_bytes(unit, original), original.filename
        else:
            values = contexts.resolve_context(unit.store, "document", args.id, unit.actor_id)["values"]
            raw, name = business_documents._file(values["file_url"]), values["file_url"]
        if hashlib.sha256(raw).hexdigest() != source["file_sha256"]:
            raise HTTPException(409, "Das Dokument wurde geändert.")
    text, warnings = _full_text(raw, name)
    fingerprint = context.content_hash([args.kind, args.id, hashlib.sha256(text.encode()).hexdigest()])
    offset = _cursor(unit, row.id, "immo_document", fingerprint, token=args.cursor) if args.cursor else 0
    end = min(offset + args.limit_chars, len(text))
    return {"ok": True, "items": [{"text": text[offset:end], "start_char": offset, "end_char": end,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "source": source}], "sources": [source], "warnings": warnings,
            "coverage": {"returned": end - offset, "total": len(text), "has_more": end < len(text), "truncated": False,
                         "text_available": bool(text.strip()), "complete": end >= len(text),
                         "next_cursor": _cursor(unit, row.id, "immo_document", fingerprint, value=end) if end < len(text) else None}}


def _report(unit, row, data, args):
    from .finance_reports import compute
    definition = args.definition
    if data.get("data_scope", "selected") == "selected" and not definition.unit_id:
        selected = context.ContextSelection.model_validate(data.get("_grant_selection", data["context"]))
        if definition.property_id not in selected.property_ids:
            raise HTTPException(404, "Ein Immobilien-Gesamtbericht benötigt die ausdrücklich ausgewählte Immobilie.")
    if definition.unit_id:
        sources = [_permitted(unit, data, "unit", definition.unit_id)]
    elif definition.property_id:
        sources = [_permitted(unit, data, "property", definition.property_id)]
    elif data.get("data_scope") == "authorized":
        # Preserve scope guards for every portfolio whose figures can be used
        # in the answer, including a future access revocation.
        sources = [_permitted(unit, data, "portfolio", portfolio.id) for portfolio in unit.store.list_portfolios()
                   if not definition.portfolio_id or portfolio.id == definition.portfolio_id]
    else:
        raise HTTPException(422, "Bericht ausdrücklich auf eine Immobilie oder Einheit begrenzen.")
    result = compute(unit.store, definition)
    fingerprint = context.content_hash([definition.model_dump(mode="json"), result["result_hash"]])
    offset = _cursor(unit, row.id, "immo_report", fingerprint, token=args.cursor) if args.cursor else 0
    all_sources = result.get("sources", [])
    end = min(offset + args.limit, len(all_sources))
    data.setdefault("_tool_reports", {})[result["definition_hash"]] = {
        "definition": definition.model_dump(mode="json"), "result_hash": result["result_hash"]}
    data["financial_summary"] = {key: result[key] for key in ("currency", "basis", "filters", "totals", "result_hash", "definition") if key in result}
    data["financial_summary"]["as_of"] = definition.as_of.isoformat()
    return {"ok": True, "report": {**result, "sources": all_sources[offset:end]}, "items": all_sources[offset:end],
            "sources": sources, "coverage": {"returned": end - offset, "total": len(all_sources),
                "has_more": end < len(all_sources), "truncated": False, "complete": end >= len(all_sources),
                "next_cursor": _cursor(unit, row.id, "immo_report", fingerprint, value=end) if end < len(all_sources) else None}}


def validate_reports(store, data):
    from .finance_reports import compute
    for proof in data.get("_tool_reports", {}).values():
        if compute(store, ReportDefinition.model_validate(proof["definition"]))["result_hash"] != proof["result_hash"]:
            raise HTTPException(409, "Eine im Gespräch verwendete Finanzrechnung wurde geändert. Bitte aktuell erneut prüfen.")
    from . import business_qol as office
    for proof in data.get("_tool_timelines", {}).values():
        page = office.timeline(store, proof["kind"], proof["id"], contexts.actor(data["_tool_actor"], store)["id"],
                               cursor=proof["cursor"], limit=proof["limit"])
        if context.content_hash(page) != proof["hash"]:
            raise HTTPException(409, "Die verwendete Chronik wurde geändert. Bitte aktuell erneut prüfen.")
    unit = SimpleNamespace(store=store, db=getattr(store, "db", None), actor_id=data.get("_tool_actor"))
    for proof in data.get("_tool_investigations", {}).values():
        current = _investigate(unit, SimpleNamespace(id=proof["run_id"]), data,
                               Investigate.model_validate(proof["arguments"]), persist=False)
        if current["result_hash"] != proof["hash"]:
            raise HTTPException(409, "Die verwendete Aktenprüfung wurde geändert. Bitte aktuell erneut prüfen.")


def call(store, actor_id: str, run_id: str, lease: str, name: str, arguments: dict) -> dict:
    """One bounded fresh unit per HTTP call; model never supplies actor/lease/store."""
    from . import assistant
    try:
        if name not in TOOLS:
            raise HTTPException(422, "Dieses Werkzeug ist nicht freigegeben.")
        args = TOOLS[name][0].model_validate(arguments)
        with db.work(store, actor_id, write=True) as unit:
            row = db.owned_child(unit, Run, run_id, lock=True)
            data = db.payload(row)
            data["_tool_actor"] = actor_id
            if row.state != "running" or data.get("_lease") != lease:
                raise HTTPException(409, "Dieser Auftrag ist nicht mehr aktiv.")
            if len(data.get("tool_calls", [])) >= MAX_CALLS:
                raise HTTPException(429, "Werkzeugbudget erreicht. Bitte den Auftrag eingrenzen.")
            if data.get("data_scope", "selected") == "none" and name != "immo_document":
                raise HTTPException(404, "Fachakten sind für diesen Auftrag nicht freigegeben.")
            if isinstance(args, Investigate):
                result = _investigate(unit, row, data, args)
            elif isinstance(args, Timeline):
                result = _timeline(unit, row, data, args)
            elif isinstance(args, Search | Related):
                result = _listing(unit, row, data, name, args)
            elif isinstance(args, Read):
                source = _permitted(unit, data, args.kind, args.id)
                result = {"ok": True, "items": [source], "sources": [source],
                          "coverage": {"returned": 1, "has_more": False, "next_cursor": None, "truncated": False}}
            elif isinstance(args, Report):
                result = _report(unit, row, data, args)
            else:
                result = _document(unit, row, data, args)
            domain_sources = [source for source in result.get("sources", []) if source["kind"] != "attachment"]
            data["_bundle"] = merge_bundle(data["_bundle"], domain_sources)
            activity = {"sequence": len(data.get("tool_calls", [])) + 1, "id": str(uuid4()), "tool": name,
                        "status": "completed", "summary": TOOLS[name][1].split(";")[0], "at": dbs.stamp(dbs.now()),
                        "sources": assistant.source_cards({"sources": result.get("sources", [])}), "coverage": result.get("coverage", {})}
            if isinstance(args, Investigate):
                activity.update(findings=result["findings"], checks=result["coverage"]["checks"],
                                as_of=result["coverage"]["as_of"], result_hash=result["result_hash"])
            data.setdefault("tool_calls", []).append(activity)
            data["activity"] = data["tool_calls"]
            data.setdefault("_tool_results", []).append({"call_id": activity["id"], "arguments": args.model_dump(mode="json"), "result": result})
            db.put(unit, Run, data, row=row)
            conversation = db.get(unit, Conversation, row.conversation_id, lock=True)
            contents = db.payload(conversation)
            previous = contents.get("_contexts", [])
            known = {(source["kind"], source["id"]) for bundle in previous for source in bundle["sources"]}
            known.update((source["kind"], source["id"]) for source in domain_sources)
            contents["_contexts"] = [{"format": context.FORMAT, "selection": {
                field: sorted(identifier for kind, identifier in known if kind == target)
                for field, target in context.SELECTIONS.items()}, "sources": [{"kind": kind, "id": identifier} for kind, identifier in sorted(known)]}]
            contents["context"] = data["_bundle"]["selection"]
            contents["context_sources"] = assistant.source_cards(data["_bundle"])
            db.put(unit, Conversation, contents, row=conversation)
            return result
    except Exception as exc:
        code = "invalid_arguments" if isinstance(exc, ValidationError) else ({
            403: "source_unavailable", 404: "source_unavailable", 409: "source_or_run_changed", 422: "invalid_arguments", 429: "tool_budget_exceeded"}.get(exc.status_code, "tool_failed")
            if isinstance(exc, HTTPException) else "tool_failed")
        message = {"source_unavailable": "Quelle ist nicht verfügbar oder nicht freigegeben.",
                   "source_or_run_changed": "Auftrag, Quellenstand oder Fortsetzung wurde geändert. Bitte erneut prüfen.",
                   "invalid_arguments": "Werkzeugargumente sind ungültig oder widersprüchlich.",
                   "tool_budget_exceeded": "Werkzeugbudget erreicht; bitte den Auftrag eingrenzen."}.get(code, "Werkzeug konnte nicht abgeschlossen werden.")
        error = {"code": code, "message": message, "retryable": False}
        # Failed attempts are also visible, without storing raw exception text.
        try:
            with db.work(store, actor_id, write=True) as unit:
                row = db.owned_child(unit, Run, run_id, lock=True)
                data = db.payload(row)
                if row.state == "running" and data.get("_lease") == lease and len(data.get("tool_calls", [])) < MAX_CALLS + 1:
                    data.setdefault("tool_calls", []).append({"sequence": len(data.get("tool_calls", [])) + 1,
                        "id": str(uuid4()), "tool": name if name in TOOLS else "unknown", "status": "failed",
                        "summary": message, "at": dbs.stamp(dbs.now()), "sources": [], "coverage": {}, "error": error})
                    data["activity"] = data["tool_calls"]
                    db.put(unit, Run, data, row=row)
        except HTTPException:
            pass
        return {"ok": False, "error": error}


def assert_active(store, actor_id: str, run_id: str, lease: str):
    with db.work(store, actor_id) as unit:
        row = db.owned_child(unit, Run, run_id)
        if row.state != "running" or db.payload(row).get("_lease") != lease:
            raise HTTPException(409, "Auftrag nicht mehr aktiv.")
