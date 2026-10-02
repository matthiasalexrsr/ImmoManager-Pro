"""Reviewed, resumable rental onboarding; one transaction publishes all objects."""

import hashlib
import json
import re
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from xml.sax.saxutils import escape

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as PDFTable
from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from .. import auth
from ..db.access_models import ResourcePortfolioORM
from ..db.contract_wizard_models import (
    WIZARD_MODELS,
    ContractAttachmentChunkORM,
    ContractAttachmentORM,
    ContractDraftORM,
    ContractSignatureORM,
    ContractTemplateORM,
    ContractWizardCommandORM,
)
from ..db.orm_models import ContractORM, DocumentORM, HandoverProtocolORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from ..models import ContractCreate, Document, DocumentCreate, HandoverProtocolCreate, Tenant
from ..permissions import may_write_resource
from ..storage import NotFoundError, ValidationError
from .contract_attachment import capture
from .contract_occupancy import assert_occupancy, begin_writer, lock_location
from .contract_wizard_types import DraftData
from .payments import _memory_lock
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def conflict(message="Der gespeicherte Stand wurde geändert. Bitte erneut laden und prüfen."):
    return HTTPException(409, message)


def identity(actor_id, *, write=False):
    record = auth.get_user_by_id(actor_id)
    if not record or not record["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    if write and not may_write_resource(record["role"], "contract-wizard"):
        raise HTTPException(403, "Keine Berechtigung zur Vertragsverwaltung.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Benutzerbindung ist nicht gültig.")
    return refresh_scope(captured) if captured is not None else scope_from_user(record)


@contextmanager
def work(store, actor_id, *, write=False):
    captured = identity(actor_id, write=write)
    sql = hasattr(store, "db")
    with scope_context(captured), _memory_lock if not sql else _empty():
        if sql:
            from ..repositories.sql_store import SQLAlchemyStore
            # An independent transaction, no facade helper may commit early.
            db = Session(store.db.get_bind(), autoflush=False, expire_on_commit=False)
            active = SQLAlchemyStore(db)
        else:
            db, active = None, store
            for model in WIZARD_MODELS:
                store.__dict__.setdefault(model.__tablename__, {})
            names = [model.__tablename__ for model in WIZARD_MODELS] + [
                "tenants", "contracts", "documents", "handover_protocols", "_resource_grants"]
            before = {key: deepcopy(store.__dict__.get(key)) for key in names} if write else None
        try:
            if sql and write:
                begin_writer(db)
            yield active, db, captured
            if write:
                refresh_scope(captured)
                if db is not None:
                    db.commit()
        except Exception:
            if db is not None:
                db.rollback()
            elif write:
                assert before is not None
                for key, value in before.items():
                    if value is None:
                        store.__dict__.pop(key, None)
                    else:
                        store.__dict__[key] = value
            raise
        finally:
            if db is not None:
                db.close()


@contextmanager
def _empty():
    yield


def rows(store, db, model):
    return db.scalars(select(model)).all() if db is not None else list(store.__dict__[model.__tablename__].values())


def get_row(store, db, model, identifier, *, lock=False):
    if db is not None:
        query = select(model).where(model.id == identifier)
        return db.scalar(query.with_for_update() if lock else query)
    return store.__dict__[model.__tablename__].get(identifier)


def add(store, db, row):
    if db is not None:
        db.add(row)
        db.flush()
    else:
        identifier = getattr(row, "id", None) or f"{row.attachment_id}:{row.position}"
        store.__dict__[row.__tablename__][identifier] = row


def allowed_portfolio(store, identifier):
    return store.get_portfolio(identifier)


def load(store, db, identifier, actor_id, *, lock=False, published=False):
    row = get_row(store, db, ContractDraftORM, identifier, lock=lock)
    if row is None or (not published and row.actor_id != actor_id):
        raise HTTPException(404, "Gespeicherter Vertragsentwurf nicht gefunden.")
    allowed_portfolio(store, row.portfolio_id)
    property = store.get_property(row.data["property_id"])
    if property.portfolio_id != row.portfolio_id:
        raise HTTPException(404, "Der Vertragsbestand wurde verschoben. Neue Zuordnung prüfen.")
    return row


def public(row, *, persistent):
    return {"id": row.id, "portfolio_id": row.portfolio_id, "data": deepcopy(row.data), "revision": row.revision,
        "state": row.state, "review": deepcopy(row.review), "review_hash": row.review_hash,
        "contract_id": row.contract_id, "document_id": row.document_id, "pdf_sha256": row.pdf_sha256,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(), "persistent": persistent,
        "pdf_url": "/contract-wizard/drafts/" + row.id + "/pdf" if row.contract_id else None,
        "preview_url": "/contract-wizard/drafts/" + row.id + "/review-pdf" if row.review_hash and row.pdf else None}


def _match_command(store, db, row, actor_id, key, request_hash):
    if db is not None:
        command = db.scalar(select(ContractWizardCommandORM).where(
            ContractWizardCommandORM.actor_id == actor_id, ContractWizardCommandORM.command_key == key))
    else:
        command = next((c for c in rows(store, db, ContractWizardCommandORM)
            if c.actor_id == actor_id and c.command_key == key), None)
    if command:
        if command.draft_id != row.id or command.request_hash != request_hash:
            raise conflict("Diese Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
        return deepcopy(command.result)
    return None


def _record(store, db, row, actor_id, payload, kind):
    row.updated_at = now()
    result = public(row, persistent=db is not None)
    add(store, db, ContractWizardCommandORM(id=str(uuid4()), portfolio_id=row.portfolio_id,
        draft_id=row.id, actor_id=actor_id, command_key=payload.idempotency_key,
        request_hash=digest({"id": row.id, "kind": kind, "payload": payload.model_dump(mode="json")}),
        result=deepcopy(result), created_at=now()))
    return result


def _claimed(store, db, row, payload, actor_id, kind):
    replay = _match_command(store, db, row, actor_id, payload.idempotency_key,
        digest({"id": row.id, "kind": kind, "payload": payload.model_dump(mode="json")}))
    if replay:
        return replay
    if row.revision != payload.expected_revision:
        raise conflict()
    return None


def _references(store, data, *, checked=False):
    property, unit = lock_location(store, data.property_id, data.unit_id)
    if hasattr(store, "db"):
        source_models: list[tuple[Any, str]] = [(PortfolioORM, property.portfolio_id),
                *(([(TenantORM, data.tenant_id)]) if data.tenant_id else []),
                *((DocumentORM, identifier) for identifier in sorted(data.attachment_ids))]
        for model, identifier in source_models:
            if store.db.scalar(select(model.id).where(model.id == identifier).with_for_update()) is None:
                raise ValidationError("Ein gewählter Quelldatensatz ist nicht mehr zugänglich.")
    portfolio = allowed_portfolio(store, property.portfolio_id)
    tenant = store.get_tenant(data.tenant_id) if data.tenant_id else data.new_tenant
    if tenant.archived:
        raise ValidationError("Archivierte Mieter können nicht neu zugeordnet werden.")
    template = None
    if data.template_id:
        db = store.db if hasattr(store, "db") else None
        template = get_row(store, db, ContractTemplateORM, data.template_id)
        if template is None or template.portfolio_id != property.portfolio_id:
            raise ValidationError("Die Vorlage gehört nicht zum ausgewählten Portfolio.")
    attachments = []
    for identifier in sorted(data.attachment_ids):
        document = store.get_document(identifier)
        # A document must be explicitly tied to this property/unit, not merely
        # accessible elsewhere in a multi-portfolio account.
        if document.property_id != data.property_id or (document.unit_id and document.unit_id != data.unit_id):
            raise ValidationError("Eine Anlage gehört nicht zum ausgewählten Objekt oder zur Einheit.")
        if document.contract_id:
            source_contract = (store.db.scalar(select(ContractORM).where(ContractORM.id == document.contract_id)
                .with_for_update()) if hasattr(store, "db") else store.get_contract(document.contract_id))
            if (source_contract is None or data.tenant_id is None
                    or source_contract.tenant_id != data.tenant_id):
                raise ValidationError("Die vertragsgebundene Anlage gehört zu einem anderen Mieter. "
                    "Bitte eine eigene oder allgemeine Objektanlage auswählen.")
        evidence = document.model_dump(mode="json")
        if identifier in data.metadata_only_attachment_ids:
            evidence.update(mode="metadata_only", sha256=None, size_bytes=None)
        elif checked:
            evidence.update(capture(document.file_url))
        attachments.append(evidence)
    terms = data.terms if data.terms.strip() else template.body if template else ""
    if checked:
        if not terms.strip():
            raise ValidationError("Bitte eine eigene geprüfte Vertragsvorlage oder Vereinbarungen ergänzen.")
        if data.deposit_amount >= 10_000_000_000:
            raise ValidationError("Die Kaution überschreitet die vorhandene Datenbankkapazität NUMERIC(12,2).")
        contract = _contract(data, data.tenant_id or "review-new-tenant")
        assert_occupancy(store, contract)
        if not hasattr(store, "db") and any(c.contract_number == data.contract_number
                for c in store.__dict__["contracts"].values()):
            raise conflict("Diese Vertragsnummer ist bereits vergeben.")
    return {"portfolio": portfolio.model_dump(mode="json"), "property": property.model_dump(mode="json"),
        "unit": unit.model_dump(mode="json"), "tenant": tenant.model_dump(mode="json"),
        "template": {"id": template.id, "version": template.version, "title": template.title, "body": template.body} if template else None,
        "attachments": attachments, "terms": terms, "parameters": data.model_dump(mode="json"),
        "deposit_policy": "expected_amount_only", "attachments_policy": "explicit_frozen_or_metadata",
        "contract_policy": "draft_non_reserving" if data.contract_status == "draft" else "active_inclusive_dates"}


def _contract(data, tenant_id):
    return ContractCreate(contract_number=data.contract_number, property_id=data.property_id,
        unit_id=data.unit_id, tenant_id=tenant_id, status=data.contract_status, start_date=data.start_date,
        end_date=data.end_date, deposit_amount=float(data.deposit_amount), notice_period=data.notice_period,
        index_rent=data.index_rent, service_charge_settlement=data.service_charge_settlement)


def create_draft(store, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        # Lock the exact location before checking its creation replay: another
        # identical PostgreSQL request may have waited on this same source row.
        source = _references(active, payload.data)
        request_hash = digest(payload.data.model_dump(mode="json"))
        if db is not None:
            previous = db.scalar(select(ContractDraftORM).where(ContractDraftORM.actor_id == actor_id,
                ContractDraftORM.create_key == payload.idempotency_key).with_for_update())
        else:
            previous = next((r for r in rows(active, db, ContractDraftORM)
                if r.actor_id == actor_id and r.create_key == payload.idempotency_key), None)
        if previous:
            load(active, db, previous.id, actor_id)
            if previous.create_hash != request_hash:
                raise conflict("Diese Entwurfsreferenz wurde bereits mit anderen Eingaben verwendet.")
            return public(previous, persistent=db is not None)
        row = ContractDraftORM(id=str(uuid4()), portfolio_id=source["property"]["portfolio_id"], actor_id=actor_id,
            create_key=payload.idempotency_key, create_hash=request_hash, data=payload.data.model_dump(mode="json"),
            revision=1, state="draft", review=None, review_hash=None, pdf=None, pdf_sha256=None,
            contract_id=None, document_id=None, published_tenant_id=None, created_at=now(), updated_at=now())
        add(active, db, row)
        return public(row, persistent=db is not None)


def get_draft(store, identifier, actor_id):
    with work(store, actor_id) as (active, db, captured):
        return public(load(active, db, identifier, actor_id), persistent=db is not None)


def list_drafts(store, actor_id, offset=0, limit=25):
    with work(store, actor_id) as (active, db, captured):
        if db is not None:
            query = select(ContractDraftORM).where(ContractDraftORM.actor_id == actor_id)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            found = db.scalars(query.order_by(ContractDraftORM.created_at.desc(), ContractDraftORM.id.desc())
                .offset(offset).limit(limit)).all()
        else:
            found = [r for r in rows(active, db, ContractDraftORM) if r.actor_id == actor_id
                and (captured.unrestricted or r.portfolio_id in captured.portfolio_ids)]
            found.sort(key=lambda r: (r.created_at, r.id), reverse=True)
            total, found = len(found), found[offset:offset + limit]
        items = []
        for row in found:
            try:
                load(active, db, row.id, actor_id)
                items.append(public(row, persistent=db is not None))
            except (NotFoundError, HTTPException):
                # A moved source cannot disclose old parties/terms via listing.
                items.append({"id": row.id, "available": False})
        return {"items": items, "total": total, "offset": offset, "limit": limit, "persistent": db is not None}


def edit_draft(store, identifier, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        row = load(active, db, identifier, actor_id, lock=True)
        replay = _claimed(active, db, row, payload, actor_id, "edit")
        if replay:
            return replay
        if row.state not in {"draft", "reviewed"}:
            raise conflict("Ein veröffentlichter Vertragsstand ist unveränderlich. Bitte einen neuen Entwurf anlegen.")
        source = _references(active, payload.data)
        if source["property"]["portfolio_id"] != row.portfolio_id:
            raise ValidationError("Ein Portfolio-Wechsel benötigt einen neuen Entwurf.")
        row.data, row.review, row.review_hash = payload.data.model_dump(mode="json"), None, None
        row.pdf, row.pdf_sha256 = None, None
        row.state, row.revision = "draft", row.revision + 1
        return _record(active, db, row, actor_id, payload, "edit")


def review_draft(store, identifier, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        row = load(active, db, identifier, actor_id, lock=True)
        replay = _claimed(active, db, row, payload, actor_id, "review")
        if replay:
            return replay
        if row.state not in {"draft", "reviewed"}:
            raise conflict("Veröffentlichten Stand aus dem Dokumentjournal öffnen.")
        row.review = _references(active, DraftData.model_validate(row.data), checked=True)
        row.review_hash = digest(row.review)
        row.pdf = build_pdf(row.review)
        if not row.pdf.startswith(b"%PDF-"):
            raise HTTPException(503, "Die vollständige Vertragsvorschau konnte nicht erzeugt werden.")
        row.pdf_sha256 = hashlib.sha256(row.pdf).hexdigest()
        row.state, row.revision = "reviewed", row.revision + 1
        return _record(active, db, row, actor_id, payload, "review")


def build_pdf(snapshot):
    from mietvertrag_wizard_fastapi_reportlab_pro.mietvertrag_wizard.pdf_theme import (
        BOTTOM_MARGIN,
        CONTENT_WIDTH,
        LEFT_MARGIN,
        RIGHT_MARGIN,
        TOP_MARGIN,
        contract_styles,
        decorate_page,
        section_heading,
        signature_table_style,
        title_block,
    )
    # Entire user text is escaped; never feed ReportLab an arbitrary HTML template.
    buffer = BytesIO()
    styles = contract_styles()
    parameters = snapshot["parameters"]
    unit, property = snapshot["unit"], snapshot["property"]
    currency = snapshot["portfolio"].get("currency") or "EUR"
    def money(value):
        number = Decimal(str(value or 0))
        if not number.is_finite():
            raise ValidationError("Gespeicherte Mietbeträge müssen vor der Vertragsprüfung korrigiert werden.")
        _, digits, exponent = number.as_tuple()
        assert isinstance(exponent, int)
        extra = -2 - exponent
        if extra > 0 and any(digits[-extra:]):
            raise ValidationError("Gespeicherte Mietbeträge müssen vor der Vertragsprüfung centgenau korrigiert werden.")
        formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return formatted + (" €" if currency == "EUR" else " " + currency)
    sections = [("Vertragsstand", parameters["contract_number"]),
        ("Vermieter", parameters["landlord_name"] + "\n" + parameters["landlord_address"]),
        ("Mieter", snapshot["tenant"]["full_name"] + "\n" + (snapshot["tenant"].get("address_line") or "")
            + "\n" + " ".join(filter(None, [snapshot["tenant"].get("postal_code"), snapshot["tenant"].get("city")]))),
        ("Mietobjekt", property["name"] + " / " + unit["label"] + "\n" + (property.get("address_line") or "")),
        ("Mietzeit", parameters["start_date"] + " – " + (parameters["end_date"] or "unbefristet")),
        ("Monatliche Basis", "Kaltmiete: " + money(unit.get("cold_rent"))
            + "; Betriebskosten: " + money(unit.get("service_charge_advance"))
            + "; Heizung: " + money(unit.get("heating_advance"))),
        ("Kaution", money(parameters["deposit_amount"]) + " vereinbart. Kein Zahlungseingang erfasst."),
        ("Mietmodell / Abrechnung", {"fixed": "Festmiete", "index": "Indexmiete", "stepped": "Staffelmiete"}[parameters["index_rent"]]
            + " / " + {"annual": "Jährliche Betriebskostenabrechnung", "monthly": "Monatliche Betriebskostenabrechnung"}[parameters["service_charge_settlement"]]),
        ("Vereinbarungen", snapshot["terms"]),
        ("Anlagenbelege", "\n".join(a["title"] + " (" + a["id"] + ") – "
            + ("Originalbytes, SHA256 " + a["sha256"] + ", " + str(a["size_bytes"]) + " Bytes"
                if a["mode"] == "frozen_bytes" else "bewusst nur Metadatenverweis, keine Originalbytes")
            for a in snapshot["attachments"]) or "Keine Anlagen gewählt."),
        ("Manuelle Unterzeichnung", "Vermieter: ____________________   Mieter: ____________________\nDatum: ____________________"),
        ("Prüfstand", "Vorlage: " + (snapshot["template"]["title"] + " v" + str(snapshot["template"]["version"]) if snapshot["template"] else "Eigener Text")
            + "\nReferenz: " + digest(snapshot) + "\nKein elektronischer Signaturnachweis. Archivierte Anlagen sind separat herunterladbar.")]
    content = [title_block(styles, title="MIETVERTRAG", subtitle="GEPRÜFTER VERWALTUNGSSTAND"), Spacer(1, 12)]
    for position, (title, text) in enumerate(sections, 1):
        if title == "Manuelle Unterzeichnung":
            table = PDFTable([[Paragraph("Vermieter<br/><br/>____________________________", styles["signature"]),
                Paragraph("Mieter<br/><br/>____________________________", styles["signature"])]],
                colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2], minRowHeights=[65])
            table.setStyle(signature_table_style())
            content.append(KeepTogether([section_heading(f"{position:02} · {title}", styles), Spacer(1, 5),
                Paragraph("Ort, Datum: __________________________________________", styles["base"]), Spacer(1, 7), table, Spacer(1, 10)]))
            continue
        block = [section_heading(f"{position:02} · {title}", styles, CONTENT_WIDTH), Spacer(1, 5),
            Paragraph(escape(text).replace("\n", "<br/>"), styles["base"]), Spacer(1, 10)]
        content.extend(block)
    def decorate(canvas, document):
        decorate_page(canvas, document, title="GEPRÜFTER MIETVERTRAG",
            footer_left="Prüfreferenz " + digest(snapshot)[:24], footer_right="Archivierte Anlagen separat abrufbar")
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=LEFT_MARGIN, rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
        title="Geprüfter Vertragsstand " + parameters["contract_number"], author=parameters["landlord_name"]
        ).build(content, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _insert_business(active, db, model, values):
    if db is not None:
        # Explicitly validated exact source references and fields only. This
        # Connection insert prevents per-repository early commit and validates
        # DB constraints within the same reviewed publication transaction.
        db.connection().execute(model.__table__.insert(), values)
    elif model is TenantORM:
        active.tenants[values["id"]] = Tenant(**values)
    elif model is ContractORM:
        from ..models import Contract
        active.contracts[values["id"]] = Contract(**values)
    elif model is DocumentORM:
        # Exact newly generated PDF URL and validated source links; the normal
        # uploaded-file grant guard cannot see bytes that live in this journal.
        object.__getattribute__(active, "__dict__")["documents"][values["id"]] = Document(**values)
    elif model is HandoverProtocolORM:
        from ..models import HandoverProtocol
        active.handover_protocols[values["id"]] = HandoverProtocol(**values)


def freeze_attachments(active, db, row, snapshot):
    for evidence in snapshot["attachments"]:
        attachment = ContractAttachmentORM(id=str(uuid4()), portfolio_id=row.portfolio_id,
            draft_id=row.id, source_document_id=evidence["id"], metadata_snapshot=evidence,
            sha256=evidence.get("sha256"), size_bytes=evidence.get("size_bytes"), mode=evidence["mode"])
        add(active, db, attachment)
        if attachment.mode == "metadata_only":
            continue
        def write_chunk(position, data):
            chunk = ContractAttachmentChunkORM(attachment_id=attachment.id, portfolio_id=row.portfolio_id,
                position=position, data=data)
            if db is not None:
                db.connection().execute(cast(Table, ContractAttachmentChunkORM.__table__).insert(),
                    {"attachment_id": attachment.id, "portfolio_id": row.portfolio_id, "position": position, "data": data})
            else:
                add(active, db, chunk)
        captured = capture(evidence["file_url"], on_chunk=write_chunk)
        if captured["sha256"] != attachment.sha256 or captured["size_bytes"] != attachment.size_bytes:
            raise conflict("Die gewählte Anlage wurde nach der Prüfung geändert. Entwurf erneut prüfen.")


def publish_draft(store, identifier, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        row = load(active, db, identifier, actor_id, lock=True)
        replay = _claimed(active, db, row, payload, actor_id, "publish")
        if replay:
            return replay
        if not payload.confirmed or row.state != "reviewed" or payload.reviewed_hash != row.review_hash:
            raise conflict("Bitte den aktuellen geprüften Entwurf ausdrücklich bestätigen.")
        data = DraftData.model_validate(row.data)
        snapshot = _references(active, data, checked=True)
        if digest(snapshot) != row.review_hash:
            raise conflict("Objekt, Mieter, Vorlage oder Anlagen wurden geändert. Bitte erneut prüfen.")
        # Publish exactly the bytes available during explicit review, including
        # renderer-version changes/restarts. No fresh, different PDF on confirm.
        pdf = row.pdf
        if not pdf or not pdf.startswith(b"%PDF-") or hashlib.sha256(pdf).hexdigest() != row.pdf_sha256:
            raise HTTPException(503, "Die vollständige Vertragsdatei konnte nicht erzeugt werden.")
        freeze_attachments(active, db, row, snapshot)
        tenant_id = data.tenant_id
        if tenant_id is None:
            assert data.new_tenant is not None
            tenant_id = str(uuid4())
            _insert_business(active, db, TenantORM, {**data.new_tenant.model_dump(), "id": tenant_id,
                "created_at": now(), "updated_at": now()})
            if db is not None:
                add(active, db, ResourcePortfolioORM(resource_type="tenants", resource_id=tenant_id, portfolio_id=row.portfolio_id))
            else:
                active.__dict__.setdefault("_resource_grants", set()).add(("tenants", tenant_id, row.portfolio_id))
        contract_id, document_id = str(uuid4()), str(uuid4())
        _insert_business(active, db, ContractORM, {**_contract(data, tenant_id).model_dump(), "id": contract_id,
            "created_at": now(), "updated_at": now()})
        file_url = "/uploads/contract-wizard/" + row.id + ".pdf"
        _insert_business(active, db, DocumentORM, {**DocumentCreate(property_id=data.property_id, unit_id=data.unit_id,
            contract_id=contract_id, title=data.contract_number, document_type="rental_contract",
            document_date=data.start_date, file_url=file_url,
            description="Geprüfter Vertragsstand " + row.review_hash).model_dump(), "id": document_id,
            "created_at": now(), "updated_at": now()})
        if data.create_handover:
            if not may_write_resource(captured.role, "handover-protocols"):
                raise HTTPException(403, "Keine Berechtigung zur Übergabevorbereitung.")
            _insert_business(active, db, HandoverProtocolORM, {**HandoverProtocolCreate(contract_id=contract_id,
                unit_id=data.unit_id, protocol_type="move_in", protocol_date=data.start_date,
                tenant_present=False, landlord_present=False, status="draft",
                notes="Nur vorbereiteter Entwurf; keine Schlüsselübergabe oder Unterschrift bestätigt.").model_dump(),
                "id": str(uuid4()), "created_at": now(), "updated_at": now()})
        row.pdf, row.pdf_sha256 = pdf, hashlib.sha256(pdf).hexdigest()
        row.contract_id, row.document_id = contract_id, document_id
        row.published_tenant_id = tenant_id
        row.state, row.revision = "committed", row.revision + 1
        return _record(active, db, row, actor_id, payload, "publish")


def record_signature(store, identifier, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        row = load(active, db, identifier, actor_id, lock=True)
        replay = _claimed(active, db, row, payload, actor_id, "signature")
        if replay:
            return replay
        if not payload.confirmed or row.state != "committed":
            raise conflict("Manuelle Unterzeichnung nur ausdrücklich für einen veröffentlichten Stand erfassen.")
        if payload.signed_document_id:
            signed = active.get_document(payload.signed_document_id)
            if signed.contract_id != row.contract_id or signed.property_id != row.data["property_id"]:
                raise ValidationError("Der Unterschriftsbeleg gehört nicht zu diesem Vertrag.")
        add(active, db, ContractSignatureORM(id=str(uuid4()), portfolio_id=row.portfolio_id,
            draft_id=row.id, actor_id=actor_id, created_at=now(), **payload.model_dump(exclude={
                "confirmed", "expected_revision", "idempotency_key"})))
        row.state, row.revision = "signed", row.revision + 1
        return _record(active, db, row, actor_id, payload, "signature")


def signature_evidence(store, identifier, actor_id, *, offset=0, limit=25):
    with work(store, actor_id) as (active, db, captured):
        row = load(active, db, identifier, actor_id)
        if db is not None:
            found = db.scalars(select(ContractSignatureORM).where(ContractSignatureORM.draft_id == row.id)
                .order_by(ContractSignatureORM.created_at, ContractSignatureORM.id).offset(offset).limit(limit + 1)).all()
        else:
            found = sorted([item for item in rows(active, db, ContractSignatureORM) if item.draft_id == row.id],
                key=lambda item: (item.created_at, item.id))[offset:offset + limit + 1]
        return {"items": [{key: getattr(item, key) for key in ("id", "signed_date", "tenant_signer", "landlord_signer", "reference", "note", "signed_document_id", "created_at")}
                for item in found[:limit]], "has_more": len(found) > limit, "offset": offset, "limit": limit}


def read_pdf(store, identifier, actor_id):
    with work(store, actor_id) as (active, db, captured):
        row = load(active, db, identifier, actor_id, published=True)
        if not row.pdf or not row.document_id or not row.contract_id:
            raise HTTPException(404, "Vertragsdatei ist noch nicht veröffentlicht.")
        contract, document = active.get_contract(row.contract_id), active.get_document(row.document_id)
        if (contract.property_id != row.data["property_id"] or contract.unit_id != row.data["unit_id"]
                or contract.tenant_id != row.published_tenant_id
                or document.contract_id != row.contract_id or document.property_id != contract.property_id
                or document.unit_id != contract.unit_id
                or document.file_url != "/uploads/contract-wizard/" + row.id + ".pdf"):
            raise HTTPException(404, "Vertragsdatei ist nicht mehr diesem Bestand zugeordnet.")
        if hashlib.sha256(row.pdf).hexdigest() != row.pdf_sha256:
            raise HTTPException(503, "Der gespeicherte Vertragsstand konnte nicht geprüft werden.")
        refresh_scope(captured)
        return row.pdf


def read_review_pdf(store, identifier, actor_id):
    with work(store, actor_id) as (active, db, captured):
        row = load(active, db, identifier, actor_id)
        if not row.review_hash or not row.pdf or hashlib.sha256(row.pdf).hexdigest() != row.pdf_sha256:
            raise HTTPException(404, "Keine vollständig geprüfte Vertragsvorschau vorhanden.")
        refresh_scope(captured)
        return row.pdf


def read_pdf_for_key(store, key):
    match = re.fullmatch(r"contract-wizard/([a-f0-9-]{36})\.pdf", key)
    if not match:
        return None
    captured = current_scope()
    if captured is None:
        raise HTTPException(401, "Anmeldung erforderlich.")
    return read_pdf(store, match[1], captured.user_id)


def attachment_evidence(store, identifier, actor_id, *, offset=0, limit=25):
    read_pdf(store, identifier, actor_id)  # Fresh document/contract binding.
    with work(store, actor_id) as (active, db, captured):
        row = load(active, db, identifier, actor_id, published=True)
        if db is not None:
            found = db.scalars(select(ContractAttachmentORM).where(ContractAttachmentORM.draft_id == row.id)
                .order_by(ContractAttachmentORM.id).offset(offset).limit(limit + 1)).all()
        else:
            found = sorted([r for r in rows(active, db, ContractAttachmentORM) if r.draft_id == row.id],
                key=lambda item: item.id)[offset:offset + limit + 1]
        return {"items": [{"id": r.id, "source_document_id": r.source_document_id,
            "title": r.metadata_snapshot["title"], "mode": r.mode, "sha256": r.sha256, "size_bytes": r.size_bytes,
            "download_url": "/contract-wizard/drafts/" + row.id + "/attachments/" + r.id + "/download"
                if r.mode == "frozen_bytes" else None} for r in found[:limit]],
            "has_more": len(found) > limit, "offset": offset, "limit": limit}


def prepare_attachment_download(store, identifier, attachment_id, actor_id, *, parent=None):
    from scripts.private_server_backup import private_workspace

    from .datev_export import CompiledExport
    read_pdf(store, identifier, actor_id)
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        path = workspace / "attachment.bin"
        checksum, size, expected_position = hashlib.sha256(), 0, 0
        with work(store, actor_id) as (active, db, captured):
            row = load(active, db, identifier, actor_id, published=True)
            attachment = get_row(active, db, ContractAttachmentORM, attachment_id)
            if attachment is None or attachment.draft_id != row.id or attachment.mode != "frozen_bytes":
                raise HTTPException(404, "Keine archivierten Anlagenbytes vorhanden. Nur der gewählte Verweis wurde bestätigt.")
            if db is not None:
                chunks = db.scalars(select(ContractAttachmentChunkORM)
                    .where(ContractAttachmentChunkORM.attachment_id == attachment_id)
                    .order_by(ContractAttachmentChunkORM.position).execution_options(yield_per=8))
            else:
                chunks = sorted((r for r in rows(active, db, ContractAttachmentChunkORM)
                    if r.attachment_id == attachment_id), key=lambda r: r.position)
            with path.open("xb") as destination:
                for chunk in chunks:
                    if chunk.position != expected_position or len(chunk.data) > 64 * 1024:
                        raise HTTPException(503, "Die gespeicherte Anlage ist unvollständig oder beschädigt.")
                    destination.write(chunk.data)
                    checksum.update(chunk.data)
                    size += len(chunk.data)
                    expected_position += 1
            if checksum.hexdigest() != attachment.sha256 or size != attachment.size_bytes:
                raise HTTPException(503, "Die gespeicherte Anlage konnte nicht vollständig geprüft werden.")
            refresh_scope(captured)
        return CompiledExport(path, {"size": size, "sha256": checksum.hexdigest()}, cleanup), captured
    except BaseException:
        cleanup.close()
        raise


def guard_destructive_reset(store):
    from .document_version_guards import guard_partial_transfer
    guard_partial_transfer(store)
    if hasattr(store, "db"):
        present = any(store.db.scalar(select(model.id).limit(1)) is not None
            for model in (ContractDraftORM, ContractTemplateORM))
    else:
        present = any(store.__dict__.get(model.__tablename__) for model in WIZARD_MODELS)
    if present:
        raise ValidationError("Vertragsentwürfe und Unterzeichnungsbelege benötigen ein vollständiges Backup. Geschäftsdatenteilreset ist gesperrt.")


def guard_delete_link(store, entity_type, identifier):
    from .document_version_guards import guard_delete_link as guard_document_history
    guard_document_history(store, entity_type, identifier)
    if entity_type not in {"contracts", "documents", "portfolios", "properties", "units", "tenants"}:
        return
    if hasattr(store, "db"):
        if entity_type == "tenants":
            # Private CRUD drafts hold FOR SHARE on this same row while saving.
            # Lock before the retention check to prevent an orphaning race.
            begin_writer(store.db)
            store.db.scalar(select(TenantORM.id).where(TenantORM.id == identifier).with_for_update())
            from .tenant_private_draft_guard import guard_private_tenant_delete
            guard_private_tenant_delete(store, identifier)
        field = {"contracts": ContractDraftORM.contract_id, "documents": ContractDraftORM.document_id,
            "portfolios": ContractDraftORM.portfolio_id, "properties": ContractDraftORM.data["property_id"].as_string(),
            "units": ContractDraftORM.data["unit_id"].as_string(), "tenants": ContractDraftORM.data["tenant_id"].as_string()}[entity_type]
        condition = field == identifier
        if entity_type == "tenants":
            condition = condition | (ContractDraftORM.published_tenant_id == identifier)
        present = store.db.scalar(select(ContractDraftORM.id).where(condition).limit(1))
        if entity_type == "documents" and not present:
            present = store.db.scalar(select(ContractSignatureORM.id).where(ContractSignatureORM.signed_document_id == identifier).limit(1))
        if entity_type == "portfolios" and not present:
            present = store.db.scalar(select(ContractTemplateORM.id).where(ContractTemplateORM.portfolio_id == identifier).limit(1))
    else:
        if entity_type == "tenants":
            from .tenant_private_draft_guard import guard_private_tenant_delete
            guard_private_tenant_delete(store, identifier)
        def linked(r):
            return {"contracts": r.contract_id, "documents": r.document_id, "portfolios": r.portfolio_id,
                "properties": r.data["property_id"], "units": r.data["unit_id"],
                "tenants": r.published_tenant_id or r.data.get("tenant_id")}[entity_type] == identifier
        present = any(linked(r) for r in store.__dict__.get(ContractDraftORM.__tablename__, {}).values())
        if entity_type == "documents" and not present:
            present = any(r.signed_document_id == identifier for r in store.__dict__.get(ContractSignatureORM.__tablename__, {}).values())
        if entity_type == "portfolios" and not present:
            present = any(r.portfolio_id == identifier for r in store.__dict__.get(ContractTemplateORM.__tablename__, {}).values())
    if not present and entity_type == "tenants":
        from .tenant_wizard_graph import has_historical_tenant_reference
        present = has_historical_tenant_reference(store, identifier)
    if present:
        raise ValidationError("Dieser Vertrag oder dieses Dokument besitzt einen unveränderlichen geprüften Vertragsbeleg und kann nicht gelöscht werden.")


def create_template(store, payload, actor_id):
    with work(store, actor_id, write=True) as (active, db, captured):
        allowed_portfolio(active, payload.portfolio_id)
        if db is not None:
            db.scalar(select(PortfolioORM.id).where(PortfolioORM.id == payload.portfolio_id).with_for_update())
            previous_command = db.scalar(select(ContractTemplateORM).where(ContractTemplateORM.actor_id == actor_id,
                ContractTemplateORM.create_key == payload.idempotency_key))
        else:
            previous_command = next((r for r in rows(active, db, ContractTemplateORM)
                if r.actor_id == actor_id and r.create_key == payload.idempotency_key), None)
        request_hash = digest(payload.model_dump(mode="json"))
        if previous_command:
            if previous_command.create_hash != request_hash:
                raise conflict("Diese Vorlagenreferenz wurde mit anderen Eingaben verwendet.")
            return template_public(previous_command)
        if payload.previous_id:
            previous = get_row(active, db, ContractTemplateORM, payload.previous_id, lock=True)
            if previous is None or previous.portfolio_id != payload.portfolio_id:
                raise HTTPException(404, "Vorlage nicht gefunden.")
            if db is not None:
                current = db.scalar(select(func.max(ContractTemplateORM.version)).where(ContractTemplateORM.root_id == previous.root_id))
            else:
                current = max(r.version for r in rows(active, db, ContractTemplateORM) if r.root_id == previous.root_id)
            if current != previous.version:
                raise conflict("Die Vorlage besitzt bereits eine neuere Fassung. Bitte diese zuerst öffnen.")
            root, version = previous.root_id, previous.version + 1
        else:
            root, version = str(uuid4()), 1
        row = ContractTemplateORM(id=str(uuid4()), portfolio_id=payload.portfolio_id, root_id=root,
            version=version, title=payload.title, body=payload.body, actor_id=actor_id,
            create_key=payload.idempotency_key, create_hash=request_hash, created_at=now())
        add(active, db, row)
        return template_public(row)


def template_public(row):
    return {key: getattr(row, key) for key in ("id", "portfolio_id", "root_id", "version", "title", "body")}


def list_templates(store, actor_id, portfolio_id, offset=0, limit=25):
    with work(store, actor_id) as (active, db, captured):
        allowed_portfolio(active, portfolio_id)
        if db is not None:
            query = select(ContractTemplateORM).where(ContractTemplateORM.portfolio_id == portfolio_id)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            found = db.scalars(query.order_by(ContractTemplateORM.created_at.desc(), ContractTemplateORM.id.desc()).offset(offset).limit(limit)).all()
        else:
            found = sorted([r for r in rows(active, db, ContractTemplateORM) if r.portfolio_id == portfolio_id],
                key=lambda r: (r.created_at, r.id), reverse=True)
            total, found = len(found), found[offset:offset + limit]
        return {"items": [template_public(r) for r in found], "total": total, "offset": offset, "limit": limit}


def choices(store, actor_id, kind, *, search="", property_id=None, selected_id=None, offset=0, limit=25):
    from ..db.booking_order import bytewise_id
    with work(store, actor_id) as (active, db, captured):
        model: Any
        model, label = {"properties": (PropertyORM, "name"), "units": (UnitORM, "label"),
            "tenants": (TenantORM, "full_name"), "documents": (DocumentORM, "title")}[kind]
        if kind in {"units", "documents"}:
            if not property_id:
                return {"items": [], "selected": None, "has_more": False, "offset": offset, "limit": limit}
            active.get_property(property_id)
        if db is not None:
            query = select(model)
            if kind in {"units", "documents"}:
                query = query.where(model.property_id == property_id)
            if kind == "tenants":
                query = query.where(model.archived.is_(False))
            selected_query = query.where(model.id == selected_id) if selected_id else None
            if search:
                escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.where(getattr(model, label).ilike("%" + escaped + "%", escape="\\"))
            found = db.scalars(query.order_by(bytewise_id(model.id)).offset(offset).limit(limit + 1)).all()
            selected = db.scalar(selected_query) if selected_query is not None else None
        else:
            values = [r for r in getattr(active, kind).values()
                if (kind not in {"units", "documents"} or r.property_id == property_id)
                and (kind != "tenants" or not r.archived)]
            selected = next((r for r in values if r.id == selected_id), None)
            found = sorted((r for r in values if not search or search.lower() in getattr(r, label).lower()),
                key=lambda r: r.id)[offset:offset + limit + 1]
        def read(row):
            return {"id": row.id, "label": getattr(row, label),
                **({"portfolio_id": row.portfolio_id} if kind == "properties" else {})}
        return {"items": [read(r) for r in found[:limit]], "selected": read(selected) if selected else None,
            "has_more": len(found) > limit, "offset": offset, "limit": limit}
