"""Immutable document originals: archive one inside the caller's transaction, read it back verified.

A feature that produces evidence (the Wohnungsgeberbestätigung) creates its
document and archives the generated PDF in one transaction opened by `work()`:
either both are stored or neither. An archived original is bound to its
document, property, unit, contract and tenant as they were when it was written;
every read checks that binding and the original's blocks against the manifest
before a single byte is returned.

Ported from the earlier release branch (f588c7fc). What this application does
not have is left out on purpose rather than replaced by placeholders:

* No portfolio read restriction exists yet: every active signed-in user may read
  (see backend/permissions.py). Writing needs the write areas the actual
  permission table grants; the account is re-read under a lock inside the
  transaction (auth.locked_account), so a role taken away or an account
  deactivated before the commit stops the write.
* No public route archives ordinary uploads yet. An uploaded file is not
  declared an original after the fact.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, NoReturn

from fastapi import HTTPException
from pydantic import ValidationError as ModelError
from sqlalchemy import LargeBinary, case, exists, func, select, type_coerce
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db.document_version_models import CHUNK_BYTES, DocumentVersionChunkORM, DocumentVersionORM
from ..db.orm_models import ContractORM, DocumentORM, PropertyORM, TenantORM, UnitORM
from ..models import Document
from ..permissions import may_write
from ..storage import ValidationError
from .document_version_validation import (
    ManifestValidationError,
    validate_feature_snapshot,
    validate_manifest_identity,
)

DOCUMENTS_AREA = "/documents"
BINDING_FIELDS = ("portfolio_id", "property_id", "unit_id", "contract_id", "tenant_id")


def fail(message: str, status: int = 409) -> NoReturn:
    raise HTTPException(status, message)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MemoryArchive:
    """The archive of an in-memory store: insert-only, like the guarded SQL tables."""

    def __init__(self) -> None:
        self.versions: dict[str, DocumentVersionORM] = {}
        self.chunks: dict[tuple[str, int], DocumentVersionChunkORM] = {}
        self.lock = threading.RLock()   # one writing unit at a time


def memory_archive(store) -> MemoryArchive:
    return store.__dict__.setdefault("_document_originals", MemoryArchive())


def begin_writer(db: Session) -> None:
    """Take SQLite's write lock now, before reading what the write depends on."""
    connection = db.connection()
    driver = connection.connection.driver_connection
    if connection.dialect.name == "sqlite" and driver is not None and not driver.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


class Unit:
    """One archive transaction: the store to read through, its SQL session (None in memory) and the actor."""

    def __init__(self, store, db: Session | None, user: dict, archive: MemoryArchive | None):
        self.store, self.db, self.user, self.archive = store, db, user, archive
        self._undo: list[tuple[dict, Any, bool, Any]] = []

    @property
    def actor_id(self) -> str:
        return self.user["id"]

    def insert(self, collection: dict, key: Any, value: Any) -> None:
        """In memory: insert into a store collection, undone if the unit fails."""
        assert self.db is None
        self._undo.append((collection, key, key in collection, collection.get(key)))
        collection[key] = value

    def remove(self, collection: dict, key: Any) -> None:
        """In memory: remove from a store collection, restored if the unit fails."""
        assert self.db is None
        self._undo.append((collection, key, key in collection, collection.get(key)))
        del collection[key]

    def rollback(self) -> None:
        for collection, key, present, value in reversed(self._undo):
            if present:
                collection[key] = value
            else:
                collection.pop(key, None)
        self._undo.clear()


def check_account(user: dict | None, *, write_areas: Iterable[str] = ()) -> dict:
    if not user or not user.get("is_active"):
        fail("Anmeldung nicht mehr gültig.", 401)
    if any(not may_write(user.get("role"), area) for area in write_areas):
        fail("Für diesen Vorgang fehlen die nötigen Schreibrechte.", 403)
    return user


@contextmanager
def work(store, actor_id: str, *, write_areas: Iterable[str] = ()) -> Iterator[Unit]:
    """A read (no write_areas) or a write unit; a write commits only if the block succeeds.

    A write holds the actor's account (auth.locked_account) from the rights check
    to the commit, and on SQLite the database's write lock for the whole unit.
    """
    areas = tuple(write_areas)
    if not hasattr(store, "db"):
        archive = memory_archive(store)
        if not areas:
            yield Unit(store, None, check_account(auth.get_user_by_id(actor_id)), archive)
            return
        with auth.locked_account(actor_id) as user, archive.lock:
            unit = Unit(store, None, check_account(user, write_areas=areas), archive)
            try:
                yield unit
            except BaseException:
                unit.rollback()
                raise
        return

    from ..repositories.sql_store import SQLAlchemyStore

    bind = store.db.get_bind()
    db = Session(bind=getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
    try:
        if not areas:
            yield Unit(SQLAlchemyStore(db), db, check_account(auth.get_user_by_id(actor_id)), None)
            return
        begin_writer(db)
        from .portfolio_scope import current_scope
        scope = current_scope()
        if scope is not None and not scope.unrestricted:
            db.info["scoped_writer"] = scope      # Core inserts skip before_flush: fence the commit anyway
        with auth.locked_account(actor_id, db) as user:
            yield Unit(SQLAlchemyStore(db), db, check_account(user, write_areas=areas), None)
            db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


# ─── Reading the archive ─────────────────────────────────────────────────────

def version_row(unit: Unit, version_id: str) -> DocumentVersionORM | None:
    if unit.db is not None:
        return unit.db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.id == version_id))
    assert unit.archive is not None
    return unit.archive.versions.get(version_id)


def head(unit: Unit, document_id: str) -> DocumentVersionORM | None:
    if unit.db is not None:
        return unit.db.scalar(select(DocumentVersionORM).where(DocumentVersionORM.document_id == document_id)
                              .order_by(DocumentVersionORM.number.desc()).limit(1))
    assert unit.archive is not None
    return max((row for row in unit.archive.versions.values() if row.document_id == document_id),
               key=lambda row: row.number, default=None)


def _lock_rows(db: Session, rows: Iterable[tuple[Any, str | None]]) -> None:
    for model, key in rows:
        if key and db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
            fail("Die Dokumentzuordnung ist nicht mehr vorhanden.", 404)


def bind_document(unit: Unit, document_id: str, *, lock: bool = False) -> tuple[Document, dict]:
    """The document and the subject an original of it is bound to.

    With `lock` (SQL) the tenant, property, unit, contract and document rows are
    locked in that order and read again, so the binding cannot change before
    the commit; a binding that changed meanwhile is refused.
    """
    store, db = unit.store, unit.db
    document = store.get_document(document_id)
    if lock and db is not None:
        before = (document.property_id, document.unit_id, document.contract_id, document.file_url)
        contract = store.get_contract(document.contract_id) if document.contract_id else None
        location = store.get_unit(document.unit_id) if document.unit_id else None
        property_id = document.property_id or (location.property_id if location else None) or (
            contract.property_id if contract else None)
        unit_id = document.unit_id or (contract.unit_id if contract else None)
        _lock_rows(db, [(TenantORM, contract.tenant_id if contract else None), (PropertyORM, property_id),
                        (UnitORM, unit_id), (ContractORM, document.contract_id), (DocumentORM, document.id)])
        db.expire_all()            # read what the locks protect, not what was read before
        document = store.get_document(document_id)
        if before != (document.property_id, document.unit_id, document.contract_id, document.file_url):
            fail("Die Dokumentzuordnung wurde während der Prüfung geändert. Bitte neu laden.")
    contract = store.get_contract(document.contract_id) if document.contract_id else None
    location = store.get_unit(document.unit_id) if document.unit_id else None
    property_id = document.property_id or (location.property_id if location else None) or (
        contract.property_id if contract else None)
    if not property_id:
        raise ValidationError("Das Dokument ist keiner Immobilie und keinem Vertrag zugeordnet.")
    prop = store.get_property(property_id)
    if (location and location.property_id != prop.id) or (contract and (
            contract.property_id != prop.id or (location and contract.unit_id != location.id))):
        raise ValidationError("Immobilie, Einheit und Vertrag des Dokuments passen nicht zusammen.")
    store.get_portfolio(prop.portfolio_id)
    _require_one_portfolio(unit, document.id, prop.portfolio_id)
    return document, {
        "portfolio_id": prop.portfolio_id, "property_id": prop.id,
        "unit_id": document.unit_id or (contract.unit_id if contract else None),
        "contract_id": document.contract_id, "tenant_id": contract.tenant_id if contract else None,
    }


def _require_one_portfolio(unit: Unit, document_id: str, portfolio_id: str) -> None:
    if unit.db is not None:
        table = DocumentVersionORM.__table__
        conflicting = unit.db.scalar(select(exists().where(
            table.c.document_id == document_id, table.c.portfolio_id.is_distinct_from(portfolio_id))))
    else:
        assert unit.archive is not None
        conflicting = any(row.document_id == document_id and row.portfolio_id != portfolio_id
                          for row in unit.archive.versions.values())
    if conflicting:
        fail("Die archivierte Dokumenthistorie gehört zu einem anderen Bestand.", 503)


def validate_manifest(row: Any) -> Document:
    try:
        snapshot = Document.model_validate(row.metadata_snapshot)
        validate_manifest_identity(row, snapshot.model_dump())
        validate_feature_snapshot(row, row.metadata_snapshot)
    except (ModelError, ManifestValidationError, ValueError, TypeError):
        fail("Die archivierten Dokumentmetadaten sind beschädigt.", 503)
    return snapshot


def authorized_version(unit: Unit, document_id: str, version_id: str, binding: dict) -> DocumentVersionORM:
    """The version, if it belongs to the document and its binding still holds."""
    row = version_row(unit, version_id)
    if row is None or row.document_id != document_id or row.portfolio_id != binding["portfolio_id"]:
        fail("Dokumentfassung nicht gefunden.", 404)
    validate_manifest(row)
    if any(getattr(row, key) != binding[key] for key in BINDING_FIELDS):
        fail("Die archivierte Dokumentzuordnung stimmt nicht mehr mit Vertrag, Einheit oder Objekt überein.")
    return row


def verified_blocks(unit: Unit, row: DocumentVersionORM) -> Iterator[bytes]:
    """The original's bytes, block by block; fails before the end if anything does not add up."""
    validate_manifest(row)
    chunks: Iterable[Any]
    if unit.db is not None:
        db = unit.db
        table = DocumentVersionChunkORM.__table__
        if db.scalar(select(exists().where(table.c.version_id == row.id,
                                           table.c.portfolio_id.is_distinct_from(row.portfolio_id)))):
            fail("Die archivierte Fassung gehört zu einem anderen Bestand.", 503)
        # Bound the block size in SQL before the driver reads a possibly damaged BLOB.
        model = DocumentVersionChunkORM
        bounded = type_coerce(case((func.length(model.data).between(1, CHUNK_BYTES), model.data), else_=None),
                              LargeBinary)
        query = (select(model.position, model.portfolio_id, bounded.label("data"))
                 .where(model.version_id == row.id).order_by(model.position))
        chunks = (SimpleNamespace(**value) for value in db.execute(query).mappings())
    else:
        assert unit.archive is not None
        chunks = sorted((chunk for chunk in unit.archive.chunks.values() if chunk.version_id == row.id),
                        key=lambda chunk: chunk.position)
    checksum, size, expected = hashlib.sha256(), 0, 0
    for chunk in chunks:
        data = chunk.data
        if not isinstance(data, (bytes, bytearray, memoryview)):
            fail("Die archivierte Fassung enthält einen ungültigen Block.", 503)
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
        fail("Die Prüfsumme der archivierten Fassung stimmt nicht.", 503)


def original_bytes(unit: Unit, row: DocumentVersionORM) -> bytes:
    return b"".join(verified_blocks(unit, row))


def public(row: DocumentVersionORM) -> dict:
    return {name: getattr(row, name) for name in (
        "id", "document_id", "number", "predecessor_id", "restored_from_id", "actor_id", "operation",
        "comment", "filename", "media_type", "sha256", "size_bytes")} | {
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "metadata_snapshot": deepcopy(row.metadata_snapshot)}


def history(store, document_id: str, actor_id: str, *, before: int | None = None, limit: int = 25) -> dict:
    """The document's versions, newest first, each checked against the current binding."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValidationError("Bitte eine Seitengröße zwischen 1 und 500 wählen.")
    with work(store, actor_id) as unit:
        _, binding = bind_document(unit, document_id)
        if unit.db is not None:
            query = select(DocumentVersionORM).where(DocumentVersionORM.document_id == document_id)
            if before is not None:
                query = query.where(DocumentVersionORM.number < before)
            found = list(unit.db.scalars(query.order_by(DocumentVersionORM.number.desc()).limit(limit + 1)))
        else:
            assert unit.archive is not None
            found = sorted((row for row in unit.archive.versions.values()
                            if row.document_id == document_id and (before is None or row.number < before)),
                           key=lambda row: row.number, reverse=True)[:limit + 1]
        items = [public(authorized_version(unit, document_id, row.id, binding)) for row in found[:limit]]
        return {"document_id": document_id, "items": items,
                "next_before": found[limit - 1].number if len(found) > limit else None}


# ─── Writing an original ─────────────────────────────────────────────────────

def filename(value: str) -> str:
    name = PurePosixPath(value.replace("\\", "/")).name
    return "".join(char for char in name if ord(char) >= 32 and ord(char) != 127) or "document.bin"


def _add(unit: Unit, value: DocumentVersionORM | DocumentVersionChunkORM) -> None:
    if unit.db is not None:
        unit.db.add(value)
        unit.db.flush()
    elif isinstance(value, DocumentVersionORM):
        assert unit.archive is not None
        unit.insert(unit.archive.versions, value.id, value)
    else:
        assert unit.archive is not None
        unit.insert(unit.archive.chunks, (value.version_id, value.position), value)


def persist_version_bytes(unit: Unit, row: DocumentVersionORM, blocks: Iterable[bytes]) -> DocumentVersionORM:
    """Write one manifest and its blocks inside the unit's transaction.

    No rights, binding or commit here: the caller has checked them. Blocks that
    do not add up to the manifest's size and checksum fail the whole unit.
    """
    _add(unit, row)
    checksum, size = hashlib.sha256(), 0
    for position, block in enumerate(blocks):
        if not isinstance(block, bytes) or not 0 < len(block) <= CHUNK_BYTES:
            raise ValidationError("Ungültiger Dokumentblock.")
        checksum.update(block)
        size += len(block)
        _add(unit, DocumentVersionChunkORM(version_id=row.id, position=position, portfolio_id=row.portfolio_id,
                                           data=block))
    if (checksum.hexdigest(), size) != (row.sha256, row.size_bytes):
        fail("Die Datei wurde während der Archivierung geändert. Es wurde nichts gespeichert.")
    return row


def publish_generated_original(unit: Unit, document: Document, binding: dict, content: bytes, request_hash: str,
                               *, version_id: str, metadata_extra: dict | None = None) -> DocumentVersionORM:
    """Archive a PDF the application generated for a document created in this unit.

    Only a first original, never a replacement. The caller has created the
    document in the same unit and owns the rights check and the transaction.
    """
    if head(unit, document.id) is not None:
        fail("Für dieses Dokument ist bereits ein Original archiviert.")
    actual, actual_binding = bind_document(unit, document.id)
    if actual_binding != binding or actual.file_url != document.file_url:
        fail("Die Dokumentzuordnung wurde geändert. Bitte erneut prüfen.")
    if not content.startswith(b"%PDF-"):
        raise ValidationError("Das erzeugte Schreiben ist kein PDF.")
    if len(content) > settings.max_upload_size_bytes:
        raise ValidationError("Das Schreiben ist größer als die erlaubte Dokumentgröße.")
    snapshot = actual.model_dump(mode="json")
    if metadata_extra is not None:
        if not isinstance(metadata_extra, dict) or any(
                not isinstance(key, str) or not key or key in snapshot for key in metadata_extra):
            raise ValidationError("Ungültige zusätzliche Originalmetadaten.")
        snapshot = {**snapshot, **deepcopy(metadata_extra)}
    row = DocumentVersionORM(
        id=version_id, document_id=document.id, **binding, number=1, predecessor_id=None,
        restored_from_id=None, actor_id=unit.actor_id, idempotency_key="generated-" + document.id,
        request_sha256=request_hash, operation="archive_original", comment="Erzeugtes und freigegebenes Original",
        filename=filename(document.file_url), media_type="application/pdf",
        sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
        metadata_snapshot=snapshot, created_at=now())
    validate_manifest(row)
    return persist_version_bytes(unit, row, (content[offset:offset + CHUNK_BYTES]
                                             for offset in range(0, len(content), CHUNK_BYTES)))


# ─── Guards for the rest of the application ──────────────────────────────────

_SUBJECT_COLUMNS = {"document": "document_id", "contract": "contract_id", "unit": "unit_id",
                    "property": "property_id", "tenant": "tenant_id", "portfolio": "portfolio_id"}

# Fields whose change would detach archived originals from what they prove.
_BOUND_FIELDS = {
    "document": ("property_id", "unit_id", "contract_id", "tenant_id", "file_url", "document_type"),
    "contract": ("property_id", "unit_id", "tenant_id"),
    "unit": ("property_id",),
    "property": ("portfolio_id",),
}


def count_originals(store, entity: str, entity_id: str) -> int:
    """How many archived versions are bound to the record (document, contract, unit, ...)."""
    column = _SUBJECT_COLUMNS[entity]
    if hasattr(store, "db"):
        return store.db.scalar(select(func.count()).select_from(DocumentVersionORM)
                               .where(getattr(DocumentVersionORM, column) == entity_id)) or 0
    return sum(1 for row in memory_archive(store).versions.values() if getattr(row, column) == entity_id)


def ensure_binding_kept(store, entity: str, entity_id: str, old: Any, changes: dict) -> None:
    """Refuse a change that would move a record with archived originals to another subject."""
    moved = [name for name in _BOUND_FIELDS[entity]
             if name in changes and changes[name] != getattr(old, name, None)]
    if moved and count_originals(store, entity, entity_id):
        fail("Für diesen Datensatz sind unveränderliche Originale archiviert (z. B. eine "
             "Wohnungsgeberbestätigung). Zuordnung und Datei lassen sich deshalb nicht mehr ändern.")


def ensure_no_originals(store, entity: str, entity_id: str) -> None:
    if count_originals(store, entity, entity_id):
        fail("Für diesen Datensatz sind unveränderliche Originale archiviert (z. B. eine "
             "Wohnungsgeberbestätigung). Er kann deshalb nicht gelöscht werden.")
