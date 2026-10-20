"""Reviewed billing correspondence, archived atomically beside its issued statement.

The existing issued PDF stays unchanged. A letter is a separate document whose
cover and annex come from one reviewed snapshot, never from client-side amounts.
"""
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import insert, select, text

from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import (
    BillingPeriodORM,
    ContractORM,
    DocumentORM,
    PropertyORM,
    TenantORM,
    UnitORM,
    UtilityStatementORM,
)
from ..models import Document, DocumentCreate
from ..permissions import may_write
from ..storage import NotFoundError
from . import document_versions as archive
from . import letterhead as letterheads
from .billing_letter_render import render_pdf
from .billing_letter_validation import (
    DOC_TYPE,
    LETTERHEAD_FORMAT_VERSION,
    SCHEMA_VERSION,
    VIRTUAL_PREFIX,
    digest,
    document_id_for,
    request_hash,
    validate_billing_letter_snapshot,
)
from .final_statements import final_version_problems
from .portfolio_scope import scope_context, scope_from_user
from .settings_catalogue import effective
from .workspace_contexts import bound_actor, resolve_context


def write_areas(statement_id):
    return (f"/billing/statements/{statement_id}/letter-publish", archive.DOCUMENTS_AREA)


@contextmanager
def work(store, actor_id, statement_id=None, *, write=False, command_key=None):
    with archive.work(store, actor_id, write_areas=write_areas(statement_id) if write else ()) as unit:
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            try:
                if write and command_key is not None and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                    # A shared account fence permits parallel requests. Lock the
                    # operation's actor/key BEFORE period and parent locks: the
                    # same key can otherwise race across unrelated periods.
                    key = hashlib.sha256(("immo:billing-letter:" + actor_id + ":" + command_key).encode()).digest()
                    unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                                    {"key": int.from_bytes(key[:8], "big", signed=True)})
                yield unit
            except NotFoundError:
                raise HTTPException(404, "Abrechnung oder zugehörige Akte nicht gefunden.") from None


def _pick(row, keys):
    return row.model_dump(mode="json", include=set(keys))


def _address(row):
    line = (row.address_line or "").strip()
    city = " ".join(value.strip() for value in (row.postal_code, row.city) if value and value.strip())
    # A default country alone is not an address suggestion.
    if not line and not city:
        return ""
    return "\n".join(value for value in (line, city, (row.country or "").strip()) if value)


def _source(unit, statement_id, *, lock=False):
    resolve_context(unit.store, "utility_statement", statement_id, unit.actor_id)
    statement = unit.store.get_utility_statement(statement_id)
    period = unit.store.get_billing_period(statement.billing_period_id)
    contract = unit.store.get_contract(statement.contract_id) if statement.contract_id else None
    if lock and unit.db is not None:
        # Period writers already serialize on this row. Parent locks then follow
        # the document archive's order, and their membership is checked again.
        before = (statement.billing_period_id, statement.unit_id, statement.contract_id,
                  contract.tenant_id if contract else None, period.property_id)
        models: list[tuple[Any, str | None]] = [(BillingPeriodORM, period.id), (TenantORM, contract.tenant_id if contract else None),
                  (PropertyORM, period.property_id), (UnitORM, statement.unit_id),
                  (ContractORM, statement.contract_id), (UtilityStatementORM, statement.id)]
        for model, identifier in models:
            if identifier and unit.db.scalar(select(model.id).where(model.id == identifier).with_for_update()) is None:
                raise HTTPException(404, "Die Abrechnungszuordnung ist nicht mehr vorhanden.")
        unit.db.expire_all()
        statement = unit.store.get_utility_statement(statement_id)
        period = unit.store.get_billing_period(statement.billing_period_id)
        contract = unit.store.get_contract(statement.contract_id) if statement.contract_id else None
        after = (statement.billing_period_id, statement.unit_id, statement.contract_id,
                 contract.tenant_id if contract else None, period.property_id)
        if before != after:
            raise HTTPException(409, "Die Abrechnungszuordnung wurde gleichzeitig geändert. Bitte erneut laden.")
        resolve_context(unit.store, "utility_statement", statement_id, unit.actor_id)
    prop = unit.store.get_property(period.property_id)
    location = unit.store.get_unit(statement.unit_id)
    tenant = unit.store.get_tenant(contract.tenant_id) if contract else None
    portfolio = unit.store.get_portfolio(prop.portfolio_id)
    if location.property_id != prop.id or (contract and (
            contract.property_id != prop.id or contract.unit_id != location.id)):
        raise HTTPException(409, "Abrechnung, Immobilie, Einheit und Vertrag passen nicht zusammen.")
    from ..routers.billing import _statement_document
    document = _statement_document(statement, target=unit.store)
    source = {
        "statement": _pick(statement, ("id", "billing_period_id", "unit_id", "contract_id", "party", "status",
            "revision", "total_cost", "advance_paid", "balance", "usage_start", "usage_end", "usage_days",
            "line_items", "advance_sections", "snapshot_hash", "final_document", "updated_at")),
        "period": _pick(period, ("id", "property_id", "label", "start_date", "end_date", "status", "revision",
                                  "corrects_period_id", "updated_at")),
        "property": _pick(prop, ("id", "portfolio_id", "name", "address_line", "postal_code", "city", "country", "updated_at")),
        "unit": _pick(location, ("id", "property_id", "label", "updated_at")),
        "contract": _pick(contract, ("id", "property_id", "unit_id", "tenant_id", "contract_number", "updated_at")) if contract else None,
        "tenant": _pick(tenant, ("id", "full_name", "address_line", "postal_code", "city", "country", "updated_at")) if tenant else None,
        "portfolio": _pick(portfolio, ("id", "name", "owner_name", "updated_at")),
        "document": document,
        "settings": {key: effective(unit, key, prop.id)[0] for key in
                     ("document_sender", "document_address", "document_signature")},
        "letterhead": letterheads.source(unit, prop.id, fallback_sender=portfolio.owner_name or portfolio.name),
    }
    return source, statement, period, prop, tenant, portfolio


def _publication_problem(unit, statement, period):
    if statement.party != "tenant" or not statement.contract_id:
        return "Leerstandsanteile sind keine an Mieter auszustellenden Abrechnungen."
    if period.status not in {"finalized", "delivered", "disputed"}:
        return "Ein Schreiben kann erst zur ausgestellten, noch nicht ersetzten Abrechnungsfassung archiviert werden."
    if not statement.snapshot_hash or not statement.final_document:
        return "Für diese ältere Abrechnung fehlt der eingefrorene Dokumentstand. Bitte zuerst eine geprüfte Korrekturfassung erstellen."
    statements = [row for row in unit.store.list_utility_statements() if row.billing_period_id == period.id]
    if final_version_problems(period, statements):
        return "Die gespeicherte Abrechnung besteht die Prüfung der finalisierten Fassung nicht."
    return None


def _public(row):
    proof = validate_billing_letter_snapshot(row, row.metadata_snapshot)
    return {"document_id": row.document_id, "version_id": row.id, "review_hash": proof["review_hash"],
            "pdf_sha256": row.sha256, "file_url": row.metadata_snapshot["file_url"],
            "download_url": "/files/download?key=" + quote(VIRTUAL_PREFIX + row.document_id + ".pdf", safe=""),
            "statement_id": proof["review"]["source"]["statement"]["id"],
            "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()}


def _verified(unit, document):
    if document.document_type != DOC_TYPE:
        raise HTTPException(404, "Abrechnungsschreiben nicht gefunden.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Das archivierte Abrechnungsschreiben ist unvollständig.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    return archive.original_bytes(unit, row), row


def _originals(unit, statement_id):
    if unit.db is not None:
        rows = list(unit.db.scalars(select(DocumentVersionORM).where(
            DocumentVersionORM.metadata_snapshot["document_type"].as_string() == DOC_TYPE,
            DocumentVersionORM.metadata_snapshot[DOC_TYPE]["review"]["source"]["statement"]["id"].as_string() == statement_id,
        ).order_by(DocumentVersionORM.created_at.desc(), DocumentVersionORM.id.desc())))
    else:
        rows = sorted((row for row in archive.memory_archive(unit.store).versions.values()
                       if row.metadata_snapshot.get("document_type") == DOC_TYPE
                       and row.metadata_snapshot.get(DOC_TYPE, {}).get("review", {}).get("source", {}).get("statement", {}).get("id") == statement_id),
                      key=lambda row: (row.created_at, row.id), reverse=True)
    result = []
    for row in rows:
        document = unit.store.get_document(row.document_id)
        _verified(unit, document)
        result.append(_public(row))
    return result


def context(store, statement_id, actor_id):
    with work(store, actor_id) as unit:
        source, statement, period, prop, tenant, portfolio = _source(unit, statement_id)
        sender = source["settings"]["document_sender"] or portfolio.owner_name or portfolio.name
        address = source["settings"]["document_address"]
        signature = source["settings"]["document_signature"] or sender
        recipient = tenant.full_name if tenant else "Leerstand (Eigentümer)"
        recipient_address = _address(tenant) if tenant else ""
        warnings = []
        if tenant and not recipient_address:
            recipient_address = _address(prop)
            warnings.append("Die Mieteranschrift fehlt; die Objektanschrift ist nur ein zu prüfender Vorschlag."
                            if recipient_address else "Die Mieteranschrift fehlt. Bitte die vollständige Empfängeranschrift ergänzen.")
        elif tenant and (not (tenant.address_line or "").strip()
                         or not any((value or "").strip() for value in (tenant.postal_code, tenant.city))):
            warnings.append("Die hinterlegte Mieteranschrift ist unvollständig; bitte die Empfängeranschrift vor der Freigabe prüfen.")
        if not address:
            warnings.append("Bitte die vollständige Absenderanschrift ergänzen oder in den Briefkopf-Vorgaben hinterlegen.")
        if period.status == "disputed":
            warnings.append("Zu dieser Abrechnungsfassung besteht ein Widerspruch; den Inhalt des Anschreibens bitte entsprechend prüfen.")
        problem = _publication_problem(unit, statement, period)
        if problem:
            warnings.append(problem)
        from ..routers.billing import _eur
        result = (f"Die Abrechnung ergibt eine Nachzahlung von {_eur(statement.balance)}." if statement.balance > 0
                  else f"Die Abrechnung ergibt ein Guthaben von {_eur(abs(statement.balance))}." if statement.balance < 0
                  else "Die Abrechnung ist ausgeglichen.")
        return {"source_revision": digest(source), "statement_status": statement.status,
                "period_status": period.status, "can_publish": not problem and all(may_write(unit.user["role"], path) for path in write_areas(statement_id)),
                "defaults": {"sender_name": sender, "sender_address": address, "recipient_name": recipient,
                    "recipient_address": recipient_address, "issue_date": datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat(),
                    "subject": f"Betriebskostenabrechnung {period.label}", "salutation": f"Guten Tag {recipient},",
                    "intro": "anbei erhalten Sie Ihre Betriebskostenabrechnung. " + result,
                    "closing": "Für Rückfragen zu Ihrer Abrechnung stehen wir Ihnen gerne zur Verfügung.\n\nMit freundlichen Grüßen",
                    "signature": signature}, "warnings": warnings, "originals": _originals(unit, statement_id)}


def _review(unit, statement_id, payload, *, lock=False):
    source, statement, period, *_ = _source(unit, statement_id, lock=lock)
    if digest(source) != payload.source_revision:
        raise HTTPException(412, "Abrechnung oder zugehörige Akten wurden geändert. Bitte die Briefvorschau neu laden.")
    draft = bool(_publication_problem(unit, statement, period))
    review = {"format_version": LETTERHEAD_FORMAT_VERSION, "source": source, "source_revision": payload.source_revision,
              "data": payload.data.model_dump(mode="json"), "draft": draft}
    logo = letterheads.logo_bytes(unit, source["property"]["id"])
    expected = source["letterhead"]["logo"]
    if (logo is None) != (expected is None) or (logo is not None and hashlib.sha256(logo).hexdigest() != expected["sha256"]):
        raise HTTPException(412, "Der Briefkopf wurde geändert. Bitte die Briefvorschau neu laden.")
    raw = render_pdf(review, logo)
    review["pdf_sha256"] = hashlib.sha256(raw).hexdigest()
    return review, digest(review), raw, statement, period


def preview(store, statement_id, payload, actor_id):
    with work(store, actor_id) as unit:
        review, review_hash, raw, *_ = _review(unit, statement_id, payload)
        return {"review_hash": review_hash, "pdf_sha256": review["pdf_sha256"], "review": review,
                "size_bytes": len(raw), "state": "preview"}


def preview_pdf(store, statement_id, payload, actor_id):
    with work(store, actor_id) as unit:
        review, review_hash, raw, *_ = _review(unit, statement_id, payload)
        return raw, review["pdf_sha256"], review_hash


def publish(store, statement_id, payload, actor_id):
    identifier, command_hash = document_id_for(actor_id, payload.idempotency_key), request_hash(statement_id, payload)
    with work(store, actor_id, statement_id, write=True, command_key=payload.idempotency_key) as unit:
        # Recheck access and bind the actual parent records before either a replay
        # or a new publication. An old successful response needs no new preview.
        _source(unit, statement_id, lock=True)
        try:
            existing = unit.store.get_document(identifier)
        except NotFoundError:
            existing = None
        if existing:
            _, row = _verified(unit, existing)
            proof = validate_billing_letter_snapshot(row, row.metadata_snapshot)
            if (row.request_sha256 != command_hash or row.actor_id != actor_id
                    or proof["review"]["source"]["statement"]["id"] != statement_id):
                raise HTTPException(409, "Die Vorgangskennung wurde bereits mit anderen Briefeingaben verwendet.")
            return _public(row)
        review, shown_hash, raw, statement, period = _review(unit, statement_id, payload, lock=True)
        problem = _publication_problem(unit, statement, period)
        if problem:
            raise HTTPException(409, problem)
        if shown_hash != payload.review_hash:
            raise HTTPException(409, "Die freizugebende Fassung stimmt nicht mit der Briefvorschau überein.")
        source = review["source"]
        stamp = archive.now()
        document = Document.model_validate({"id": identifier, **DocumentCreate(
            title=payload.data.subject, document_type=DOC_TYPE, document_date=payload.data.issue_date,
            property_id=source["property"]["id"], unit_id=statement.unit_id, contract_id=statement.contract_id,
            description=f"Geprüftes Abrechnungsschreiben zur Einzelabrechnung {statement_id}",
            file_url=f"/uploads/{VIRTUAL_PREFIX}{identifier}.pdf", tags="betriebskostenabrechnung,anschreiben",
        ).model_dump(), "created_at": stamp, "updated_at": stamp})
        if unit.db is not None:
            unit.db.execute(insert(DocumentORM), document.model_dump())
        else:
            unit.insert(unit.store.documents, document.id, document)
        binding = {key + "_id": source[key]["id"] for key in ("portfolio", "property", "unit", "contract", "tenant")}
        proof = {"schema_version": SCHEMA_VERSION, "review": review, "review_hash": shown_hash,
                 "request_sha256": command_hash, "actor_id": actor_id, "idempotency_key": payload.idempotency_key}
        row = archive.publish_generated_original(unit, document, binding, raw, command_hash,
                    version_id=str(uuid4()), metadata_extra={DOC_TYPE: proof})
        return _public(row)


def read_pdf_for_key(store, key, actor_id):
    if not key.startswith(VIRTUAL_PREFIX):
        return None
    identifier = key[len(VIRTUAL_PREFIX):-4] if key.endswith(".pdf") else ""
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Abrechnungsschreiben nicht gefunden.") from None
    with work(store, actor_id) as unit:
        document = unit.store.get_document(identifier)
        raw, row = _verified(unit, document)
        proof = validate_billing_letter_snapshot(row, row.metadata_snapshot)
        resolve_context(unit.store, "utility_statement", proof["review"]["source"]["statement"]["id"], unit.actor_id)
        if document.file_url != "/uploads/" + key:
            raise HTTPException(404, "Abrechnungsschreiben nicht gefunden.")
        return raw
