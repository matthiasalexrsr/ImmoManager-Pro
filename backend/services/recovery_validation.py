"""Validate secret-dependent fields and local document paths in recovery images."""

import base64
import hashlib
import json
import sqlite3
import stat
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlsplit

from cryptography.fernet import Fernet, InvalidToken

from .recovery_archive import RecoveryError


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _tables(db):
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        columns = {item[1] for item in db.execute("PRAGMA table_xinfo(" + _quote(name) + ")")}
        yield name, columns


def verify_iban_key(database: Path, secret: str, *, deadline: float | None = None):
    key = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"immomanager-iban-encryption-salt", 100_000)
    cipher = Fernet(base64.urlsafe_b64encode(key[:32]))
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        _deadline(db, deadline)
        for table, columns in _tables(db):
            for column in sorted(columns & {"iban"}):
                for (value,) in db.execute("SELECT " + _quote(column) + " FROM " + _quote(table)):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise RecoveryError("Schlüsselprüfung hat das Zeitlimit überschritten.")
                    if isinstance(value, str) and value.startswith("enc:"):
                        try:
                            cipher.decrypt(value[4:].encode())
                        except (InvalidToken, ValueError) as exc:
                            raise RecoveryError("Das Runtime-Geheimnis kann vorhandene IBAN-Daten nicht entschluesseln.") from exc


_REFERENCE_COLUMNS = {"file_url", "receipt_url", "file_path", "document_url", "document_path", "receipt_path", "storage_key", "ocr_url", "photo_url"}
_REFERENCE_LIST_COLUMNS = {"photos"}


@dataclass(frozen=True)
class FileReferenceReport:
    local_references: int
    local_files: frozenset[str]
    external_reference_count: int


def _deadline(db, deadline):
    """The caller supplies an absolute monotonic deadline, never a new budget."""
    if deadline is not None:
        if time.monotonic() >= deadline:
            raise RecoveryError("Zeitlimit der Dateiverweispruefung ueberschritten.")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)


def _key(value: str) -> str:
    value = value.replace("\\", "/")
    parts = value.split("/")
    if (not value or value.startswith("/") or PureWindowsPath(value).drive
            or any(part in {"", ".", ".."} for part in parts)
            or any(char in value for char in ':<>"|?*')
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise RecoveryError("Ungueltiger lokaler Upload-Dateiverweis.")
    return "/".join(parts)


def _reference(value: str, old_root: str):
    """Return (relative key, absolute-path flag); explicit remote URLs stay remote."""
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {"http", "https", "s3"}:
        if not parsed.netloc:
            raise RecoveryError("Ungueltiger externer Dateiverweis.")
        return None, False
    normalized = value.replace("\\", "/")
    if normalized.startswith(("/uploads/", "uploads/")):
        return _key(unquote(urlsplit(normalized).path.split("uploads/", 1)[1], errors="strict")), False
    if normalized.startswith("/api/"):
        if not parsed.path.endswith("/files/download"):
            raise RecoveryError("Nicht unterstuetzter lokaler API-Dateiverweis.")
        query = parse_qs(parsed.query, keep_blank_values=True, errors="strict")
        if len(query.get("key", [])) != 1:
            raise RecoveryError("Der lokale Download-Verweis enthaelt keinen eindeutigen Dateischluessel.")
        return _key(query["key"][0]), False
    if parsed.scheme.lower() == "file":
        value = unquote(parsed.path, errors="strict")
        if parsed.netloc and parsed.netloc != "localhost":
            value = "//" + parsed.netloc + value
        elif value.startswith("/") and PureWindowsPath(value[1:]).drive:
            value = value[1:]
    elif parsed.scheme and not PureWindowsPath(value).drive:
        raise RecoveryError("Nicht unterstuetzter Dateiverweis.")
    windows = bool(PureWindowsPath(value).drive)
    path = PureWindowsPath(value) if windows else PurePosixPath(value)
    root = PureWindowsPath(old_root) if windows else PurePosixPath(old_root)
    if not path.is_absolute():
        if windows:
            raise RecoveryError("Ungueltiger relativer Windows-Dateiverweis.")
        return _key(value), False
    try:
        suffix = path.relative_to(root)
    except ValueError as exc:
        raise RecoveryError("Ein lokaler Dateiverweis liegt ausserhalb des gesicherten Upload-Baums.") from exc
    return _key(suffix.as_posix()), True


def _local_suffix(value: str, old_root: str):
    key, _ = _reference(value, old_root)
    return PurePosixPath(key).parts if key is not None else None


def _catalog(expected_upload_files):
    if expected_upload_files is None:
        return None
    catalog = {}
    for value in expected_upload_files:
        if not isinstance(value, str):
            raise RecoveryError("Ungueltige Liste gesicherter Upload-Dateien.")
        key = _key(value)
        if key.casefold() in catalog:
            raise RecoveryError("Gesicherte Upload-Dateinamen kollidieren.")
        catalog[key.casefold()] = key
    return catalog


def _covered_key(key, old_root, catalog):
    if catalog is not None:
        known = catalog.get(key.casefold())
        windows = bool(PureWindowsPath(old_root).drive)
        if known is None or (not windows and known != key):
            raise RecoveryError("Referenzierte Upload-Datei fehlt im gesicherten Baum: " + key)
        return known
    root = Path(old_root)
    candidate = root
    try:
        for part in (None, *PurePosixPath(key).parts):
            if part is not None:
                candidate /= part
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RecoveryError("Ein referenzierter Upload verwendet einen Symlink oder Reparsepunkt.")
        resolved = candidate.resolve(strict=True)
        if not stat.S_ISREG(info.st_mode) or not resolved.is_relative_to(root.resolve()):
            raise RecoveryError("Referenzierter Upload ist keine Datei im gesicherten Baum.")
    except OSError as exc:
        raise RecoveryError("Referenzierte Upload-Datei fehlt oder ist unlesbar: " + key) from exc
    return key


def _scan(db, old_root, destination, catalog):
    root = PureWindowsPath(old_root) if PureWindowsPath(old_root).drive else PurePosixPath(old_root)
    if not root.is_absolute():
        raise RecoveryError("Der gesicherte Upload-Wurzelpfad muss absolut sein.")
    updates, files = {}, set()
    local_count = external_count = 0
    for table, columns in _tables(db):
        for column in sorted(columns & (_REFERENCE_COLUMNS | _REFERENCE_LIST_COLUMNS)):
            for (value,) in db.execute("SELECT " + _quote(column) + " FROM " + _quote(table)):
                if value is None or value == "":
                    continue
                if not isinstance(value, str):
                    raise RecoveryError("Nichttextueller Dateiverweis in der Sicherung.")
                references = json.loads(value) if column in _REFERENCE_LIST_COLUMNS else [value]
                if not isinstance(references, list) or any(not isinstance(item, str) or not item.strip() for item in references):
                    raise RecoveryError("Ungueltige Liste von Foto-Dateiverweisen in der Sicherung.")
                rebased_references = []
                for reference in references:
                    key, absolute = _reference(reference, old_root)
                    rebased = reference
                    if key is None:
                        external_count += 1
                    else:
                        covered = _covered_key(key, old_root, catalog)
                        files.add(covered)
                        local_count += 1
                        if destination is not None:
                            rebased = str(destination.joinpath(*PurePosixPath(covered).parts)) if absolute else reference
                            if covered != key and not absolute:
                                # Correct Windows case aliases for a portable restored tree.
                                rebased = "/uploads/" + covered
                    rebased_references.append(rebased)
                if rebased_references != references:
                    updates[table, column, value] = json.dumps(rebased_references, ensure_ascii=False) if column in _REFERENCE_LIST_COLUMNS else rebased_references[0]
    return updates, FileReferenceReport(local_count, frozenset(files), external_count)


def _schema(db):
    return tuple(db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"))


def _rows_fingerprint(db, updates):
    """Stream full rows, applying only the exact approved cell replacements."""
    result = {}
    modulus = 1 << 256
    for table, _ in _tables(db):
        columns = [item[1] for item in db.execute("PRAGMA table_xinfo(" + _quote(table) + ")")]
        total, xor, count = 0, 0, 0
        for row in db.execute("SELECT " + ", ".join(map(_quote, columns)) + " FROM " + _quote(table)):
            digest = hashlib.sha256()
            for column, value in zip(columns, row):
                if isinstance(value, str):
                    value = updates.get((table, column, value), value)
                if value is None:
                    kind, data = b"n", b""
                elif isinstance(value, bytes):
                    kind, data = b"b", value
                elif isinstance(value, str):
                    kind, data = b"s", value.encode("utf-8")
                elif isinstance(value, int):
                    kind, data = b"i", str(value).encode("ascii")
                else:
                    kind, data = b"f", value.hex().encode("ascii")
                digest.update(kind + len(data).to_bytes(8, "big") + data)
            number = int.from_bytes(digest.digest(), "big")
            total = (total + number) % modulus
            xor ^= number
            count += 1
        result[table] = count, total, xor
    return result


def validate_file_references(database: Path, old_root: str, *, expected_upload_files: set[str] | None = None, deadline: float | None = None) -> FileReferenceReport:
    """Read-only coverage proof. Expected keys are relative to the upload root."""
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            _deadline(db, deadline)
            db.execute("BEGIN")
            return _scan(db, old_root, None, _catalog(expected_upload_files))[1]
    except (sqlite3.Error, UnicodeError, ValueError) as exc:
        if isinstance(exc, RecoveryError):
            raise
        raise RecoveryError("Dateiverweise der Sicherung konnten nicht vollstaendig geprueft werden.") from exc


def rebase_file_references(database: Path, old_root: str, destination: Path | None = None, *, expected_upload_files: set[str] | None = None, deadline: float | None = None):
    """Validate coverage; mutate only a caller-owned staged copy during restore.

    Staging callers must pass the manifest's relative upload file set because the
    destination has not been published yet. Ordinary triggers are suspended and
    restored within one transaction; every row and schema entry is checked before
    committing so foreign-key cascades cannot silently change other business data.
    """
    if destination is None:
        validate_file_references(database, old_root, expected_upload_files=expected_upload_files, deadline=deadline)
        return 0
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA foreign_keys=ON")
            _deadline(db, deadline)
            db.execute("BEGIN IMMEDIATE")
            try:
                updates, _ = _scan(db, old_root, destination, _catalog(expected_upload_files))
                if not updates:
                    db.rollback()
                    return 0
                schema, expected_rows = _schema(db), _rows_fingerprint(db, updates)
                triggers = list(db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid"))
                for name, sql in triggers:
                    if not sql:
                        raise RecoveryError("Ein SQLite-Trigger kann nicht unveraendert erhalten werden.")
                    db.execute("DROP TRIGGER " + _quote(name))
                changed = 0
                for (table, column, old), new in updates.items():
                    table_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
                    if table_sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
                        raise RecoveryError("Dateiverweise virtueller Tabellen koennen nicht sicher umgeschrieben werden.")
                    cursor = db.execute("UPDATE " + _quote(table) + " SET " + _quote(column) + "=? WHERE " + _quote(column) + "=? COLLATE BINARY", (new, old))
                    changed += cursor.rowcount
                for _, sql in triggers:
                    db.execute(sql)
                if _schema(db) != schema or _rows_fingerprint(db, {}) != expected_rows:
                    raise RecoveryError("Die Pfadumschreibung hat nicht genehmigte Geschaeftsdaten oder das Schema veraendert.")
                if db.execute("PRAGMA quick_check").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise RecoveryError("Datenintegritaet nach Pfadumschreibung ist verletzt.")
                db.commit()
                return changed
            except Exception:
                db.rollback()
                raise
    except (sqlite3.Error, UnicodeError, ValueError) as exc:
        if isinstance(exc, RecoveryError):
            raise
        raise RecoveryError("Dateiverweise der Staging-Datenbank konnten nicht sicher umgeschrieben werden.") from exc
