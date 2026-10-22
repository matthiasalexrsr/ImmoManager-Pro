"""Letters to a tenant from a template: compose, review as PDF, archive one immutable original.

The flow follows the billing letters: `context` names the templates and the letters
already archived for the contract, `compose` fills a template for the contract's
current source, the client may edit every text, `preview` renders the PDF and
returns its checksum, and `publish` archives exactly that PDF as a document of
type `template_letter`, bound to property, unit, contract and tenant. The same
command key always names the same document; a letter with an error-level check is
a draft and cannot be archived. Nothing is sent.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import insert, select, text

from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import ContractORM, DocumentORM, PropertyORM, TenantORM, UnitORM, UtilityStatementORM
from ..domain.clock import local_today
from ..models import Document, DocumentCreate
from ..permissions import may_write
from ..storage import NotFoundError
from . import document_versions as archive
from . import letter_templates as templates
from . import letterhead, price_index
from .contract_letter_types import ComposeRequest, LetterPreview, LetterPublish
from .contract_letter_validation import (
    DOC_TYPE,
    FORMAT_VERSION,
    SCHEMA_VERSION,
    VIRTUAL_PREFIX,
    digest,
    document_id_for,
    request_hash,
    validate_contract_letter_snapshot,
)
from .letter_layout import block_names, render_letter
from .portfolio_scope import scope_context, scope_from_user
from .rent_history import rent_steps
from .workspace_contexts import bound_actor, resolve_context

TEXT_FIELDS = (("subject", "Betreff"), ("salutation", "Anrede"), ("body", "Text"), ("closing", "Schlussformel"),
               ("appendix", "Anhang"))


def write_areas(contract_id: str) -> tuple[str, str]:
    return (f"/contracts/{contract_id}/letters", archive.DOCUMENTS_AREA)


@contextmanager
def work(store, actor_id, contract_id=None, *, write=False, command_key=None):
    with archive.work(store, actor_id, write_areas=write_areas(contract_id) if write else ()) as unit:
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            try:
                if write and command_key is not None and unit.db is not None \
                        and unit.db.get_bind().dialect.name == "postgresql":
                    # Same key, same document: serialize the actor's key before any parent lock.
                    key = hashlib.sha256(("immo:template-letter:" + actor_id + ":" + command_key).encode()).digest()
                    unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                                    {"key": int.from_bytes(key[:8], "big", signed=True)})
                yield unit
            except NotFoundError:
                raise HTTPException(404, "Vertrag oder zugehörige Akte nicht gefunden.") from None


_today = local_today


def _pick(row, keys):
    return row.model_dump(mode="json", include=set(keys))


def _parents(unit, contract_id: str, *, lock: bool = False):
    resolve_context(unit.store, "contract", contract_id, unit.actor_id)
    contract = unit.store.get_contract(contract_id)
    if lock and unit.db is not None:
        before = (contract.property_id, contract.unit_id, contract.tenant_id)
        for model, key in ((TenantORM, contract.tenant_id), (PropertyORM, contract.property_id),
                           (UnitORM, contract.unit_id), (ContractORM, contract.id)):
            if unit.db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                raise HTTPException(404, "Vertrag oder Zuordnung nicht mehr vorhanden.")
        unit.db.expire_all()
        contract = unit.store.get_contract(contract_id)
        if before != (contract.property_id, contract.unit_id, contract.tenant_id):
            raise HTTPException(409, "Die Vertragszuordnung wurde gleichzeitig geändert. Bitte neu laden.")
        resolve_context(unit.store, "contract", contract_id, unit.actor_id)
    prop = unit.store.get_property(contract.property_id)
    location = unit.store.get_unit(contract.unit_id)
    tenant = unit.store.get_tenant(contract.tenant_id)
    portfolio = unit.store.get_portfolio(prop.portfolio_id)
    if location.property_id != prop.id:
        raise HTTPException(409, "Einheit und Objekt des Vertrags passen nicht zusammen. Bitte den Bestand prüfen.")
    return contract, prop, location, tenant, portfolio


def _statement(unit, contract_id: str) -> dict | None:
    """The contract's latest issued tenant statement (not a superseded version)."""
    if unit.db is not None:
        rows = list(unit.db.scalars(select(UtilityStatementORM.id).where(UtilityStatementORM.contract_id == contract_id)))
        statements = [unit.store.get_utility_statement(identifier) for identifier in rows]
    else:
        statements = [row for row in unit.store.list_utility_statements() if row.contract_id == contract_id]
    found = []
    for statement in statements:
        if statement.party != "tenant":
            continue
        period = unit.store.get_billing_period(statement.billing_period_id)
        if period.status in templates.ISSUED_STATUSES:
            found.append((period.end_date, period.id, statement, period))
    if not found:
        return None
    _, _, statement, period = max(found, key=lambda item: (item[0], item[1]))
    start, end = statement.usage_start or period.start_date, statement.usage_end or period.end_date
    days = statement.usage_days or (end - start).days + 1
    return {"id": statement.id, "billing_period_id": period.id, "label": period.label,
            "start": start.isoformat(), "end": end.isoformat(), "usage_days": days,
            "months": round(days * 12 / 365.25, 2), "total_cost": str(statement.total_cost),
            "advance_paid": str(statement.advance_paid), "balance": str(statement.balance),
            "issued_on": statement.delivered_at.date().isoformat() if statement.delivered_at else None}


def _source(unit, contract_id: str, *, lock: bool = False):
    contract, prop, location, tenant, portfolio = _parents(unit, contract_id, lock=lock)
    steps = [{"valid_from": step.valid_from.isoformat(), "cold_rent": str(step.charge.cold_rent),
              "service_charge_advance": str(step.charge.service_charge_advance),
              "heating_advance": str(step.charge.heating_advance)} for step in rent_steps(unit.store, contract)]
    source = {
        "contract": _pick(contract, ("id", "contract_number", "property_id", "unit_id", "tenant_id", "status",
                                     "start_date", "end_date", "notice_period", "deposit_amount", "index_rent",
                                     "persons", "updated_at")),
        "tenant": _pick(tenant, ("id", "full_name", "address_line", "postal_code", "city", "country", "updated_at")),
        "unit": _pick(location, ("id", "property_id", "label", "unit_type", "area_sqm", "rooms", "floor", "updated_at")),
        "property": _pick(prop, ("id", "portfolio_id", "name", "address_line", "postal_code", "city", "country",
                                 "updated_at")),
        "portfolio": _pick(portfolio, ("id", "name", "owner_name", "updated_at")),
        "rent_steps": steps,
        "statement": _statement(unit, contract.id),
        "letterhead": letterhead.source(unit, prop.id, fallback_sender=portfolio.owner_name or portfolio.name),
        "price_index": {key: value for key, value in price_index.read(unit).items() if key != "revision"},
    }
    return source, contract, prop, location, tenant


def _recipient_address(source: dict) -> str:
    def lines(row):
        city = " ".join(part for part in (row.get("postal_code"), row.get("city")) if part)
        country = (row.get("country") or "").strip()
        return "\n".join(part for part in (row.get("address_line"), city,
                                           "" if country.casefold() in ("de", "deutschland", "germany") else country)
                         if part)
    tenant = source["tenant"]
    if tenant.get("address_line") and (tenant.get("postal_code") or tenant.get("city")):
        return lines(tenant)
    return lines({**source["property"], "country": None})


def _info(source: dict) -> list[list[str]]:
    return [["Mietvertrag", source["contract"]["contract_number"]],
            ["Objekt", f"{source['property']['name']}, {source['unit']['label']}"]]


def _public(row) -> dict:
    proof = validate_contract_letter_snapshot(row, row.metadata_snapshot)
    review = proof["review"]
    return {"document_id": row.document_id, "version_id": row.id, "review_hash": proof["review_hash"],
            "pdf_sha256": row.sha256, "file_url": row.metadata_snapshot["file_url"],
            "download_url": "/files/download?key=" + quote(VIRTUAL_PREFIX + row.document_id + ".pdf", safe=""),
            "contract_id": review["source"]["contract"]["id"], "subject": review["data"]["subject"],
            "issue_date": review["data"]["issue_date"], "template": review["template"],
            "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()}


def _verified(unit, document):
    if document.document_type != DOC_TYPE:
        raise HTTPException(404, "Brief nicht gefunden.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Der archivierte Brief ist unvollständig.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    return archive.original_bytes(unit, row), row


def _originals(unit, contract_id: str) -> list[dict]:
    if unit.db is not None:
        rows = list(unit.db.scalars(select(DocumentVersionORM).where(
            DocumentVersionORM.contract_id == contract_id, DocumentVersionORM.number == 1,
            DocumentVersionORM.metadata_snapshot["document_type"].as_string() == DOC_TYPE,
        ).order_by(DocumentVersionORM.created_at.desc(), DocumentVersionORM.id.desc())))
    else:
        rows = sorted((row for row in archive.memory_archive(unit.store).versions.values()
                       if row.contract_id == contract_id and row.number == 1
                       and row.metadata_snapshot.get("document_type") == DOC_TYPE),
                      key=lambda row: (row.created_at, row.id), reverse=True)
    result = []
    for row in rows:
        try:
            document = unit.store.get_document(row.document_id)
        except NotFoundError:
            continue        # the document was deleted with its archive; nothing to show
        _verified(unit, document)
        result.append(_public(row))
    return result


def context(store, contract_id: str, actor_id: str) -> dict:
    with work(store, actor_id) as unit:
        source, contract, prop, *_ = _source(unit, contract_id)
        head = source["letterhead"]
        warnings = []
        if not head["sender_address"]:
            warnings.append("Im Briefkopf fehlt die Absenderanschrift (Einstellungen → Briefkopf).")
        if not head["bank"]:
            warnings.append("Im Briefkopf fehlt die Bankverbindung; Briefe mit Zahlungsbitte nennen dann kein Konto.")
        return {"source_revision": digest(source), "contract_id": contract.id,
                "can_publish": all(may_write(unit.user["role"], path) for path in write_areas(contract_id)),
                "templates": templates.all_templates(unit), **templates.catalogue(),
                "letterhead": {key: head[key] for key in ("sender_name", "sender_address", "contact", "bank", "footer")}
                | {"has_logo": head["logo"] is not None},
                "warnings": warnings, "originals": _originals(unit, contract_id)}


def _defaults(source: dict, template: dict, issue: date) -> dict:
    head = source["letterhead"]
    return {"recipient_name": source["tenant"]["full_name"], "recipient_address": _recipient_address(source),
            "issue_date": issue.isoformat(), "signature": head.get("signature") or head.get("sender_name") or ""}


def compose(store, contract_id: str, request: ComposeRequest, actor_id: str) -> dict:
    """A template filled for this contract: suggested inputs, and with complete inputs the text and checks."""
    with work(store, actor_id) as unit:
        source, *_ = _source(unit, contract_id)
        template = templates.template(unit, request.template_id)
        if template.get("archived"):
            raise HTTPException(409, "Diese Vorlage ist archiviert. Bitte eine andere wählen.")
        kind = template["kind"]
        issue = request.issue_date or _today()
        result: dict[str, Any] = {"source_revision": digest(source),
                                  "template": {key: template[key] for key in ("id", "revision", "kind", "name")},
                                  "data": None, "checks": [], "blocks": {}}
        if request.inputs is None:
            suggested = templates.default_inputs(kind, source, issue)
            result["inputs"] = suggested
            complete = all(suggested.get(field["key"]) not in (None, "") or not field["required"]
                           for field in templates.KINDS[kind]["inputs"])
            if not complete:
                return result
            inputs = templates.parse_inputs(kind, suggested)
        else:
            inputs = templates.parse_inputs(kind, request.inputs)
            result["inputs"] = inputs
        evaluated = templates.evaluate(kind, source, inputs, issue)
        filled = {field: templates.fill(template[field], kind, evaluated["values"]) for field, _ in TEXT_FIELDS}
        result.update({"data": {**_defaults(source, template, issue), **filled},
                       "checks": evaluated["checks"], "blocks": evaluated["blocks"]})
        return result


def _review(unit, contract_id: str, payload: LetterPreview, *, lock: bool = False):
    source, contract, prop, location, tenant = _source(unit, contract_id, lock=lock)
    if digest(source) != payload.source_revision:
        raise HTTPException(412, "Vertrag, Mieter, Miete oder Briefkopf wurden geändert. Bitte den Brief neu laden.")
    template = templates.template(unit, payload.template_id)
    kind = template["kind"]
    inputs = templates.parse_inputs(kind, payload.inputs)
    data = payload.data
    evaluated = templates.evaluate(kind, source, inputs, data.issue_date)
    checks = list(evaluated["checks"])
    for field, label in TEXT_FIELDS:
        for problem in templates.text_problems(kind, getattr(data, field), field=label, filled=True):
            checks.append({"level": "error", "text": problem})
    used = block_names(data.body) + block_names(data.appendix)
    for name in used:
        if name not in evaluated["blocks"]:
            checks.append({"level": "error", "text": f"Die Tabelle „tabelle.{name}“ ist für diesen Brief nicht verfügbar."})
    blocks = {name: evaluated["blocks"][name] for name in used if name in evaluated["blocks"]}
    draft = any(check["level"] == "error" for check in checks)
    review = {"format_version": FORMAT_VERSION, "source": source, "source_revision": payload.source_revision,
              "template": {key: template[key] for key in ("id", "revision", "kind", "name")},
              "inputs": inputs, "data": data.model_dump(mode="json"), "checks": checks, "blocks": blocks,
              "draft": draft}
    logo = letterhead.logo_bytes(unit, prop.id)
    expected = source["letterhead"]["logo"]
    if (logo is None) != (expected is None) or (logo is not None and hashlib.sha256(logo).hexdigest() != expected["sha256"]):
        raise HTTPException(412, "Der Briefkopf wurde geändert. Bitte den Brief neu laden.")
    letter = {**review["data"], "info": _info(source)}
    raw = render_letter(letter, source["letterhead"], logo, draft=draft, blocks=blocks)
    review["pdf_sha256"] = hashlib.sha256(raw).hexdigest()
    return review, digest(review), raw, contract, prop, location, tenant


def preview(store, contract_id: str, payload: LetterPreview, actor_id: str) -> dict:
    with work(store, actor_id) as unit:
        review, review_hash, raw, *_ = _review(unit, contract_id, payload)
        return {"review_hash": review_hash, "pdf_sha256": review["pdf_sha256"], "review": review,
                "size_bytes": len(raw), "state": "preview"}


def preview_pdf(store, contract_id: str, payload: LetterPreview, actor_id: str):
    with work(store, actor_id) as unit:
        review, review_hash, raw, *_ = _review(unit, contract_id, payload)
        return raw, review["pdf_sha256"], review_hash


def publish(store, contract_id: str, payload: LetterPublish, actor_id: str) -> dict:
    identifier, command_hash = document_id_for(actor_id, payload.idempotency_key), request_hash(contract_id, payload)
    with work(store, actor_id, contract_id, write=True, command_key=payload.idempotency_key) as unit:
        _parents(unit, contract_id, lock=True)
        try:
            existing = unit.store.get_document(identifier)
        except NotFoundError:
            existing = None
        if existing:
            _, row = _verified(unit, existing)
            proof = validate_contract_letter_snapshot(row, row.metadata_snapshot)
            if (row.request_sha256 != command_hash or row.actor_id != actor_id
                    or proof["review"]["source"]["contract"]["id"] != contract_id):
                raise HTTPException(409, "Die Vorgangskennung wurde bereits mit anderen Briefeingaben verwendet.")
            return _public(row)
        review, shown_hash, raw, contract, prop, location, tenant = _review(unit, contract_id, payload, lock=True)
        if review["draft"]:
            problems = [check["text"] for check in review["checks"] if check["level"] == "error"]
            raise HTTPException(409, "Der Brief kann so nicht archiviert werden: " + " ".join(problems[:3]))
        if shown_hash != payload.review_hash:
            raise HTTPException(409, "Die freizugebende Fassung stimmt nicht mit der Briefvorschau überein.")
        stamp = archive.now()
        document = Document.model_validate({"id": identifier, **DocumentCreate(
            title=payload.data.subject[:250], document_type=DOC_TYPE, document_date=payload.data.issue_date,
            property_id=prop.id, unit_id=location.id, contract_id=contract.id,
            description=f"Brief aus der Vorlage „{review['template']['name']}“",
            file_url=f"/uploads/{VIRTUAL_PREFIX}{identifier}.pdf",
            tags="brief," + review["template"]["kind"].replace("_", "-"),
        ).model_dump(), "created_at": stamp, "updated_at": stamp})
        if unit.db is not None:
            unit.db.execute(insert(DocumentORM), document.model_dump())
        else:
            unit.insert(unit.store.documents, document.id, document)
        source = review["source"]
        binding = {key + "_id": source[key]["id"] for key in ("portfolio", "property", "unit", "contract", "tenant")}
        proof = {"schema_version": SCHEMA_VERSION, "review": review, "review_hash": shown_hash,
                 "request_sha256": command_hash, "actor_id": actor_id, "idempotency_key": payload.idempotency_key}
        row = archive.publish_generated_original(unit, document, binding, raw, command_hash,
                                                 version_id=str(uuid4()), metadata_extra={DOC_TYPE: proof})
        return _public(row)


def read_pdf_for_key(store, key: str, actor_id: str) -> bytes | None:
    if not key.startswith(VIRTUAL_PREFIX):
        return None
    identifier = key[len(VIRTUAL_PREFIX):-4] if key.endswith(".pdf") else ""
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Brief nicht gefunden.") from None
    with work(store, actor_id) as unit:
        document = unit.store.get_document(identifier)
        raw, row = _verified(unit, document)
        proof = validate_contract_letter_snapshot(row, row.metadata_snapshot)
        resolve_context(unit.store, "contract", proof["review"]["source"]["contract"]["id"], unit.actor_id)
        if document.file_url != "/uploads/" + key:
            raise HTTPException(404, "Brief nicht gefunden.")
        return raw
