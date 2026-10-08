"""Checks of archived document originals that need no running application.

`validate_manifest_identity` is the one rule for a single manifest, used by live
reads and by the checks below. `verify_document_versions` proves a whole archive
in a database (a SQLite file before it is restored, or the live database): every
chain is complete and numbered, every manifest still matches its document and
contract, and every original's blocks add up to its size and checksum. Blocks
are bounded inside SQL before the driver reads them, so a damaged row cannot
make the check allocate arbitrary memory.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any, NoReturn

from pydantic import TypeAdapter
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from ..db.document_version_models import ARCHIVE_TABLES, CHUNK_BYTES

SHA256 = re.compile(r"[a-f0-9]{64}")
VERSION_FIELDS = ("id", "document_id", "portfolio_id", "property_id", "unit_id", "contract_id", "tenant_id",
                  "number", "predecessor_id", "restored_from_id", "operation", "sha256", "size_bytes",
                  "actor_id", "idempotency_key", "request_sha256", "filename", "media_type", "created_at")
_TIMESTAMP = TypeAdapter(datetime)


class ManifestValidationError(ValueError):
    """One manifest is inconsistent; callers choose the error they report."""


class ArchiveIntegrityError(ValueError):
    """The archive in a database is damaged, incomplete or wrongly assigned."""

    def __init__(self, message: str = (
            "Archivierte Originale sind beschädigt, unvollständig oder falsch zugeordnet. "
            "Die Daten wurden nicht übernommen.")):
        super().__init__(message)


def _value(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def validate_manifest_identity(row: Any, snapshot: Mapping) -> None:
    """A version's own fields agree, and its document snapshot names the same subject."""
    number, size, operation = _value(row, "number"), _value(row, "size_bytes"), _value(row, "operation")
    sha256 = _value(row, "sha256")
    invalid = (type(number) is not int or number < 1 or type(size) is not int or size < 0
               or not isinstance(sha256, str) or not SHA256.fullmatch(sha256))
    invalid = invalid or (number == 1 and (operation != "archive_original" or _value(row, "predecessor_id") is not None))
    invalid = invalid or (number != 1 and (operation not in {"upload", "restore"}
                                           or not isinstance(_value(row, "predecessor_id"), str)
                                           or not _value(row, "predecessor_id")))
    restored = _value(row, "restored_from_id")
    invalid = invalid or (operation == "restore" and (not isinstance(restored, str) or not restored))
    invalid = invalid or (operation != "restore" and restored is not None)
    invalid = invalid or (
        snapshot.get("id") != _value(row, "document_id") or snapshot.get("contract_id") != _value(row, "contract_id")
        or snapshot.get("property_id") is not None and snapshot.get("property_id") != _value(row, "property_id")
        or snapshot.get("unit_id") is not None and snapshot.get("unit_id") != _value(row, "unit_id"))
    if invalid:
        raise ManifestValidationError("Invalid immutable document manifest")


def validate_feature_snapshot(row: Any, snapshot: Mapping) -> None:
    """Checks of a feature that stores its proof in the manifest (Wohnungsgeberbestätigung, protocol)."""
    from .housing_confirmation_validation import validate_housing_confirmation_snapshot
    from .maintenance_protocol_validation import validate_maintenance_protocol_snapshot

    validate_housing_confirmation_snapshot(row, snapshot)
    validate_maintenance_protocol_snapshot(row, snapshot)


def _fail() -> NoReturn:
    raise ArchiveIntegrityError()


class _Database:
    """The same queries on a plain sqlite3 connection and on a SQLAlchemy connection."""

    def __init__(self, connection):
        self.connection = connection
        self.sqlite = isinstance(connection, sqlite3.Connection)
        self.dialect = "sqlite" if self.sqlite else connection.dialect.name

    def execute(self, statement: str, values: dict | None = None):
        if self.sqlite:
            return self.connection.execute(statement, values or {})
        return self.connection.execute(text(statement), values or {})

    def one(self, statement: str, values: dict | None = None):
        cursor = self.execute(statement, values)
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def tables(self) -> set[str]:
        if self.sqlite:
            return {row[0] for row in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return set(inspect(self.connection).get_table_names())

    def columns(self, table: str) -> set[str]:
        if self.sqlite:
            return {row[1] for row in self.execute(f'PRAGMA table_info("{table}")')}
        return {column["name"] for column in inspect(self.connection).get_columns(table)}

    def json_field(self, field: str) -> str:
        if self.dialect == "sqlite":
            return f"CASE WHEN json_valid(v.metadata_snapshot) THEN json_extract(v.metadata_snapshot, '$.{field}') END"
        return f"(v.metadata_snapshot::jsonb ->> '{field}')"


def _verified_chunks(db: _Database, row: dict) -> None:
    bounded = "length(data) BETWEEN 1 AND 65536"
    if db.dialect == "sqlite":
        bounded = "typeof(data) = 'blob' AND " + bounded
    cursor = db.execute(
        f"SELECT position, portfolio_id, CASE WHEN {bounded} THEN data ELSE NULL END "
        "FROM document_version_chunks WHERE version_id = :id ORDER BY position", {"id": row["id"]})
    checksum, size, expected = hashlib.sha256(), 0, 0
    try:
        while values := cursor.fetchone():
            position, portfolio_id, data = values
            if type(position) is not int or position != expected or portfolio_id != row["portfolio_id"]:
                _fail()
            if not isinstance(data, (bytes, bytearray, memoryview)):
                _fail()
            length = data.nbytes if isinstance(data, memoryview) else len(data)
            if not 0 < length <= CHUNK_BYTES:
                _fail()
            size += length
            if size > row["size_bytes"]:
                _fail()
            checksum.update(data)
            expected += 1
    finally:
        cursor.close()
    if (size, checksum.hexdigest()) != (row["size_bytes"], row["sha256"]):
        _fail()


def _verify(connection) -> int:
    db = _Database(connection)
    present = db.tables() & set(ARCHIVE_TABLES)
    if not present:
        return 0                 # a database from before the archive
    if present != set(ARCHIVE_TABLES):
        _fail()
    if not set(VERSION_FIELDS) | {"metadata_snapshot", "comment"} <= db.columns("document_versions"):
        _fail()
    if not {"version_id", "position", "portfolio_id", "data"} <= db.columns("document_version_chunks"):
        _fail()
    if db.one("SELECT 1 FROM document_version_chunks ch LEFT JOIN document_versions v ON v.id = ch.version_id "
              "WHERE v.id IS NULL LIMIT 1"):
        _fail()
    fields = ", ".join(
        "CASE WHEN typeof(v.created_at) = 'text' AND length(v.created_at) <= 64 THEN v.created_at END"
        if name == "created_at" and db.dialect == "sqlite" else f"v.{name}" for name in VERSION_FIELDS)
    snapshot_fields = ("id", "property_id", "unit_id", "contract_id", "file_url", "document_type")
    projections = ", ".join(db.json_field(name) for name in snapshot_fields)
    query = (f"SELECT {fields}, {projections}, d.id, d.file_url, d.property_id, d.unit_id, d.contract_id, "
             "p.portfolio_id, pf.id, u.property_id, c.property_id, c.unit_id, c.tenant_id, t.id, du.property_id "
             "FROM document_versions v LEFT JOIN documents d ON d.id = v.document_id "
             "LEFT JOIN properties p ON p.id = v.property_id LEFT JOIN portfolios pf ON pf.id = v.portfolio_id "
             "LEFT JOIN units u ON u.id = v.unit_id LEFT JOIN contracts c ON c.id = v.contract_id "
             "LEFT JOIN tenants t ON t.id = v.tenant_id LEFT JOIN units du ON du.id = d.unit_id "
             "ORDER BY v.document_id, v.number")
    rows = db.execute(query).fetchall()
    previous: dict | None = None
    commands: set[tuple[str, str]] = set()
    for values in rows:
        row = dict(zip(VERSION_FIELDS, values[:len(VERSION_FIELDS)]))
        snapshot = dict(zip(snapshot_fields, values[len(VERSION_FIELDS):len(VERSION_FIELDS) + len(snapshot_fields)]))
        (document_id, document_url, document_property, document_unit, document_contract, property_portfolio,
         portfolio_id, unit_property, contract_property, contract_unit, contract_tenant, tenant_id,
         document_unit_property) = values[-13:]
        if row["created_at"] is None:
            _fail()
        _TIMESTAMP.validate_python(row["created_at"])
        if any(not isinstance(row[name], str) or not row[name]
               for name in ("id", "document_id", "actor_id", "idempotency_key", "filename", "media_type")):
            _fail()
        if not isinstance(row["request_sha256"], str) or not SHA256.fullmatch(row["request_sha256"]):
            _fail()
        command = (row["actor_id"], row["idempotency_key"])
        if command in commands:
            _fail()
        commands.add(command)
        try:
            validate_manifest_identity(row, snapshot)
        except ManifestValidationError:
            _fail()
        if (not document_id or not isinstance(document_url, str) or not document_url.strip()
                or property_portfolio != row["portfolio_id"] or not portfolio_id
                or row["unit_id"] is not None and unit_property != row["property_id"]
                or row["contract_id"] is not None and (contract_property != row["property_id"]
                                                       or contract_unit != row["unit_id"]
                                                       or contract_tenant != row["tenant_id"])
                or row["tenant_id"] is not None and tenant_id != row["tenant_id"]
                or row["contract_id"] is None and row["tenant_id"] is not None
                or document_contract != row["contract_id"]
                or (document_property or document_unit_property or contract_property) != row["property_id"]
                or (document_unit or contract_unit) != row["unit_id"]
                or snapshot["file_url"] != document_url):
            _fail()
        if previous is None or previous["document_id"] != row["document_id"]:
            if row["number"] != 1 or row["operation"] != "archive_original":
                _fail()
        elif row["number"] != previous["number"] + 1 or row["predecessor_id"] != previous["id"]:
            _fail()
        if row["operation"] == "restore":
            source = db.one("SELECT document_id, number, sha256, size_bytes FROM document_versions WHERE id = :id",
                            {"id": row["restored_from_id"]})
            if source is None or tuple(source) != (row["document_id"], source[1], row["sha256"], row["size_bytes"]) \
                    or type(source[1]) is not int or not source[1] < row["number"]:
                _fail()
        if snapshot["document_type"] is not None:
            raw = db.one("SELECT metadata_snapshot FROM document_versions WHERE id = :id", {"id": row["id"]})
            full = raw[0] if raw else None
            if isinstance(full, str):
                try:
                    full = json.loads(full)
                except (json.JSONDecodeError, UnicodeError):
                    _fail()
            if not isinstance(full, Mapping):
                _fail()
            try:
                validate_feature_snapshot(row, full)
            except ValueError:
                _fail()
        _verified_chunks(db, row)
        previous = row
    return len(rows)


def verify_document_versions(connection) -> int:
    """Prove the archive in `connection` (sqlite3 or SQLAlchemy); return the number of versions."""
    try:
        return _verify(connection)
    except ArchiveIntegrityError:
        raise
    except (sqlite3.Error, SQLAlchemyError, TypeError, ValueError, UnicodeError):
        _fail()
