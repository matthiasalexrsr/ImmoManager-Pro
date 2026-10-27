"""The utility statement assistant: documents of metering services read into costs and meter readings."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..audit import log_action
from ..auth import get_current_user
from ..dependencies import store
from ..domain.clock import local_today
from ..models import UserRead
from ..permissions import may_write
from ..services import document_share, document_text, meter_documents, meter_documents_ai
from ..storage import NotFoundError

router = APIRouter(prefix="/billing", tags=["Nebenkosten-Assistent"])
READER_LABELS = {"local": "Lokale Regeln", "claude": "Claude", "codex": "ChatGPT"}


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: str | None = Field(default=None, max_length=120)
    billing_period_id: str | None = Field(default=None, max_length=120)
    reader: Literal["local", "claude", "codex"] = "local"
    model: str | None = Field(default=None, max_length=128)


class ImportCost(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, le=10_000_000)
    cost_category: str | None = Field(default=None, max_length=40)
    allocation_key_id: str = Field(min_length=1, max_length=120)
    is_recoverable: bool = True
    consumption_share: float | None = Field(default=None, ge=50, le=70)
    fixed_key_id: str | None = Field(default=None, max_length=120)


class ImportReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meter_id: str = Field(min_length=1, max_length=120)
    reading_date: date
    value: float = Field(ge=0, le=1_000_000_000)


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: str | None = Field(default=None, max_length=120)
    billing_period_id: str | None = Field(default=None, max_length=120)
    costs: list[ImportCost] = Field(default_factory=list, max_length=200)
    readings: list[ImportReading] = Field(default_factory=list, max_length=2000)


def _document(document_id: str):
    try:
        return store.get_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _period(period_id: str | None):
    if not period_id:
        return None
    try:
        return store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _property(document, period, property_id: str | None) -> str:
    chosen = period.property_id if period is not None else (property_id or document.property_id)
    if not chosen:
        raise HTTPException(422, "Bitte die Immobilie wählen, zu der das Dokument gehört.")
    try:
        store.get_property(chosen)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return chosen


@router.get("/guide")
def billing_guide(property_id: str, period_id: str | None = None) -> dict:
    """The utility statement assistant's view of a property and period: situation, hints, steps, check."""
    from ..services import billing_guide as guide_service
    from .billing import _run_billing_period_preflight
    try:
        store.get_property(property_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    period = _period(period_id)
    if period is not None and period.property_id != property_id:
        raise HTTPException(422, "Die Abrechnungsperiode gehört zu einer anderen Immobilie.")
    checks = _run_billing_period_preflight(period.id) if period is not None else None
    return guide_service.guide(store, property_id, period.id if period is not None else None, checks=checks)


@router.get("/meter-documents/readers")
def meter_document_readers(actor: Annotated[UserRead, Depends(get_current_user)]) -> list[dict]:
    """Who can read a document: the local rules always, Claude or ChatGPT once connected in the assistant."""
    from ..services import assistant_providers
    readers = [{"id": "local", "label": READER_LABELS["local"], "available": True, "ai": False}]
    for provider in ("claude", "codex"):
        try:
            status = assistant_providers.connection_status(actor.id, provider)
            connected = bool(status.get("connected")) and status.get("client_available", True) is not False
        except Exception:                    # an unreadable account vault means "not connected", never a failed page
            connected = False
        readers.append({"id": provider, "label": READER_LABELS[provider], "available": connected, "ai": True})
    return readers


@router.post("/meter-documents/{document_id}/analysis")
def analyse_meter_document(document_id: str, payload: AnalysisRequest,
                           actor: Annotated[UserRead, Depends(get_current_user)]) -> dict:
    """A proposal from the document; nothing is stored."""
    document = _document(document_id)
    period = _period(payload.billing_period_id)
    property_id = _property(document, period, payload.property_id)
    file = document_share.current_file(store, document)
    text, source = document_text.extract(file.content, file.filename)
    if payload.reader == "local":
        if not text.strip():
            raise HTTPException(422, "Aus dieser Datei ließ sich kein Text lesen (Scan oder Foto ohne Texterkennung). "
                                     "Mit der KI-Auswertung (Claude oder ChatGPT) lassen sich auch Scans lesen.")
        facts = meter_documents.property_facts(store, property_id)
        known = {key for meter in facts.meters for key in meter_documents.serial_keys(meter.serial_number)}
        extraction = meter_documents.extract_local(text, known)
    else:
        facts = meter_documents.property_facts(store, property_id)
        extraction = meter_documents_ai.extract(actor.id, payload.reader, file, text, facts,
                                                model=payload.model, today=local_today())
    result = meter_documents.proposal(store, document, extraction, property_id=property_id, period=period,
                                      reader=payload.reader)
    result.update(property_id=property_id, billing_period_id=period.id if period is not None else None,
                  text_source=source, reader_label=READER_LABELS[payload.reader])
    return result


@router.post("/meter-documents/{document_id}/apply")
def apply_meter_document(document_id: str, payload: ApplyRequest,
                         actor: Annotated[UserRead, Depends(get_current_user)]) -> dict:
    """Takes over the chosen costs (cost items of the period) and meter readings in one transaction."""
    if not payload.costs and not payload.readings:
        raise HTTPException(422, "Bitte mindestens eine Kostenposition oder einen Zählerstand auswählen.")
    if payload.costs and not may_write(actor.role, "/billing/cost-items"):
        raise HTTPException(403, "Kosten der Abrechnung übernehmen dürfen Eigentümer, Verwaltung und Buchhaltung.")
    if payload.readings and not may_write(actor.role, "/meters"):
        raise HTTPException(403, "Zählerstände übernehmen dürfen Eigentümer, Verwaltung und Technik.")
    document = _document(document_id)
    period = _period(payload.billing_period_id)
    if period is not None and payload.costs:
        from .billing import _assert_period_mutable
        _assert_period_mutable(period)
    property_id = _property(document, period, payload.property_id)
    result = meter_documents.apply(store, document, period=period, property_id=property_id,
                                   costs=[cost.model_dump() for cost in payload.costs],
                                   readings=[reading.model_dump() for reading in payload.readings], actor=actor)
    log_action("IMPORT", "document", document.id, user_id=actor.id, username=actor.username,
               changes={"billing_period_id": period.id if period is not None else None,
                        "cost_items": len(result["cost_items"]), "readings": result["readings_created"]})
    return result
