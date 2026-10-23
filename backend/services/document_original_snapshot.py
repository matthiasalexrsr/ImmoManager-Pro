"""Archived document originals in JSON snapshots (export, import, restore).

A snapshot carries every original with its bytes (base64, one string per
64 KiB block), so an export loses nothing. Importing adds originals only after
proving each one against the data it will sit next to: blocks against size and
checksum, the manifest against its document, the binding against property,
unit and contract. Originals already present must arrive unchanged.

Restoring a snapshot replaces all business data. Archived originals cannot be
deleted, so a restore over a database that holds any is refused; the complete
database backup (.db) restores them as they are.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import ValidationError as ModelError
from sqlalchemy import func, select

from ..db.document_version_models import CHUNK_BYTES, DocumentVersionChunkORM, DocumentVersionORM
from ..models import Document
from .document_version_validation import (
    SHA256,
    VERSION_FIELDS,
    ManifestValidationError,
    validate_feature_snapshot,
    validate_manifest_identity,
)
from .document_versions import memory_archive

SNAPSHOT_KEY = "document_originals"
RESTORE_REFUSED = (
    "Der Datenbestand enthält unveränderliche Originale (z. B. Wohnungsgeberbestätigungen), die eine "
    "Wiederherstellung löschen würde. Bitte die vollständige Datenbanksicherung (.db) verwenden"
)
_TEXT_FIELDS = ("comment", "filename", "media_type")

Incoming = tuple[DocumentVersionORM, list[bytes]]


def _is_sql(store: Any) -> bool:
    return hasattr(store, "db")


def has_originals(store: Any) -> bool:
    if _is_sql(store):
        return bool(store.db.scalar(select(func.count()).select_from(DocumentVersionORM)))
    return bool(memory_archive(store).versions)


def _manifests(store: Any) -> list[DocumentVersionORM]:
    if _is_sql(store):
        return list(store.db.scalars(select(DocumentVersionORM)
                                     .order_by(DocumentVersionORM.document_id, DocumentVersionORM.number)))
    return sorted(memory_archive(store).versions.values(), key=lambda row: (row.document_id, row.number))


def _blocks(store: Any, version_id: str) -> list[bytes]:
    if _is_sql(store):
        return [bytes(data) for data in store.db.scalars(
            select(DocumentVersionChunkORM.data).where(DocumentVersionChunkORM.version_id == version_id)
            .order_by(DocumentVersionChunkORM.position))]
    chunks = memory_archive(store).chunks
    return [chunk.data for _, chunk in sorted((key, value) for key, value in chunks.items() if key[0] == version_id)]


def export(store: Any) -> list[dict]:
    exported = []
    for row in _manifests(store):
        record: dict[str, Any] = {name: getattr(row, name) for name in VERSION_FIELDS + ("comment",)}
        record["created_at"] = row.created_at.isoformat()
        record["metadata_snapshot"] = row.metadata_snapshot
        record["blocks"] = [base64.b64encode(block).decode("ascii") for block in _blocks(store, row.id)]
        exported.append(record)
    return exported


def parse(raw: Any) -> tuple[list[Incoming], list[str]]:
    """Decode the snapshot's originals; problems name the record, nothing is checked against data yet."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{SNAPSHOT_KEY}: Liste erwartet"]
    parsed: list[Incoming] = []
    problems: list[str] = []
    for index, item in enumerate(raw):
        label = f"{SNAPSHOT_KEY}[{index}]"
        try:
            parsed.append(_decode(item))
        except (ValueError, TypeError, KeyError, binascii.Error) as exc:
            problems.append(f"{label}: {exc}")
    return parsed, problems


def _decode(item: Any) -> Incoming:
    if not isinstance(item, dict):
        raise ValueError("Objekt erwartet")
    missing = [name for name in VERSION_FIELDS + ("comment", "metadata_snapshot", "blocks") if name not in item]
    if missing:
        raise ValueError(f"Felder fehlen: {', '.join(missing)}")
    for name in ("id", "document_id", "portfolio_id", "property_id", "actor_id", "idempotency_key") + _TEXT_FIELDS:
        if not isinstance(item[name], str) or (name != "comment" and not item[name]):
            raise ValueError(f"{name}: Text erwartet")
    for name in ("unit_id", "contract_id", "tenant_id", "predecessor_id", "restored_from_id"):
        if item[name] is not None and not isinstance(item[name], str):
            raise ValueError(f"{name}: Text erwartet")
    for name in ("sha256", "request_sha256"):
        if not isinstance(item[name], str) or not SHA256.fullmatch(item[name]):
            raise ValueError(f"{name}: Prüfsumme erwartet")
    if not isinstance(item["metadata_snapshot"], dict) or not isinstance(item["blocks"], list):
        raise ValueError("metadata_snapshot oder blocks ungültig")
    created_at = datetime.fromisoformat(item["created_at"]) if isinstance(item["created_at"], str) else None
    if created_at is None:
        raise ValueError("created_at: Zeitpunkt erwartet")
    blocks = []
    for block in item["blocks"]:
        if not isinstance(block, str):
            raise ValueError("blocks: Text erwartet")
        data = base64.b64decode(block, validate=True)
        if not 0 < len(data) <= CHUNK_BYTES:
            raise ValueError("blocks: ungültige Blockgröße")
        blocks.append(data)
    row = DocumentVersionORM(**{name: item[name] for name in VERSION_FIELDS if name != "created_at"},
                             comment=item["comment"], metadata_snapshot=item["metadata_snapshot"],
                             created_at=created_at.replace(tzinfo=None))
    return row, blocks


def _same(a: DocumentVersionORM, b: DocumentVersionORM) -> bool:
    fields = [name for name in VERSION_FIELDS if name != "created_at"] + ["comment", "metadata_snapshot"]
    return all(getattr(a, name) == getattr(b, name) for name in fields) and \
        a.created_at.replace(tzinfo=None) == b.created_at.replace(tzinfo=None)


def check(store: Any, incoming: list[Incoming], records: dict[str, dict[str, Any]]) -> tuple[list[Incoming], int, list[str]]:
    """Originals to write, the number already present, and problems.

    `records` is the business data as it will be after the import (entity key ->
    id -> record): every new original is proven against it.
    """
    existing = {row.id: row for row in _manifests(store)}
    commands = {(row.actor_id, row.idempotency_key): row.id for row in existing.values()}
    archived_documents = {row.document_id for row in existing.values()}
    problems: list[str] = []
    fresh: list[Incoming] = []
    skipped = 0
    seen: set[str] = set()
    for row, blocks in incoming:
        label = f"{SNAPSHOT_KEY} {row.id}"
        if row.id in seen:
            problems.append(f"{label}: kommt mehrfach vor")
            continue
        seen.add(row.id)
        if row.id in existing:
            if _same(existing[row.id], row) and b"".join(blocks) == b"".join(_blocks(store, row.id)):
                skipped += 1
            else:
                problems.append(f"{label}: weicht vom bereits archivierten Original ab")
            continue
        if row.document_id in archived_documents:
            problems.append(f"{label}: für das Dokument sind bereits andere Originale archiviert")
            continue
        owner = commands.setdefault((row.actor_id, row.idempotency_key), row.id)
        if owner != row.id:
            problems.append(f"{label}: Vorgangsreferenz ist bereits vergeben")
            continue
        problem = _prove(row, blocks, records)
        if problem:
            problems.append(f"{label}: {problem}")
            continue
        fresh.append((row, blocks))
    problems += _check_chains(fresh)
    return fresh, skipped, problems


def _prove(row: DocumentVersionORM, blocks: list[bytes], records: dict[str, dict[str, Any]]) -> str | None:
    content = b"".join(blocks)
    if (hashlib.sha256(content).hexdigest(), len(content)) != (row.sha256, row.size_bytes):
        return "Inhalt passt nicht zu Größe und Prüfsumme"
    try:
        snapshot = Document.model_validate(row.metadata_snapshot)
        validate_manifest_identity(row, snapshot.model_dump())
        validate_feature_snapshot(row, row.metadata_snapshot)
    except (ModelError, ManifestValidationError, ValueError, TypeError):
        return "Metadaten sind beschädigt"
    document = records.get("documents", {}).get(row.document_id)
    if document is None:
        return "das zugehörige Dokument fehlt"
    if document.file_url != snapshot.file_url:
        return "die Datei des Dokuments wurde geändert"
    contract = records.get("contracts", {}).get(document.contract_id) if document.contract_id else None
    unit = records.get("units", {}).get(document.unit_id) if document.unit_id else None
    property_id = document.property_id or (unit.property_id if unit else None) or (
        contract.property_id if contract else None)
    prop = records.get("properties", {}).get(property_id) if property_id else None
    if prop is None or (document.contract_id and contract is None):
        return "Objekt oder Vertrag des Dokuments fehlt"
    binding = {"portfolio_id": prop.portfolio_id, "property_id": prop.id,
               "unit_id": document.unit_id or (contract.unit_id if contract else None),
               "contract_id": document.contract_id, "tenant_id": contract.tenant_id if contract else None}
    if any(getattr(row, key) != value for key, value in binding.items()):
        return "die Zuordnung zu Objekt, Einheit oder Vertrag stimmt nicht"
    if (unit and unit.property_id != prop.id) or (contract and (
            contract.property_id != prop.id or (unit and contract.unit_id != unit.id))):
        return "Objekt, Einheit und Vertrag passen nicht zusammen"
    return None


def _check_chains(fresh: list[Incoming]) -> list[str]:
    by_document: dict[str, list[DocumentVersionORM]] = defaultdict(list)
    for row, _ in fresh:
        by_document[row.document_id].append(row)
    problems = []
    for document_id, rows in by_document.items():
        rows.sort(key=lambda row: row.number)
        previous = None
        for row in rows:
            expected = 1 if previous is None else previous.number + 1
            if row.number != expected or row.predecessor_id != (previous.id if previous else None) or (
                    previous is None and row.operation != "archive_original"):
                problems.append(f"{SNAPSHOT_KEY} {row.id}: Fassungsfolge des Dokuments {document_id} ist lückenhaft")
                break
            previous = row
    return problems


def _chunks(row: DocumentVersionORM, blocks: list[bytes]) -> list[DocumentVersionChunkORM]:
    return [DocumentVersionChunkORM(version_id=row.id, position=position, portfolio_id=row.portfolio_id, data=data)
            for position, data in enumerate(blocks)]


def write_sql(session: Any, fresh: list[Incoming]) -> None:
    """Insert within the caller's transaction (versions in chain order before their blocks)."""
    for row, blocks in sorted(fresh, key=lambda item: (item[0].document_id, item[0].number)):
        session.add(row)
        session.flush()
        session.add_all(_chunks(row, blocks))
        session.flush()


def write_memory(store: Any, fresh: list[Incoming]) -> None:
    archive = memory_archive(store)
    with archive.lock:
        for row, blocks in fresh:
            archive.versions[row.id] = row
            for chunk in _chunks(row, blocks):
                archive.chunks[(chunk.version_id, chunk.position)] = chunk
