"""Explicit, freshly authorized assistant sources and deterministic local analysis.

Document text and descriptions are evidence, never instructions. This module has
no model/provider dependency and does not write any domain or assistant records.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..finance_models import ReportDefinition
from . import business_documents, document_versions, finance_reports, workspace_contexts
from .portfolio_scope import scope_context, scope_from_user

SourceKind = Literal["property", "unit", "tenant", "contact", "document"]
FORMAT = "immomanager-assistant-context/1"
DOCUMENT_TEXT_CHARS = 64_000
SELECTIONS: dict[str, SourceKind] = {
    "property_ids": "property", "unit_ids": "unit", "tenant_ids": "tenant",
    "contact_ids": "contact", "document_ids": "document",
}
# Explicit disclosure allowlist. In particular no banking data, credentials,
# historical AI output, upload URLs or unselected related record contents.
FIELDS = {
    "property": {"name", "property_type", "status", "year_built", "living_area_sqm", "usable_area_sqm",
                 "address_line", "postal_code", "city", "country"},
    "unit": {"property_id", "label", "unit_type", "status", "area_sqm", "rooms", "floor",
             "cold_rent", "service_charge_advance", "heating_advance", "features", "person_count"},
    "tenant": {"full_name", "email", "phone", "address_line", "postal_code", "city", "country"},
    "contact": {"first_name", "last_name", "company_name", "email", "phone", "address_line",
                "postal_code", "city", "country", "notes"},
    "document": {"property_id", "unit_id", "contract_id", "tenant_id", "title", "document_type",
                 "document_date", "tags", "description"},
}


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_ids: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)
    tenant_ids: list[str] = Field(default_factory=list)
    contact_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)

    @field_validator("property_ids", "unit_ids", "tenant_ids", "contact_ids", "document_ids")
    @classmethod
    def identifiers(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 120 or value != value.strip() for value in values):
            raise ValueError("Ungültige Kontext-ID")
        return sorted(set(values))


def content_hash(value: Any) -> str:
    raw = json.dumps(jsonable_encoder(value), sort_keys=True, ensure_ascii=False,
                     allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source(store, kind: str, identifier: str, actor_id: str) -> dict:
    if kind not in FIELDS:
        raise HTTPException(422, "Diese Quellenart ist nicht für den Assistenten freigegeben.")
    user = workspace_contexts.actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        resolved = workspace_contexts.resolve_context(store, kind, identifier, actor_id)
        values = jsonable_encoder({key: value for key, value in resolved["values"].items() if key in FIELDS[kind]})
        source = {"kind": kind, "id": identifier, "revision": resolved["revision"],
                  "title": resolved["title"], "href": resolved["href"], "values": values,
                  "content_role": "untrusted_evidence"}
        if kind == "document":
            # Includes mutable upload bytes or the verified immutable original.
            source["file_sha256"] = business_documents.document_hash(store, identifier, actor_id)
    source["sha256"] = content_hash(source)
    return source


def build_context(store, selection: ContextSelection | dict, actor_id: str) -> dict:
    selected = ContextSelection.model_validate(selection)
    user = workspace_contexts.actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        sources = [_source(store, kind, identifier, actor_id)
                   for field, kind in SELECTIONS.items() for identifier in getattr(selected, field)]
    bundle = {"format": FORMAT, "selection": selected.model_dump(), "sources": sources,
              "warnings": [], "automatic_related_records": False}
    bundle["sha256"] = content_hash(bundle)
    return bundle


def assert_context_access(store, bundle: dict, actor_id: str) -> None:
    """Old replies stay readable after ordinary edits, never after lost access."""
    workspace_contexts.actor(actor_id, store)
    selected = ContextSelection.model_validate(bundle["selection"])
    expected = {(kind, identifier) for field, kind in SELECTIONS.items()
                for identifier in getattr(selected, field)}
    actual = {(source["kind"], source["id"]) for source in bundle["sources"]}
    if expected != actual or bundle.get("format") != FORMAT:
        raise HTTPException(409, "Der gespeicherte Kontext ist unvollständig. Bitte neu auswählen.")
    for kind, identifier in sorted(expected):
        workspace_contexts.resolve_context(store, kind, identifier, actor_id)


def revalidate_context(store, bundle: dict, actor_id: str) -> dict:
    assert_context_access(store, bundle, actor_id)
    current = build_context(store, bundle["selection"], actor_id)
    supplied = {key: value for key, value in bundle.items() if key != "sha256"}
    if content_hash(supplied) != bundle.get("sha256") or current["sha256"] != bundle["sha256"]:
        raise HTTPException(409, {"code": "assistant_context_changed",
                                  "message": "Eine Kontextquelle wurde geändert. Bitte neu prüfen."})
    return current


def _document_analysis(store, source: dict, actor_id: str) -> dict:
    """Read the verified original when present, otherwise the authorized upload."""
    user = workspace_contexts.actor(actor_id, store)
    unit = document_versions.Unit(store, getattr(store, "db", None), user,
                                  None if hasattr(store, "db") else document_versions.memory_archive(store))
    with scope_context(scope_from_user(user)):
        resolved = workspace_contexts.resolve_context(store, "document", source["id"], actor_id)
        original = document_versions.head(unit, source["id"])
        if original is not None:
            _, binding = document_versions.bind_document(unit, source["id"])
            original = document_versions.authorized_version(unit, source["id"], original.id, binding)
            content = document_versions.original_bytes(unit, original)
            filename = original.filename
        else:
            filename = resolved["values"]["file_url"]
            content = business_documents._file(filename)
        if hashlib.sha256(content).hexdigest() != source["file_sha256"]:
            raise HTTPException(409, "Die Dokumentdatei wurde geändert. Bitte neu prüfen.")
        # Extract once; use the same existing regex engine as document intake.
        from .ai.document_ai import analyze_document
        from .ocr_service import extract_text_from_bytes
        extension = filename.rsplit(".", 1)[-1].lower()
        intake = None
        if extension in {"docx", "txt", "csv"}:
            from .assistant import inspect_attachment
            intake = inspect_attachment(content, filename)
            text = intake["text"]
        else:
            text = extract_text_from_bytes(content, extension)
        if not text:
            raise ValueError("Kein Text extrahierbar")
        analyzed = analyze_document(text, use_ai=False)
        truncated = len(text) > DOCUMENT_TEXT_CHARS or bool(intake and intake["text_truncated"])
        extracted = {"document_type": analyzed.document_type, "summary": analyzed.summary,
                     "entities": analyzed.entities, "invoice_number": analyzed.invoice_number,
                     "invoice_date": analyzed.invoice_date, "total_amount": analyzed.total_amount,
                     "supplier": analyzed.supplier, "cost_category": analyzed.cost_category,
                     "ai_model": None, "origin": {"method": "regex", "model": None},
                     "confidence": {"document_type": None, "other_fields": None},
                     "text": text[:DOCUMENT_TEXT_CHARS], "text_truncated": truncated,
                     "omissions": list(intake["omissions"]) if intake else ["Dokumenttext auf 64.000 Zeichen begrenzt; weitere Inhalte wurden nicht an das Modell übergeben."] if truncated else [],
                     "confirmation": {"required": True, "confirmed": False}, "financial_writes": False}
    # No upload locator is disclosed to the model; the authoritative source link
    # is the locally generated document route in the source card.
    extracted["source"] = {"kind": "document", "id": source["id"], "revision": source["revision"],
                           "sha256": source["sha256"], "file_sha256": source["file_sha256"],
                           "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "text_sha256_scope": "selected_excerpt" if intake and intake["text_truncated"] else "full_extracted_text"}
    return extracted


def local_analysis(store, selection: ContextSelection | dict, actor_id: str, *,
                   report: ReportDefinition | dict | None = None, extract_documents: bool = False) -> dict:
    bundle = build_context(store, selection, actor_id)
    findings: list[dict] = []
    extracted = []
    for source in bundle["sources"]:
        values = source["values"]
        evidence = {key: source[key] for key in ("kind", "id", "revision", "sha256", "href")}
        if source["kind"] == "document":
            if not any(values.get(key) for key in ("property_id", "unit_id", "contract_id", "tenant_id")):
                findings.append({"code": "document_unassigned", "severity": "review",
                                 "message": "Das Dokument hat keinen Immobilien-, Einheiten-, Vertrags- oder Parteienbezug.",
                                 "evidence": [evidence]})
            if extract_documents:
                try:
                    extracted.append(_document_analysis(store, source, actor_id))
                except ValueError:
                    findings.append({"code": "document_text_unavailable", "severity": "review",
                                     "message": "Aus dieser Datei konnte lokal kein Text extrahiert werden.",
                                     "evidence": [evidence]})
        if source["kind"] == "unit" and values.get("area_sqm") is None:
            findings.append({"code": "unit_area_missing", "severity": "review",
                             "message": "Für diese Einheit ist keine Fläche erfasst.", "evidence": [evidence]})
    calculated = None
    if report is not None:
        definition = ReportDefinition.model_validate(report)
        selected = ContextSelection.model_validate(selection)
        # Financial aggregation needs its own explicit selected dimension. A
        # selected party/document must not silently authorize the whole estate.
        if definition.unit_id:
            if definition.unit_id not in selected.unit_ids:
                raise HTTPException(422, "Die Berichtseinheit muss ausdrücklich im Kontext gewählt sein.")
        elif not definition.property_id or definition.property_id not in selected.property_ids:
            raise HTTPException(422, "Die Berichtsimmobilie muss ausdrücklich im Kontext gewählt sein.")
        user = workspace_contexts.actor(actor_id, store)
        with scope_context(scope_from_user(user)):
            calculated = finance_reports.compute(store, definition)
    # Fail closed if rights, metadata or document bytes changed while computing.
    revalidate_context(store, bundle, actor_id)
    return {"format": "immomanager-assistant-local-analysis/1", "mode": "local", "context": bundle,
            "findings": findings, "documents": extracted, "finance": calculated,
            "financial_engine": "finance_reports.compute" if calculated is not None else None,
            "model_used": False, "domain_writes": False}
