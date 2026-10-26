"""Policy and fingerprints for added data families; never delete from a timer."""
import hashlib
import json
from datetime import date, timedelta

from fastapi import HTTPException

from ...db import external_portal_models as portal
from ...db.data_transfer_models import ImportBatchORM, ImportFileORM, PortabilityExportORM
from ...db.e_invoice_models import EInvoiceIntakeORM, EInvoiceValidationORM
from ...domain.clock import local_date, local_today
from .. import document_retention, document_versions
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows
from .storage import control, rows

MODELS = {"e_invoice_intake": EInvoiceIntakeORM, "import_batch": ImportBatchORM,
          "portability_export": PortabilityExportORM, "portal_case": portal.PortalCaseORM,
          "portal_identity": portal.PortalIdentityORM}
LABELS = {"document": "Dokument", "e_invoice_intake": "E-Rechnungseingang", "import_batch": "Importquellen",
          "portability_export": "Erstelltes Exportpaket", "portal_case": "Externe Vorgangskommunikation", "portal_identity": "Externes Zugangskonto"}


def _plain(value):
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _state(row):
    return {key: _plain(value) for key, value in db.values(row).items()}


def _year_end(moment, years):
    return date(local_date(moment).year + years, 12, 31)


def inspect_resource(unit, kind, identifier):
    policy = control(unit, kind, identifier)
    if policy and policy.erased_at:
        return {"kind": kind, "id": identifier, "label": LABELS[kind], "title": "Gelöschte Daten",
            "held": policy.held, "restricted": True, "erased_at": policy.erased_at.isoformat(), "erasure_due": False, "revision": policy.revision,
            "source_sha256": policy.source_sha256, "retention_until": None, "can_erase": False, "blockers": ["Löschentscheidung bereits ausgeführt."], "reason": policy.reason}
    blockers, state, until = [], {}, None
    settings = document_retention.years(unit.store)
    if kind == "document":
        row = unit.store.get_document(identifier)
        state = row.model_dump(mode="json")
        retention = document_retention.assess_all(unit.store, [row])[identifier]
        until = date.fromisoformat(retention["until"]) if retention["until"] else None
        if retention["locked"]:
            blockers.append(retention["text"])
        # This addition manages retention holds on original archives. Their
        # existing immutable evidence lifecycle remains authoritative.
        if document_versions.head(unit, identifier):
            blockers.append("Archivierter Originalnachweis: Die unveränderliche Belegakte bleibt erhalten; eine Löschanfrage muss die aufbewahrten Originale ausdrücklich ausweisen.")
        else:
            blockers.append("Das Dokument kann nach Aufhebung aller Sperren in der Dokumentakte mit deren Referenzprüfung gelöscht werden.")
        title = row.title
    elif kind in MODELS:
        row = db.row(unit, MODELS[kind], identifier)
        state = _state(row)
        title = getattr(row, "title", None) or getattr(row, "filename", None) or getattr(row, "source_system", None) or getattr(row, "email", None) or identifier
        if kind == "e_invoice_intake":
            state["validation_runs"] = [_state(item) for item in rows(unit, EInvoiceValidationORM, intake_id=identifier)]
            until = _year_end(row.created_at, settings["document_retention_booking_years"])
            if row.invoice_id:
                blockers.append("Der Eingang ist Originalnachweis einer übernommenen Rechnung und bleibt mit deren Belegakte erhalten.")
            if row.state == "queued":
                blockers.append("Die lokale Belegprüfung ist noch ausstehend.")
        elif kind == "import_batch":
            state["files"] = [_state(item) for item in rows(unit, ImportFileORM, batch_id=identifier)]
            until = _year_end(row.created_at, settings["document_retention_booking_years"]) if row.state == "committed" else local_date(row.created_at) + timedelta(days=30)
        elif kind == "portability_export":
            until = local_date(row.created_at) + timedelta(days=7)
            if row.state == "queued":
                blockers.append("Der Exportauftrag ist noch ausstehend.")
        elif kind == "portal_case":
            case = Rows.of(unit).require("maintenance_cases", row.case_id, "Interne Schadenakte nicht gefunden.")
            messages = rows(unit, portal.PortalMessageORM, case_link_id=identifier)
            state["messages"] = [_state(item) for item in messages]
            state["images"] = [_state(image) for item in messages for image in rows(unit, portal.PortalAttachmentORM, message_id=item.id)]
            state["case_revision"] = case.updated_at.isoformat()
            until = _year_end(max([row.updated_at, *[item.created_at for item in messages]]), settings["document_retention_letters_years"])
            if case.status not in ("completed", "cancelled", "done", "closed"):
                blockers.append("Die zugehörige Schadenbearbeitung ist noch nicht abgeschlossen oder abgebrochen.")
        else:
            grants = rows(unit, portal.PortalGrantORM, identity_id=identifier)
            state["grants"] = [_state(item) for item in grants]
            if row.active or any(item.active for item in grants):
                blockers.append("Das Konto und alle zugehörigen Freigaben müssen vor Löschung deaktiviert sein.")
    else:
        raise HTTPException(422, "Unbekannte Datenart.")
    if until and local_today() <= until:
        blockers.append("Aufbewahrungs- bzw. Bearbeitungsfrist läuft bis " + until.isoformat() + ".")
    if policy and policy.held:
        blockers.append("Dokumentierte Aufbewahrungssperre: " + policy.reason)
    return {"kind": kind, "id": identifier, "label": LABELS[kind], "title": title, "revision": policy.revision if policy else 0,
        "source_sha256": digest(state), "held": bool(policy and policy.held), "restricted": bool(policy and policy.restricted),
        "erased_at": None, "erasure_due": bool(policy and policy.erasure_due), "retention_until": until.isoformat() if until else None, "can_erase": not blockers,
        "blockers": blockers, "reason": policy.reason if policy else ""}


def erase(unit, kind, identifier):
    """Called only after the locked fingerprint, retention and hold checks."""
    if kind == "document":
        raise HTTPException(409, "Dokumentlöschungen verwenden die bestehende Dokumentakte mit ihrer eigenen Belegprüfung.")
    row = db.row(unit, MODELS[kind], identifier, lock=True)
    if kind == "e_invoice_intake":
        for validation in rows(unit, EInvoiceValidationORM, intake_id=identifier):
            db.remove(unit, EInvoiceValidationORM, validation.id)
        db.remove(unit, EInvoiceIntakeORM, identifier)
        return {"removed": "Eingangsoriginal, Extraktion und Validierungsberichte", "retained": "Löschentscheidung mit Quellenhash"}
    if kind == "import_batch":
        for source in rows(unit, ImportFileORM, batch_id=identifier):
            db.remove(unit, ImportFileORM, source.id)
        db.put(unit, ImportBatchORM, {**db.values(row), "state": "erased", "source_system": "Gelöschte Importquellen", "mappings": {}, "preview": {},
            "result": {"erased": True}, "revision": row.revision + 1, "updated_at": db.now()})
        return {"removed": "Importquelldateien, Vorschau und Feldzuordnungen", "retained": "Geschäftsdaten, historische Fachnachweise und Referenz-Prüfsummen"}
    if kind == "portability_export":
        db.put(unit, PortabilityExportORM, {**db.values(row), "state": "erased", "content": None, "manifest": {}, "error": None,
            "revision": row.revision + 1, "updated_at": db.now()})
        return {"removed": "Erstelltes Kundenexportpaket", "retained": "Geschäftsdaten, Auftragsmetadaten und Archivprüfsumme"}
    if kind == "portal_case":
        for message in rows(unit, portal.PortalMessageORM, case_link_id=identifier):
            for image in rows(unit, portal.PortalAttachmentORM, message_id=message.id):
                db.remove(unit, portal.PortalAttachmentORM, image.id)
            db.remove(unit, portal.PortalMessageORM, message.id)
        # Command responses may repeat the external title; remove those copies.
        for command in rows(unit, portal.PortalCommandORM):
            if command.response.get("id") == identifier or identifier in command.operation:
                db.remove(unit, portal.PortalCommandORM, command.id)
        db.put(unit, portal.PortalCaseORM, {**db.values(row), "title": "Gelöschte externe Kommunikation", "active": False,
            "revision": row.revision + 1, "updated_at": db.now()})
        return {"removed": "Externe Nachrichten, Bilder und Antwortkopien", "retained": "Interne Schadenakte, Freigabe- und Löschentscheidungen"}
    for model in (portal.PortalSessionORM,):
        for session in rows(unit, model, identity_id=identifier):
            db.remove(unit, model, session.id)
    for access in rows(unit, portal.PortalGrantORM, identity_id=identifier):
        for invitation in rows(unit, portal.PortalInvitationORM, grant_id=access.id):
            db.remove(unit, portal.PortalInvitationORM, invitation.id)
    grant_ids = {access.id for access in rows(unit, portal.PortalGrantORM, identity_id=identifier)}
    for command in rows(unit, portal.PortalCommandORM):
        payload = json.dumps(command.response, ensure_ascii=False)
        if any(value in payload or value in command.operation for value in (identifier, row.email, *grant_ids)):
            db.remove(unit, portal.PortalCommandORM, command.id)
    db.put(unit, portal.PortalIdentityORM, {**db.values(row), "email": "erased-" + identifier + "@invalid.example", "password_hash": None,
        "active": False, "revision": row.revision + 1, "updated_at": db.now()})
    return {"removed": "E-Mail-Kontofeld, Passwort, Sitzungen, Einladungen und zugehörige Antwortkopien", "retained": "Fachliche Zuordnungen und historische Entscheidungen, getrennte Kommunikation und interne Parteistammdaten"}
