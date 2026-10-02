"""Template rendering, reviewed document snapshots and dispatch preparation."""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from html import escape
from uuid import uuid4

from fastapi import HTTPException
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..communication_models import (
    CommunicationBlockCreate,
    CommunicationBlockUpdate,
    CommunicationDraft,
    CommunicationDraftCreate,
    CommunicationDraftUpdate,
    CommunicationTemplateCreate,
    CommunicationTemplateUpdate,
    RenderPreview,
    RenderRequest,
)
from ..db.communication_center_models import (
    CommunicationBlockORM,
    CommunicationDraftORM,
    CommunicationTemplateORM,
)
from ..db.orm_models import ContactORM, ContractORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from ..outbox_models import OutboxCreate
from . import outbox
from .integrations.manager import integration_manager
from .portfolio_scope import scoped_clause

VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_.-]*)\s*}}")
BLOCK_PATTERN = re.compile(r"{{\s*block:([a-z0-9][a-z0-9_.-]*)\s*}}")

STARTER_BLOCKS = [
    {"key": "salutation.standard", "name": "Anrede", "category": "standard",
     "content_template": "Guten Tag {{recipient.name}},"},
    {"key": "closing.standard", "name": "Grußformel", "category": "standard",
     "content_template": "Mit freundlichen Grüßen\n{{sender.name}}"},
    {"key": "reference.contract", "name": "Vertragsreferenz", "category": "rental",
     "content_template": "Vertragsnummer: {{contract.number}}\nObjekt: {{property.name}} · {{unit.label}}"},
]

STARTER_TEMPLATES = [
    {"name": "Allgemeines Mieterschreiben", "category": "general", "audience": "tenant",
     "channel": "universal", "subject_template": "Ihr Mietverhältnis · {{contract.number}}",
     "body_template": "{{block:salutation.standard}}\n\n{{block:reference.contract}}\n\n[Ihr Anliegen]\n\n{{block:closing.standard}}"},
    {"name": "Terminankündigung", "category": "appointment", "audience": "tenant",
     "channel": "universal", "subject_template": "Terminankündigung · {{property.name}}",
     "body_template": "{{block:salutation.standard}}\n\nwir möchten einen Termin bezüglich {{property.name}} / {{unit.label}} abstimmen.\n\n[Termin und Anlass ergänzen]\n\n{{block:closing.standard}}"},
    {"name": "Zahlungserinnerung – neutral", "category": "finance", "audience": "tenant",
     "channel": "email", "subject_template": "Bitte um Prüfung · Vertrag {{contract.number}}",
     "body_template": "{{block:salutation.standard}}\n\nbitte prüfen Sie den aktuellen Zahlungsstand zu Ihrem Vertrag {{contract.number}}. Konkrete Beträge und Fälligkeiten bitte vor Versand ergänzen und prüfen.\n\n{{block:closing.standard}}"},
    {"name": "Hinweis zur Betriebskostenabrechnung", "category": "billing", "audience": "tenant",
     "channel": "universal", "subject_template": "Betriebskosten · {{property.name}}",
     "body_template": "{{block:salutation.standard}}\n\nwir informieren Sie zur Betriebskostenabrechnung für {{property.name}} / {{unit.label}}.\n\n[Abrechnungszeitraum und konkreten Hinweis ergänzen]\n\n{{block:closing.standard}}"},
    {"name": "Allgemeines Unternehmensschreiben", "category": "business", "audience": "company",
     "channel": "universal", "subject_template": "[Betreff ergänzen]",
     "body_template": "{{block:salutation.standard}}\n\n[Nachricht ergänzen]\n\n{{block:closing.standard}}"},
]

VARIABLES = [
    ("recipient.name", "Empfängername / Firma"),
    ("recipient.email", "E-Mail-Adresse"),
    ("recipient.phone", "Telefon / Mobil"),
    ("recipient.street", "Straße und Hausnummer"),
    ("recipient.postal_code", "Postleitzahl"),
    ("recipient.city", "Ort"),
    ("recipient.country", "Land"),
    ("recipient.address", "Empfängeranschrift"),
    ("sender.name", "Absender / Firma"),
    ("sender.email", "Absender-E-Mail"),
    ("sender.street", "Absenderstraße"),
    ("sender.postal_code", "Absender-PLZ"),
    ("sender.city", "Absenderort"),
    ("contract.number", "Vertragsnummer"),
    ("contract.start_date", "Vertragsbeginn"),
    ("contract.end_date", "Vertragsende"),
    ("contract.deposit_amount", "Kaution"),
    ("unit.label", "Einheit"),
    ("unit.cold_rent", "Kaltmiete"),
    ("unit.service_charge_advance", "Nebenkostenvorauszahlung"),
    ("unit.heating_advance", "Heizkostenvorauszahlung"),
    ("property.name", "Objekt"),
    ("property.address", "Objektanschrift"),
    ("portfolio.name", "Portfolio"),
    ("portfolio.owner_name", "Absender / Eigentümer"),
    ("system.today", "Heutiges Datum"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def database(store):
    if not hasattr(store, "db"):
        raise HTTPException(503, "communication_center_requires_persistent_sql")
    return store.db


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _iso(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _money(value):
    if value is None:
        return None
    return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _date(value):
    return value.strftime("%d.%m.%Y") if value else None


def _as_template(row: CommunicationTemplateORM) -> dict:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def _as_block(row: CommunicationBlockORM) -> dict:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def _as_draft(row: CommunicationDraftORM) -> CommunicationDraft:
    values = {column.key: getattr(row, column.key) for column in row.__table__.columns
              if column.key not in {"context_json", "document_pdf"}}
    for key in ("created_at", "updated_at", "reviewed_at"):
        value = values.get(key)
        if value is not None and value.tzinfo is None:
            values[key] = value.replace(tzinfo=timezone.utc)
    return CommunicationDraft.model_validate(values)


def _commit(db):
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "communication_center_database_unavailable") from None


def list_templates(store):
    db = database(store)
    rows = db.scalars(select(CommunicationTemplateORM).order_by(
        CommunicationTemplateORM.category, CommunicationTemplateORM.name
    )).all()
    return [_as_template(row) for row in rows]


def create_template(store, data: CommunicationTemplateCreate):
    db = database(store)
    now = utcnow().replace(tzinfo=None)
    row = CommunicationTemplateORM(id=str(uuid4()), revision=1, created_at=now, updated_at=now,
                                   **data.model_dump())
    db.add(row)
    _commit(db)
    return _as_template(row)


def update_template(store, identifier: str, data: CommunicationTemplateUpdate):
    db = database(store)
    row = db.get(CommunicationTemplateORM, identifier)
    if row is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    if row.revision != data.expected_revision:
        raise HTTPException(412, "Vorlage wurde zwischenzeitlich geändert")
    for key, value in data.model_dump(exclude={"expected_revision"}).items():
        setattr(row, key, value)
    row.revision += 1
    row.updated_at = utcnow().replace(tzinfo=None)
    _commit(db)
    return _as_template(row)


def delete_template(store, identifier: str):
    db = database(store)
    row = db.get(CommunicationTemplateORM, identifier)
    if row is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    used = db.scalar(select(CommunicationDraftORM.id).where(
        CommunicationDraftORM.template_id == identifier
    ).limit(1))
    if used:
        raise HTTPException(409, "Vorlage wird von Korrespondenzen referenziert; deaktivieren statt löschen")
    db.delete(row)
    _commit(db)


def list_blocks(store):
    db = database(store)
    rows = db.scalars(select(CommunicationBlockORM).order_by(
        CommunicationBlockORM.category, CommunicationBlockORM.name
    )).all()
    return [_as_block(row) for row in rows]


def create_block(store, data: CommunicationBlockCreate):
    db = database(store)
    now = utcnow().replace(tzinfo=None)
    row = CommunicationBlockORM(id=str(uuid4()), revision=1, created_at=now, updated_at=now,
                                **data.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Baustein-Schlüssel und Sprache müssen eindeutig sein") from None
    return _as_block(row)


def update_block(store, identifier: str, data: CommunicationBlockUpdate):
    db = database(store)
    row = db.get(CommunicationBlockORM, identifier)
    if row is None:
        raise HTTPException(404, "Baustein nicht gefunden")
    if row.revision != data.expected_revision:
        raise HTTPException(412, "Baustein wurde zwischenzeitlich geändert")
    for key, value in data.model_dump(exclude={"expected_revision"}).items():
        setattr(row, key, value)
    row.revision += 1
    row.updated_at = utcnow().replace(tzinfo=None)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Baustein-Schlüssel und Sprache müssen eindeutig sein") from None
    return _as_block(row)


def delete_block(store, identifier: str):
    db = database(store)
    row = db.get(CommunicationBlockORM, identifier)
    if row is None:
        raise HTTPException(404, "Baustein nicht gefunden")
    db.delete(row)
    _commit(db)


def install_starter_library(store) -> dict:
    db = database(store)
    existing_blocks = {
        (row.key, row.locale)
        for row in db.scalars(select(CommunicationBlockORM)).all()
    }
    existing_templates = {
        (row.name, row.locale)
        for row in db.scalars(select(CommunicationTemplateORM)).all()
    }
    blocks_added = 0
    templates_added = 0
    for values in STARTER_BLOCKS:
        key = (values["key"], "de-DE")
        if key not in existing_blocks:
            create_block(store, CommunicationBlockCreate.model_validate(values))
            existing_blocks.add(key)
            blocks_added += 1
    for values in STARTER_TEMPLATES:
        key = (values["name"], "de-DE")
        if key not in existing_templates:
            create_template(store, CommunicationTemplateCreate.model_validate(values))
            existing_templates.add(key)
            templates_added += 1
    return {
        "blocks_added": blocks_added,
        "templates_added": templates_added,
        "blocks_total": len(list_blocks(store)),
        "templates_total": len(list_templates(store)),
    }


def _portfolio(db, portfolio_id: str) -> PortfolioORM:
    query = select(PortfolioORM).where(PortfolioORM.id == portfolio_id)
    predicate = scoped_clause(PortfolioORM)
    if predicate is not None:
        query = query.where(predicate)
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, "Portfolio nicht gefunden")
    return row


def _recipient(db, recipient_type: str, recipient_id: str):
    model = TenantORM if recipient_type == "tenant" else ContactORM
    row = db.get(model, recipient_id)
    if row is None:
        raise HTTPException(404, "Empfänger nicht gefunden")
    if recipient_type == "tenant":
        return row, {
            "name": row.full_name,
            "email": row.email,
            "phone": row.phone,
            "street": row.address_line,
            "postal_code": row.postal_code,
            "city": row.city,
            "country": row.country or "DE",
            "address": "\n".join(filter(None, [
                row.address_line,
                " ".join(filter(None, [row.postal_code, row.city])),
                row.country if row.country not in (None, "", "DE", "Deutschland") else None,
            ])),
        }
    name = row.company_name or " ".join(filter(None, [row.first_name, row.last_name]))
    return row, {
        "name": name.strip(),
        "email": row.email,
        "phone": row.mobile or row.phone,
        "street": row.street,
        "postal_code": row.zip_code,
        "city": row.city,
        "country": row.country or "DE",
        "address": "\n".join(filter(None, [
            row.street,
            " ".join(filter(None, [row.zip_code, row.city])),
            row.country if row.country not in (None, "", "DE", "Deutschland") else None,
        ])),
    }


def _sender_context(channel: str | None, portfolio: PortfolioORM) -> dict:
    sender = {
        "name": portfolio.owner_name or portfolio.name,
        "email": None, "street": None, "postal_code": None, "city": None,
    }
    integration_id = "email" if channel == "email" else "deutsche-post" if channel == "post" else None
    if integration_id is None:
        return sender
    try:
        config = integration_manager.get_integration(integration_id).get("config", {})
    except KeyError:
        return sender
    if channel == "email":
        sender.update(name=config.get("sender_name") or sender["name"], email=config.get("sender_email"))
    else:
        sender.update(
            name=config.get("sender_name") or sender["name"], street=config.get("sender_street"),
            postal_code=config.get("sender_zip_code"), city=config.get("sender_city"),
        )
    return sender


def _contract_context(db, recipient_type: str, recipient_id: str, contract_id: str | None):
    contract = None
    if contract_id:
        contract = db.get(ContractORM, contract_id)
        if contract is None:
            raise HTTPException(404, "Vertrag nicht gefunden")
        if recipient_type == "tenant" and contract.tenant_id != recipient_id:
            raise HTTPException(409, "Vertrag gehört nicht zur ausgewählten Mietpartei")
    elif recipient_type == "tenant":
        active = db.scalars(select(ContractORM).where(
            ContractORM.tenant_id == recipient_id, ContractORM.status == "active"
        )).all()
        if len(active) == 1:
            contract = active[0]
        elif len(active) > 1:
            raise HTTPException(409, "Mehrere aktive Verträge: Vertrag ausdrücklich auswählen")
    if contract is None:
        return None, None, None
    unit = db.get(UnitORM, contract.unit_id)
    property_row = db.get(PropertyORM, contract.property_id)
    if unit is None or property_row is None or unit.property_id != property_row.id:
        raise HTTPException(409, "Vertragsbezug ist unvollständig oder widersprüchlich")
    return contract, unit, property_row


def _validate_draft_references(db, portfolio_id, recipient_type, recipient_id, contract_id):
    portfolio = _portfolio(db, portfolio_id)
    _recipient(db, recipient_type, recipient_id)
    if recipient_type != "tenant" and contract_id:
        raise HTTPException(422, "Ein Vertragsbezug ist nur für Mietparteien zulässig")
    if not contract_id:
        return
    _, _, property_row = _contract_context(db, recipient_type, recipient_id, contract_id)
    if property_row is None or property_row.portfolio_id != portfolio.id:
        raise HTTPException(409, "Vertrag und ausgewähltes Portfolio stimmen nicht überein")


def resolve_context(store, portfolio_id: str, request: RenderRequest) -> tuple[dict, dict]:
    db = database(store)
    portfolio = _portfolio(db, portfolio_id)
    _, recipient = _recipient(db, request.recipient_type, request.recipient_id)
    contract, unit, property_row = _contract_context(
        db, request.recipient_type, request.recipient_id, request.contract_id
    )
    if property_row is not None and property_row.portfolio_id != portfolio.id:
        raise HTTPException(409, "Vertrag und ausgewähltes Portfolio stimmen nicht überein")
    sender = _sender_context(request.channel, portfolio)
    context = {
        "recipient": recipient,
        "sender": sender,
        "tenant": recipient if request.recipient_type == "tenant" else {},
        "contact": recipient if request.recipient_type == "contact" else {},
        "contract": {} if contract is None else {
            "number": contract.contract_number,
            "start_date": _date(contract.start_date),
            "end_date": _date(contract.end_date),
            "status": contract.status,
            "deposit_amount": _money(contract.deposit_amount),
        },
        "unit": {} if unit is None else {
            "label": unit.label,
            "area_sqm": unit.area_sqm,
            "cold_rent": _money(unit.cold_rent),
            "service_charge_advance": _money(unit.service_charge_advance),
            "heating_advance": _money(unit.heating_advance),
        },
        "property": {} if property_row is None else {
            "name": property_row.name,
            "address_line": property_row.address_line,
            "postal_code": property_row.postal_code,
            "city": property_row.city,
            "country": property_row.country,
            "address": " ".join(filter(None, [
                property_row.address_line,
                " ".join(filter(None, [property_row.postal_code, property_row.city])),
            ])),
        },
        "portfolio": {
            "name": portfolio.name,
            "owner_name": portfolio.owner_name,
            "currency": portfolio.currency,
            "timezone": portfolio.timezone,
        },
        "system": {"today": date.today().strftime("%d.%m.%Y")},
    }
    return context, recipient


def _value(context: dict, path: str):
    node = context
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _expand_blocks(db, text: str, locale: str) -> str:
    for _ in range(8):
        keys = BLOCK_PATTERN.findall(text)
        if not keys:
            return text
        mapping = {}
        for key in set(keys):
            row = db.scalar(select(CommunicationBlockORM).where(
                CommunicationBlockORM.key == key,
                CommunicationBlockORM.locale == locale,
                CommunicationBlockORM.is_active.is_(True),
            ))
            if row is None:
                raise HTTPException(422, f"Unbekannter oder inaktiver Baustein: {key}")
            mapping[key] = row.content_template
        text = BLOCK_PATTERN.sub(lambda match: mapping[match.group(1)], text)
    raise HTTPException(422, "Bausteine enthalten eine zyklische oder zu tiefe Verschachtelung")


def _render_text(context: dict, text: str) -> tuple[str, list[str]]:
    missing = []
    def replace(match):
        key = match.group(1)
        value = _value(context, key)
        if value in (None, ""):
            missing.append(key)
            return f"⟦FEHLT: {key}⟧"
        return str(value)
    return VARIABLE_PATTERN.sub(replace, text), sorted(set(missing))


def _source(db, request: RenderRequest):
    subject = request.subject_template
    body = request.body_template
    locale = "de-DE"
    if request.template_id:
        template = db.get(CommunicationTemplateORM, request.template_id)
        if template is None or not template.is_active:
            raise HTTPException(404, "Vorlage nicht gefunden oder inaktiv")
        expected_audience = "tenant" if request.recipient_type == "tenant" else "company"
        if template.audience not in {"any", expected_audience}:
            raise HTTPException(422, "Vorlage passt nicht zur ausgewählten Empfängerart")
        if request.channel and template.channel not in {"universal", request.channel}:
            raise HTTPException(422, "Vorlage passt nicht zum ausgewählten Versandkanal")
        locale = template.locale
        subject = template.subject_template if subject is None else subject
        body = template.body_template if body is None else body
    if body is None or not body.strip():
        raise HTTPException(422, "Dokumentinhalt fehlt")
    return subject or "", body, locale


def preview(store, portfolio_id: str, request: RenderRequest) -> RenderPreview:
    db = database(store)
    context, recipient = resolve_context(store, portfolio_id, request)
    subject_source, body_source, locale = _source(db, request)
    subject_source = _expand_blocks(db, subject_source, locale)
    body_source = _expand_blocks(db, body_source, locale)
    subject, missing_subject = _render_text(context, subject_source)
    body, missing_body = _render_text(context, body_source)
    missing = sorted(set(missing_subject + missing_body))
    warnings = []
    if request.recipient_type == "tenant" and not context["contract"]:
        warnings.append("Kein eindeutiger aktiver Vertrag gefunden; Vertragsvariablen stehen nicht zur Verfügung.")
    return RenderPreview(
        subject=subject, body=body, recipient=recipient, context=context,
        context_sha256=digest(canonical(context)), missing_fields=missing, warnings=warnings,
    )


def _pdf(snapshot: RenderPreview, title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=72 * mm, bottomMargin=24 * mm,
        title=title, author="ImmoManager Pro",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "LetterBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=10.5, leading=15, alignment=TA_LEFT, spaceAfter=7,
    )
    subject_style = ParagraphStyle(
        "LetterSubject", parent=body_style, fontName="Helvetica-Bold",
        fontSize=11.5, leading=15, spaceAfter=14,
    )
    context = snapshot.context
    recipient = snapshot.recipient

    def first_page(canvas, document):
        width, height = A4
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(25 * mm, height - 20 * mm, context["portfolio"].get("name") or "ImmoManager Pro")
        canvas.setFont("Helvetica", 7)
        sender = context.get("sender", {})
        sender_line = " · ".join(filter(None, [
            sender.get("name"), sender.get("street"),
            " ".join(filter(None, [sender.get("postal_code"), sender.get("city")])),
            sender.get("email"),
        ]))
        canvas.drawString(25 * mm, height - 42 * mm, sender_line[:125])
        canvas.setFont("Helvetica", 10)
        y = height - 48 * mm
        for line in [recipient.get("name"), recipient.get("street"),
                     " ".join(filter(None, [recipient.get("postal_code"), recipient.get("city")])),
                     recipient.get("country") if recipient.get("country") not in (None, "", "DE", "Deutschland") else None]:
            if line:
                canvas.drawString(25 * mm, y, str(line)[:100])
                y -= 5 * mm
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(width - 25 * mm, height - 65 * mm, context["system"]["today"])
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(
            width / 2, 12 * mm,
            f"ImmoManager Pro · geprüfter Korrespondenz-Snapshot · Seite {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    def later_page(canvas, document):
        width, height = A4
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(
            25 * mm, height - 20 * mm,
            context["portfolio"].get("name") or "ImmoManager Pro",
        )
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(
            width / 2, 12 * mm,
            f"ImmoManager Pro · geprüfter Korrespondenz-Snapshot · Seite {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    story = []
    if snapshot.subject.strip():
        story.append(Paragraph(escape(snapshot.subject), subject_style))
    for paragraph in re.split(r"\n\s*\n", snapshot.body.strip()):
        safe = "<br/>".join(escape(line) for line in paragraph.splitlines())
        story.extend([Paragraph(safe, body_style), Spacer(1, 2 * mm)])
    doc.build(story, onFirstPage=first_page, onLaterPages=later_page)
    return buffer.getvalue()


def list_drafts(store, portfolio_id: str):
    db = database(store)
    _portfolio(db, portfolio_id)
    rows = db.scalars(select(CommunicationDraftORM).where(
        CommunicationDraftORM.portfolio_id == portfolio_id
    ).order_by(CommunicationDraftORM.updated_at.desc(), CommunicationDraftORM.id.desc())).all()
    return [_as_draft(row) for row in rows]


def get_draft(store, identifier: str):
    db = database(store)
    row = db.get(CommunicationDraftORM, identifier)
    if row is None:
        raise HTTPException(404, "Korrespondenz nicht gefunden")
    _portfolio(db, row.portfolio_id)
    return row


def create_draft(store, data: CommunicationDraftCreate, actor_id: str):
    db = database(store)
    _validate_draft_references(
        db, data.portfolio_id, data.recipient_type, data.recipient_id, data.contract_id
    )
    source = RenderRequest(**data.model_dump(include={
        "recipient_type", "recipient_id", "channel", "contract_id", "template_id",
        "subject_template", "body_template",
    }))
    subject, body, _ = _source(db, source)
    template_revision = (
        db.get(CommunicationTemplateORM, data.template_id).revision if data.template_id else None
    )
    now = utcnow().replace(tzinfo=None)
    row = CommunicationDraftORM(
        id=str(uuid4()), portfolio_id=data.portfolio_id, title=data.title,
        channel=data.channel, recipient_type=data.recipient_type, recipient_id=data.recipient_id,
        contract_id=data.contract_id, template_id=data.template_id,
        template_revision=template_revision,
        subject_template=subject, body_template=body, status="draft", revision=1,
        created_by=actor_id, whatsapp_template_name=data.whatsapp_template_name,
        whatsapp_language_code=data.whatsapp_language_code,
        created_at=now, updated_at=now,
    )
    db.add(row)
    _commit(db)
    return _as_draft(row)


def update_draft(store, identifier: str, data: CommunicationDraftUpdate):
    db = database(store)
    row = get_draft(store, identifier)
    if row.status != "draft":
        raise HTTPException(409, "Freigegebene Korrespondenz ist unveränderlich")
    if row.revision != data.expected_revision:
        raise HTTPException(412, "Korrespondenz wurde zwischenzeitlich geändert")
    changes = data.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if "template_id" in changes:
        if changes["template_id"]:
            request = RenderRequest(
                recipient_type=changes.get("recipient_type", row.recipient_type),
                recipient_id=changes.get("recipient_id", row.recipient_id),
                channel=changes.get("channel", row.channel),
                contract_id=changes.get("contract_id", row.contract_id),
                template_id=changes["template_id"],
            )
            template_subject, template_body, _ = _source(db, request)
            template_row = db.get(CommunicationTemplateORM, changes["template_id"])
            changes["template_revision"] = template_row.revision
            changes.setdefault("subject_template", template_subject)
            changes.setdefault("body_template", template_body)
        else:
            changes["template_revision"] = None
    recipient_type = changes.get("recipient_type", row.recipient_type)
    recipient_id = changes.get("recipient_id", row.recipient_id)
    contract_id = changes.get("contract_id", row.contract_id)
    channel = changes.get("channel", row.channel)
    _validate_draft_references(db, row.portfolio_id, recipient_type, recipient_id, contract_id)
    _source(db, RenderRequest(
        recipient_type=recipient_type, recipient_id=recipient_id, channel=channel,
        contract_id=contract_id, template_id=changes.get("template_id", row.template_id),
        subject_template=changes.get("subject_template", row.subject_template),
        body_template=changes.get("body_template", row.body_template),
    ))
    for key, value in changes.items():
        setattr(row, key, value)
    row.revision += 1
    row.updated_at = utcnow().replace(tzinfo=None)
    _commit(db)
    return _as_draft(row)


def review_draft(store, identifier: str, expected_revision: int, actor_id: str):
    db = database(store)
    row = get_draft(store, identifier)
    if row.status != "draft":
        raise HTTPException(409, "Korrespondenz ist bereits freigegeben")
    if row.revision != expected_revision:
        raise HTTPException(412, "Korrespondenz wurde zwischenzeitlich geändert")
    request = RenderRequest(
        recipient_type=row.recipient_type, recipient_id=row.recipient_id, channel=row.channel,
        contract_id=row.contract_id, template_id=row.template_id,
        subject_template=row.subject_template, body_template=row.body_template,
    )
    rendered = preview(store, row.portfolio_id, request)
    if rendered.missing_fields:
        raise HTTPException(409, {
            "code": "communication_missing_data",
            "missing_fields": rendered.missing_fields,
        })
    if row.recipient_type == "tenant" and not rendered.context.get("contract"):
        raise HTTPException(
            409, "Mieterkorrespondenz erfordert einen eindeutigen oder ausdrücklich gewählten Vertrag"
        )
    recipient = rendered.recipient
    sender = rendered.context.get("sender", {})
    if row.channel == "email":
        if not recipient.get("email"):
            raise HTTPException(409, "Für E-Mail fehlt eine Empfängeradresse")
        if not sender.get("email"):
            raise HTTPException(409, "Für E-Mail fehlt eine konfigurierte Absenderadresse")
    if row.channel == "whatsapp":
        if not recipient.get("phone"):
            raise HTTPException(409, "Für WhatsApp fehlt eine Mobil-/Telefonnummer")
        if not row.whatsapp_template_name:
            raise HTTPException(409, "WhatsApp-Korrespondenz erfordert ein freigegebenes Meta-Template")
    if row.channel == "post":
        if not all(recipient.get(key) for key in ("name", "street", "postal_code", "city")):
            raise HTTPException(409, "Für Briefversand ist die Empfängeranschrift unvollständig")
        if not all(sender.get(key) for key in ("name", "street", "postal_code", "city")):
            raise HTTPException(409, "Für Briefversand ist die konfigurierte Absenderanschrift unvollständig")
    snapshot = {
        "subject": rendered.subject, "body": rendered.body, "context": rendered.context,
        "recipient": rendered.recipient, "channel": row.channel,
        "template_id": row.template_id, "template_revision": row.template_revision,
        "whatsapp_template_name": row.whatsapp_template_name,
        "whatsapp_language_code": row.whatsapp_language_code,
    }
    pdf = _pdf(rendered, row.title)
    now = utcnow().replace(tzinfo=None)
    row.rendered_subject = rendered.subject
    row.rendered_body = rendered.body
    row.context_json = canonical(rendered.context)
    row.context_sha256 = rendered.context_sha256
    row.snapshot_sha256 = digest(canonical(snapshot))
    row.document_pdf = pdf
    row.pdf_sha256 = digest(pdf)
    row.status = "reviewed"
    row.reviewed_by = actor_id
    row.reviewed_at = now
    row.revision += 1
    row.updated_at = now
    _commit(db)
    return _as_draft(row)


def pdf_bytes(store, identifier: str) -> tuple[bytes, str]:
    row = get_draft(store, identifier)
    if row.status == "draft" or row.document_pdf is None:
        raise HTTPException(409, "Dokument muss vor PDF-Download freigegeben werden")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", row.title).strip("_") or "korrespondenz"
    return row.document_pdf, f"{safe}.pdf"


def dispatch_email(store, row: CommunicationDraftORM, actor_id: str):
    if row.status not in {"reviewed", "queued"}:
        raise HTTPException(409, "Nur freigegebene Korrespondenz kann versendet werden")
    context = json.loads(row.context_json or "{}")
    recipient = context.get("recipient", {})
    enabled, config = outbox.configuration()
    if not enabled:
        raise HTTPException(409, "SMTP-Integration ist deaktiviert")
    sender = context.get("sender", {})
    if (sender.get("email"), sender.get("name")) != (config.from_address, config.from_name):
        raise HTTPException(
            409, "SMTP-Absender wurde seit der Freigabe geändert; Dokument erneut prüfen und freigeben"
        )
    command = OutboxCreate(
        portfolio_id=row.portfolio_id,
        idempotency_key=f"communication:{row.id}:{row.snapshot_sha256}",
        recipient=recipient["email"],
        sender_address=config.from_address,
        sender_name=config.from_name,
        subject=row.rendered_subject or "",
        body_text=row.rendered_body or "",
        reviewed_by=row.reviewed_by or actor_id,
        review_confirmed=True,
    )
    result = outbox.create_message(store, command, actor_id)
    row.external_reference = result["id"]
    row.external_status = result["state"]
    row.status = "queued"
    row.updated_at = utcnow().replace(tzinfo=None)
    _commit(database(store))
    return result


def dispatch_external(store, row: CommunicationDraftORM, action: str, test_mode: bool):
    if row.status != "reviewed":
        raise HTTPException(409, "Externe Übergabe erfordert einen unveränderten freigegebenen Snapshot")
    context = json.loads(row.context_json or "{}")
    recipient = context.get("recipient", {})
    if action == "whatsapp":
        if not row.whatsapp_template_name:
            raise HTTPException(409, "WhatsApp-Korrespondenz besitzt kein freigegebenes Meta-Template")
        payload = {
            "action": "template",
            "to": recipient.get("phone"),
            "text": row.rendered_body,
            "template_name": row.whatsapp_template_name,
            "language_code": row.whatsapp_language_code,
        }
        provider = "whatsapp"
    elif action == "post":
        current = integration_manager.get_integration("deutsche-post")
        config_sender = current.get("config", {})
        reviewed_sender = context.get("sender", {})
        expected_sender = {
            "name": config_sender.get("sender_name"),
            "street": config_sender.get("sender_street"),
            "postal_code": config_sender.get("sender_zip_code"),
            "city": config_sender.get("sender_city"),
        }
        if any(reviewed_sender.get(key) != value for key, value in expected_sender.items()):
            raise HTTPException(
                409, "E-POST-Absender wurde seit der Freigabe geändert; Dokument erneut prüfen und freigeben"
            )
        payload = {
            "action": "send",
            "filename": f"communication-{row.id}.pdf",
            "pdf_base64": __import__("base64").b64encode(row.document_pdf or b"").decode("ascii"),
            "recipient": recipient,
            "sender": context.get("sender", {}),
            "test_mode": test_mode,
            "pdfa_validated": False,
            "reference": row.id,
        }
        provider = "deutsche-post"
    else:
        raise HTTPException(422, "Unbekannter Versandkanal")
    result = integration_manager.run(provider, payload)
    if not result.get("success"):
        raise HTTPException(502, result)
    row.external_reference = str((result.get("details") or {}).get("external_reference") or "")
    row.external_status = "accepted"
    row.status = "queued"
    row.updated_at = utcnow().replace(tzinfo=None)
    _commit(database(store))
    return provider, result


def catalog(store):
    return {
        "variables": [{"key": key, "label": label} for key, label in VARIABLES],
        "channels": [
            {"id": "email", "label": "E-Mail", "mode": "reviewed_outbox"},
            {"id": "post", "label": "Deutsche Post / E-POST", "mode": "test_safe"},
            {"id": "whatsapp", "label": "WhatsApp Cloud API", "mode": "explicit"},
        ],
        "blocks": list_blocks(store),
        "templates": list_templates(store),
    }
