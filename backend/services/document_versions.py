"""Explicit immutable originals, with authoritative parent locks and replay.

The legacy Document URL always identifies the original. The latest archived
version is a separate, explicit object; ordinary metadata edits remain possible.
"""

import hashlib
import mimetypes
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Iterable, NoReturn
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError as ModelError
from sqlalchemy import LargeBinary, case, exists, func, select, type_coerce
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db.document_version_models import DOCUMENT_VERSION_MODELS, DocumentVersionChunkORM, DocumentVersionORM
from ..db.orm_models import ContractORM, DocumentORM, PropertyORM, TenantORM, UnitORM
from ..models import Document
from ..permissions import may_write_resource
from ..storage import ValidationError
from .concurrency import etag
from .contract_attachment import CHUNK_BYTES, local_source
from .contract_occupancy import begin_writer
from .contract_wizard import digest
from .document_version_validation import ManifestValidationError, validate_manifest_identity
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user
from .tenant_privacy import _memory_privacy_lock


def fail(message, status=409) -> NoReturn:
    raise HTTPException(status, message)


def identity(actor_id, write):
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        fail("Anmeldung nicht mehr gültig.", 401)
    if write and not may_write_resource(user["role"], "documents"):
        fail("Keine Berechtigung zur Dokumentverwaltung.", 403)
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        fail("Benutzerbindung ist nicht gültig.", 403)
    return refresh_scope(captured) if captured is not None else scope_from_user(user)


@contextmanager
def work(store, actor_id, *, write=False):
    sql = hasattr(store, "db")
    # Account -> domain ordering matches compound private-draft/privacy writes.
    with nullcontext() if sql else _memory_privacy_lock():
        captured = identity(actor_id, write)
        with scope_context(captured):
            db = Session(store.db.get_bind(), expire_on_commit=False, autoflush=False) if sql else None
            if db is not None:
                from ..repositories.sql_store import SQLAlchemyStore
                active = SQLAlchemyStore(db)
            else:
                active = store
                for model in DOCUMENT_VERSION_MODELS:
                    store.__dict__.setdefault(model.__tablename__, {})
                before = {m.__tablename__: deepcopy(store.__dict__[m.__tablename__]) for m in DOCUMENT_VERSION_MODELS} if write else None
            try:
                if db is not None and write:
                    begin_writer(db)
                yield active, db, captured
                refresh_scope(captured)
                if db is not None and write:
                    db.commit()
            except BaseException:
                if db is not None:
                    db.rollback()
                elif write:
                    assert before is not None
                    for name, value in before.items():
                        store.__dict__[name] = value
                raise
            finally:
                if db is not None:
                    db.close()


def _row(store, db, version_id):
    return db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.id == version_id)) if db is not None else store.__dict__["document_versions"].get(version_id)


def _head(store, db, document_id):
    if db is not None:
        return db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.document_id == document_id)
            .order_by(DocumentVersionORM.number.desc()).limit(1))
    return max((r for r in store.__dict__["document_versions"].values() if r.document_id == document_id),
        key=lambda r: r.number, default=None)


def _document(store, db, identifier, *, lock=False):
    document = store.get_document(identifier)
    # Acquire subject/location rows before the document. A profile anonymization
    # or parent deletion cannot change its subject during publication.
    if lock and db is not None:
        original_binding = (document.property_id, document.unit_id, document.contract_id, document.file_url)
        contract = store.get_contract(document.contract_id) if document.contract_id else None
        unit = store.get_unit(document.unit_id) if document.unit_id else None
        parents: list[tuple[Any, str | None]] = [(TenantORM, contract.tenant_id)] if contract else []
        property_id = document.property_id or (unit.property_id if unit else None) or (contract.property_id if contract else None)
        unit_id = document.unit_id or (contract.unit_id if contract else None)
        parents += [(PropertyORM, property_id), (UnitORM, unit_id), (ContractORM, document.contract_id)]
        for model, key in parents:
            if key and db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                fail("Die Dokumentzuordnung ist nicht mehr zugänglich.", 404)
        if db.scalar(select(DocumentORM.id).where(DocumentORM.id == identifier).with_for_update()) is None:
            fail("Dokument nicht gefunden.", 404)
        document = store.get_document(identifier)
        if original_binding != (document.property_id, document.unit_id, document.contract_id, document.file_url):
            fail("Die Dokumentzuordnung wurde während der Prüfung geändert. Erneut laden.")
    contract = store.get_contract(document.contract_id) if document.contract_id else None
    unit = store.get_unit(document.unit_id) if document.unit_id else None
    property_id = document.property_id or (unit.property_id if unit else None) or (contract.property_id if contract else None)
    if not property_id:
        raise ValidationError("Vor der Versionierung bitte das Dokument einer Immobilie oder einem Vertrag zuordnen.")
    prop = store.get_property(property_id)
    if (unit and unit.property_id != prop.id) or (contract and (contract.property_id != prop.id
            or (unit and contract.unit_id != unit.id))):
        raise ValidationError("Immobilie, Einheit und Vertrag des Dokuments passen nicht zusammen.")
    store.get_portfolio(prop.portfolio_id)
    _require_journal_portfolio(store, db, identifier, prop.portfolio_id)
    return document, dict(portfolio_id=prop.portfolio_id, property_id=prop.id,
        unit_id=document.unit_id or (contract.unit_id if contract else None), contract_id=document.contract_id,
        tenant_id=contract.tenant_id if contract else None)


def _require_journal_portfolio(store, db, document_id, portfolio_id):
    """Check an authorized document's full journal before scoped head queries."""
    if db is not None:
        table = DocumentVersionORM.__table__
        conflicting = db.connection().scalar(select(exists(select(1).select_from(table).where(
            table.c.document_id == document_id, table.c.portfolio_id.is_distinct_from(portfolio_id)))))
    else:
        conflicting = any(row.document_id == document_id and row.portfolio_id != portfolio_id
            for row in store.__dict__.get("document_versions", {}).values())
    if conflicting:
        fail("Die archivierte Dokumenthistorie besitzt eine widersprüchliche Portfoliozuordnung.", 503)


def _authorized_version(store, db, document_id, version_id, binding):
    row = _row(store, db, version_id)
    if row is None or row.document_id != document_id or row.portfolio_id != binding["portfolio_id"]:
        fail("Dokumentfassung nicht gefunden.", 404)
    validate_manifest(row)
    if any(getattr(row, key) != binding[key] for key in ("property_id", "unit_id", "contract_id", "tenant_id")):
        fail("Die archivierte Dokumentzuordnung stimmt nicht mehr mit der Quelle überein.")
    # Historical immutable subjects cannot be turned into another party's
    # evidence by reassigning a source contract through an unrelated pathway.
    if row.contract_id and store.get_contract(row.contract_id).tenant_id != row.tenant_id:
        fail("Die historische Vertragszuordnung wurde geändert. Belege müssen geprüft werden.")
    return row


def validate_manifest(row):
    """Pure validation usable by coherent recovery/privacy readers before DML."""
    try:
        snapshot = Document.model_validate(row.metadata_snapshot)
        validate_manifest_identity(row, snapshot.model_dump())
    except (ModelError, ManifestValidationError):
        fail("Die archivierten Dokumentmetadaten sind beschädigt.", 503)
    return snapshot


def public(row):
    return {name: getattr(row, name) for name in ("id", "document_id", "number", "predecessor_id", "restored_from_id",
        "actor_id", "operation", "comment", "filename", "media_type", "sha256", "size_bytes")} | {
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "metadata_snapshot": deepcopy(row.metadata_snapshot),
        "download_url": f"/documents/{row.document_id}/versions/{row.id}/download"}


def history(store, document_id, actor_id, *, before=None, limit=25):
    with work(store, actor_id) as (active, db, _):
        document, binding = _document(active, db, document_id)
        head = _head(active, db, document_id)
        if head:
            _authorized_version(active, db, document_id, head.id, binding)
        if db is not None:
            query = select(DocumentVersionORM).where(DocumentVersionORM.document_id == document_id)
            if before is not None:
                query = query.where(DocumentVersionORM.number < before)
            found = list(db.scalars(query.order_by(DocumentVersionORM.number.desc()).limit(limit + 1)))
        else:
            found = sorted((r for r in active.__dict__["document_versions"].values()
                if r.document_id == document_id and (before is None or r.number < before)), key=lambda r: r.number, reverse=True)[:limit + 1]
        return {"document_id": document_id, "document_etag": etag("documents", document_id, document.updated_at),
            "head": public(head) if head else None, "items": [public(_authorized_version(active, db, document_id, r.id, binding)) for r in found[:limit]],
            "next_before": found[limit - 1].number if len(found) > limit else None, "persistent": db is not None,
            "original_url": document.file_url, "original_url_policy": "unchanged_original"}


@contextmanager
def original_source(store, document):
    # Exact existing wizard references are immutable originals stored in SQL.
    from ..routers.files import _file_url_to_key
    from .contract_wizard import read_pdf_for_key
    key = _file_url_to_key(document.file_url)
    if key.startswith("contract-wizard/"):
        from ..db.contract_wizard_models import ContractDraftORM
        from .contract_wizard import get_row
        if document.file_url != "/uploads/" + key:
            raise ValidationError("Der ursprüngliche Vertragsbeleg benötigt seinen exakten verwalteten Quellenverweis.")
        draft = get_row(store, getattr(store, "db", None), ContractDraftORM, key.removeprefix("contract-wizard/").removesuffix(".pdf"))
        if draft is None or draft.document_id != document.id:
            raise ValidationError("Der ursprüngliche Vertragsbeleg ist nicht diesem Dokument zugeordnet.")
        content = read_pdf_for_key(store, key)
        if content is None:
            raise ValidationError("Der ursprüngliche Vertragsbeleg ist nicht verfügbar.")
        yield BytesIO(content)
    else:
        value = document.file_url
        if not value.startswith(("/uploads/", "uploads/")) and Path(value).is_absolute():
            from .contract_attachment import get_file_storage
            from .file_storage import LocalStorage
            storage = get_file_storage()
            if not isinstance(storage, LocalStorage):
                raise ValidationError("Das lokale Original ist nicht im verwalteten Uploadspeicher verfügbar.")
            try:
                key = Path(value).resolve().relative_to(storage.base_dir.resolve()).as_posix()
            except (ValueError, OSError):
                raise ValidationError("Das absolute Original liegt außerhalb des verwalteten Uploadspeichers.") from None
            value = storage.get_url(key)
        with local_source(value) as source:
            yield source


def _measure(source, on_chunk=None):
    checksum, size, position = hashlib.sha256(), 0, 0
    while block := source.read(CHUNK_BYTES):
        size += len(block)
        if size > settings.max_upload_size_bytes:
            raise ValidationError("Datei überschreitet das konfigurierte technische Uploadbudget. Budget anpassen oder Datei aufteilen.")
        checksum.update(block)
        if on_chunk:
            on_chunk(position, block)
        position += 1
    return checksum.hexdigest(), size


def source_preview(store, document_id, actor_id):
    with work(store, actor_id) as (active, db, _):
        document, _ = _document(active, db, document_id)
        with original_source(active, document) as source:
            sha256, size = _measure(source)
        return {"document_etag": etag("documents", document_id, document.updated_at), "sha256": sha256,
            "size_bytes": size, "filename": filename(document.file_url), "source_policy": "existing_managed_original"}


def filename(value):
    name = PurePosixPath(value.replace("\\", "/")).name
    return "".join(char for char in name if ord(char) >= 32 and ord(char) != 127) or "document.bin"


def _add(store, db, row):
    if db is not None:
        db.add(row)
        db.flush()
    else:
        key = row.id if isinstance(row, DocumentVersionORM) else (row.version_id, row.position)
        store.__dict__[row.__tablename__][key] = row


def _claim(store, db, document, command, actor_id, request_hash):
    existing = db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.actor_id == actor_id,
        DocumentVersionORM.idempotency_key == command.idempotency_key)) if db is not None else next(
        (r for r in store.__dict__["document_versions"].values() if r.actor_id == actor_id and r.idempotency_key == command.idempotency_key), None)
    if existing:
        if existing.document_id != document.id or existing.request_sha256 != request_hash:
            fail("Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
        return existing, None
    head = _head(store, db, document.id)
    if (head.id if head else None) != command.expected_head_id:
        fail("Eine andere Fassung wurde gespeichert. Verlauf neu laden und bewusst prüfen.")
    if etag("documents", document.id, document.updated_at) != command.expected_document_etag:
        fail("Die Dokumentmetadaten wurden geändert. Neu laden und prüfen.", 412)
    if not command.confirmed:
        raise ValidationError("Die Archivierung muss ausdrücklich bestätigt werden.")
    return None, head


def publish(store, document_id, command, actor_id, *, source=None, upload_name=None, restore=False):
    identity(actor_id, True)
    operation = "restore" if restore else "upload" if source is not None else "archive_original"
    measured = None
    if source is not None:
        from ..routers.files import _validate_upload
        upload_name = filename(upload_name or "document.bin")
        _validate_upload(UploadFile(source, filename=upload_name))
        source.seek(0)
        measured = _measure(source)
        source.seek(0)
    request_hash = digest({"document_id": document_id, "operation": operation,
        "command": command.model_dump(mode="json"), "upload_name": upload_name, "bytes": measured})
    with work(store, actor_id, write=True) as (active, db, _):
        document, binding = _document(active, db, document_id, lock=True)
        replay, head = _claim(active, db, document, command, actor_id, request_hash)
        if replay:
            _authorized_version(active, db, document_id, replay.id, binding)
            return public(replay)
        if (operation == "archive_original") != (head is None):
            raise ValidationError("Zuerst das vorhandene Original bewusst archivieren; spätere Fassungen als neue Version veröffentlichen.")
        if head:
            _authorized_version(active, db, document_id, head.id, binding)
        old = _authorized_version(active, db, document_id, command.source_version_id, binding) if restore else None
        with ExitStack() as sources:
            if old:
                blocks = verified_blocks(active, old)
                expected = (old.sha256, old.size_bytes)
                name, mime = old.filename, old.media_type
            else:
                actual_source = source if source is not None else sources.enter_context(original_source(active, document))
                expected = measured if measured is not None else _measure(actual_source)
                actual_source.seek(0)
                name = upload_name if source is not None else filename(document.file_url)
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if operation == "archive_original" and expected[0] != command.expected_sha256:
                    fail("Die Originaldatei wurde seit der Vorschau geändert. Erneut prüfen.")
                blocks = iter(lambda: actual_source.read(CHUNK_BYTES), b"")
            row = DocumentVersionORM(id=str(uuid4()), document_id=document_id, **binding,
                number=(head.number + 1) if head else 1, predecessor_id=head.id if head else None,
                restored_from_id=old.id if old else None, actor_id=actor_id, idempotency_key=command.idempotency_key,
                request_sha256=request_hash, operation=operation, comment=command.comment,
                filename=name, media_type=mime, sha256=expected[0], size_bytes=expected[1],
                metadata_snapshot=document.model_dump(mode="json"), created_at=datetime.now(timezone.utc).replace(tzinfo=None))
            _add(active, db, row)
            checksum, size = hashlib.sha256(), 0
            for position, block in enumerate(blocks):
                checksum.update(block)
                size += len(block)
                _add(active, db, DocumentVersionChunkORM(version_id=row.id, position=position,
                    portfolio_id=row.portfolio_id, data=block))
            if (checksum.hexdigest(), size) != expected:
                fail("Die Quelldatei wurde während der Archivierung geändert. Es wurde keine Fassung gespeichert.")
        return public(row)


def verified_blocks(store, row):
    validate_manifest(row)
    db = getattr(store, "db", None)
    chunks: Iterable[Any]
    if db is not None:
        # Scoped ORM queries must not hide a corrupt extra block, including for
        # an otherwise valid zero-byte original. Read only an existence bit for
        # this authorized version, in the same transaction, before loading data.
        table = DocumentVersionChunkORM.__table__
        conflicting = db.connection().scalar(select(exists(select(1).select_from(table).where(
            table.c.version_id == row.id, table.c.portfolio_id.is_distinct_from(row.portfolio_id)))))
        if conflicting:
            fail("Die archivierte Fassung besitzt eine widersprüchliche Portfoliozuordnung.", 503)
        # Check inside SQL BEFORE the driver materializes a possibly corrupt
        # BLOB. A restored database may not have enforced its original CHECK.
        model = DocumentVersionChunkORM
        bounded_data = type_coerce(case((func.length(model.data).between(1, CHUNK_BYTES), model.data), else_=None), LargeBinary)
        query = select(model.position, model.portfolio_id, bounded_data.label("data")).where(model.version_id == row.id)
        chunks = (SimpleNamespace(**value) for value in db.execute(query.order_by(model.position)
            .execution_options(yield_per=8)).mappings())
    else:
        chunks = sorted((r for r in store.__dict__.get("document_version_chunks", {}).values()
            if r.version_id == row.id), key=lambda r: r.position)
    checksum, size, expected = hashlib.sha256(), 0, 0
    for chunk in chunks:
        data = chunk.data
        if data is None or not isinstance(data, (bytes, bytearray, memoryview)):
            fail("Die archivierte Fassung besitzt einen ungültigen Datenblock.", 503)
        length = data.nbytes if isinstance(data, memoryview) else len(data)
        if chunk.position != expected or chunk.portfolio_id != row.portfolio_id or not 0 < length <= CHUNK_BYTES:
            fail("Die archivierte Fassung ist unvollständig oder beschädigt.", 503)
        block = bytes(data)
        checksum.update(block)
        size += length
        if size > row.size_bytes:
            fail("Die archivierte Fassung hat eine ungültige Größe.", 503)
        yield block
        expected += 1
    if (checksum.hexdigest(), size) != (row.sha256, row.size_bytes):
        fail("Prüfsumme der archivierten Fassung ist ungültig.", 503)


def prepare_download(store, document_id, version_id, actor_id, *, parent=None):
    from scripts.private_server_backup import private_workspace, protected_new_file

    from .datev_export import CompiledExport
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        path = workspace / "document.bin"
        with work(store, actor_id) as (active, db, captured):
            _, binding = _document(active, db, document_id)
            row = _authorized_version(active, db, document_id, version_id, binding)
            with protected_new_file(path) as output:
                for block in verified_blocks(active, row):
                    output.write(block)
            refresh_scope(captured)
            manifest = {"size": row.size_bytes, "sha256": row.sha256, "filename": row.filename,
                "media_type": row.media_type}
        return CompiledExport(path, manifest, cleanup), captured
    except BaseException:
        cleanup.close()
        raise
