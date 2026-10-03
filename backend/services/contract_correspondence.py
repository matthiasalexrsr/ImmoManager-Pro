"""Explicit local approval and manual facts. No SMTP or contract mutation."""

import hashlib
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import date
from heapq import nlargest, nsmallest
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Table, and_, or_, select

from .. import auth
from ..config import settings
from ..db.contract_correspondence_models import (
    CORRESPONDENCE_MODELS,
    CorrespondenceCommandORM,
    CorrespondenceDraftORM,
    CorrespondenceEventORM,
)
from ..db.contract_lifecycle_models import ContractLifecycleCommandORM, ContractLifecycleDraftORM
from ..db.contract_wizard_models import ContractTemplateORM
from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import ContractORM, DocumentORM, TenantORM
from ..models import Document, DocumentCreate
from ..storage import ValidationError
from . import contract_lifecycle as lifecycle
from . import document_versions
from .concurrency import etag
from .contract_correspondence_render import pdf_hash, render_pdf, render_text
from .contract_correspondence_types import (
    ApproveLetter,
    CreateLetter,
    EditLetter,
    LetterData,
    ManualEvent,
    RevisionCommand,
)
from .contract_correspondence_validation import (
    EvidenceError,
    draft_public,
    event_public,
    validate_command,
    validate_draft,
    validate_event,
    validate_event_response,
)
from .contract_lifecycle_validation import JournalValidationError, validate_command_evidence
from .portfolio_scope import memory_visible, refresh_scope, scoped_clause
from .tenant_privacy import _memory_privacy_lock


@contextmanager
def work(store, actor_id, *, write=False):
    # A real auth refresh acquires the Account lock. Privacy takes account
    # before domain; hold that exact order throughout this compound command.
    with nullcontext() if hasattr(store, "db") else _memory_privacy_lock():
        with lifecycle.work(store, actor_id, write=write) as unit:
            if unit.db is None:
                for model in CORRESPONDENCE_MODELS:
                    store.__dict__.setdefault(model.__tablename__, {})
            elif write and isinstance(auth._user_store, auth.SQLUserStore):
                # Same account-marker -> domain order as private drafts/reset.
                # Revalidate after waiting, and hold grants stable until commit.
                auth._user_store._lock_management(unit.db)
                refresh_scope(unit.captured)
            yield unit


def row(unit, model, identifier):
    return unit.db.scalar(select(model).where(model.id == identifier)) if unit.db is not None else unit.store.__dict__.get(model.__tablename__, {}).get(identifier)


def parents(unit, contract_id, *, lock=False):
    # Tenant -> location -> contract matches version publication and privacy.
    initial = unit.store.get_contract(contract_id)
    if lock and unit.db is not None:
        if unit.db.scalar(select(TenantORM.id).where(TenantORM.id == initial.tenant_id).with_for_update(read=True)) is None:
            raise HTTPException(404, "Vertragspartei nicht zugänglich.")
    contract, property = lifecycle.parent(unit, contract_id, lock=lock)
    if initial.tenant_id != contract.tenant_id:
        raise lifecycle.conflict("Die Vertragspartei wurde geändert. Erneut prüfen.")
    complete_subject(unit, contract, property.portfolio_id)
    return contract, property


def complete_subject(unit, contract, portfolio_id):
    if unit.db is not None:
        drafts: Any = CorrespondenceDraftORM.__table__
        commands: Any = CorrespondenceCommandORM.__table__
        events: Any = CorrespondenceEventORM.__table__
        predicates = [select(drafts.c.id).where(drafts.c.contract_id == contract.id, or_(
            drafts.c.portfolio_id.is_distinct_from(portfolio_id), drafts.c.property_id.is_distinct_from(contract.property_id),
            drafts.c.unit_id.is_distinct_from(contract.unit_id), drafts.c.tenant_id.is_distinct_from(contract.tenant_id)))]
        for child in (commands, events):
            predicates.append(select(child.c.id).select_from(child.outerjoin(drafts, child.c.draft_id == drafts.c.id)).where(
                child.c.contract_id == contract.id, or_(child.c.portfolio_id.is_distinct_from(portfolio_id),
                    drafts.c.id.is_(None), drafts.c.contract_id.is_distinct_from(contract.id),
                    drafts.c.portfolio_id.is_distinct_from(portfolio_id))))
        versions: Any = DocumentVersionORM.__table__
        documents: Any = DocumentORM.__table__
        broken_original = select(drafts.c.id).select_from(drafts.outerjoin(versions,
            versions.c.id == drafts.c.document_version_id).outerjoin(documents, documents.c.id == drafts.c.document_id)).where(
            drafts.c.contract_id == contract.id, drafts.c.state == "approved", or_(versions.c.id.is_(None), documents.c.id.is_(None),
                versions.c.document_id.is_distinct_from(drafts.c.document_id), versions.c.portfolio_id.is_distinct_from(portfolio_id),
                versions.c.property_id.is_distinct_from(contract.property_id), versions.c.unit_id.is_distinct_from(contract.unit_id),
                versions.c.contract_id.is_distinct_from(contract.id), versions.c.tenant_id.is_distinct_from(contract.tenant_id),
                documents.c.contract_id.is_distinct_from(contract.id), and_(documents.c.property_id.is_not(None),
                    documents.c.property_id != contract.property_id), and_(documents.c.unit_id.is_not(None), documents.c.unit_id != contract.unit_id)))
        predicates.append(broken_original)
        bad = any(unit.db.connection().scalar(select(query.exists())) for query in predicates)
    else:
        drafts = unit.store.__dict__.get(CorrespondenceDraftORM.__tablename__, {})
        bad = any(value.contract_id == contract.id and any(getattr(value, key) != expected for key, expected in (
            ("portfolio_id", portfolio_id), ("property_id", contract.property_id), ("unit_id", contract.unit_id),
            ("tenant_id", contract.tenant_id))) for value in drafts.values())
        for model in (CorrespondenceCommandORM, CorrespondenceEventORM):
            bad = bad or any(value.contract_id == contract.id and (value.portfolio_id != portfolio_id
                or value.draft_id not in drafts or drafts[value.draft_id].contract_id != contract.id
                or drafts[value.draft_id].portfolio_id != portfolio_id)
                for value in unit.store.__dict__.get(model.__tablename__, {}).values())
        for value in drafts.values():
            if value.contract_id == contract.id and value.state == "approved":
                version = unit.store.__dict__.get("document_versions", {}).get(value.document_version_id)
                document = unit.store.__dict__["documents"].get(value.document_id)
                bad = bad or version is None or document is None
                if version is not None and document is not None:
                    bad = bad or version.document_id != document.id or any(getattr(version, key) != expected for key, expected in (
                        ("portfolio_id", portfolio_id), ("property_id", contract.property_id), ("unit_id", contract.unit_id),
                        ("contract_id", contract.id), ("tenant_id", contract.tenant_id))) or document.contract_id != contract.id or any(
                            getattr(document, key) is not None and getattr(document, key) != expected
                            for key, expected in (("property_id", contract.property_id), ("unit_id", contract.unit_id)))
    if bad:
        raise HTTPException(503, "Die Korrespondenzhistorie besitzt eine widersprüchliche Zuordnung.")


def load(unit, contract, property, identifier, actor_id, *, private=False):
    found = row(unit, CorrespondenceDraftORM, identifier)
    if found is None or found.contract_id != contract.id or found.portfolio_id != property.portfolio_id or (
            found.actor_id != actor_id and (private or found.state != "approved")):
        raise HTTPException(404, "Schreiben nicht gefunden oder nicht zugänglich.")
    try:
        validate_draft(found)
    except EvidenceError:
        raise HTTPException(503, "Gespeichertes Schreiben ist beschädigt. Bestand prüfen.") from None
    return found


def public(found, persistent):
    return draft_public(found, persistent)


def request_hash(operation, payload):
    return lifecycle.digest({"operation": operation, "payload": payload.model_dump(mode="json")})


def replay(unit, contract, property, identifier, payload, actor_id, operation):
    if unit.db is not None:
        saved = unit.db.scalar(select(CorrespondenceCommandORM).where(CorrespondenceCommandORM.actor_id == actor_id,
            CorrespondenceCommandORM.command_key == payload.idempotency_key).limit(1))
    else:
        saved = next((value for value in unit.store.__dict__[CorrespondenceCommandORM.__tablename__].values()
            if value.actor_id == actor_id and value.command_key == payload.idempotency_key), None)
    if saved is not None:
        if saved.contract_id != contract.id or (identifier is not None and saved.draft_id != identifier) or saved.request_hash != request_hash(operation, payload):
            raise lifecycle.conflict("Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
        current = load(unit, contract, property, saved.draft_id, actor_id)
        try:
            validate_command(saved, current)
            if operation == "event":
                observed = row(unit, CorrespondenceEventORM, saved.result["event"]["id"])
                validate_event_response(saved, observed)
                dispatch = row(unit, CorrespondenceEventORM, observed.data["dispatch_event_id"]) if observed.data["dispatch_event_id"] else None
                validate_event(observed, current, dispatch)
        except (EvidenceError, KeyError, TypeError, AttributeError):
            raise HTTPException(503, "Gespeicherter Vorgangsbeleg ist beschädigt. Bestand prüfen.") from None
        return deepcopy(saved.result)
    return None


def record(unit, found, actor_id, payload, operation, *, event=None):
    result = public(found, unit.db is not None)
    if event is not None:
        result["event"] = event_public(event)
    unit.add(CorrespondenceCommandORM(id=str(uuid4()), portfolio_id=found.portfolio_id, contract_id=found.contract_id,
        draft_id=found.id, actor_id=actor_id, command_key=payload.idempotency_key, operation=operation,
        request=payload.model_dump(mode="json"), request_hash=request_hash(operation, payload), result=result, created_at=lifecycle.now()))
    return result


def change(unit, found):
    unit.touch(found.__tablename__, found.id)
    found.revision, found.updated_at = str(uuid4()), lifecycle.now()


def revision(found, payload):
    if found.revision != payload.expected_revision:
        raise lifecycle.conflict("Das Schreiben wurde geändert. Aktuellen Entwurf laden.")


def source(unit, contract, property, data):
    tenant, location = unit.store.get_tenant(contract.tenant_id), unit.store.get_unit(contract.unit_id)
    template = None
    body = data.body
    if data.template_id is not None:
        selected = row(unit, ContractTemplateORM, data.template_id)
        if selected is None or selected.portfolio_id != property.portfolio_id:
            raise HTTPException(404, "Vorlagenfassung nicht in diesem Vertragsbestand verfügbar.")
        template = {"id": selected.id, "root_id": selected.root_id, "version": selected.version,
            "title": selected.title, "body_sha256": lifecycle.digest(selected.body)}
        body = selected.body
    context = {"contract_number": contract.contract_number, "tenant_name": tenant.full_name,
        "property_name": property.name, "unit_label": location.label, "start_date": contract.start_date.isoformat(),
        "end_date": contract.end_date.isoformat() if contract.end_date else "", "deadline_date": data.deadline_date.isoformat(),
        "deadline_basis": data.deadline_basis, "recipient_name": data.recipient_name, "recipient_address": data.recipient_address}
    binding = None
    if data.lifecycle_command_id is not None:
        command = row(unit, ContractLifecycleCommandORM, data.lifecycle_command_id)
        accepted = row(unit, ContractLifecycleDraftORM, command.draft_id) if command is not None else None
        if command is None or accepted is None or command.contract_id != contract.id or command.portfolio_id != property.portfolio_id or command.operation not in {"confirm", "finalize"}:
            raise HTTPException(404, "Akzeptierter Vertragsvorgang nicht verfügbar.")
        try:
            validate_command_evidence(command, accepted)
        except JournalValidationError:
            raise HTTPException(503, "Der zugeordnete Vertragsbeleg ist beschädigt.") from None
        if accepted.state not in {"confirmed", "pending_effective", "completed"}:
            raise lifecycle.conflict("Der zugeordnete Vertragsvorgang wurde abgelöst. Neu prüfen.")
        binding = {"command_id": command.id, "draft_id": accepted.id, "review_hash": accepted.review_hash,
            "result_hash": lifecycle.digest(command.result), "current_state": accepted.state}
    try:
        LetterData.plain_text(body)
        rendered = render_text(body, context)
    except ValueError as error:
        raise ValidationError(str(error)) from None
    return {"data": data.model_dump(mode="json"), "source_contract": contract.model_dump(mode="json"),
        "source_contract_etag": lifecycle.contract_etag(contract), "source_context": {"portfolio_id": property.portfolio_id,
            "property_etag": etag("properties", property.id, property.updated_at), "unit_etag": etag("units", location.id, location.updated_at),
            "tenant_etag": etag("tenants", tenant.id, tenant.updated_at), "names": context},
        "template": template, "lifecycle": binding, "rendered_body": rendered}


def current_review(unit, contract, property, found):
    reviewed = source(unit, contract, property, LetterData.model_validate(found.data))
    reviewed["pdf_sha256"] = pdf_hash(reviewed)
    return reviewed


def create_draft(store, contract_id, payload: CreateLetter, actor_id):
    with work(store, actor_id, write=True) as unit:
        contract, property = parents(unit, contract_id, lock=True)
        previous = replay(unit, contract, property, None, payload, actor_id, "create")
        if previous:
            return previous
        lifecycle.source_match(contract, payload.expected_contract_etag)
        stamp = lifecycle.now()
        found = CorrespondenceDraftORM(id=str(uuid4()), portfolio_id=property.portfolio_id, contract_id=contract.id,
            property_id=contract.property_id, unit_id=contract.unit_id, tenant_id=contract.tenant_id, actor_id=actor_id,
            create_key=payload.idempotency_key, create_hash=request_hash("create", payload), revision=str(uuid4()), state="draft",
            deadline_date=payload.data.deadline_date, data=payload.data.model_dump(mode="json"), source_contract_etag=payload.expected_contract_etag,
            review=None, review_hash=None, document_id=None, document_version_id=None, approved_at=None, created_at=stamp, updated_at=stamp)
        unit.add(found)
        return record(unit, found, actor_id, payload, "create")


def get_draft(store, contract_id, identifier, actor_id):
    with work(store, actor_id) as unit:
        contract, property = parents(unit, contract_id)
        found = load(unit, contract, property, identifier, actor_id)
        return public(found, unit.db is not None) | {"source_review_status": source_status(unit, contract, property, found),
            "current_contract_etag": lifecycle.contract_etag(contract)}


def source_status(unit, contract, property, found):
    if found.review is None:
        return "not_reviewed"
    try:
        current = source(unit, contract, property, LetterData.model_validate(found.data))
        reviewed = {key: value for key, value in found.review.items() if key != "pdf_sha256"}
        return "current" if current == reviewed else "requires_review"
    except HTTPException as error:
        if error.status_code not in {404, 409, 412}:
            raise
        return "requires_review"


def start(unit, contract_id, identifier, payload, actor_id, operation):
    contract, property = parents(unit, contract_id, lock=True)
    previous = replay(unit, contract, property, identifier, payload, actor_id, operation)
    if previous:
        return contract, property, None, previous
    found = load(unit, contract, property, identifier, actor_id, private=True)
    revision(found, payload)
    lifecycle.source_match(contract, payload.expected_contract_etag)
    if found.state == "approved":
        raise lifecycle.conflict("Das freigegebene Schreiben bleibt unverändert. Neuen Entwurf anlegen.")
    return contract, property, found, None


def edit_draft(store, contract_id, identifier, payload: EditLetter, actor_id):
    with work(store, actor_id, write=True) as unit:
        _, _, found, previous = start(unit, contract_id, identifier, payload, actor_id, "edit")
        if previous:
            return previous
        change(unit, found)
        found.data, found.deadline_date = payload.data.model_dump(mode="json"), payload.data.deadline_date
        found.source_contract_etag = payload.expected_contract_etag
        found.state, found.review, found.review_hash = "draft", None, None
        return record(unit, found, actor_id, payload, "edit")


def review_draft(store, contract_id, identifier, payload: RevisionCommand, actor_id):
    with work(store, actor_id, write=True) as unit:
        contract, property, found, previous = start(unit, contract_id, identifier, payload, actor_id, "review")
        if previous:
            return previous
        reviewed = current_review(unit, contract, property, found)
        change(unit, found)
        found.state, found.review, found.review_hash = "reviewed", reviewed, lifecycle.digest(reviewed)
        found.source_contract_etag = payload.expected_contract_etag
        return record(unit, found, actor_id, payload, "review")


def approve_draft(store, contract_id, identifier, payload: ApproveLetter, actor_id):
    with work(store, actor_id, write=True) as unit:
        contract, property, found, previous = start(unit, contract_id, identifier, payload, actor_id, "approve")
        if previous:
            return previous
        if not payload.confirmed or found.state != "reviewed" or payload.reviewed_hash != found.review_hash:
            raise lifecycle.conflict("Genau die geprüfte Schreibenfassung ausdrücklich freigeben.")
        if current_review(unit, contract, property, found) != found.review:
            raise lifecycle.conflict("Vertrag, Partei oder Vorlage wurde geändert. Vorschau erneut prüfen.")
        content = render_pdf(found.review)
        if hashlib.sha256(content).hexdigest() != found.review["pdf_sha256"]:
            raise lifecycle.conflict("Die Vorschau wurde mit einer anderen PDF-Version erzeugt. Entwurf erneut prüfen.")
        values = DocumentCreate(property_id=property.id, unit_id=contract.unit_id, contract_id=contract.id,
            title=found.data["subject"], document_type="contract_correspondence", document_date=date.fromisoformat(found.data["letter_date"]),
            file_url=f"/uploads/contract-correspondence/{found.id}.pdf")
        document_versions.identity(actor_id, True)
        stamp = lifecycle.now()
        document = Document(id=str(uuid4()), **values.model_dump(), created_at=stamp, updated_at=stamp)
        if unit.db is not None:
            # Same narrow generated-original insert as G07. All parents and
            # the exact new virtual key were authorized above; no user URL or
            # uploaded-file grant is accepted. No facade commit occurs here.
            unit.db.connection().execute(cast(Table, DocumentORM.__table__).insert(), document.model_dump())
        else:
            unit.touch("documents", document.id, inserted=True)
            unit.store.__dict__["documents"][document.id] = document
        binding = {key: getattr(found, key) for key in ("portfolio_id", "property_id", "unit_id", "contract_id", "tenant_id")}
        version = document_versions.publish_generated_original(unit.store, unit.db, document, binding, actor_id, content,
            request_hash("approve", payload), before_insert=lambda collection, key: unit.touch(collection, key, inserted=True))
        change(unit, found)
        found.state, found.approved_at = "approved", lifecycle.now()
        found.document_id, found.document_version_id = document.id, version.id
        return record(unit, found, actor_id, payload, "approve")


def review_pdf(store, contract_id, identifier, actor_id):
    with work(store, actor_id) as unit:
        contract, property = parents(unit, contract_id)
        found = load(unit, contract, property, identifier, actor_id, private=True)
        if found.state != "reviewed":
            raise lifecycle.conflict("Zuerst die Schreibenfassung prüfen.")
        content = render_pdf(found.review)
        if hashlib.sha256(content).hexdigest() != found.review["pdf_sha256"]:
            raise lifecycle.conflict("Die Vorschau wurde mit einer anderen PDF-Version erzeugt. Entwurf erneut prüfen.")
        refresh_scope(unit.captured)
        return content, found.review["pdf_sha256"]


def last_event(unit, identifier):
    return unit.db.scalar(select(CorrespondenceEventORM).where(CorrespondenceEventORM.draft_id == identifier)
        .order_by(CorrespondenceEventORM.event_revision.desc()).limit(1)) if unit.db is not None else max(
        (value for value in unit.store.__dict__[CorrespondenceEventORM.__tablename__].values() if value.draft_id == identifier),
        key=lambda value: value.event_revision, default=None)


def record_event(store, contract_id, identifier, payload: ManualEvent, actor_id):
    with work(store, actor_id, write=True) as unit:
        contract, property = parents(unit, contract_id, lock=True)
        previous = replay(unit, contract, property, identifier, payload, actor_id, "event")
        if previous:
            return previous
        found = load(unit, contract, property, identifier, actor_id)
        revision(found, payload)
        if found.state != "approved":
            raise lifecycle.conflict("Versand oder Empfang nur zu einem freigegebenen Schreiben erfassen.")
        _, binding = document_versions._document(unit.store, unit.db, found.document_id)
        original = document_versions._authorized_version(unit.store, unit.db, found.document_id, found.document_version_id, binding)
        # Every new fact refers to the complete stored original; never attach
        # observations to a corrupt/truncated/foreign version silently.
        for _ in document_versions.verified_blocks(unit.store, original):
            pass
        last = last_event(unit, identifier)
        current = last.event_revision if last else 0
        if payload.expected_event_revision != current:
            raise lifecycle.conflict("Zwischenzeitlich wurde ein Ereignis erfasst. Verlauf erneut laden.")
        if payload.kind == "dispatched" and source_status(unit, contract, property, found) != "current":
            raise lifecycle.conflict("Der Vertrags-/Schreibenstand wurde geändert. Vor neuem Versand einen neuen Entwurf prüfen.")
        dispatch = row(unit, CorrespondenceEventORM, payload.dispatch_event_id) if payload.dispatch_event_id else None
        event = CorrespondenceEventORM(id=str(uuid4()), portfolio_id=found.portfolio_id, contract_id=found.contract_id,
            draft_id=found.id, actor_id=actor_id, event_revision=current + 1, data=payload.model_dump(mode="json"),
            document_version_id=found.document_version_id, review_hash=found.review_hash, created_at=lifecycle.now())
        try:
            validate_event(event, found, dispatch)
        except EvidenceError:
            raise ValidationError("Empfang und Versand gehören nicht zum selben Schreiben oder die Datumsfolge ist ungültig.") from None
        unit.add(event)
        return record(unit, found, actor_id, payload, "event", event=event)


def listing(store, contract_id, actor_id, *, before=None, limit=25, history=False):
    maximum = getattr(settings, "contract_correspondence_page_max_size", 100)
    if not 1 <= limit <= maximum:
        raise HTTPException(422, "Seitengröße überschreitet das konfigurierbare technische Budget.")
    point = lifecycle._cursor(before)
    with work(store, actor_id) as unit:
        contract, property = parents(unit, contract_id)
        if unit.db is not None:
            query = select(CorrespondenceDraftORM).where(CorrespondenceDraftORM.contract_id == contract.id,
                CorrespondenceDraftORM.portfolio_id == property.portfolio_id)
            query = query.where(CorrespondenceDraftORM.state == "approved") if history else query.where(CorrespondenceDraftORM.actor_id == actor_id)
            if point:
                query = query.where(or_(CorrespondenceDraftORM.created_at < point[0], and_(
                    CorrespondenceDraftORM.created_at == point[0], CorrespondenceDraftORM.id < point[1])))
            found = list(unit.db.scalars(query.order_by(CorrespondenceDraftORM.created_at.desc(), CorrespondenceDraftORM.id.desc()).limit(limit + 1)))
        else:
            found = nlargest(limit + 1, (value for value in unit.store.__dict__[CorrespondenceDraftORM.__tablename__].values()
                if value.contract_id == contract.id and value.portfolio_id == property.portfolio_id and
                (value.state == "approved" if history else value.actor_id == actor_id) and
                (point is None or (value.created_at, value.id) < point)), key=lambda value: (value.created_at, value.id))
        items = []
        for value in found[:limit]:
            checked = load(unit, contract, property, value.id, actor_id)
            items.append(public(checked, unit.db is not None) | {"source_review_status": source_status(unit, contract, property, checked),
                "current_contract_etag": lifecycle.contract_etag(contract)})
        import base64
        cursor = base64.urlsafe_b64encode(lifecycle.packed([found[limit - 1].created_at.isoformat(), found[limit - 1].id]).encode()).decode() if len(found) > limit else None
        return {"items": items, "next_before": cursor, "has_more": len(found) > limit, "persistent": unit.db is not None}


def events(store, contract_id, identifier, actor_id, *, before=None, limit=25):
    if not 1 <= limit <= getattr(settings, "contract_correspondence_page_max_size", 100):
        raise HTTPException(422, "Ungültige technische Seitengröße.")
    with work(store, actor_id) as unit:
        contract, property = parents(unit, contract_id)
        found = load(unit, contract, property, identifier, actor_id)
        if unit.db is not None:
            query = select(CorrespondenceEventORM).where(CorrespondenceEventORM.draft_id == identifier)
            if before is not None:
                query = query.where(CorrespondenceEventORM.event_revision < before)
            selected = list(unit.db.scalars(query.order_by(CorrespondenceEventORM.event_revision.desc()).limit(limit + 1)))
        else:
            selected = nlargest(limit + 1, (event for event in unit.store.__dict__[CorrespondenceEventORM.__tablename__].values()
                if event.draft_id == identifier and (before is None or event.event_revision < before)), key=lambda event: event.event_revision)
        last = last_event(unit, identifier)
        return {"items": [event_public(value) for value in selected[:limit]], "event_revision": last.event_revision if last else 0,
            "next_before": selected[limit - 1].event_revision if len(selected) > limit else None, "document_version_id": found.document_version_id,
            "policy": "manual_observation_only"}


def prepare_download(store, contract_id, identifier, actor_id, *, parent=None):
    with work(store, actor_id) as unit:
        contract, property = parents(unit, contract_id)
        found = load(unit, contract, property, identifier, actor_id)
        if found.state != "approved":
            raise lifecycle.conflict("Das Schreiben wurde noch nicht freigegeben.")
        document_id, version_id = found.document_id, found.document_version_id
    return document_versions.prepare_download(store, document_id, version_id, actor_id, parent=parent)


def read_pdf_for_key(store, key, actor_id):
    """Optional files/original-source hook; exact owned virtual key, never disk."""
    prefix = "contract-correspondence/"
    if not key.startswith(prefix) or not key.endswith(".pdf"):
        return None
    identifier = key[len(prefix):-4]
    try:
        from uuid import UUID
        if str(UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    with work(store, actor_id) as unit:
        found = row(unit, CorrespondenceDraftORM, identifier)
        if found is None:
            raise HTTPException(404, "Schreiben nicht verfügbar.")
        contract, property = parents(unit, found.contract_id)
        found = load(unit, contract, property, identifier, actor_id)
        if found.state != "approved":
            raise HTTPException(404, "Schreiben nicht veröffentlicht.")
        document, binding = document_versions._document(unit.store, unit.db, found.document_id)
        if document.file_url != "/uploads/" + key:
            raise HTTPException(409, "Der Quellenverweis wurde geändert. Archiviertes Original verwenden.")
        version = document_versions._authorized_version(unit.store, unit.db, found.document_id, found.document_version_id, binding)
        return b"".join(document_versions.verified_blocks(unit.store, version))


def guard_delete_link(store, entity_type, identifier):
    """Inside ordinary location/party/delete locks; no new authorization path."""
    kind = {"properties": "property", "units": "unit", "tenants": "tenant", "contracts": "contract", "portfolios": "portfolio", "documents": "document"}.get(entity_type, entity_type)
    field = {"property": "property_id", "unit": "unit_id", "tenant": "tenant_id", "contract": "contract_id", "portfolio": "portfolio_id", "document": "document_id"}.get(kind)
    if field is None:
        return
    if hasattr(store, "db"):
        present = store.db.connection().scalar(select(select(CorrespondenceDraftORM.__table__.c.id).where(
            getattr(CorrespondenceDraftORM.__table__.c, field) == identifier).exists()))
    else:
        present = any(getattr(value, field) == identifier for value in store.__dict__.get(CorrespondenceDraftORM.__tablename__, {}).values())
    if present:
        raise ValidationError("Vertragskorrespondenz mit fester Partei-/Bestandsbindung vorhanden. Historie erhalten oder vollständiges Archiv wiederherstellen.")


def guard_destructive_reset(store):
    for model in CORRESPONDENCE_MODELS:
        if hasattr(store, "db"):
            table = model.__table__
            present = store.db.connection().scalar(select(select(table.c.id).exists()))
        else:
            present = bool(store.__dict__.get(model.__tablename__))
        if present:
            raise ValidationError("Korrespondenzjournal vorhanden. Vollständiges Offline-Archiv verwenden; Teilersatz/Reset würde Originale und manuelle Belege verlieren.")


def deadline_projection(store, contract_id, actor_id, *, before=None, limit=25):
    page = listing(store, contract_id, actor_id, before=before, limit=limit, history=True)
    page["items"] = [{"id": item["id"], "contract_id": contract_id, "date": item["data"]["deadline_date"],
        "basis": item["data"]["deadline_basis"], "review_hash": item["review_hash"], "source_review_status": item["source_review_status"],
        "policy": "user_confirmed_management_date"}
        for item in page["items"]]
    return page


def due_deadlines(store, actor_id, as_of: date, *, after=None, limit=25):
    """Bounded operational/calendar hook; never exposes private letter bodies.

    A scheduled integration must retain the explicit management-date label and
    skip requires_review projections. Idempotent projection key remains tied
    to the immutable approval, not a mutable contract end date.
    """
    if not 1 <= limit <= getattr(settings, "contract_correspondence_page_max_size", 100):
        raise HTTPException(422, "Ungültige technische Seitengröße.")
    point = None
    if after is not None:
        try:
            point = (date.fromisoformat(after[0]), after[1])
        except (ValueError, TypeError, IndexError):
            raise HTTPException(422, "Ungültige Fristenseite.") from None
    with work(store, actor_id) as unit:
        if unit.db is not None:
            query = select(CorrespondenceDraftORM).join(ContractORM, ContractORM.id == CorrespondenceDraftORM.contract_id).where(
                CorrespondenceDraftORM.state == "approved", CorrespondenceDraftORM.deadline_date <= as_of)
            for model in (CorrespondenceDraftORM, ContractORM):
                predicate = scoped_clause(model, scope=unit.captured)
                if predicate is not None:
                    query = query.where(predicate)
            if point:
                query = query.where(or_(CorrespondenceDraftORM.deadline_date > point[0], and_(
                    CorrespondenceDraftORM.deadline_date == point[0], CorrespondenceDraftORM.id > point[1])))
            found = list(unit.db.scalars(query.order_by(CorrespondenceDraftORM.deadline_date, CorrespondenceDraftORM.id).limit(limit + 1)))
        else:
            contracts = unit.store.__dict__["contracts"]
            found = nsmallest(limit + 1, (value for value in unit.store.__dict__[CorrespondenceDraftORM.__tablename__].values()
                if value.state == "approved" and value.deadline_date <= as_of and (point is None or (value.deadline_date, value.id) > point)
                and value.contract_id in contracts and memory_visible(unit.store, "contracts", contracts[value.contract_id], scope=unit.captured)),
                key=lambda value: (value.deadline_date, value.id))
        items = []
        for value in found[:limit]:
            contract, property = parents(unit, value.contract_id)
            checked = load(unit, contract, property, value.id, actor_id)
            items.append({"id": checked.id, "contract_id": checked.contract_id, "portfolio_id": checked.portfolio_id,
                "property_id": checked.property_id, "unit_id": checked.unit_id, "date": checked.deadline_date.isoformat(),
                "basis": checked.data["deadline_basis"], "source_review_status": source_status(unit, contract, property, checked),
                "projection_key": "contract-correspondence:" + checked.id + ":" + checked.review_hash,
                "policy": "user_confirmed_management_date"})
        return {"items": items, "next_after": [found[limit - 1].deadline_date.isoformat(), found[limit - 1].id] if len(found) > limit else None}
