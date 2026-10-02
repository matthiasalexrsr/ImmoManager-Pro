"""Offline SQLite + uploads + configuration recovery into a new directory.

Callers must stop application/background writers. Filesystem changes are checked;
this is not a transactional hot backup of a concurrently modified filesystem.
"""

import hashlib
import json
import math
import os
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from zipfile import ZipFile

from .recovery_archive import CHUNK, RecoveryError, check_zip_budget, decrypt_zip, encrypted_zip
from .recovery_validation import (
    rebase_file_references,
    validate_file_references,
    verify_iban_key,
    verify_private_drafts,
)


@dataclass(frozen=True)
class RecoveryPlan:
    database: Path
    uploads: Path
    configuration: dict[str, str]
    runtime_env: Path | None = None
    integration_state: Path | None = None


@dataclass(frozen=True)
class RecoveryLimits:
    total_bytes: int = 8 * 1024**3
    file_bytes: int = 4 * 1024**3
    files: int = 100_000
    compression_ratio: int = 1000
    timeout_seconds: float = 300
    metadata_bytes: int = 16 * 1024**2
    manifest_bytes: int = 64 * 1024**2
    central_directory_bytes: int = 32 * 1024**2

    def __post_init__(self):
        for name in ("total_bytes", "file_bytes", "files", "compression_ratio", "metadata_bytes",
                     "manifest_bytes", "central_directory_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise RecoveryError("Sicherungsgrenzen müssen positive ganze Zahlen sein.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise RecoveryError("Das Zeitlimit muss positiv und endlich sein.")


def _safe_stat(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RecoveryError("Symlinks und Windows-Reparsepunkte werden nicht gesichert.")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise RecoveryError("Nicht unterstuetzter Dateityp in der Sicherung.")
    return info


def _fingerprint(path: Path):
    info = _safe_stat(path)
    return info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RecoveryError("Die Sicherung/Wiederherstellung hat das Zeitlimit überschritten.")
    return remaining


def _tree(root: Path, limits: RecoveryLimits = RecoveryLimits(), *, deadline: float | None = None):
    if not stat.S_ISDIR(_safe_stat(root).st_mode):
        raise RecoveryError("Upload-Verzeichnis fehlt.")
    files: dict[str, tuple[int, int, int, int]] = {}
    directories: list[str] = []
    deadline, total = deadline or time.monotonic() + limits.timeout_seconds, 0
    def unreadable(_error):
        raise RecoveryError("Upload-Verzeichnis konnte nicht vollständig gelesen werden.")
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        if time.monotonic() > deadline:
            raise RecoveryError("Upload-Prüfung hat das Zeitlimit überschritten.")
        if len(files) + len(directories) + len(dirs) + len(names) > limits.files:
            raise RecoveryError("Zu viele Dateien für eine Sicherung.")
        dirs.sort()
        for name in dirs:
            path = Path(parent) / name
            _safe_stat(path)
            directories.append(path.relative_to(root).as_posix())
        for name in sorted(names):
            path = Path(parent) / name
            fingerprint = _fingerprint(path)
            total += fingerprint[0]
            if fingerprint[0] > limits.file_bytes or total > limits.total_bytes:
                raise RecoveryError("Upload-Dateien überschreiten das Sicherungslimit.")
            files[path.relative_to(root).as_posix()] = fingerprint
    return files, directories


def _json(raw: bytes):
    # Bound nesting before json.loads allocates the manifest object graph.
    depth, quoted, escaped = 0, False, False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
        elif value in (91, 123):
            depth += 1
            if depth > 48:
                raise RecoveryError("JSON-Metadaten sind zu tief verschachtelt.")
        elif value in (93, 125):
            depth -= 1
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RecoveryError("Doppelte JSON-Felder im Sicherungsmanifest.")
            result[key] = value
        return result
    def reject_constant(value):
        raise RecoveryError("Nicht endliche Zahl in der Sicherung.")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise RecoveryError("Ungültige JSON-Metadaten in der Sicherung.") from exc


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def _database_info(path: Path, *, timeout_seconds: float = 300) -> dict:
    deadline = time.monotonic() + timeout_seconds
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                                 timeout=min(0.2, timeout_seconds))) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RecoveryError("SQLite-Integritaetspruefung fehlgeschlagen.")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RecoveryError("SQLite enthaelt ungueltige Fremdschluessel.")
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"users", "auth_setup", "portfolios", "bookings", "receivables", "rent_charges", "payments", "payment_reversals"}
        if not required.issubset(tables):
            raise RecoveryError("Unbekanntes oder unvollstaendiges ImmoManager-Datenbankschema.")
        from ..db.auth_models import AuthSetupORM  # noqa: F401 — register installation metadata
        from ..db.orm_models import Base
        # Pre-G03 archives have no managed families. Rotating their signer is
        # still mandatory; do not silently accept a partially missing journal.
        session_tables = {"auth_sessions", "auth_refresh_tokens"}
        if tables & session_tables and not session_tables.issubset(tables):
            raise RecoveryError("Das Sitzungsschema ist unvollständig; kompatible vollständige Sicherung erforderlich.")
        document_version_tables = {"document_versions", "document_version_chunks"}
        if tables & document_version_tables and not document_version_tables.issubset(tables):
            raise RecoveryError("Die Dokumenthistorie ist unvollständig. Vollständige Sicherung mit Originalen verwenden.")
        lifecycle_tables = {"contract_lifecycle_drafts", "contract_lifecycle_commands"}
        correspondence_tables = {"contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events"}
        if tables & correspondence_tables and not correspondence_tables.issubset(tables):
            raise RecoveryError("Die Vertragskorrespondenz ist unvollständig. Vollständige Sicherung mit Originalen verwenden.")
        from .contract_correspondence_validation import EvidenceError, validate_correspondence_journal
        try:
            validate_correspondence_journal(db, deadline=deadline)
        except (EvidenceError, sqlite3.Error):
            raise RecoveryError("Die Vertragskorrespondenz ist ungültig. Vollständige unveränderte Sicherung mit Originalen verwenden.") from None
        if tables & lifecycle_tables and not lifecycle_tables.issubset(tables):
            raise RecoveryError("Die Vertragsablaufhistorie ist unvollständig. Vollständige Sicherung verwenden.")
        for table in Base.metadata.sorted_tables:
            if table.name in session_tables and not tables & session_tables:
                continue
            # x1 adds a private journal. An older complete image has no table;
            # an existing but incomplete table must still fail column validation.
            if table.name == "form_drafts" and table.name not in tables:
                continue
            # y1 is an atomic pair. A complete older image has neither table;
            # an existing pair must still meet the current column contract.
            if table.name in document_version_tables and not tables & document_version_tables:
                continue
            if table.name in lifecycle_tables and not tables & lifecycle_tables:
                continue
            if table.name in correspondence_tables and not tables & correspondence_tables:
                continue
            actual = {column[1] for column in db.execute('PRAGMA table_info("' + table.name.replace('"', '""') + '")')}
            # A verified backup must precede the offline w1 migration. These
            # two additive columns were absent in the supported two-target
            # receipt schema; preserve that schema verbatim, including triggers.
            # All other missing columns and incomplete journals remain errors.
            compatible_missing = {"invoices": {"amount_paid"}, "payments": {"invoice_id"}}
            missing = set(table.columns.keys()) - actual
            if missing - compatible_missing.get(table.name, set()):
                raise RecoveryError("Das Datenbankschema passt nicht zu dieser Programmversion.")
        counts = {}
        for table in sorted(tables - {"sqlite_sequence"}):
            if time.monotonic() > deadline:
                raise RecoveryError("Datenbankprüfung hat das Zeitlimit überschritten.")
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = db.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
        return {"schema_sha256": hashlib.sha256(_json_bytes(schema)).hexdigest(), "rows": counts}


def _add_file(archive, name: str, path: Path, expected, limits: RecoveryLimits, *, deadline: float | None = None):
    digest, size = hashlib.sha256(), 0
    if expected[0] > limits.file_bytes:
        raise RecoveryError("Eine Datei ueberschreitet das Sicherungslimit.")
    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
        while block := source.read(CHUNK):
            if deadline is not None:
                _remaining(deadline)
            size += len(block)
            if size > limits.file_bytes:
                raise RecoveryError("Dateigroesse hat das Sicherungslimit ueberschritten.")
            digest.update(block)
            target.write(block)
    if size != expected[0] or _fingerprint(path) != expected:
        raise RecoveryError("Quelldatei wurde waehrend der Sicherung geaendert.")
    return {"size": size, "sha256": digest.hexdigest()}


def _add_bytes(archive, name: str, data: bytes, *, maximum: int = 16 * 1024**2):
    if len(data) > maximum:
        raise RecoveryError("Runtime-Metadaten überschreiten die Größengrenze.")
    archive.writestr(name, data)
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _configuration(values: Any) -> dict[str, str]:
    from ..settings import ExplicitSettings, Settings
    allowed = {name.upper() for name in Settings.model_fields}
    if not isinstance(values, dict) or set(values) - allowed:
        raise RecoveryError("Nicht unterstuetzte Runtime-Konfiguration.")
    if any(not isinstance(v, str) or "\x00" in v for v in values.values()):
        raise RecoveryError("Runtime-Konfiguration muss Textwerte enthalten.")
    if not values.get("JWT_SECRET_KEY"):
        raise RecoveryError("Das zur Entschluesselung erforderliche JWT-Geheimnis fehlt.")
    try:
        ExplicitSettings(**{key.lower(): value for key, value in values.items()})
    except ValueError as exc:
        raise RecoveryError("Runtime-Konfiguration enthält ungültige Einstellungen.") from exc
    return dict(values)


def create_full_backup(plan: RecoveryPlan, destination: Path, password: str, *,
                       offline: bool = False, limits: RecoveryLimits = RecoveryLimits()) -> dict:
    if not offline:
        raise RecoveryError("Anwendung und Hintergrundschreiber zuerst beenden; Offline-Modus bestaetigen.")
    deadline = time.monotonic() + limits.timeout_seconds
    configuration = _configuration(plan.configuration)
    config_bytes = _json_bytes(configuration)
    if len(config_bytes) > min(limits.file_bytes, limits.metadata_bytes):
        raise RecoveryError("Runtime-Konfiguration überschreitet die Größengrenze.")
    _safe_stat(plan.database)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise RecoveryError("Eine bestehende Sicherungsdatei wird nicht ueberschrieben.")
    uploads = plan.uploads.resolve()
    if destination.resolve().is_relative_to(uploads) or plan.database.resolve().is_relative_to(uploads):
        raise RecoveryError("Sicherung und Datenbank duerfen nicht im Upload-Baum liegen.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files, directories = _tree(plan.uploads, limits, deadline=deadline)
    extras = {}
    if plan.runtime_env is not None:
        extras["original-runtime.env"] = (plan.runtime_env, _fingerprint(plan.runtime_env))
    if plan.integration_state is not None:
        extras["integrations.json"] = (plan.integration_state, _fingerprint(plan.integration_state))
        if extras["integrations.json"][1][0] > min(limits.metadata_bytes, limits.file_bytes):
            raise RecoveryError("Integrationszustand überschreitet die Größengrenze.")
        if not isinstance(_json(plan.integration_state.read_bytes()), dict):
            raise RecoveryError("Integrationszustand muss ein JSON-Objekt sein.")
    if any(expected[0] > min(limits.metadata_bytes, limits.file_bytes) for _, expected in extras.values()):
        raise RecoveryError("Runtime-Metadaten überschreiten die Größengrenze.")
    if len(files) + len(directories) + len(extras) + 4 > limits.files:
        raise RecoveryError("Zu viele Dateien fuer eine Sicherung.")
    with tempfile.TemporaryDirectory(prefix=".immo-backup-", dir=destination.parent) as temporary_name:
        temporary = Path(temporary_name)
        image, package = temporary / "database.sqlite3", temporary / "archive.partial"
        with closing(sqlite3.connect(plan.database.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=min(0.2, _remaining(deadline)))) as source:
            version = source.execute("PRAGMA data_version").fetchone()[0]
            page_size = source.execute("PRAGMA page_size").fetchone()[0]
            if source.execute("PRAGMA page_count").fetchone()[0] * page_size > min(limits.file_bytes, limits.total_bytes):
                raise RecoveryError("Die Datenbank überschreitet das Sicherungslimit.")
            def progress(_status, _remaining_pages, total_pages):
                _remaining(deadline)
                if total_pages * page_size > min(limits.file_bytes, limits.total_bytes):
                    raise RecoveryError("Die Datenbank überschreitet das Sicherungslimit.")
            with closing(sqlite3.connect(image)) as target:
                source.backup(target, pages=256, progress=progress, sleep=0.02)
                target.execute("PRAGMA journal_mode=DELETE")
            database_info = _database_info(image, timeout_seconds=_remaining(deadline))
            verify_iban_key(image, configuration, deadline=deadline)
            verify_private_drafts(image, configuration, deadline=deadline)
            reference_report = validate_file_references(image, str(uploads), expected_upload_files=set(files), deadline=deadline)
            manifest = {"format": "immomanager-full", "version": 1,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "database": database_info, "directories": directories, "files": {},
                        "original_upload_root": str(uploads)}
            records = manifest["files"]
            with encrypted_zip(package, password) as archive:
                records["database.sqlite3"] = _add_file(archive, "database.sqlite3", image, _fingerprint(image), limits, deadline=deadline)
                records["configuration.json"] = _add_bytes(archive, "configuration.json", config_bytes, maximum=limits.metadata_bytes)
                if "integrations.json" not in extras:
                    records["integrations.json"] = _add_bytes(archive, "integrations.json", b"{}", maximum=limits.metadata_bytes)
                for name, (path, expected) in extras.items():
                    records[name] = _add_file(archive, name, path, expected, limits, deadline=deadline)
                for name, expected in files.items():
                    _remaining(deadline)
                    portable = _portable("uploads/" + name)
                    records[portable] = _add_file(archive, portable, uploads / name, expected, limits, deadline=deadline)
                    if sum(item["size"] for item in records.values()) > limits.total_bytes:
                        raise RecoveryError("Gesamtgroesse der Sicherung ueberschritten.")
                if _tree(plan.uploads, limits, deadline=deadline) != (files, directories):
                    raise RecoveryError("Upload-Baum wurde waehrend der Sicherung geaendert.")
                if any(_fingerprint(path) != expected for path, expected in extras.values()):
                    raise RecoveryError("Runtime-Konfiguration wurde waehrend der Sicherung geaendert.")
                if source.execute("PRAGMA data_version").fetchone()[0] != version:
                    raise RecoveryError("Datenbank wurde waehrend der Offline-Sicherung geaendert.")
                if sum(item["size"] for item in records.values()) > limits.total_bytes:
                    raise RecoveryError("Gesamtgroesse der Sicherung ueberschritten.")
                for directory in directories:
                    _portable("uploads/" + directory)
                _add_bytes(archive, "manifest.json", _json_bytes(manifest), maximum=min(limits.manifest_bytes, limits.file_bytes))
                names = [entry.filename.casefold() for entry in archive.infolist()]
                directory_bytes = sum(78 + len(entry.filename.encode("utf-8")) + len(entry.extra) + len(entry.comment)
                                      for entry in archive.infolist())
                if directory_bytes > limits.central_directory_bytes:
                    raise RecoveryError("ZIP-Verzeichnis überschreitet die Metadatengrenze.")
                directory_names = [("uploads/" + item).casefold() for item in directories]
                if len(set(names + directory_names)) != len(names + directory_names):
                    raise RecoveryError("Dateinamen kollidieren auf einem portablen Dateisystem.")
                if any(entry.file_size > max(1, entry.compress_size) * limits.compression_ratio
                       for entry in archive.infolist()):
                    raise RecoveryError("Datei ist staerker komprimiert als die Entpackgrenze erlaubt.")
        if package.stat().st_size > limits.total_bytes:
            raise RecoveryError("Verschluesselte Sicherung ist zu gross.")
        # Hard-link publication is exclusive: never overwrite a racing destination.
        _remaining(deadline)
        os.link(package, destination)
    return {"backup": str(destination), "size_bytes": destination.stat().st_size,
            "scope": "sqlite-uploads-users-configuration", "encrypted": True,
            "external_reference_count": reference_report.external_reference_count}


def _portable(name: str) -> str:
    path = PurePosixPath(name)
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
    if not name or path.is_absolute() or PureWindowsPath(name).drive or path.as_posix() != name:
        raise RecoveryError("Unzulaessiger Archivpfad.")
    if len(path.parts) > 48 or len(name) > 4000:
        raise RecoveryError("Archivpfad ist zu lang oder zu tief verschachtelt.")
    for part in path.parts:
        if (part in {".", ".."} or part.rstrip(" .") != part or len(part) > 240
                or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)):
            raise RecoveryError("Nicht portabler oder unsicherer Archivpfad.")
    return name


def _checked_manifest(archive: ZipFile, limits: RecoveryLimits):
    entries = archive.infolist()
    if len(entries) > limits.files:
        raise RecoveryError("Zu viele Archiveintraege.")
    names, seen = {}, set()
    for entry in entries:
        name = _portable(entry.filename)
        folded = name.casefold()
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if folded in seen or entry.is_dir() or mode not in (0, stat.S_IFREG):
            raise RecoveryError("Doppelter Archivpfad oder spezieller Dateityp.")
        if (entry.file_size > limits.file_bytes or
                entry.file_size > max(1, entry.compress_size) * limits.compression_ratio):
            raise RecoveryError("Archiveintrag ueberschreitet Entpackgrenzen.")
        names[name] = entry
        seen.add(folded)
    if "manifest.json" not in names or names["manifest.json"].file_size > limits.manifest_bytes:
        raise RecoveryError("Sicherungsmanifest fehlt oder ist zu gross.")
    manifest = _json(archive.read("manifest.json"))
    if (not isinstance(manifest, dict) or manifest.get("format") != "immomanager-full"
            or manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict)):
        raise RecoveryError("Unbekanntes Sicherungsmanifest.")
    if not isinstance(manifest.get("original_upload_root"), str):
        raise RecoveryError("Der urspruengliche Upload-Pfad fehlt im Manifest.")
    records = manifest["files"]
    required = {"database.sqlite3", "configuration.json", "integrations.json"}
    if not required.issubset(records) or set(records) | {"manifest.json"} != set(names):
        raise RecoveryError("Archiv und Manifest enthalten unterschiedliche Dateien.")
    total = 0
    for name, record in records.items():
        if not (name in required | {"original-runtime.env"} or name.startswith("uploads/")):
            raise RecoveryError("Unerwarteter Inhalt im Vollbackup.")
        if (not isinstance(record, dict) or type(record.get("size")) is not int
                or record["size"] < 0 or record["size"] != names[name].file_size
                or not isinstance(record.get("sha256"), str) or len(record["sha256"]) != 64):
            raise RecoveryError("Ungueltige Dateiangaben im Sicherungsmanifest.")
        if name in {"configuration.json", "integrations.json", "original-runtime.env"} and record["size"] > limits.metadata_bytes:
            raise RecoveryError("Runtime-Metadaten ueberschreiten die Groessengrenze.")
        total += record["size"]
    dirs = manifest.get("directories")
    if (not isinstance(dirs, list) or any(not isinstance(d, str) for d in dirs)
            or len(dirs) + len(names) > limits.files or total > limits.total_bytes):
        raise RecoveryError("Entpackgrenzen ueberschritten oder Verzeichnisse ungueltig.")
    file_keys = {name.casefold() for name in records}
    directory_keys: set[str] = set()
    for directory in dirs:
        name = _portable("uploads/" + directory)
        folded = name.casefold()
        if folded in file_keys | directory_keys:
            raise RecoveryError("Widerspruechliche Datei-/Verzeichnispfade.")
        directory_keys.add(folded)
    for name in list(records) + ["uploads/" + d for d in dirs]:
        if any(parent.as_posix().casefold() in file_keys for parent in PurePosixPath(name).parents):
            raise RecoveryError("Archivdatei wird zugleich als Verzeichnis verwendet.")
    return manifest


def _publish_directory(source: Path, target: Path):
    if os.name == "nt":
        os.rename(source, target)  # Windows rename refuses an existing destination.
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RecoveryError("Exklusive Verzeichnisfreigabe wird hier nicht unterstuetzt.")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def _rebased_configuration(values, destination: Path):
    values = _configuration(values)
    values.update(DATA_DIR=str(destination), UPLOADS_DIR=str(destination / "uploads"),
                  BACKUP_DIR=str(destination / "backups"), LOG_FILE=str(destination / "logs" / "immomanager.log"),
                  DATABASE_URL="sqlite:///" + (destination / "database.sqlite3").as_posix(),
                  INTEGRATION_STATE_FILE=str(destination / "integrations.json"),
                  SQLITE_PERSISTENT_STORE="true", ALLOW_INMEMORY_FALLBACK="false",
                  PLUGIN_DIRS="[]")
    from ..settings import ExplicitSettings
    effective = ExplicitSettings(**{key.lower(): value for key, value in values.items()})
    return {key.upper(): value if isinstance(value, str) else json.dumps(value)
            for key, value in effective.model_dump(mode="json").items() if value is not None}


def restore_full_backup(source: Path, destination: Path, password: str, *,
                        limits: RecoveryLimits = RecoveryLimits()) -> dict:
    deadline = time.monotonic() + limits.timeout_seconds
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise RecoveryError("Wiederherstellung erfordert ein neues, nicht vorhandenes Zielverzeichnis.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".immo-restore-", dir=destination.parent) as temporary_name:
        temporary = Path(temporary_name)
        decoded, staged = temporary / "authenticated.zip", temporary / "installation"
        decrypt_zip(source, decoded, password, limits.total_bytes)
        check_zip_budget(decoded, maximum_entries=limits.files,
                         maximum_directory_bytes=limits.central_directory_bytes,
                         timeout_seconds=_remaining(deadline))
        staged.mkdir()
        with ZipFile(decoded) as archive:
            manifest = _checked_manifest(archive, limits)
            for name, record in manifest["files"].items():
                _remaining(deadline)
                target = staged.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with archive.open(name) as incoming, target.open("xb") as output:
                    while block := incoming.read(CHUNK):
                        _remaining(deadline)
                        size += len(block)
                        if size > record["size"] or size > limits.file_bytes:
                            raise RecoveryError("Archiveintrag enthaelt zu viele Daten.")
                        digest.update(block)
                        output.write(block)
                if size != record["size"] or digest.hexdigest() != record["sha256"]:
                    raise RecoveryError("Pruefsumme oder Dateigroesse der Sicherung stimmt nicht.")
        for directory in manifest["directories"]:
            (staged / "uploads").joinpath(*PurePosixPath(directory).parts).mkdir(parents=True, exist_ok=True)
        for directory in ("uploads", "backups", "logs"):
            (staged / directory).mkdir(exist_ok=True)
        if _database_info(staged / "database.sqlite3", timeout_seconds=_remaining(deadline)) != manifest["database"]:
            raise RecoveryError("Datenbankschema oder Zeilenanzahlen stimmen nicht mit der Sicherung ueberein.")
        if not isinstance(_json((staged / "integrations.json").read_bytes()), dict):
            raise RecoveryError("Integrationszustand ist kein JSON-Objekt.")
        values = _rebased_configuration(_json((staged / "configuration.json").read_bytes()), destination)
        verify_iban_key(staged / "database.sqlite3", values, deadline=deadline)
        verify_private_drafts(staged / "database.sqlite3", values, deadline=deadline)
        upload_files = {name.removeprefix("uploads/") for name in manifest["files"] if name.startswith("uploads/")}
        reference_report = validate_file_references(staged / "database.sqlite3", manifest["original_upload_root"],
                                                   expected_upload_files=upload_files, deadline=deadline)
        rebase_file_references(staged / "database.sqlite3", manifest["original_upload_root"], destination / "uploads",
                              expected_upload_files=upload_files, deadline=deadline)
        from .recovery_sessions import SessionRestoreError, secure_sqlite_restore
        try:
            values, session_report = secure_sqlite_restore(staged / "database.sqlite3", values, deadline=deadline)
        except SessionRestoreError as exc:
            raise RecoveryError(str(exc)) from None
        (staged / "original-configuration.json").write_bytes((staged / "configuration.json").read_bytes())
        (staged / "configuration.json").write_bytes(_json_bytes(values))
        # The recovery launcher reads JSON exactly; .env is a convenience for simple settings.
        simple = {k: v for k, v in values.items() if not any(c in v for c in "\r\n") and v.strip('\"\'') == v}
        (staged / ".env").write_text("".join(f"{k}={v}\n" for k, v in simple.items()), encoding="utf-8")
        (staged / "recovery-manifest.json").write_bytes(_json_bytes(manifest))
        _remaining(deadline)
        _publish_directory(staged, destination)
    return {"restored_to": str(destination), "scope": "sqlite-uploads-users-configuration",
            "requires_restart": True, "existing_installation_changed": False,
            "external_reference_count": reference_report.external_reference_count,
            "sessions_revoked": session_report["revoked_session_count"], "signing_key_rotated": True}


def load_recovered_environment(directory: Path):
    """Load declared application settings, never unrelated shell configuration."""
    import sys
    if "backend.app" in sys.modules or "backend.dependencies" in sys.modules:
        raise RecoveryError("Die wiederhergestellte Anwendung muss in einem neuen Prozess gestartet werden.")
    directory = directory.resolve()
    values = _rebased_configuration(_json((directory / "configuration.json").read_bytes()), directory)
    from ..settings import ExplicitSettings, Settings
    for key in list(os.environ):
        if key.lower() in Settings.model_fields:
            os.environ.pop(key, None)
    os.environ.update(values)
    from .. import config
    constructor_options: dict[str, Any] = {key.lower(): value for key, value in values.items()}
    config.settings = ExplicitSettings(**constructor_options)
    return values
