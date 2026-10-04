"""Read-only offline proof of every archived document and its subject chain.

No application store, principal, metadata registration or session mutation is
needed. Native SQLite and an offline SQLAlchemy Connection share the validator.
Original blocks are bounded inside SQL before the driver materializes bytes.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from pydantic import TypeAdapter
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ..models import Document
from .recovery_archive import RecoveryError

TABLES = frozenset({"document_versions", "document_version_chunks"})
CHUNK_BYTES = 65536
VERSION_FIELDS = ("id", "document_id", "portfolio_id", "property_id", "unit_id", "contract_id", "tenant_id",
                  "number", "predecessor_id", "restored_from_id", "operation", "sha256", "size_bytes",
                  "actor_id", "idempotency_key", "request_sha256", "filename", "media_type", "created_at")
_TIMESTAMP = TypeAdapter(datetime)


class ManifestValidationError(ValueError):
    """Pure manifest failure; callers choose their HTTP/offline error boundary."""


def validate_manifest_identity(row, snapshot: Mapping) -> None:
    """One identity/manifest policy for live reads and offline SQL projections."""
    def value(name):
        return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)
    number, size, operation = value("number"), value("size_bytes"), value("operation")
    invalid = (type(number) is not int or number < 1 or type(size) is not int or size < 0
               or not isinstance(value("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", value("sha256")))
    invalid = invalid or (number == 1 and (operation != "archive_original" or value("predecessor_id") is not None))
    invalid = invalid or (number != 1 and (operation not in {"upload", "restore"}
        or not isinstance(value("predecessor_id"), str) or not value("predecessor_id")))
    restored = value("restored_from_id")
    invalid = invalid or (operation == "restore" and (not isinstance(restored, str) or not restored))
    invalid = invalid or (operation != "restore" and restored is not None)
    invalid = invalid or (snapshot.get("id") != value("document_id") or snapshot.get("contract_id") != value("contract_id")
        or snapshot.get("property_id") is not None and snapshot.get("property_id") != value("property_id")
        or snapshot.get("unit_id") is not None and snapshot.get("unit_id") != value("unit_id"))
    if invalid:
        raise ManifestValidationError("Invalid immutable document manifest")


def validate_table_pair(tables: set[str]) -> bool:
    present = tables & TABLES
    if present and present != TABLES:
        raise RecoveryError("Dokumentversionsschema ist unvollständig. Unveränderte vollständige Sicherung verwenden.")
    return bool(present)


def _remaining(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise RecoveryError("Zeitlimit der Dokumentversionsprüfung überschritten. Wiederherstellung nicht freigegeben.")


class _Database:
    def __init__(self, connection):
        self.connection = connection
        self.sqlite = isinstance(connection, sqlite3.Connection)
        self.dialect = "sqlite" if self.sqlite else connection.dialect.name

    def execute(self, statement, values=None, *, stream=False):
        if self.sqlite:
            return self.connection.execute(statement, values or {})
        previous = self.connection.get_execution_options().get("stream_results", False)
        try:
            return self.connection.execution_options(stream_results=stream, max_row_buffer=1).execute(text(statement), values or {})
        finally:
            self.connection.execution_options(stream_results=previous)

    def one(self, statement, values=None):
        cursor = self.execute(statement, values)
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def tables(self):
        if self.sqlite:
            return {row[0] for row in self.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table' AND name IN (:versions, :chunks)",
                {"versions": "document_versions", "chunks": "document_version_chunks"},
            )}
        return set(inspect(self.connection).get_table_names())

    def columns(self, table):
        if self.sqlite:
            return {row[1] for row in self.execute('PRAGMA table_info("' + table + '")')}
        return {column["name"] for column in inspect(self.connection).get_columns(table)}

    def snapshot(self, field):
        # Select only identity/source fields, never the entire OCR/description
        # snapshot. CASE avoids JSON extraction on malformed SQLite text.
        if self.dialect == "sqlite":
            return "CASE WHEN json_valid(v.metadata_snapshot) THEN json_extract(v.metadata_snapshot,'$." + field + "') END"
        return "v.metadata_snapshot::jsonb ->> '" + field + "'"

    def snapshot_shape(self):
        # Validate all Document field types in SQL without transferring huge
        # description/OCR text. PostgreSQL ->> alone would coerce JSON numbers
        # and booleans into apparently valid strings.
        def kind(field=None):
            if self.dialect == "sqlite":
                return "json_type(v.metadata_snapshot,'$" + ("." + field if field else "") + "')"
            value = "v.metadata_snapshot::jsonb" + (" -> '" + field + "'" if field else "")
            return "jsonb_typeof(" + value + ")"
        string = "text" if self.dialect == "sqlite" else "string"
        conditions = [kind() + "='object'"]
        for field in ("id", "title", "file_url"):
            conditions.append(kind(field) + "='" + string + "'")
        for field in ("property_id", "unit_id", "contract_id", "document_type", "tags", "description",
                      "ai_document_type", "ai_summary", "ai_entities_json", "ai_model"):
            conditions.append("(" + kind(field) + " IS NULL OR " + kind(field) + " IN ('null','" + string + "'))")
        for field in ("document_date", "ai_analyzed_at", "created_at", "updated_at"):
            nullable = "'null'," if field in {"document_date", "ai_analyzed_at"} else ""
            # Native Python/Pydantic canonical ISO dates fit well inside this
            # scalar projection. Reject invalid long date strings inside SQL,
            # rather than allocating arbitrary metadata in the driver.
            conditions.append("(" + kind(field) + " IS NULL OR " + kind(field) + " IN (" + nullable + "'" + string + "')"
                              " AND (" + self.snapshot(field) + " IS NULL OR length(" + self.snapshot(field) + ")<=128))")
        numeric = "'integer','real'" if self.dialect == "sqlite" else "'number'"
        conditions.append("(" + kind("ai_confidence") + " IS NULL OR " + kind("ai_confidence") + " IN ('null'," + numeric + "))")
        result = "CASE WHEN " + " AND ".join(conditions) + " THEN 1 ELSE 0 END"
        return "CASE WHEN json_valid(v.metadata_snapshot) THEN " + result + " ELSE 0 END" if self.dialect == "sqlite" else result

    def temporal_snapshot(self, field):
        expression = self.snapshot(field)
        return "CASE WHEN length(" + expression + ")<=128 THEN " + expression + " ELSE NULL END"


def _fail() -> NoReturn:
    raise RecoveryError("Dokumentversionen sind beschädigt, unvollständig oder falsch zugeordnet. Unveränderte vollständige Sicherung verwenden; das Ziel wurde nicht freigegeben.")


def _schema(db):
    if not validate_table_pair(db.tables()):
        return False
    if not set(VERSION_FIELDS) | {"metadata_snapshot", "comment", "created_at"} <= db.columns("document_versions"):
        _fail()
    if not {"version_id", "position", "portfolio_id", "data"} <= db.columns("document_version_chunks"):
        _fail()
    for table, fields in {
        "documents": {"id", "property_id", "unit_id", "contract_id", "file_url"},
        "portfolios": {"id"}, "properties": {"id", "portfolio_id"},
        "units": {"id", "property_id"}, "contracts": {"id", "property_id", "unit_id", "tenant_id"},
        "tenants": {"id"},
    }.items():
        if not fields <= db.columns(table):
            _fail()
    return True


def _verified_chunks(db, row, deadline):
    expression = "length(data) BETWEEN 1 AND 65536"
    if db.dialect == "sqlite":
        expression = "typeof(data)='blob' AND " + expression
    statement = ("SELECT position, portfolio_id, CASE WHEN " + expression +
                 " THEN data ELSE NULL END FROM document_version_chunks WHERE version_id=:id ORDER BY position")
    cursor = db.execute(statement, {"id": row["id"]}, stream=True)
    digest, size, expected = hashlib.sha256(), 0, 0
    try:
        while value := cursor.fetchone():
            _remaining(deadline)
            position, portfolio, data = value
            if type(position) is not int or position != expected or portfolio != row["portfolio_id"]:
                _fail()
            if not isinstance(data, (bytes, bytearray, memoryview)):
                _fail()
            length = data.nbytes if isinstance(data, memoryview) else len(data)
            if not 0 < length <= CHUNK_BYTES:
                _fail()
            size += length
            if size > row["size_bytes"]:
                _fail()
            digest.update(data)
            expected += 1
    finally:
        cursor.close()
    if (size, digest.hexdigest()) != (row["size_bytes"], row["sha256"]):
        _fail()


def _verify_document_versions(connection, *, deadline=None) -> int:
    """Verify a coherent caller-owned offline snapshot; return version count.

    Pre-y1 images with neither table are compatible. A partial journal never is.
    Working memory is one manifest and one SQL-bounded original block at a time.
    """
    db = _Database(connection)
    _remaining(deadline)
    if not _schema(db):
        return 0
    orphan = db.one("SELECT 1 FROM document_version_chunks ch LEFT JOIN document_versions v ON v.id=ch.version_id WHERE v.id IS NULL LIMIT 1")
    duplicate = db.one("SELECT 1 FROM document_versions GROUP BY actor_id,idempotency_key HAVING COUNT(*)<>1 LIMIT 1")
    if orphan or duplicate:
        _fail()
    fields = ",".join("CASE WHEN typeof(v.created_at)='text' AND length(v.created_at)<=128 THEN v.created_at ELSE NULL END"
                      if name == "created_at" and db.dialect == "sqlite" else "v." + name for name in VERSION_FIELDS)
    identity_fields = ("id", "property_id", "unit_id", "contract_id", "file_url", "document_type")
    date_fields = ("document_date", "ai_analyzed_at", "created_at", "updated_at")
    snapshot_fields = identity_fields + date_fields
    projections = ",".join([*(db.snapshot(name) for name in identity_fields),
                            *(db.temporal_snapshot(name) for name in date_fields)])
    query = ("SELECT " + fields + "," + projections + "," + db.snapshot_shape() + ",d.id,d.file_url,d.property_id,d.unit_id,d.contract_id,"
             "p.portfolio_id,pf.id,u.property_id,c.property_id,c.unit_id,c.tenant_id,t.id,du.property_id "
             "FROM document_versions v LEFT JOIN documents d ON d.id=v.document_id "
             "LEFT JOIN properties p ON p.id=v.property_id LEFT JOIN portfolios pf ON pf.id=v.portfolio_id "
             "LEFT JOIN units u ON u.id=v.unit_id LEFT JOIN contracts c ON c.id=v.contract_id "
             "LEFT JOIN tenants t ON t.id=v.tenant_id LEFT JOIN units du ON du.id=d.unit_id "
             "ORDER BY v.document_id,v.number")
    cursor = db.execute(query, stream=True)
    previous = None
    count = 0
    try:
        while values := cursor.fetchone():
            _remaining(deadline)
            row = dict(zip(VERSION_FIELDS, values[:len(VERSION_FIELDS)]))
            _TIMESTAMP.validate_python(row["created_at"])
            snapshot = dict(zip(snapshot_fields, values[len(VERSION_FIELDS):len(VERSION_FIELDS)+len(snapshot_fields)]))
            if values[len(VERSION_FIELDS)+len(snapshot_fields)] != 1:
                _fail()
            # Strings were type-checked without reading their full contents.
            # Datetimes need actual scalar validation so live reads/downloads
            # will accept this restored snapshot, rather than fail later.
            Document.model_validate({"title": "", **{key: value for key, value in snapshot.items()
                if value is not None or key not in {"created_at", "updated_at"}}})
            validate_manifest_identity(row, snapshot)
            if snapshot.get("document_type") == "housing_confirmation":
                raw = db.one(
                    "SELECT metadata_snapshot FROM document_versions WHERE id=:id",
                    {"id": row["id"]},
                )
                if raw is None:
                    _fail()
                full_snapshot = raw[0]
                if isinstance(full_snapshot, str):
                    try:
                        full_snapshot = json.loads(full_snapshot)
                    except (json.JSONDecodeError, UnicodeError):
                        _fail()
                if not isinstance(full_snapshot, Mapping):
                    _fail()
                from .housing_confirmation_validation import (
                    HousingConfirmationValidationError,
                    validate_housing_confirmation_snapshot,
                )
                try:
                    validate_housing_confirmation_snapshot(row, full_snapshot)
                except HousingConfirmationValidationError:
                    _fail()
            (document_id, document_source, document_property, document_unit, document_contract, property_portfolio, portfolio_id,
             unit_property, contract_property, contract_unit, contract_tenant, tenant_id, document_unit_property) = values[-13:]
            if (type(row["number"]) is not int or row["number"] < 1 or type(row["size_bytes"]) is not int or row["size_bytes"] < 0
                    or any(not isinstance(row[name], str) or not row[name] for name in ("id", "document_id", "actor_id", "idempotency_key", "filename", "media_type"))
                    or any(not isinstance(row[name], str) or not re.fullmatch(r"[a-f0-9]{64}", row[name]) for name in ("sha256", "request_sha256"))):
                _fail()
            if (not document_id or not isinstance(document_source, str) or not document_source.strip()
                    or property_portfolio != row["portfolio_id"] or not portfolio_id
                    or row["unit_id"] is not None and unit_property != row["property_id"]
                    or row["contract_id"] is not None and (contract_property != row["property_id"] or contract_unit != row["unit_id"] or contract_tenant != row["tenant_id"])
                    or row["tenant_id"] is not None and tenant_id != row["tenant_id"]
                    or row["contract_id"] is None and row["tenant_id"] is not None
                    or document_contract != row["contract_id"]
                    or (document_property or document_unit_property or contract_property) != row["property_id"]
                    or (document_unit or contract_unit) != row["unit_id"]):
                _fail()
            if (snapshot["id"] != row["document_id"] or snapshot["contract_id"] != row["contract_id"]
                    or snapshot["property_id"] is not None and snapshot["property_id"] != row["property_id"]
                    or snapshot["unit_id"] is not None and snapshot["unit_id"] != row["unit_id"]
                    or not isinstance(snapshot["file_url"], str) or not snapshot["file_url"]):
                _fail()
            first = previous is None or previous["document_id"] != row["document_id"]
            if first:
                if row["number"] != 1 or row["operation"] != "archive_original" or row["predecessor_id"] is not None or row["restored_from_id"] is not None:
                    _fail()
            else:
                assert previous is not None
                if (row["number"] != previous["number"] + 1 or row["predecessor_id"] != previous["id"]
                        or row["operation"] not in {"upload", "restore"}):
                    _fail()
            if row["operation"] == "restore":
                source = db.one("SELECT document_id,number,sha256,size_bytes,filename,media_type FROM document_versions WHERE id=:id", {"id": row["restored_from_id"]})
                if source is None or tuple(source) != (row["document_id"], source[1], row["sha256"], row["size_bytes"], row["filename"], row["media_type"]) or type(source[1]) is not int or not source[1] < row["number"]:
                    _fail()
            elif row["restored_from_id"] is not None:
                _fail()
            _verified_chunks(db, row, deadline)
            previous = row
            count += 1
    finally:
        cursor.close()
    return count


def verify_document_versions(connection, *, deadline=None) -> int:
    try:
        return _verify_document_versions(connection, deadline=deadline)
    except RecoveryError:
        raise
    except (sqlite3.Error, SQLAlchemyError, TypeError, ValueError, UnicodeError):
        _fail()


@dataclass(frozen=True)
class OriginalProof:
    document_id: str
    historical_uri: str
    sha256: str
    size_bytes: int


def archived_original(connection, document_id: str, *, verified_schema: bool = False) -> OriginalProof | None:
    """Only call after full validation in the same snapshot; exact ID boundary."""
    db = _Database(connection)
    if not verified_schema and not validate_table_pair(db.tables()):
        return None
    row = db.one("SELECT v.document_id," + db.snapshot("file_url") + ",v.sha256,v.size_bytes FROM document_versions v WHERE v.document_id=:id AND v.number=1 AND v.operation='archive_original'",
                 {"id": document_id})
    return OriginalProof(*row) if row else None
