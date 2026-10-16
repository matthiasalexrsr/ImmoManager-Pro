"""Durable document review proposals and explainable, non-destructive duplicate hints."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import DecimalException
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, exists, false, func, or_, select, true

from ..business_qol_models import (
    DocumentIntake,
    DuplicateAccept,
    DuplicateCheck,
    DuplicateException,
    ProcessDocument,
    ReviewDocument,
)
from ..db.business_qol_models import DocumentIntakeORM, DuplicateExceptionORM
from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import ContactORM, DocumentORM, InvoiceORM
from ..domain import invoice_review as invoice_rules
from ..domain.money import money
from ..domain.revision_time import next_updated_at
from ..models import Document, DocumentCreate, DocumentPatch
from ..permissions import may_write
from . import business_qol as office
from . import document_versions as archive
from .business_field_history import record_unit_changes
from .file_storage import LocalStorage, S3Storage, get_file_storage
from .portfolio_scope import require_file_access, scope_context, scope_from_user
from .workspace_contexts import actor, resolve_context

office.RECORDS.update(
    {
        "business_document_intake": (DocumentIntakeORM, DocumentIntake),
        "business_duplicate_exceptions": (DuplicateExceptionORM, DuplicateException),
    }
)
DOCUMENT_FIELDS = {
    "title",
    "document_type",
    "property_id",
    "unit_id",
    "contract_id",
    "tenant_id",
    "tags",
    "description",
}


def intake_id(document_id: str) -> str:
    return office.command_id("document-intake", document_id)


def _intake(unit, document_id: str):
    return office.get_record(unit, "business_document_intake", intake_id(document_id))


def _original(store, identifier: str) -> bool:
    if hasattr(store, "db"):
        return (
            store.db.scalar(select(DocumentVersionORM.id).where(DocumentVersionORM.document_id == identifier).limit(1))
            is not None
        )
    return any(row.document_id == identifier for row in archive.memory_archive(store).versions.values())


def _file(file_url: str) -> bytes:
    from ..routers.files import _file_url_to_key

    key = _file_url_to_key(file_url)
    if not key:
        raise HTTPException(422, "Ungültige Datei-URL.")
    require_file_access(key)
    content = get_file_storage().get(key)
    if content is None:
        raise HTTPException(404, "Datei nicht vorhanden.")
    return content


def file_hash(file_url: str) -> str:
    """Hash mutable uploads with bounded reads; checksum comparisons never buffer a file."""
    from ..routers.files import _file_url_to_key

    key = _file_url_to_key(file_url)
    if not key:
        raise HTTPException(422, "Ungültige Datei-URL.")
    require_file_access(key)
    storage = get_file_storage()
    stream: Any
    try:
        if isinstance(storage, LocalStorage):
            stream = storage._path(key).open("rb")
        elif isinstance(storage, S3Storage) and storage._client is not None:
            bound = storage.binding(key)
            if storage.legacy_local is not None and bound is None:
                stream = storage.legacy_local._path(key).open("rb")
            else:
                response = storage._call("get_object", key)
                if response is None:
                    raise HTTPException(404, "Datei nicht vorhanden.")
                stream = response["Body"]
        else:
            raise HTTPException(503, "Dieser Dateispeicher unterstützt keine begrenzte Prüfsummenlesung.")
        try:
            checksum = hashlib.sha256()
            while block := stream.read(65536):
                checksum.update(block)
            digest = checksum.hexdigest()
            if isinstance(storage, S3Storage) and bound is not None and digest != bound["sha256"]:
                from .file_storage import StorageUnavailable

                raise StorageUnavailable("Originalprüfsumme stimmt nicht mit der Speicherbindung überein")
            return digest
        finally:
            stream.close()
    except (OSError, KeyError):
        raise HTTPException(404, "Datei nicht vorhanden oder nicht lesbar.") from None


def document_hash(store, identifier: str, actor_id: str, *, version_id: str | None = None) -> str:
    unit = archive.Unit(
        store,
        getattr(store, "db", None),
        actor(actor_id, store),
        None if hasattr(store, "db") else archive.memory_archive(store),
    )
    context = resolve_context(store, "document", identifier, actor_id)
    original = archive.version_row(unit, version_id) if version_id else archive.head(unit, identifier)
    if original is not None:
        _, binding = archive.bind_document(unit, identifier)
        original = archive.authorized_version(unit, identifier, original.id, binding)
        # Validate the manifest AND all immutable blocks before confirming a match.
        for _block in archive.verified_blocks(unit, original):
            pass
        return original.sha256
    return file_hash(context["values"]["file_url"])


def file_coverage(store) -> dict:
    """A scoped completeness statement; old unprocessed files are never called checked."""
    if hasattr(store, "db"):
        indexed = or_(
            exists(select(DocumentVersionORM.id).where(DocumentVersionORM.document_id == DocumentORM.id)),
            exists(
                select(DocumentIntakeORM.id).where(
                    DocumentIntakeORM.document_id == DocumentORM.id,
                    DocumentIntakeORM.source_file_url == DocumentORM.file_url,
                    DocumentIntakeORM.sha256.is_not(None),
                )
            ),
        )
        total = store.db.scalar(select(func.count()).select_from(DocumentORM)) or 0
        count = store.db.scalar(select(func.count()).select_from(DocumentORM).where(indexed)) or 0
    else:
        originals = {row.document_id for row in archive.memory_archive(store).versions.values()}
        hashes = {row.document_id: row for row in store.business_document_intake.values() if row.sha256}
        docs = store.documents.values()
        total = len(docs)
        count = sum(
            row.id in originals or row.id in hashes and hashes[row.id].source_file_url == row.file_url for row in docs
        )
    return {
        "indexed_count": count,
        "unindexed_count": total - count,
        "complete": total == count,
        "note": "Archivierte Fassungen und analysierte Dateien. Unverarbeitete oder ersetzte Dateien bitte in der Dokumentwarteschlange analysieren.",
        "pending_href": "/document-queue?status=pending",
    }


def analyze_bytes(content: bytes, file_url: str, *, use_ai: bool = False) -> dict:
    """Use the existing extraction/analysis engines without publishing sidecar files."""
    from .ai.document_ai import analyze_document
    from .ocr_service import extract_text_from_bytes

    extension = file_url.rsplit(".", 1)[-1].lower()
    text = extract_text_from_bytes(content, extension)
    if not text:
        raise ValueError("Kein Text extrahierbar")
    result = analyze_document(text, use_ai=use_ai)
    return {
        "document_type": result.document_type,
        "summary": result.summary,
        "entities": result.entities,
        "invoice_number": result.invoice_number,
        "invoice_date": result.invoice_date,
        "total_amount": result.total_amount,
        "supplier": result.supplier,
        "cost_category": result.cost_category,
        "ai_model": result.ai_model,
        "origin": {"method": "ai" if result.ai_model else "regex", "model": result.ai_model},
        "confidence": {
            "document_type": result.document_type_confidence if result.ai_model else None,
            "other_fields": None,
        },
        "source": {
            "file_url": file_url,
            "sha256": hashlib.sha256(content).hexdigest(),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "confirmation": {"required": True, "confirmed": False},
        "financial_writes": False,
    }


def _public(context: dict, item: DocumentIntake | None, user: dict) -> dict:
    if item is not None and item.source_file_url != context["values"]["file_url"]:
        item = None
    status = item.status if item else "pending"
    result = item.result if item else None
    lease_expired = bool(item and item.lease_until and office.utc(item.lease_until) <= office.timestamp())
    return {
        "document_id": context["entity_id"],
        "title": context["title"],
        "href": context["href"],
        "file_url": context["values"]["file_url"],
        "document_revision": context["revision"],
        "revision": item.updated_at.isoformat() if item else "0",
        "status": status,
        "result": result,
        "error": item.error if item else None,
        "sha256": item.sha256 if item else None,
        "lease_expired": lease_expired,
        "can_process": may_write(user["role"], "/documents") and (status != "processing" or lease_expired),
        "can_review": may_write(user["role"], "/documents") and status != "processing",
    }


def document_detail(store, identifier: str, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit:
        context = resolve_context(unit.store, "document", identifier, actor_id)
        immutable = _original(unit.store, identifier)
        result = _public(context, _intake(unit, identifier), unit.user)
        if immutable:
            result.update(can_process=False, can_review=False)
        return {"document": office.dump(context["values"]), "intake": result}


def document_queue(store, actor_id: str, *, status=None, cursor=None, limit=50) -> dict:
    query = ["documents", actor_id, status]
    before = office.cursor_decode(cursor, query)
    if before and (len(before) != 2 or not all(isinstance(value, str) for value in before)):
        raise HTTPException(422, "Ungültige Fortsetzung.")
    if before:
        try:
            datetime.fromisoformat(before[0])
        except ValueError:
            raise HTTPException(422, "Ungültige Fortsetzung.") from None
    with archive.work(store, actor_id) as unit:
        if unit.db is not None:
            valid = and_(
                DocumentIntakeORM.document_id == DocumentORM.id,
                DocumentIntakeORM.source_file_url == DocumentORM.file_url,
            )
            original = exists(select(DocumentVersionORM.id).where(DocumentVersionORM.document_id == DocumentORM.id))
            selected = select(DocumentORM, DocumentIntakeORM).outerjoin(DocumentIntakeORM, valid).where(~original)
            if status == "pending":
                selected = selected.where(DocumentIntakeORM.id.is_(None))
            elif status:
                selected = selected.where(DocumentIntakeORM.status == status)
            else:
                selected = selected.where(or_(DocumentIntakeORM.id.is_(None), DocumentIntakeORM.status != "done"))
            if before:
                moment = office.utc(datetime.fromisoformat(before[0])).replace(tzinfo=None)
                selected = selected.where(
                    or_(
                        DocumentORM.created_at < moment,
                        and_(DocumentORM.created_at == moment, DocumentORM.id < before[1]),
                    )
                )
            rows = unit.db.execute(
                selected.order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc()).limit(limit + 1)
            )
            candidates = [
                (
                    document,
                    None
                    if item is None
                    else DocumentIntake.model_validate(
                        {col.key: getattr(item, col.key) for col in DocumentIntakeORM.__table__.c}
                    ),
                )
                for document, item in rows
            ]
        else:
            candidates = []
            for document in unit.store.documents.values():
                if _original(unit.store, document.id):
                    continue
                item = _intake(unit, document.id)
                matching = item is not None and item.source_file_url == document.file_url
                state = item.status if matching else "pending"
                key = (office.utc(document.created_at).isoformat(), document.id)
                if not status and state == "done" or status and state != status or before and key >= tuple(before):
                    continue
                candidates.append((document, item))
            candidates.sort(key=lambda pair: (office.utc(pair[0].created_at), pair[0].id), reverse=True)
            candidates = candidates[: limit + 1]
        values = []
        for document, item in candidates:
            context = resolve_context(unit.store, "document", document.id, actor_id)
            values.append(
                {**_public(context, item, unit.user), "created_at": office.utc(document.created_at).isoformat()}
            )
        return office.page(values, limit, query, lambda item: [item["created_at"], item["document_id"]])


def process_document(store, identifier: str, payload: ProcessDocument, actor_id: str) -> dict:
    operation = "document_process:" + identifier
    with archive.work(store, actor_id, write_areas=("/documents",)) as unit:
        context = resolve_context(unit.store, "document", identifier, actor_id, lock=True)
        if _original(unit.store, identifier):
            raise office.conflict("Archivierte Originale werden nicht durch die Dokumentwarteschlange geändert.")
        item = _intake(unit, identifier)
        receipt = office.get_record(unit, "business_qol_commands", office.command_id(actor_id, payload.idempotency_key))
        expired_own = bool(
            receipt
            and (receipt.response.get("intake", {}).get("status") or receipt.response.get("status")) == "processing"
            and item
            and item.command_id == receipt.id
            and item.lease_until
            and office.utc(item.lease_until) <= office.timestamp()
        )
        if expired_own and receipt.fingerprint != office.fingerprint(operation, payload):
            raise office.conflict("Diese Vorgangskennung wurde bereits mit anderen Angaben verwendet.")
        if not expired_own:
            previous = office.replay(unit, actor_id, operation, payload)
            if previous:
                return previous
        office.check_revision(payload.base_revision, context["revision"])
        if (
            item
            and item.status == "processing"
            and item.lease_until
            and office.utc(item.lease_until) > office.timestamp()
        ):
            raise office.conflict("Dieses Dokument wird bereits verarbeitet. Bitte später erneut versuchen.")
        stamp = office.timestamp()
        item = DocumentIntake(
            id=intake_id(identifier),
            document_id=identifier,
            property_id=context["property_id"],
            source_file_url=context["values"]["file_url"],
            source_revision=context["revision"],
            status="processing",
            command_id=office.command_id(actor_id, payload.idempotency_key),
            lease_until=stamp + timedelta(minutes=10),
            actor_id=actor_id,
            created_at=item.created_at if item else stamp,
            updated_at=stamp,
        )
        office.put_record(unit, "business_document_intake", item)
        claim_response = {"intake": _public(context, item, unit.user), "replayed": False}
        if expired_own:
            assert receipt is not None
            claim = office.advance_command(
                unit, actor_id, operation, payload, receipt.updated_at.isoformat(), claim_response
            )
        else:
            claim = office.save_command(unit, actor_id, operation, payload, context, claim_response)
        source = dict(context)
    # Extraction is outside the database/account writer locks. Nothing from the
    # proposal is written into financial data or the document until review.
    error, result, sha256 = None, None, None
    user = actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        try:
            content = _file(source["values"]["file_url"])
            sha256 = hashlib.sha256(content).hexdigest()
            result = office.dump(analyze_bytes(content, source["values"]["file_url"], use_ai=payload.use_ai))
        except Exception:
            error = "Die Datei konnte nicht analysiert werden. Bitte Datei prüfen und erneut versuchen."
    with archive.work(store, actor_id, write_areas=("/documents",)) as unit:
        context = resolve_context(unit.store, "document", identifier, actor_id, lock=True)
        current = _intake(unit, identifier)
        if (
            current is None
            or current.command_id != item.command_id
            or current.status != "processing"
            or not office.same_revision(current.updated_at.isoformat(), item.updated_at.isoformat())
        ):
            raise office.conflict("Die Verarbeitung wurde inzwischen ersetzt. Bitte Warteschlange neu laden.")
        if not office.same_revision(source["revision"], context["revision"]):
            error = "Das Dokument wurde während der Analyse geändert. Bitte erneut verarbeiten."
            result = None
        current = current.model_copy(
            update={
                "status": "failed" if error else "review",
                "sha256": sha256,
                "result": result,
                "error": error,
                "lease_until": None,
                "updated_at": next_updated_at(current.updated_at, office.timestamp()),
            }
        )
        office.put_record(unit, "business_document_intake", current)
        response = {"intake": _public(context, current, unit.user), "replayed": False}
        office.advance_command(unit, actor_id, operation, payload, claim.updated_at.isoformat(), response)
        return response


def review_document(store, identifier: str, payload: ReviewDocument, actor_id: str) -> dict:
    if set(payload.changes) - DOCUMENT_FIELDS:
        raise HTTPException(422, "Die Prüfung darf nur Dokumentmetadaten übernehmen.")
    with archive.work(store, actor_id, write_areas=("/documents",)) as unit:
        context = resolve_context(unit.store, "document", identifier, actor_id, lock=True)
        previous = office.replay(unit, actor_id, "document_review:" + identifier, payload)
        if previous:
            return previous
        if _original(unit.store, identifier):
            raise office.conflict("Ein archiviertes Original bleibt unverändert.")
        item = _intake(unit, identifier)
        if item is None or item.status == "processing":
            raise office.conflict("Bitte die Analyse abschließen oder erneut starten.")
        office.check_revision(payload.base_revision, item.updated_at.isoformat())
        office.check_revision(payload.document_revision, context["revision"])
        if item.source_file_url != context["values"]["file_url"]:
            raise office.conflict("Die Quelldatei wurde geändert. Bitte erneut analysieren.")
        if item.sha256 and file_hash(item.source_file_url) != item.sha256:
            raise office.conflict("Der Dateiinhalt wurde geändert. Bitte erneut analysieren.")
        patch = DocumentPatch.model_validate(payload.changes)
        changes = patch.model_dump(exclude_unset=True)
        original = unit.store.get_document(identifier)
        inverse = {"fields": office.dump({key: getattr(original, key) for key in changes}), "intake": office.dump(item)}
        values = DocumentCreate.model_validate(
            {**original.model_dump(include=set(DocumentCreate.model_fields)), **changes}
        )
        unit.store.validate_document_associations(values)
        archive.ensure_binding_kept(unit.store, "document", identifier, original, changes)
        updated = Document.model_validate(
            {
                **original.model_dump(),
                **values.model_dump(),
                "updated_at": next_updated_at(original.updated_at, office.timestamp()),
            }
        )
        if unit.db is None:
            unit.insert(unit.store.documents, identifier, updated)
        else:
            row = unit.db.scalar(select(DocumentORM).where(DocumentORM.id == identifier).with_for_update())
            for key, value in updated.model_dump().items():
                setattr(row, key, office.utc(value).replace(tzinfo=None) if isinstance(value, datetime) else value)
            unit.db.flush()
        record_unit_changes(unit, "documents", original, updated)
        proposal = dict(item.result or {})
        proposal["confirmation"] = {
            "required": True,
            "confirmed": True,
            "actor_id": actor_id,
            "at": office.timestamp().isoformat(),
            "fields": sorted(changes),
        }
        item = item.model_copy(
            update={
                "status": "done",
                "source_revision": updated.updated_at.isoformat(),
                "result": proposal,
                "property_id": updated.property_id,
                "updated_at": next_updated_at(item.updated_at, office.timestamp()),
            }
        )
        office.put_record(unit, "business_document_intake", item)
        context = resolve_context(unit.store, "document", identifier, actor_id)
        response = {
            "document": office.dump(updated),
            "intake": _public(context, item, unit.user),
            "replayed": False,
            "revision": context["revision"],
            "undo_id": office.command_id(actor_id, payload.idempotency_key),
        }
        office.save_command(
            unit,
            actor_id,
            "document_review:" + identifier,
            payload,
            context,
            response,
            inverse=inverse,
            post_revision=context["revision"],
        )
        return response


def undo_document(store, identifier: str, payload: Any, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=("/documents",)) as unit:
        original = office.get_record(unit, "business_qol_commands", identifier)
        if original is None or original.actor_id != actor_id or not original.operation.startswith("document_review:"):
            raise HTTPException(404, "Rückgängig-Vorgang nicht vorhanden.")
        context = resolve_context(unit.store, "document", original.entity_id, actor_id, lock=True)
        previous = office.replay(unit, actor_id, "undo:" + identifier, payload)
        if previous:
            return previous
        if original.undone_by or _original(unit.store, original.entity_id):
            raise office.conflict("Die Änderung wurde bereits rückgängig gemacht oder als Original veröffentlicht.")
        office.check_revision(payload.base_revision, context["revision"])
        office.check_revision(original.post_revision or "", context["revision"])
        intake = _intake(unit, original.entity_id)
        if intake is None:
            raise office.conflict("Der Prüfstand wurde inzwischen geändert. Bitte neu laden.")
        office.check_revision(original.response.get("intake", {}).get("revision", ""), intake.updated_at.isoformat())
        inverse = original.inverse or {}
        fields = inverse.get("fields", {})
        if not isinstance(fields, dict) or set(fields) - DOCUMENT_FIELDS or "intake" not in inverse:
            raise office.conflict("Für diesen Vorgang liegt keine rücksetzbare Dokumentzuordnung vor.")
        before = unit.store.get_document(original.entity_id)
        patch = DocumentPatch.model_validate(fields)
        values = DocumentCreate.model_validate(
            {**before.model_dump(include=set(DocumentCreate.model_fields)), **patch.model_dump(exclude_unset=True)}
        )
        unit.store.validate_document_associations(values)
        archive.ensure_binding_kept(unit.store, "document", before.id, before, fields)
        updated = Document.model_validate(
            {
                **before.model_dump(),
                **values.model_dump(),
                "updated_at": next_updated_at(before.updated_at, office.timestamp()),
            }
        )
        if unit.db is None:
            unit.insert(unit.store.documents, updated.id, updated)
        else:
            row = unit.db.scalar(select(DocumentORM).where(DocumentORM.id == updated.id).with_for_update())
            for key, value in updated.model_dump().items():
                setattr(row, key, office.utc(value).replace(tzinfo=None) if isinstance(value, datetime) else value)
            unit.db.flush()
        record_unit_changes(unit, "documents", before, updated)
        restored = DocumentIntake.model_validate(inverse["intake"]).model_copy(
            update={
                "source_revision": updated.updated_at.isoformat(),
                "property_id": updated.property_id,
                "updated_at": next_updated_at(intake.updated_at, office.timestamp()),
            }
        )
        office.put_record(unit, "business_document_intake", restored)
        context = resolve_context(unit.store, "document", updated.id, actor_id)
        response = {
            "record": office.dump(updated),
            "document": office.dump(updated),
            "revision": context["revision"],
            "intake": _public(context, restored, unit.user),
            "replayed": False,
        }
        receipt = office.save_command(unit, actor_id, "undo:" + identifier, payload, context, response)
        office.put_record(
            unit,
            "business_qol_commands",
            original.model_copy(update={"undone_by": receipt.id, "updated_at": office.timestamp()}),
        )
        return response


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _normalized_phone(column):
    result: Any = func.coalesce(column, "")
    for symbol in (" ", "+", "-", "(", ")", "/", "."):
        result = func.replace(result, symbol, "")
    return result


def _phone_candidate(column, wanted: str):
    normalized = _normalized_phone(column)
    residue = normalized
    for digit in "0123456789":
        residue = func.replace(residue, digit, "")
    # Python's digit filter accepts arbitrary separators and Unicode digits.
    # Rows beyond the ordinary ASCII format must reach that exact comparison.
    return or_(normalized == wanted, func.length(residue) > 0)


def _text_candidate(store, column, wanted: str):
    value = func.coalesce(column, "")
    dialect = store.db.get_bind().dialect.name
    if dialect == "postgresql":
        # C lower is exact for printable ASCII, independent of the installation
        # locale (e.g. Turkish I). Unicode casefold remains Python's decision.
        ordinary = func.lower(func.trim(value).collate("C"))
        unusual = or_(
            func.octet_length(func.convert_to(value, "UTF8")) > func.length(value), value.op("~")("[[:cntrl:]]")
        )
    elif dialect == "sqlite":
        ordinary = func.lower(func.trim(value))
        unusual = value.op("GLOB")("*[^ -~]*")
    else:
        # A new dialect must never silently narrow a Unicode casefold search.
        return true()
    return or_(ordinary == wanted, unusual)


def _duplicate_rows(store, payload: DuplicateCheck, after: str | None):
    query: Any
    values, kind = payload.candidate, payload.kind
    if kind == "contact":
        email, phone = _text(values.get("email")), _digits(values.get("phone") or values.get("mobile"))
        first, last, company = (_text(values.get(name)) for name in ("first_name", "last_name", "company_name"))
        address = _text(values.get("street")), _text(values.get("zip_code"))
        if hasattr(store, "db"):
            clauses = []
            if email:
                clauses.append(_text_candidate(store, ContactORM.email, email))
            if phone:
                clauses.extend([_phone_candidate(ContactORM.phone, phone), _phone_candidate(ContactORM.mobile, phone)])
            if address[0] and address[1] and (last or company):
                names = []
                if last:
                    names.append(
                        and_(
                            _text_candidate(store, ContactORM.first_name, first),
                            _text_candidate(store, ContactORM.last_name, last),
                        )
                    )
                if company:
                    names.append(_text_candidate(store, ContactORM.company_name, company))
                clauses.append(
                    and_(
                        or_(*names),
                        _text_candidate(store, ContactORM.street, address[0]),
                        _text_candidate(store, ContactORM.zip_code, address[1]),
                    )
                )
            query = select(ContactORM).where(or_(*clauses) if clauses else false())
            if after:
                query = query.where(ContactORM.id > after)
            if payload.exclude_id:
                query = query.where(ContactORM.id != payload.exclude_id)
            records = store.db.scalars(query.order_by(ContactORM.id).execution_options(yield_per=100))
        else:
            records = sorted(store.contacts.values(), key=lambda item: item.id)
        for row in records:
            if row.id == payload.exclude_id or after and row.id <= after:
                continue
            reason = (
                "email"
                if email and _text(row.email) == email
                else "phone"
                if phone and phone in (_digits(row.phone), _digits(row.mobile))
                else None
            )
            names_match = (
                last
                and _text(row.first_name) == first
                and _text(row.last_name) == last
                or company
                and _text(row.company_name) == company
            )
            if (
                not reason
                and address[0]
                and address[1]
                and names_match
                and (_text(row.street), _text(row.zip_code)) == address
            ):
                reason = "name_address"
            if reason:
                yield row, reason, "high" if reason in ("email", "phone") else "medium"
    elif kind == "invoice":
        try:
            gross = money(values["gross_amount"])
            if not gross.is_finite():
                raise ValueError
            candidate = invoice_rules.InvoiceFacts(
                payload.exclude_id or "",
                str(values["supplier"]),
                values.get("invoice_number"),
                date.fromisoformat(str(values["invoice_date"])),
                gross,
            )
        except (KeyError, ValueError, TypeError, DecimalException):
            raise HTTPException(
                422, "Für die Dublettenprüfung werden Lieferant, Rechnungsdatum und Bruttobetrag benötigt."
            ) from None
        from .invoice_review import _settings
        from .maintenance_rows import Rows

        window = _settings(Rows.reading(store)).duplicate_window_days
        if hasattr(store, "db"):
            near = and_(
                InvoiceORM.gross_amount == float(candidate.gross),
                InvoiceORM.invoice_date >= candidate.invoice_date - timedelta(days=window),
                InvoiceORM.invoice_date <= candidate.invoice_date + timedelta(days=window),
            )
            clauses = [near]
            number = invoice_rules.number_key(candidate.invoice_number)
            if number:
                column = InvoiceORM.__table__.c.get("invoice_number")
                if column is not None:
                    # The domain folds arbitrary separators, accents and zero
                    # padding. A raw substring is not a sound prefilter (RE10
                    # also equals RE1-0). Stream numbered candidates until a
                    # durable normalized index exists; never lose an old match.
                    clauses.append(column.is_not(None))
            query = select(InvoiceORM).where(or_(*clauses))
            if after:
                query = query.where(InvoiceORM.id > after)
            if payload.exclude_id:
                query = query.where(InvoiceORM.id != payload.exclude_id)
            records = store.db.scalars(query.order_by(InvoiceORM.id).execution_options(yield_per=100))
        else:
            records = sorted(store.invoices.values(), key=lambda item: item.id)
        for row in records:
            if row.id == payload.exclude_id or after and row.id <= after:
                continue
            other = invoice_rules.InvoiceFacts(
                row.id, row.supplier, getattr(row, "invoice_number", None), row.invoice_date, money(row.gross_amount)
            )
            found = invoice_rules.duplicates(candidate, [other], window)
            if found:
                yield row, found[0]["reason"], "high" if found[0]["reason"] == "same_number" else "medium"
    else:
        if values.get("document_id"):
            source = resolve_context(store, "document", str(values["document_id"]), values["_actor_id"])
            file_url = source["values"]["file_url"]
        elif values.get("file_url"):
            file_url = str(values["file_url"])
        else:
            raise HTTPException(422, "Bitte eine zugängliche Quelldatei auswählen.")
        digest = (
            document_hash(store, str(values["document_id"]), values["_actor_id"])
            if values.get("document_id")
            else file_hash(file_url)
        )
        if hasattr(store, "db"):
            query = select(DocumentORM).where(
                or_(
                    exists(
                        select(DocumentVersionORM.id).where(
                            DocumentVersionORM.document_id == DocumentORM.id, DocumentVersionORM.sha256 == digest
                        )
                    ),
                    exists(
                        select(DocumentIntakeORM.id).where(
                            DocumentIntakeORM.document_id == DocumentORM.id,
                            DocumentIntakeORM.sha256 == digest,
                            DocumentIntakeORM.source_file_url == DocumentORM.file_url,
                        )
                    ),
                )
            )
            if after:
                query = query.where(DocumentORM.id > after)
            if payload.exclude_id:
                query = query.where(DocumentORM.id != payload.exclude_id)
            records = store.db.scalars(query.order_by(DocumentORM.id).execution_options(yield_per=100))
        else:
            records = sorted(
                (
                    document
                    for document in store.documents.values()
                    if any(
                        version.document_id == document.id and version.sha256 == digest
                        for version in archive.memory_archive(store).versions.values()
                    )
                    or any(
                        item.document_id == document.id
                        and item.sha256 == digest
                        and item.source_file_url == document.file_url
                        for item in store.business_document_intake.values()
                    )
                ),
                key=lambda item: item.id,
            )
        for row in records:
            if row.id != payload.exclude_id and (not after or row.id > after):
                if hasattr(store, "db"):
                    version = store.db.scalar(
                        select(DocumentVersionORM.id)
                        .where(DocumentVersionORM.document_id == row.id, DocumentVersionORM.sha256 == digest)
                        .order_by(DocumentVersionORM.number.desc())
                        .limit(1)
                    )
                else:
                    archived = next(
                        (
                            item
                            for item in archive.memory_archive(store).versions.values()
                            if item.document_id == row.id and item.sha256 == digest
                        ),
                        None,
                    )
                    version = archived.id if archived else None
                if document_hash(store, row.id, values["_actor_id"], version_id=version) == digest:
                    yield row, "archived_content" if version else "same_content", "confirmed"


def duplicate_check(store, payload: DuplicateCheck, actor_id: str) -> dict:
    user = actor(actor_id, store)
    signature = office.fingerprint(
        "duplicate_check", {"kind": payload.kind, "candidate": payload.candidate, "exclude_id": payload.exclude_id}
    )
    query = ["duplicates", actor_id, signature]
    after = office.cursor_decode(payload.cursor, query)
    if after and (len(after) != 1 or not isinstance(after[0], str)):
        raise HTTPException(422, "Ungültige Fortsetzung.")
    with scope_context(scope_from_user(user)):
        if payload.exclude_id:
            resolve_context(store, "document" if payload.kind == "file" else payload.kind, payload.exclude_id, actor_id)
        request = payload.model_copy(update={"candidate": {**payload.candidate, "_actor_id": actor_id}})
        incomplete = (
            payload.kind == "invoice"
            and any(payload.candidate.get(name) in (None, "") for name in ("supplier", "invoice_date", "gross_amount"))
            or payload.kind == "file"
            and not (payload.candidate.get("document_id") or payload.candidate.get("file_url"))
        )
        coverage = file_coverage(store) if payload.kind == "file" else None
        if incomplete:
            return {
                "items": [],
                "has_more": False,
                "next_cursor": None,
                "fingerprint": signature,
                "incomplete": True,
                "coverage": coverage,
            }
        values = []
        for row, reason, confidence in _duplicate_rows(store, request, after[0] if after else None):
            context = resolve_context(store, "document" if payload.kind == "file" else payload.kind, row.id, actor_id)
            values.append(
                {
                    "id": row.id,
                    "entity_id": row.id,
                    "kind": payload.kind,
                    "title": context["title"],
                    "href": context["href"],
                    "revision": context["revision"],
                    "reason": reason,
                    "confidence": confidence,
                    "exception": None,
                }
            )
            if len(values) > payload.limit:
                break
        if payload.exclude_id and values:
            kind = "document" if payload.kind == "file" else payload.kind
            source = resolve_context(store, kind, payload.exclude_id, actor_id)
            wanted = {item["id"] for item in values}
            if hasattr(store, "db"):
                rows = store.db.scalars(
                    select(DuplicateExceptionORM)
                    .where(
                        DuplicateExceptionORM.entity_type == kind,
                        or_(
                            and_(
                                DuplicateExceptionORM.entity_id == payload.exclude_id,
                                DuplicateExceptionORM.duplicate_id.in_(wanted),
                            ),
                            and_(
                                DuplicateExceptionORM.duplicate_id == payload.exclude_id,
                                DuplicateExceptionORM.entity_id.in_(wanted),
                            ),
                        ),
                    )
                    .order_by(DuplicateExceptionORM.updated_at.desc(), DuplicateExceptionORM.id.desc())
                )
            else:
                rows = sorted(
                    (
                        row
                        for row in store.business_duplicate_exceptions.values()
                        if row.entity_type == kind
                        and (
                            row.entity_id == payload.exclude_id
                            and row.duplicate_id in wanted
                            or row.duplicate_id == payload.exclude_id
                            and row.entity_id in wanted
                        )
                    ),
                    key=lambda row: (office.utc(row.updated_at), row.id),
                    reverse=True,
                )
            by_id = {item["id"]: item for item in values}
            for row in rows:
                forward = row.entity_id == payload.exclude_id
                target = by_id[row.duplicate_id if forward else row.entity_id]
                left = row.source_revision if forward else row.duplicate_revision
                right = row.duplicate_revision if forward else row.source_revision
                if (
                    target["exception"] is None
                    and office.same_revision(left, source["revision"])
                    and office.same_revision(right, target["revision"])
                ):
                    target["exception"] = {
                        "id": row.id,
                        "reason": row.reason,
                        "actor_id": row.actor_id,
                        "updated_at": row.updated_at.isoformat(),
                    }
        result = office.page(values, payload.limit, query, lambda item: [item["id"]])
        return {**result, "fingerprint": signature, "incomplete": False, "coverage": coverage}


def accept_duplicate(store, payload: DuplicateAccept, actor_id: str) -> dict:
    kind = "document" if payload.kind == "file" else payload.kind
    area = {"document": "/documents", "contact": "/contacts", "invoice": "/invoices"}[kind]
    if payload.entity_id == payload.duplicate_id:
        raise HTTPException(422, "Die Ausnahme braucht zwei verschiedene Datensätze.")
    with archive.work(store, actor_id, write_areas=(area,)) as unit:
        contexts = {
            identifier: resolve_context(unit.store, kind, identifier, actor_id, lock=True)
            for identifier in sorted((payload.entity_id, payload.duplicate_id))
        }
        source, other = contexts[payload.entity_id], contexts[payload.duplicate_id]
        previous = office.replay(unit, actor_id, "duplicate_exception", payload)
        if previous:
            return previous
        office.check_revision(payload.base_revision, source["revision"])
        office.check_revision(payload.duplicate_revision, other["revision"])
        request = DuplicateCheck(
            kind=payload.kind,
            candidate=source["values"] if kind != "document" else {"document_id": payload.entity_id},
            exclude_id=payload.entity_id,
            limit=100,
        )
        request = request.model_copy(update={"candidate": {**request.candidate, "_actor_id": actor_id}})
        if not any(
            row.id == payload.duplicate_id for row, _reason, _confidence in _duplicate_rows(unit.store, request, None)
        ):
            raise office.conflict("Die Datensätze sind nach dem aktuellen Stand keine Dublettenhinweise mehr.")
        stamp = office.timestamp()
        exception = DuplicateException(
            id=str(uuid4()),
            entity_type=kind,
            entity_id=payload.entity_id,
            duplicate_id=payload.duplicate_id,
            property_id=source["property_id"],
            source_revision=source["revision"],
            duplicate_revision=other["revision"],
            reason=payload.reason,
            actor_id=actor_id,
            created_at=stamp,
            updated_at=stamp,
        )
        office.put_record(unit, "business_duplicate_exceptions", exception)
        response = {"exception": office.dump(exception), "replayed": False}
        office.save_command(unit, actor_id, "duplicate_exception", payload, source, response)
        return response
