"""Transactional receipt commands built on the existing invoice/archive services."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import PurePath
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import defer

from ...db.document_version_models import DocumentVersionORM
from ...db.e_invoice_models import EInvoiceIntakeORM as Intake
from ...db.e_invoice_models import EInvoiceValidationORM as Validation
from ...e_invoice_models import AcceptIntake, RetryValidation
from ...invoice_review_models import InvoiceDraft, ReceiptRequest, VatLineInput
from ...models import Document
from ...storage import NotFoundError
from .. import document_versions as archive
from .. import invoice_review
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows, stamp
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor
from . import parser, validator
from .extraction import read_isolated

AREA = "/e-invoice-intakes"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@contextmanager
def work(store, actor_id, *, write=False, key=None):
    with archive.work(store, actor_id, write_areas=(AREA,) if write else ()) as unit:
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            if write and key and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                token = int.from_bytes(hashlib.sha256(("e-invoice:" + actor_id + ":" + key).encode()).digest()[:8], "big", signed=True)
                unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": token})
            yield unit


def get(unit, identifier, *, lock=False):
    row = db.row(unit, Intake, identifier, lock=lock)
    # Memory has no ORM scope hook. Also makes direct/background service calls
    # enforce the same current property grant as the HTTP middleware.
    Rows.of(unit).require("properties", row.property_id, "Rechnungseingang nicht gefunden")
    return row


def view(row) -> dict:
    excluded = {"original", "xml", "request_sha256", "accept_sha256", "accept_key", "idempotency_key"}
    values = {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.c if column.key not in excluded}
    return {key: value.isoformat() + "Z" if key.endswith("_at") else value for key, value in values.items()}


def _filename(name: str, content: bytes) -> str:
    name = PurePath(name.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:180]
    return name or ("Rechnung.pdf" if content.startswith(b"%PDF-") else "Rechnung.xml")


def create(store, actor_id: str, property_id: str, content: bytes, filename: str, key: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
        raise HTTPException(422, "Für den Upload ist eine gültige Wiederholungskennung erforderlich.")
    if not content or len(content) > parser.MAX_FILE:
        raise HTTPException(413, "Der Rechnungsbeleg ist leer oder größer als 25 MiB.")
    checksum = hashlib.sha256(content).hexdigest()
    name = _filename(filename, content)
    request_hash = digest({"sha256": checksum, "property_id": property_id, "filename": name})
    with work(store, actor_id, write=True, key=key) as unit:
        Rows.of(unit).require("properties", property_id, "Immobilie nicht gefunden")
        existing = db.find_one(unit, Intake, created_by=actor_id, idempotency_key=key, lock=True)
        if existing is not None:
            get(unit, existing.id)
            if existing.request_sha256 != request_hash:
                raise HTTPException(409, "Diese Wiederholungskennung gehört zu einem anderen Upload.")
            return view(existing)
        moment = db.now()
        row = db.put(unit, Intake, dict(id=str(uuid4()), property_id=property_id, created_by=actor_id,
            validation_actor_id=actor_id,
            idempotency_key=key, request_sha256=request_hash, original_sha256=checksum,
            filename=name, original=content, xml=None, container="pdf" if content.startswith(b"%PDF-") else "xml",
            format=None, reading={}, state="queued", blockers=[], revision=1, validation_number=0,
            invoice_id=None, document_id=None, accept_key=None, accept_sha256=None, created_at=moment, updated_at=moment))
        result = view(row)
    # The committed queued receipt is the outbox. A process crash before wakeup
    # is recovered by the installation's durable scheduler.
    from ..jobs.scheduler import request_wakeup
    request_wakeup()
    return result


def listing(store, actor_id, *, skip=0, limit=50) -> dict:
    with work(store, actor_id) as unit:
        if unit.db is not None:
            from sqlalchemy import func
            total = unit.db.scalar(select(func.count()).select_from(Intake))
            rows = list(unit.db.scalars(select(Intake).options(defer(Intake.original), defer(Intake.xml))
                                       .order_by(Intake.created_at.desc(), Intake.id).offset(skip).limit(limit)))
        else:
            visible = []
            for row in db.memory(unit, Intake).values():
                try:
                    get(unit, row.id)
                    visible.append(row)
                except (NotFoundError, HTTPException) as error:
                    if isinstance(error, HTTPException) and error.status_code != 404:
                        raise
            total = len(visible)
            rows = sorted(visible, key=lambda r: (r.created_at, r.id), reverse=True)[skip:skip + limit]
        return {"items": [view(row) for row in rows], "total": total}


def validations(unit, identifier):
    if unit.db is not None:
        return list(unit.db.scalars(select(Validation).where(Validation.intake_id == identifier).order_by(Validation.number)))
    return sorted((row for row in db.memory(unit, Validation).values() if row.intake_id == identifier), key=lambda row: row.number)


def detail(store, actor_id, identifier):
    with work(store, actor_id) as unit:
        result = view(get(unit, identifier))
        result["validations"] = [{k: v.isoformat() + "Z" if k == "created_at" else v
                                  for k, v in db.values(row).items() if k != "report"}
                                 for row in validations(unit, identifier)]
        return result


def download(store, actor_id, identifier, kind, number=None):
    with work(store, actor_id) as unit:
        row = get(unit, identifier)
        if kind == "original":
            return row.original, row.filename, "application/pdf" if row.container == "pdf" else "application/xml"
        if kind == "xml" and row.xml is not None:
            return row.xml, "Rechnungsdaten.xml", "application/xml"
        if kind == "report":
            report = next((v for v in validations(unit, identifier) if v.number == number), None)
            if report is not None and report.report:
                return report.report.encode("utf-8"), f"Pruefbericht-{number}.xml", "application/xml"
        raise HTTPException(404, "Die angeforderte Datei ist nicht vorhanden.")


def retry(store, actor_id, identifier, command: RetryValidation):
    with work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = get(unit, identifier, lock=True)
        request_hash = digest(command.model_dump(mode="json"))
        if row.accept_key == command.idempotency_key:
            if row.accept_sha256 != request_hash:
                raise HTTPException(409, "Die Wiederholungskennung gehört zu einer anderen Aktion.")
            return view(row)
        db.revision(row, command.expected_revision)
        if row.state in {"queued", "accepted"}:
            raise HTTPException(409, "Dieser Eingang kann derzeit nicht erneut geprüft werden.")
        row = db.put(unit, Intake, {**db.values(row), "state": "queued", "revision": row.revision + 1,
                                   "validation_actor_id": actor_id,
                                   "accept_key": command.idempotency_key, "accept_sha256": request_hash, "updated_at": db.now()})
        result = view(row)
    from ..jobs.scheduler import request_wakeup
    request_wakeup()
    return result


def inspect(content: bytes) -> dict:
    try:
        container, xml, reading = read_isolated(content)
        result = validator.validate(content, container, reading["format"])
        return {"xml": xml, "reading": reading, "format": reading["format"],
                "blockers": reading["blockers"], "validation": result}
    except parser.Unreadable as error:
        return {"xml": None, "reading": {}, "format": None, "blockers": [str(error)],
                "validation": {"engine": "safe-parser", "engine_version": "1", "bundle_sha256": "",
                               "state": "invalid", "messages": [{"severity": "error", "text": str(error)}], "report": ""}}
    except Exception as error:
        message = str(error) if isinstance(error, validator.ValidatorUnavailable) else "Die lokale Belegauswertung wurde technisch unterbrochen."
        return {"xml": None, "reading": {}, "format": None, "blockers": [message],
                "validation": {"engine": "safe-parser", "engine_version": "1", "bundle_sha256": "",
                               "state": "technical_error", "messages": [{"severity": "technical_error", "text": message}], "report": ""}}


def apply_validation(unit, identifier, revision, result):
    row = get(unit, identifier, lock=True)
    if row.revision != revision or row.state != "queued":
        return False
    run = result["validation"]
    number = row.validation_number + 1
    db.put(unit, Validation, {"id": str(uuid4()), "intake_id": identifier, "number": number, **run,
        "original_sha256": row.original_sha256, "report_sha256": hashlib.sha256(run["report"].encode()).hexdigest(), "created_at": db.now()})
    db.put(unit, Intake, {**db.values(row), **{key: result[key] for key in ("xml", "reading", "format", "blockers")},
                         "state": run["state"], "validation_number": number, "revision": row.revision + 1, "updated_at": db.now()})
    return True


def _archive_original(unit, row, unit_id):
    identifier, version_id = str(uuid4()), str(uuid4())
    extension = "pdf" if row.container == "pdf" else "xml"
    document = Document(id=identifier, property_id=row.property_id, unit_id=unit_id,
        title=f"E-Rechnung {row.reading['number']}", document_type="invoice",
        document_date=date.fromisoformat(row.reading["issued_on"]),
        file_url=f"/uploads/e-invoices/{identifier}.{extension}",
        description="Unverändertes Original des strukturierten Rechnungseingangs", created_at=stamp("documents"))
    Rows.of(unit).add("documents", document)
    _, binding = archive.bind_document(unit, identifier, lock=True)
    manifest = DocumentVersionORM(id=version_id, document_id=identifier, **binding, number=1,
        predecessor_id=None, restored_from_id=None, actor_id=unit.actor_id, idempotency_key="e-invoice-" + row.id,
        request_sha256=row.request_sha256, operation="archive_original", comment="Original des E-Rechnungseingangs",
        filename=row.filename, media_type="application/pdf" if extension == "pdf" else "application/xml",
        sha256=row.original_sha256, size_bytes=len(row.original), metadata_snapshot=document.model_dump(mode="json"), created_at=archive.now())
    archive.validate_manifest(manifest)
    archive.persist_version_bytes(unit, manifest, (row.original[i:i + archive.CHUNK_BYTES]
                                                  for i in range(0, len(row.original), archive.CHUNK_BYTES)))
    return identifier


def accept(store, actor_id, identifier, command: AcceptIntake):
    with work(store, actor_id, write=True, key=command.idempotency_key) as unit:
        row = get(unit, identifier, lock=True)
        request_hash = digest(command.model_dump(mode="json"))
        if row.accept_key == command.idempotency_key and row.accept_sha256 == request_hash and row.state == "accepted":
            return {"intake": view(row), "invoice_id": row.invoice_id}
        if row.state == "accepted":
            raise HTTPException(409, "Dieser Eingang ist bereits übernommen.")
        db.revision(row, command.expected_revision)
        if row.state not in {"valid", "warning"} or row.blockers:
            raise HTTPException(409, "Der Beleg ist noch nicht übernahmefähig. Bitte Prüfbericht und Sperrgründe beachten.")
        if row.state == "warning" and (not command.acknowledge_warnings or len((command.warning_reason or "").strip()) < 10):
            raise HTTPException(422, "Warnungen müssen mit einer nachvollziehbaren Begründung bestätigt werden.")
        reading = row.reading
        prop = Rows.of(unit).require("properties", row.property_id, "Immobilie nicht gefunden")
        portfolio = unit.store.get_portfolio(prop.portfolio_id)
        if portfolio.currency != reading["currency"]:
            raise HTTPException(409, "Die Belegwährung passt nicht zum Zielbestand. Eine Umrechnung erfolgt nicht automatisch.")
        if command.unit_id:
            location = Rows.of(unit).require("units", command.unit_id, "Einheit nicht gefunden")
            if location.property_id != row.property_id:
                raise HTTPException(409, "Die Einheit gehört nicht zur zugeordneten Immobilie.")
        if reading["kind"] == "credit_note" and command.credit_for_invoice_id:
            original = Rows.of(unit).require("invoices", command.credit_for_invoice_id, "Ursprungsrechnung nicht gefunden")
            if original.property_id != row.property_id or (reading["original_reference"] and
                    original.invoice_number != reading["original_reference"]):
                raise HTTPException(409, "Der gewählte Ursprungsbeleg passt nicht zur Gutschrift.")
        document_id = _archive_original(unit, row, command.unit_id)
        receipt = ReceiptRequest(invoice=InvoiceDraft(property_id=row.property_id, supplier=reading["supplier"],
            invoice_number=reading["number"], invoice_date=reading["issued_on"], due_date=reading["due_on"],
            performance_start=reading["performance_start"], performance_end=reading["performance_end"],
            net_amount=reading["net"], vat_amount=reading["vat"], gross_amount=reading["due"],
            vat_rate=float(reading["taxes"][0]["rate"]), payment_terms=reading["payment_terms"] or None,
            payment_reference=reading["payment_reference"] or None), document_id=document_id,
            property_id=row.property_id, unit_id=command.unit_id, kind=reading["kind"],
            credit_for_invoice_id=command.credit_for_invoice_id,
            vat_lines=[VatLineInput(**tax) for tax in reading["taxes"]],
            rounding_amount=reading["rounding"],
            accept_duplicate=command.accept_duplicate, duplicate_reason=command.duplicate_reason,
            cost_category=command.cost_category, recoverable=command.recoverable, note=command.warning_reason)
        result = invoice_review.start_review(unit.store, None, receipt, actor_id, _unit=unit)
        from ..payment_security import import_suggestion
        import_suggestion(unit, result["invoice"]["id"], reading)
        row = db.put(unit, Intake, {**db.values(row), "state": "accepted", "invoice_id": result["invoice"]["id"],
            "document_id": document_id, "revision": row.revision + 1, "accept_key": command.idempotency_key,
            "accept_sha256": request_hash, "updated_at": db.now()})
        return {"intake": view(row), "invoice_id": row.invoice_id}


def invoice_context(store, invoice_id):
    sql = getattr(store, "db", None)
    unit = archive.Unit(store, sql, {}, None if sql is not None else archive.memory_archive(store))
    row = db.find_one(unit, Intake, invoice_id=invoice_id)
    if row is None:
        return None
    get(unit, row.id)
    return {"id": row.id, "format": row.format, "original_sha256": row.original_sha256,
            "href": "/invoice-review?intake=" + row.id}
