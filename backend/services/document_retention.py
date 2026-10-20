"""How long a document must be kept, and the deletion lock while that period runs.

Every document has a retention class: the one chosen on the document, otherwise the one
its type implies (TYPE_CLASSES). Periods start at the end of the calendar year of the
document (§ 147 Abs. 4 AO) and end on 31 December after the class's years:

* booking record (invoices, receipts, statements, settlements): 8 years, § 147 Abs. 1
  Nr. 4, Abs. 3 AO and § 14b UStG as amended from 1 January 2025;
* books, annual accounts, tax papers: 10 years, § 147 Abs. 1 Nr. 1, Abs. 3 AO;
* business letters and other tax-relevant papers: 6 years, § 147 Abs. 1 Nr. 2, 3, 5 AO;
* contract papers: until the end of the contract plus 3 years (regular limitation,
  §§ 195, 199 BGB; a recommendation, not a statutory period). The end is the linked
  contract's end date, else the document's own "Gültig bis"; without one the period runs;
* permanent (e.g. land register extracts) and none.

The years are installation-wide settings (settings_catalogue.RETENTION_YEARS). While a
period runs, deleting the document is refused; an owner or manager can delete it anyway
with a written reason, which goes to the audit journal. This is a guard against
accidental deletion, not a certified archive.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import SettingRuleORM
from .settings_catalogue import RETENTION_YEARS

CLASSES: dict[str, dict[str, Any]] = {
    "booking_record": {"label": "Buchungsbeleg", "setting": "document_retention_booking_years",
                       "basis": "§ 147 Abs. 1 Nr. 4, Abs. 3 AO, § 14b UStG"},
    "accounts": {"label": "Bücher, Abschlüsse, Steuerunterlagen", "setting": "document_retention_accounts_years",
                 "basis": "§ 147 Abs. 1 Nr. 1, Abs. 3 AO"},
    "business_letter": {"label": "Geschäftsbrief oder sonstige Unterlage", "setting": "document_retention_letters_years",
                        "basis": "§ 147 Abs. 1 Nr. 2, 3, 5, Abs. 3 AO"},
    "contract": {"label": "Vertragsunterlage", "setting": "document_retention_contract_years",
                 "basis": "Verjährung, §§ 195, 199 BGB (Empfehlung)"},
    "permanent": {"label": "Dauerhaft aufbewahren", "setting": None, "basis": "z. B. Eigentumsnachweis"},
    "none": {"label": "Keine Aufbewahrungsfrist", "setting": None, "basis": ""},
}

# Types the program files itself (stable keys) and the types of the document form.
TYPE_CLASSES: dict[str, str] = {
    **dict.fromkeys(("Rechnung", "Handwerkerrechnung", "Nebenkostenabrechnung", "Betriebskostenabrechnung",
                     "invoice", "receipt", "credit_note", "statement", "billing_statement_letter",
                     "deposit_settlement", "teha_original"), "booking_record"),
    "Steuerbescheid": "accounts",
    **dict.fromkeys(("Mahnung", "dunning_letter", "template_letter", "letter", "Brief", "Protokoll",
                     "maintenance_protocol", "housing_confirmation"), "business_letter"),
    **dict.fromkeys(("Mietvertrag", "contract", "Kündigung", "Übergabeprotokoll", "handover_protocol",
                     "service_contract", "Versicherung"), "contract"),
    "Grundbuchauszug": "permanent",
}

OVERRIDE_ROLES = ("eigentuemer", "verwalter")


def _de(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def years(store) -> dict[str, int]:
    """The configured years per setting key (installation-wide rules, else the defaults)."""
    saved: dict[str, Any] = {}
    if hasattr(store, "db"):
        for row in store.db.scalars(select(SettingRuleORM).where(SettingRuleORM.scope == "global",
                                                                 SettingRuleORM.key.in_(list(RETENTION_YEARS)))):
            if "value" in (row.payload or {}):
                saved[row.key] = row.payload["value"]
    else:
        rules = store.__dict__.get("_daily_rules", {})
        for key in RETENTION_YEARS:
            payload = rules.get(("global", key), {}).get("payload", {})
            if "value" in payload:
                saved[key] = payload["value"]
    return {key: int(saved.get(key, default)) for key, default in RETENTION_YEARS.items()}


def class_of(document: Any) -> tuple[str, bool]:
    """(class, chosen on the document)."""
    if document.retention_class:
        return document.retention_class, True
    return TYPE_CLASSES.get(document.document_type or "", "none"), False


def assess(document: Any, contract_end: date | None, configured: dict[str, int], today: date | None = None) -> dict:
    """Retention of one document: class, period end, state and whether deleting is locked.

    state: "none" (no period), "running" (until `until`), "open" (contract papers whose
    contract has no end yet), "permanent", "ended" (period over, may be deleted)."""
    today = today or _today()
    key, chosen = class_of(document)
    meta = CLASSES[key]
    count = configured[meta["setting"]] if meta["setting"] else None
    until: date | None = None
    end: date | None = None
    if key == "none":
        state = "none"
    elif key == "permanent":
        state = "permanent"
    elif key == "contract":
        end = contract_end or document.valid_until
        if end is None:
            state = "open"
        else:
            until = date(end.year + int(count or 0), 12, 31)
            state = "running" if today <= until else "ended"
    else:
        created = document.created_at.date() if isinstance(document.created_at, datetime) else document.created_at
        start = document.document_date or created or today
        until = date(start.year + int(count or 0), 12, 31)
        state = "running" if today <= until else "ended"
    return {"retention_class": key, "chosen": chosen, "label": meta["label"], "basis": meta["basis"], "years": count,
            "until": until.isoformat() if until else None, "contract_end": end.isoformat() if end else None,
            "state": state, "locked": state in ("running", "open", "permanent"), "text": describe(key, state, until, count)}


def describe(key: str, state: str, until: date | None, count: int | None) -> str:
    label = CLASSES[key]["label"]
    if state == "none":
        return "Keine Aufbewahrungsfrist."
    if state == "permanent":
        return "Dauerhaft aufzubewahren."
    if state == "open":
        return f"{label}: aufzubewahren bis {count} Jahre nach Vertragsende; der Vertrag hat noch kein Ende."
    assert until is not None
    if state == "ended":
        return f"{label}: Aufbewahrungsfrist am {_de(until)} abgelaufen; das Dokument darf gelöscht werden."
    return f"{label}: aufzubewahren bis {_de(until)}."


def _contract_ends(store, documents: list[Any]) -> dict[str, date | None]:
    wanted = {document.contract_id for document in documents if document.contract_id}
    if not wanted:
        return {}
    return {contract.id: contract.end_date for contract in store.list_contracts() if contract.id in wanted}


def assess_all(store, documents: list[Any] | None = None, today: date | None = None) -> dict[str, dict]:
    """Retention of the given (default: all visible) documents, by id."""
    documents = store.list_documents() if documents is None else documents
    configured = years(store)
    ends = _contract_ends(store, documents)
    return {document.id: assess(document, ends.get(document.contract_id) if document.contract_id else None,
                                configured, today) for document in documents}


def rules(store) -> dict:
    configured = years(store)
    return {"classes": [{"key": key, "label": meta["label"], "basis": meta["basis"],
                         "years": configured[meta["setting"]] if meta["setting"] else None}
                        for key, meta in CLASSES.items()],
            "type_classes": TYPE_CLASSES}


def ensure_deletable(store, document_id: str, *, actor: dict | None = None, override_reason: str | None = None) -> dict:
    """Refuse deleting while the retention period runs (409), unless an owner or manager gives
    a reason; returns the assessment (with `override` when the lock was overridden)."""
    document = store.get_document(document_id)
    result = assess_all(store, [document])[document.id]
    if not result["locked"]:
        return result
    reason = (override_reason or "").strip()
    if not reason:
        basis = f" Grundlage: {result['basis']}." if result["basis"] else ""
        raise HTTPException(409, f"Löschen gesperrt: {result['text']}{basis} Wer das Dokument trotzdem löschen muss "
                                 "(z. B. ein versehentlich abgelegtes Duplikat), gibt dafür als Eigentümer oder "
                                 "Verwaltung einen Grund an, oder ändert die Aufbewahrung im Dokument.")
    if actor is None or actor.get("role") not in OVERRIDE_ROLES:
        raise HTTPException(403, "Nur Eigentümer oder Verwaltung dürfen ein Dokument trotz Aufbewahrungsfrist löschen.")
    if not 10 <= len(reason) <= 500:
        raise HTTPException(422, "Bitte den Grund in 10 bis 500 Zeichen angeben.")
    return {**result, "override": reason}


def record_override(store, actor: dict, document: Any, result: dict) -> None:
    """Audit journal entry for a deletion despite a running retention period. On SQL it is
    written in the transaction that deletes the document, so both commit or neither does."""
    from .. import audit as audit_service
    from ..models import AuditLogEntry
    now = datetime.now(timezone.utc)
    changes = {"reason": result["override"], "title": document.title, "document_type": document.document_type,
               "retention": {key: result[key] for key in ("retention_class", "chosen", "until", "state", "text")}}
    entry = AuditLogEntry(id=hashlib.sha256(f"{actor.get('id')}:retention:{document.id}:{now.isoformat()}".encode()).hexdigest(),
                          user_id=str(actor.get("id")), username=actor.get("username"), action="document_retention_override",
                          entity_type="document", entity_id=document.id,
                          changes=json.dumps(changes, ensure_ascii=False, default=str), timestamp=now)
    if hasattr(store, "db"):
        from ..db.orm_models import AuditLogORM
        store.db.add(AuditLogORM(**entry.model_dump()))
        store.db.flush()
    else:
        audit_service._audit_store.add(entry)
