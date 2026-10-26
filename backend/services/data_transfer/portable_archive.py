"""Versioned customer archive with explicit members, relationships and checksums.

No account, session, provider connection or personal employee setting is selected.
Opaque protected operating data remains the responsibility of full backup/restore.
"""
import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import unquote

from fastapi import HTTPException
from sqlalchemy import select

from ...db.data_transfer_models import ExternalReferenceORM, ImportBatchORM, ImportedEvidenceORM
from ...db.e_invoice_models import EInvoiceIntakeORM, EInvoiceValidationORM
from ...db.payment_security_models import (
    PaymentAuthorizationORM,
    PaymentRecipientORM,
    PaymentSecurityEventORM,
    PaymentTotpUseORM,
)
from .. import data_snapshot as snapshots
from .. import document_original_snapshot as originals
from ..file_storage import get_file_storage, validate_key
from ..integrations import connection_storage as db
from ..upload_policy import DOCUMENT_EXTENSIONS, content_matches, file_extension
from .common import digest, encoded
from .imports import _controls

FORMAT = "immomanager-customer-portability"
VERSION = 1
MAX_EXPANDED = 128 * 1024 * 1024
MAX_MEMBERS = 100_000
# Every column of these models is business evidence. In particular TOTP *uses*
# contain a counter and timestamp, never a secret, recovery code or OTP value.
EVIDENCE_MODELS = (EInvoiceIntakeORM, EInvoiceValidationORM, PaymentRecipientORM,
                   PaymentAuthorizationORM, PaymentSecurityEventORM, PaymentTotpUseORM, ExternalReferenceORM, ImportBatchORM)
ACTIVE_MODELS = (EInvoiceIntakeORM, EInvoiceValidationORM, PaymentRecipientORM)


def _rows(unit, model):
    if unit.db is not None:
        return list(unit.db.scalars(select(model).order_by(model.id)))
    return sorted(db.memory(unit, model).values(), key=lambda row: row.id)


def _scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _uploads(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _uploads(item)
    elif isinstance(value, list):
        for item in value:
            yield from _uploads(item)
    elif isinstance(value, str) and value.startswith("/uploads/"):
        yield unquote(value[len("/uploads/"):])


def _asset_key(key):
    validate_key(key)
    if key.startswith(("assistant/", "assistant-private/")) or file_extension(key) not in DOCUMENT_EXTENSIONS:
        raise ValueError("Nicht übertragbarer Dateipfad im Geschäftsdatenbestand.")
    return key


def external_links(snapshot):
    """Explicit links are metadata, not offline originals; never fetch them."""
    result = []
    for table, records in snapshot.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            for field in ("file_url", "photo_url", "image_url", "attachment_url"):
                value = record.get(field)
                if value and not value.startswith("/uploads/"):
                    result.append({"entity": table, "id": record.get("id"), "field": field, "url": value})
    return result


def build(unit):
    parts: dict[str, bytes] = {}
    size = 0
    def put(name, content):
        nonlocal size
        if name in parts:
            if parts[name] != content:
                raise ValueError("Widersprüchliche Exportdatei.")
            return name
        size += len(content)
        if size > MAX_EXPANDED or len(parts) >= MAX_MEMBERS:
            raise HTTPException(413, "Der Kundenexport überschreitet 128 MiB. Die vollständige Sicherung bleibt verfügbar.")
        parts[name] = content
        return name
    def blob(content):
        sha = hashlib.sha256(content).hexdigest()
        return {"blob": put("blobs/" + sha, content), "sha256": sha, "size_bytes": len(content)}

    backend = snapshots._backend(unit.store)
    snapshot = {"format": snapshots.SNAPSHOT_FORMAT, "format_version": snapshots.SNAPSHOT_FORMAT_VERSION}
    plan = [(spec, backend.records(spec)) for spec in snapshots.entity_specs()]
    for spec, rows in plan:
        snapshot[spec.key] = [row.model_dump(mode="json") for row in rows]
    archived, archived_keys = [], set()
    for manifest in originals.export(unit.store):
        content = b"".join(base64.b64decode(block, validate=True) for block in manifest.pop("blocks"))
        if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
            raise ValueError("Beschädigtes Dokumentoriginal im Quellbestand.")
        archived.append({**manifest, "source": blob(content)})
        archived_keys.update(_uploads(manifest.get("metadata_snapshot", {})))
    evidence = []
    for model in EVIDENCE_MODELS:
        for row in _rows(unit, model):
            payload = {column.name: blob(value) if isinstance(value := getattr(row, column.name), bytes) else _scalar(value)
                       for column in model.__table__.columns}
            evidence.append({"source_type": model.__tablename__, "record_id": row.id, "payload": payload, "sha256": digest(payload)})
    # Imported historical decisions remain historical on every later export.
    for row in _rows(unit, ImportedEvidenceORM):
        if digest(row.payload) != row.sha256:
            raise ValueError("Beschädigter historischer Übernahmenachweis.")
        evidence.append({"source_type": row.source_type, "record_id": row.record_id, "payload": row.payload, "sha256": row.sha256, "historical": True})
    assets = []
    storage = get_file_storage()
    for key in sorted(set(_uploads(snapshot)) - archived_keys):
        _asset_key(key)
        attachment = storage.get(key)
        if attachment is None:
            raise ValueError("Eine zugeordnete Quelldatei fehlt. Der Export wäre unvollständig.")
        assets.append({"storage_key": key, "source": blob(attachment)})
    schema = {spec.key: {"fields": list(spec.model.model_fields), "references": spec.references} for spec in snapshots.entity_specs()}
    put("business.json", encoded(snapshot))
    put("originals.json", encoded(archived))
    put("evidence.json", encoded(evidence))
    put("attachments.json", encoded(assets))
    put("schema.json", encoded(schema))
    put("README.md", ("# Kundenexport\n\nGeschäftsdaten: business.json; Beziehungen und Felder: schema.json.\n"
        "Originalversionen: originals.json; Anhänge: attachments.json; zusätzliche Fachnachweise: evidence.json.\n"
        "Binärdateien liegen unter blobs/ mit SHA-256 im Namen. manifest.json prüft jeden Bestandteil.\n"
        "Zugangskonten, Sitzungen, Schlüssel, Anbieterzugänge und private Mitarbeitereinstellungen sind ausgeschlossen.\n"
        "Diese Datei ist keine Betriebswiederherstellung. Beim Import bleiben alte Bankfreigaben historische Nachweise;\n"
        "jede Zahlung braucht eine neue Entscheidung. Noch nicht übernommene E-Rechnungen werden erneut lokal geprüft.\n"
        "Einladungen und Portalsitzungen werden nicht aktiviert. Das Vollbackup bewahrt zusätzlich Betriebsdaten.\n").encode())
    manifest = {"format": FORMAT, "version": VERSION, "created_at": db.now().isoformat(), "controls": _controls(plan),
        "originals": [{"id": row["id"], "sha256": row["sha256"]} for row in archived],
        "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)} for name, content in parts.items()},
        "external_links_without_original": external_links(snapshot),
        "excluded": ["internal_users", "sessions", "tokens", "keyrings", "provider_connections", "private_employee_settings", "active_payment_authorizations", "portal_sessions"]}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
        archive.writestr("manifest.json", encoded(manifest))
    content = output.getvalue()
    if len(content) > 64 * 1024 * 1024:
        raise HTTPException(413, "Das Exportpaket überschreitet die Grenze von 64 MiB je Übernahmedatei.")
    return content, manifest


def read(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_MEMBERS or sum(entry.file_size for entry in entries) > MAX_EXPANDED or len({entry.filename for entry in entries}) != len(entries):
                raise ValueError("Archiv zu groß oder doppelte Mitglieder.")
            for entry in entries:
                if entry.flag_bits & 1 or entry.is_dir() or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("Verschlüsselte oder unbekannte Archivbestandteile.")
                if entry.filename not in {"manifest.json", "business.json", "originals.json", "evidence.json", "attachments.json", "schema.json", "README.md"} and not re.fullmatch(r"blobs/[a-f0-9]{64}", entry.filename):
                    raise ValueError("Unerwarteter Archivpfad.")
            parts = {entry.filename: archive.read(entry) for entry in entries}
        manifest = json.loads(parts.pop("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION or set(manifest["files"]) != set(parts):
            raise ValueError("Unbekanntes oder unvollständiges Kundenexportformat.")
        for name, raw in parts.items():
            expected = manifest["files"][name]
            if expected != {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}:
                raise ValueError("Prüfsumme oder Größe eines Archivbestandteils stimmt nicht.")
        def extract(source):
            raw = parts[source["blob"]]
            if source != {"blob": "blobs/" + hashlib.sha256(raw).hexdigest(), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}:
                raise ValueError("Ungültige Binärreferenz.")
            return raw
        snapshot = json.loads(parts["business.json"])
        versions = json.loads(parts["originals.json"])
        snapshot[originals.SNAPSHOT_KEY] = [{**{key: value for key, value in row.items() if key != "source"},
            "blocks": [base64.b64encode(raw[index:index + originals.CHUNK_BYTES]).decode() for index in range(0, len(raw), originals.CHUNK_BYTES)]}
            for row in versions for raw in [extract(row["source"])]]
        evidence = json.loads(parts["evidence.json"])
        models = {model.__tablename__: model for model in EVIDENCE_MODELS}
        for record in evidence:
            if record["source_type"] not in models or digest(record["payload"]) != record["sha256"]:
                raise ValueError("Unbekannter oder beschädigter Fachnachweis.")
            model = models[record["source_type"]]
            if set(record["payload"]) != set(model.__table__.columns.keys()) or record["record_id"] != record["payload"]["id"]:
                raise ValueError("Fachnachweis passt nicht zu seinem Datensatzschema.")
        assets = json.loads(parts["attachments.json"])
        seen = set()
        wanted = set(_uploads(snapshot)) - set(key for row in versions for key in _uploads(row.get("metadata_snapshot", {})))
        for asset in assets:
            key = _asset_key(asset["storage_key"])
            raw = extract(asset["source"])
            if key in seen or key not in wanted or not content_matches(file_extension(key), raw):
                raise ValueError("Anhang ist doppelt, falsch zugeordnet oder besitzt einen falschen Dateityp.")
            seen.add(key)
        if seen != wanted:
            raise ValueError("Die Anlagenliste ist unvollständig.")
        encoded(snapshot)  # reject NaN/Infinity and excessive recursion
        return snapshot, evidence, [(asset["storage_key"], extract(asset["source"])) for asset in assets], extract, manifest
    except (KeyError, TypeError, ValueError, RecursionError, zipfile.BadZipFile, NotImplementedError, RuntimeError, UnicodeError) as error:
        raise ValueError("Kundenexport nicht sicher lesbar: " + str(error)[:250]) from None
