"""Full backups: database, uploads, configuration and keys in one verifiable archive.

Archive (ZIP64), one file per backup in <BACKUP_DIR>/full:

  manifest.json                         format, app/Alembic versions, row counts, SHA-256 + size per file
  database/immo_manager.sqlite3         SQLite: consistent copy through the online backup API
  database/postgres.dump                PostgreSQL: pg_dump (custom format) from one exported snapshot;
                                        the row counts come from the same snapshot
  uploads/<path>                        every regular file of the upload directory
  config/integrations.json              integration settings (secret fields are ciphertext)
  config/integrations-journal.sqlite3   integration journal (online backup copy)
  secrets/keyring.json, config/env      key file and .env, readable: without BACKUP_PASSPHRASE the
                                        archive is as sensitive as the key itself
  secrets/secrets.enc                   with BACKUP_PASSPHRASE: key file and .env sealed (scrypt + AES-GCM)

Next to every archive lies <name>.sha256 (sha256sum format). An archive is written as
.partial, re-read and verified, and only then renamed. Verification checks the archive
digest, every file's digest and size, and refuses files the manifest does not list. A
restore probe extracts into an isolated directory, opens the database read-only, compares
revision and row counts, decrypts the stored secrets with the archived keys, and deletes
the directory again. Nothing here imports the running application (backend.dependencies),
so the explicit upgrade can call it before the program starts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from ..config import settings
from ..paths import get_backup_dir, get_data_dir, get_uploads_dir
from . import secret_box

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

FORMAT = "immomanager-full-backup"
FORMAT_VERSION = 1
LOG_NAME = "ops-log.jsonl"
_NAME = re.compile(r"^immomanager-full-(\d{8}T\d{6})Z-([a-z-]+)-([0-9a-f]{4})\.zip$")
_CHUNK = 1024 * 1024
_STORED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".zip", ".gz", ".7z", ".docx", ".xlsx",
                    ".pptx", ".odt", ".ods", ".mp4", ".mov", ".dump"}
# Paths in .env that point at the old installation; dropped when restoring elsewhere.
_PATH_KEYS = ("DATA_DIR", "UPLOADS_DIR", "BACKUP_DIR", "LOG_FILE", "INTEGRATION_STATE_FILE", "SECRET_KEY_FILE")
_LOCK_STALE_SECONDS = 6 * 3600
TRIGGERS = ("scheduled", "manual", "pre-upgrade", "cli")

DB_SQLITE = "database/immo_manager.sqlite3"
DB_POSTGRES = "database/postgres.dump"
INTEGRATIONS = "config/integrations.json"
JOURNAL = "config/integrations-journal.sqlite3"
KEYRING = "secrets/keyring.json"
ENV = "config/env"
SEALED = "secrets/secrets.enc"


class BackupError(RuntimeError):
    """A backup, probe or restore cannot run; nothing was replaced."""


# --- configuration ------------------------------------------------------------------------

@dataclass
class Sources:
    database_url: str
    data_dir: Path
    uploads_dir: Path
    root: Path                          # <BACKUP_DIR>/full
    integration_state: Path
    key_file: Path
    env_file: Path
    second_target: Path | None = None
    passphrase: str = ""
    keep_daily: int = 14
    keep_monthly: int = 6
    keep_pre_upgrade: int = 3
    pg_bin_dir: str = ""
    probe_postgres_url: str = ""
    env_secret_keys: str = ""

    @classmethod
    def from_settings(cls) -> Sources:
        data_dir = get_data_dir()
        state = settings.integration_state_file or str(data_dir / "integrations.json")
        second = settings.backup_second_target.strip()
        return cls(
            database_url=settings.database_url, data_dir=data_dir, uploads_dir=get_uploads_dir(),
            root=get_backup_dir() / "full", integration_state=Path(state).expanduser(),
            key_file=secret_box.default_key_file(), env_file=data_dir / ".env",
            second_target=Path(second).expanduser() if second else None, passphrase=settings.backup_passphrase,
            keep_daily=settings.backup_keep_daily, keep_monthly=settings.backup_keep_monthly,
            keep_pre_upgrade=settings.backup_keep_pre_upgrade, pg_bin_dir=settings.pg_bin_dir,
            probe_postgres_url=settings.restore_probe_postgres_url, env_secret_keys=settings.secret_keys,
        )

    @property
    def dialect(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def journal(self) -> Path:
        return self.integration_state.with_suffix(self.integration_state.suffix + ".history.sqlite3")


class _Pulse:
    """Throttled heartbeat for long copies (keeps the job lease)."""

    def __init__(self, heartbeat: Callable[[], None] | None, every: float = 15.0):
        self.heartbeat, self.every, self.last = heartbeat, every, time.monotonic()

    def beat(self) -> None:
        if self.heartbeat is not None and time.monotonic() - self.last >= self.every:
            self.heartbeat()
            self.last = time.monotonic()


# --- small helpers ------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path, pulse: _Pulse | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
            if pulse:
                pulse.beat()
    return digest.hexdigest()


def _fsync(path: Path) -> None:
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _write_sidecar(archive: Path, digest: str) -> None:
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")


def _read_sidecar(archive: Path) -> str | None:
    sidecar = archive.with_name(archive.name + ".sha256")
    try:
        return sidecar.read_text(encoding="utf-8").split()[0].lower()
    except (OSError, IndexError):
        return None


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and "\\" not in name and not path.is_absolute() and ".." not in path.parts \
        and ":" not in path.parts[0]


def _sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if not url.database or url.database == ":memory:":
        raise BackupError("Die SQLite-Datenbank liegt nur im Arbeitsspeicher; kein Vollbackup möglich.")
    return Path(url.database)


def sqlite_online_copy(source: Path, target: Path) -> None:
    """Consistent copy of a live (WAL) SQLite file; never creates a missing source."""
    if not source.is_file():
        raise BackupError(f"Datenbankdatei nicht gefunden: {source}")
    src = sqlite3.connect(source, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _sqlite_facts(path: Path, *, full_check: bool) -> dict[str, Any]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        check = connection.execute("PRAGMA integrity_check" if full_check else "PRAGMA quick_check").fetchone()[0]
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None
        return {"integrity": check, "row_counts": counts, "revision": revision}
    finally:
        connection.close()


def _pg_tool(name: str, bin_dir: str) -> str:
    found = (shutil.which(name, path=bin_dir) if bin_dir else None) or shutil.which(name)
    if not found:
        raise BackupError(f"{name} nicht gefunden. PostgreSQL-Client installieren (gleiche oder neuere Hauptversion "
                          f"als der Server) oder PG_BIN_DIR setzen; ohne {name} kein Vollbackup.")
    return found


def _libpq(database_url: str) -> tuple[str, dict[str, str]]:
    """Connection URI without password (that one goes into PGPASSWORD) for the pg_* tools."""
    url = make_url(database_url)
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    plain = url.set(drivername="postgresql", password=None)
    return plain.render_as_string(hide_password=False), env


def _run(command: list[str], env: dict[str, str] | None = None, timeout: float = 6 * 3600) -> str:
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=timeout)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-800:]
        raise BackupError(f"{Path(command[0]).name} fehlgeschlagen: {tail}")
    return result.stdout


def _pg_tables(connection) -> list[str]:
    return sorted(inspect(connection).get_table_names())


def _pg_dump(sources: Sources, target: Path) -> dict[str, Any]:
    """pg_dump of one exported snapshot; row counts read inside the same snapshot."""
    tool = _pg_tool("pg_dump", sources.pg_bin_dir)
    conninfo, env = _libpq(sources.database_url)
    engine = create_engine(sources.database_url, poolclass=NullPool, isolation_level="REPEATABLE READ")
    try:
        with engine.connect() as connection:
            with connection.begin():
                snapshot = connection.execute(text("SELECT pg_export_snapshot()")).scalar()
                tables = _pg_tables(connection)
                counts = {table: connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                          for table in tables}
                revision = None
                if "alembic_version" in tables:
                    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                server = connection.execute(text("SHOW server_version")).scalar()
                _run([tool, "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}",
                      f"--file={target}", "--dbname", conninfo], env)
    finally:
        engine.dispose()
    return {"integrity": "pg_dump ok", "row_counts": counts, "revision": revision, "server_version": server}


class _Lock:
    """One full backup/probe at a time per backup directory (job, button and CLI alike)."""

    def __init__(self, root: Path):
        self.path = root / ".lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > _LOCK_STALE_SECONDS:
                    self.path.unlink(missing_ok=True)
                    continue
                raise BackupError("Eine andere Sicherung oder Wiederherstellungsprobe läuft gerade.") from None
            with os.fdopen(fd, "w") as handle:
                handle.write(f"{socket.gethostname()}:{os.getpid()} {_utcnow().isoformat()}\n")
            return self
        raise BackupError("Sperrdatei der Sicherung konnte nicht angelegt werden.")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


# --- ops log ------------------------------------------------------------------------------

def record_event(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    event = {"at": _utcnow().isoformat(timespec="seconds"), **event}
    path = root / LOG_NAME
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)[-2000:]
            temporary = path.with_suffix(".tmp")
            temporary.write_text("".join(lines), encoding="utf-8")
            os.replace(temporary, path)
    except OSError:
        logger.warning("Could not trim %s", path, exc_info=True)
    return event


def read_events(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    """Newest first; unreadable lines are skipped."""
    try:
        lines = (root / LOG_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in reversed(lines):
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
        if len(events) >= limit:
            break
    return events


# --- archives -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Archive:
    path: Path
    created_at: datetime
    trigger: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def local_date(self):
        return self.created_at.astimezone(BERLIN).date()


def list_archives(directory: Path) -> list[Archive]:
    """Finished archives, newest first (a .partial never counts)."""
    archives: list[Archive] = []
    if not directory.is_dir():
        return archives
    for path in directory.iterdir():
        match = _NAME.match(path.name)
        if match and path.is_file():
            created = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            archives.append(Archive(path, created, match.group(2)))
    return sorted(archives, key=lambda item: (item.created_at, item.name), reverse=True)


def retention_keep(archives: list[Archive], keep_daily: int, keep_monthly: int, keep_pre_upgrade: int) -> set[str]:
    """Newest per local day (keep_daily days), newest per month (keep_monthly months), the
    last pre-upgrade archives, and always the newest archive."""
    keep: set[str] = set()
    if not archives:
        return keep
    ordered = sorted(archives, key=lambda item: (item.created_at, item.name), reverse=True)
    keep.add(ordered[0].name)
    days: set = set()
    months: set = set()
    for archive in ordered:
        day = archive.local_date
        if day not in days and len(days) < keep_daily:
            days.add(day)
            keep.add(archive.name)
        month = (day.year, day.month)
        if month not in months and len(months) < keep_monthly:
            months.add(month)
            keep.add(archive.name)
    keep.update(item.name for item in [a for a in ordered if a.trigger == "pre-upgrade"][:keep_pre_upgrade])
    return keep


def apply_retention(directory: Path, keep_daily: int, keep_monthly: int, keep_pre_upgrade: int) -> list[str]:
    archives = list_archives(directory)
    keep = retention_keep(archives, keep_daily, keep_monthly, keep_pre_upgrade)
    removed = []
    for archive in archives:
        if archive.name not in keep:
            archive.path.unlink(missing_ok=True)
            archive.path.with_name(archive.name + ".sha256").unlink(missing_ok=True)
            removed.append(archive.name)
    return removed


def _archive_name(trigger: str, now: datetime) -> str:
    return f"immomanager-full-{now.strftime('%Y%m%dT%H%M%S')}Z-{trigger}-{secrets.token_hex(2)}.zip"


# --- writing ------------------------------------------------------------------------------

@dataclass
class _Writer:
    zf: zipfile.ZipFile
    pulse: _Pulse
    files: list[dict[str, Any]] = field(default_factory=list)

    def add_file(self, source: Path, arcname: str, kind: str) -> None:
        stat = source.stat()
        info = zipfile.ZipInfo(arcname, time.gmtime(max(stat.st_mtime, 315532800))[:6])
        info.compress_type = zipfile.ZIP_STORED if source.suffix.lower() in _STORED_SUFFIXES \
            else zipfile.ZIP_DEFLATED
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as handle, self.zf.open(info, "w", force_zip64=True) as out:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
                self.pulse.beat()
        self.files.append({"path": arcname, "sha256": digest.hexdigest(), "size": size, "kind": kind})

    def add_bytes(self, data: bytes, arcname: str, kind: str) -> None:
        info = zipfile.ZipInfo(arcname, time.gmtime()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        self.zf.writestr(info, data)
        self.files.append({"path": arcname, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                           "kind": kind})


def _iter_uploads(directory: Path) -> Iterator[tuple[Path, str]]:
    if not directory.is_dir():
        return
    for current, dirs, files in os.walk(directory, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            yield path, f"uploads/{relative}"


def _env_key_ids(env_bytes: bytes | None) -> list[str]:
    if not env_bytes:
        return []
    for line in env_bytes.decode("utf-8", "replace").splitlines():
        key, _, value = line.strip().partition("=")
        if key.strip() == "SECRET_KEYS":
            try:
                return [key.id for key in secret_box.parse_env_keys(value.strip().strip('"').strip("'"))]
            except secret_box.SecretError:
                return []
    return []


def _needed_key_ids(state_bytes: bytes | None) -> list[str]:
    if not state_bytes:
        return []
    try:
        state = json.loads(state_bytes.decode("utf-8"))
    except ValueError:
        return []
    ids = set()
    for values in (state.get("config") or {}).values() if isinstance(state, dict) else []:
        for value in (values or {}).values() if isinstance(values, dict) else []:
            if secret_box.is_sealed(value):
                try:
                    ids.add(secret_box.token_key_id(value))
                except secret_box.SecretError:
                    pass
    return sorted(ids)


def _code_head() -> str | None:
    try:
        from ..db.schema_state import head_revision

        return head_revision()
    except Exception:  # pragma: no cover - a broken migration directory must not block a backup
        logger.exception("Could not determine the Alembic head")
        return None


def create_full_backup(trigger: str = "manual", sources: Sources | None = None,
                       heartbeat: Callable[[], None] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Write, verify, copy to the second target, apply retention; returns the logged event."""
    sources = sources or Sources.from_settings()
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger}")
    started = time.monotonic()
    try:
        with _Lock(sources.root):
            event = _create(trigger, sources, _Pulse(heartbeat), now or _utcnow())
    except Exception as exc:
        _record_failure(sources.root, {"event": "backup", "ok": False, "trigger": trigger, "error": _message(exc),
                                       "duration_s": round(time.monotonic() - started, 1)})
        raise
    event["duration_s"] = round(time.monotonic() - started, 1)
    return record_event(sources.root, event)


def _record_failure(root: Path, event: dict[str, Any]) -> None:
    """Log a failure; an unwritable backup directory must not hide the original error."""
    logger.error("%s failed: %s", event["event"], event.get("error"))
    try:
        record_event(root, event)
    except OSError:
        logger.warning("Could not write the operations log in %s", root, exc_info=True)


def _message(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, (BackupError, secret_box.SecretError)) else f"{type(exc).__name__}: {exc}"


def _create(trigger: str, sources: Sources, pulse: _Pulse, now: datetime) -> dict[str, Any]:
    dialect = sources.dialect
    if dialect not in ("sqlite", "postgresql"):
        raise BackupError(f"Vollbackup für {dialect} wird nicht unterstützt (nur SQLite und PostgreSQL).")
    sources.root.mkdir(parents=True, exist_ok=True)
    work = sources.root / f".work-{secrets.token_hex(4)}"
    work.mkdir()
    name = _archive_name(trigger, now)
    final = sources.root / name
    partial = sources.root / (name + ".partial")
    try:
        if dialect == "sqlite":
            db_copy = work / "db.sqlite3"
            sqlite_online_copy(_sqlite_path(sources.database_url), db_copy)
            facts = _sqlite_facts(db_copy, full_check=False)
            if facts["integrity"] != "ok":
                raise BackupError(f"Datenbank-Prüfung fehlgeschlagen: {facts['integrity']}")
            db_entry = DB_SQLITE
        else:
            db_copy = work / "postgres.dump"
            facts = _pg_dump(sources, db_copy)
            db_entry = DB_POSTGRES
        pulse.beat()

        journal_copy = None
        if sources.journal.is_file():
            journal_copy = work / "journal.sqlite3"
            sqlite_online_copy(sources.journal, journal_copy)
        state_bytes = sources.integration_state.read_bytes() if sources.integration_state.is_file() else None
        keyring_bytes = sources.key_file.read_bytes() if sources.key_file.is_file() else None
        env_bytes = sources.env_file.read_bytes() if sources.env_file.is_file() else None

        needed = _needed_key_ids(state_bytes)
        included_ids = set(_env_key_ids(env_bytes))
        if keyring_bytes:
            included_ids |= {key.id for key in secret_box.keys_from_bytes(keyring_bytes)}
        included = sorted(included_ids)
        missing = sorted(set(needed) - included_ids)

        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            writer = _Writer(zf, pulse)
            writer.add_file(db_copy, db_entry, "database")
            upload_count = upload_bytes = 0
            for path, arcname in _iter_uploads(sources.uploads_dir):
                writer.add_file(path, arcname, "upload")
                upload_count += 1
                upload_bytes += writer.files[-1]["size"]
            if state_bytes is not None:
                writer.add_bytes(state_bytes, INTEGRATIONS, "config")
            if journal_copy is not None:
                writer.add_file(journal_copy, JOURNAL, "config")
            protected: list[dict[str, Any]] = []
            plain = {KEYRING: keyring_bytes, ENV: env_bytes}
            if sources.passphrase:
                bundle = {arc: base64.b64encode(data).decode("ascii") for arc, data in plain.items() if data}
                protected = [{"path": arc, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                             for arc, data in plain.items() if data]
                if bundle:
                    sealed = secret_box.seal_with_passphrase(json.dumps(bundle).encode("utf-8"), sources.passphrase)
                    writer.add_bytes(sealed, SEALED, "secret")
            else:
                for arc, data in plain.items():
                    if data is not None:
                        writer.add_bytes(data, arc, "secret" if arc == KEYRING else "config")
            manifest = {
                "format": FORMAT, "format_version": FORMAT_VERSION, "trigger": trigger,
                "created_at": now.isoformat(timespec="seconds"),
                "local_date": now.astimezone(BERLIN).date().isoformat(),
                "app_version": settings.app_version, "alembic_head": _code_head(),
                "host": socket.gethostname(),
                "database": {"dialect": dialect, "path": db_entry, "revision": facts["revision"],
                             "row_counts": facts["row_counts"], "integrity": facts["integrity"],
                             **({"server_version": facts["server_version"]} if "server_version" in facts else {})},
                "uploads": {"files": upload_count, "bytes": upload_bytes},
                "secrets": {"protection": "passphrase" if sources.passphrase else "none",
                            "protected_files": protected, "needed_key_ids": needed, "included_key_ids": included,
                            "missing_key_ids": missing},
                "files": writer.files,
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        _fsync(partial)
        digest = sha256_file(partial, pulse)
        report = verify_archive(partial, expected_sha256=digest, pulse=pulse)
        if not report["ok"]:
            raise BackupError("Neues Archiv besteht die Prüfung nicht: " + "; ".join(report["problems"][:5]))
        os.replace(partial, final)
        _write_sidecar(final, digest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    event: dict[str, Any] = {
        "event": "backup", "ok": True, "trigger": trigger, "archive": name, "size": final.stat().st_size,
        "sha256": digest, "revision": facts["revision"], "dialect": dialect, "uploads": upload_count,
        "secrets_protection": "passphrase" if sources.passphrase else "none", "missing_key_ids": missing,
        "rows": sum(facts["row_counts"].values()),
    }
    if sources.second_target is not None:
        try:
            _copy_verified(final, digest, sources.second_target, pulse)
            event["second_target"] = {"ok": True, "path": str(sources.second_target)}
            event["second_target"]["removed"] = apply_retention(
                sources.second_target, sources.keep_daily, sources.keep_monthly, sources.keep_pre_upgrade)
        except (OSError, BackupError) as exc:
            logger.error("Copy to the second backup target failed: %s", exc)
            event["second_target"] = {"ok": False, "path": str(sources.second_target), "error": _message(exc)}
    event["removed"] = apply_retention(sources.root, sources.keep_daily, sources.keep_monthly,
                                       sources.keep_pre_upgrade)
    return event


def _copy_verified(archive: Path, digest: str, directory: Path, pulse: _Pulse) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / (archive.name + ".partial")
    try:
        with archive.open("rb") as source, partial.open("wb") as target:
            for chunk in iter(lambda: source.read(_CHUNK), b""):
                target.write(chunk)
                pulse.beat()
            target.flush()
            os.fsync(target.fileno())
        copied = sha256_file(partial, pulse)
        if copied != digest:
            raise BackupError(f"Kopie im zweiten Ziel weicht ab (SHA-256 {copied[:12]}… statt {digest[:12]}…)")
        os.replace(partial, directory / archive.name)
        _write_sidecar(directory / archive.name, digest)
    finally:
        partial.unlink(missing_ok=True)


# --- verification -------------------------------------------------------------------------

def _recorded_digest(root: Path, name: str) -> str | None:
    for event in read_events(root, limit=2000):
        if event.get("event") == "backup" and event.get("archive") == name and event.get("sha256"):
            return str(event["sha256"])
    return None


def verify_archive(path: Path, *, expected_sha256: str | None = None, pulse: _Pulse | None = None) -> dict[str, Any]:
    """Digest of the archive (sidecar, expected), every file's digest/size, no unlisted files."""
    pulse = pulse or _Pulse(None)
    problems: list[str] = []
    if not path.is_file():
        return {"ok": False, "problems": [f"Archiv nicht gefunden: {path.name}"], "archive": path.name}
    digest = sha256_file(path, pulse)
    sidecar = _read_sidecar(path)
    if sidecar is not None and sidecar != digest:
        problems.append("SHA-256 des Archivs stimmt nicht mit der .sha256-Datei überein")
    if expected_sha256 is not None and expected_sha256 != digest:
        problems.append("SHA-256 des Archivs weicht vom protokollierten Wert ab")
    manifest: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if len(names) != len(set(names)):
                problems.append("Archiv enthält doppelte Einträge")
            unsafe = [name for name in names if not _safe_member(name)]
            if unsafe:
                problems.append(f"Unsichere Pfade im Archiv: {unsafe[:3]}")
            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("format") != FORMAT:
                problems.append("Kein Vollbackup von ImmoManager Pro")
            elif int(manifest.get("format_version", 0)) > FORMAT_VERSION:
                problems.append("Vollbackup stammt aus einer neueren Programmversion")
            entries = {entry["path"]: entry for entry in manifest.get("files", [])}
            extra = sorted(set(names) - set(entries) - {"manifest.json"})
            if extra:
                problems.append(f"Nicht im Manifest aufgeführte Dateien: {extra[:3]}")
            for name, entry in entries.items():
                if name not in names:
                    problems.append(f"Fehlt im Archiv: {name}")
                    continue
                file_digest, size = hashlib.sha256(), 0
                with zf.open(name) as handle:
                    for chunk in iter(lambda: handle.read(_CHUNK), b""):
                        file_digest.update(chunk)
                        size += len(chunk)
                        pulse.beat()
                if file_digest.hexdigest() != entry.get("sha256") or size != entry.get("size"):
                    problems.append(f"Prüfsumme oder Größe stimmt nicht: {name}")
            if manifest.get("database", {}).get("path") not in entries:
                problems.append("Archiv enthält keine Datenbank")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, zipfile.LargeZipFile) as exc:
        problems.append(f"Archiv nicht lesbar: {type(exc).__name__}: {exc}")
    return {"ok": not problems, "problems": problems, "archive": path.name, "sha256": digest,
            "files": len(manifest.get("files", [])), "manifest": _manifest_summary(manifest)}


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    database = manifest.get("database", {})
    return {"created_at": manifest.get("created_at"), "trigger": manifest.get("trigger"),
            "app_version": manifest.get("app_version"), "alembic_head": manifest.get("alembic_head"),
            "revision": database.get("revision"), "dialect": database.get("dialect"),
            "uploads": manifest.get("uploads"), "secrets": manifest.get("secrets")}


# --- extraction ---------------------------------------------------------------------------

def _extract(path: Path, target: Path, pulse: _Pulse) -> dict[str, Any]:
    """Extract the listed files (and only those); re-hash what landed on disk."""
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        for entry in manifest["files"]:
            name = entry["path"]
            if not _safe_member(name):
                raise BackupError(f"Unsicherer Pfad im Archiv: {name}")
            destination = target.joinpath(*PurePosixPath(name).parts)
            if not destination.resolve().is_relative_to(target.resolve()):
                raise BackupError(f"Pfad außerhalb des Zielverzeichnisses: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out, _CHUNK)
            if sha256_file(destination, pulse) != entry["sha256"]:
                raise BackupError(f"Wiederhergestellte Datei weicht ab: {name}")
    return manifest


def _secret_files(manifest: dict[str, Any], extracted: Path, passphrase: str) -> tuple[dict[str, bytes], str | None]:
    """Key file and .env of the archive (decrypted with the passphrase); (files, warning)."""
    if manifest["secrets"]["protection"] == "passphrase":
        sealed = extracted / SEALED
        if not sealed.is_file():
            return {}, None
        if not passphrase:
            return {}, "Schlüsselsicherung ist mit Passphrase geschützt; ohne Passphrase nicht geprüft."
        bundle = json.loads(secret_box.open_with_passphrase(sealed.read_bytes(), passphrase))
        files = {arc: base64.b64decode(data) for arc, data in bundle.items()}
        for entry in manifest["secrets"]["protected_files"]:
            if hashlib.sha256(files.get(entry["path"], b"")).hexdigest() != entry["sha256"]:
                raise BackupError(f"Geschützte Datei weicht ab: {entry['path']}")
        return files, None
    files = {}
    for arc in (KEYRING, ENV):
        if (extracted / arc).is_file():
            files[arc] = (extracted / arc).read_bytes()
    return files, None


def _check_secrets(manifest: dict[str, Any], extracted: Path, passphrase: str, env_secret_keys: str) -> dict:
    files, warning = _secret_files(manifest, extracted, passphrase)
    state_path = extracted / INTEGRATIONS
    tokens = []
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for integration_id, values in (state.get("config") or {}).items():
            for key, value in (values or {}).items():
                if secret_box.is_sealed(value):
                    tokens.append((f"integrations/{integration_id}/{key}", value))
    result: dict[str, Any] = {"sealed_values": len(tokens), "decrypted": 0, "warning": warning}
    if not tokens or warning:
        return result
    keys = secret_box.keys_from_bytes(files[KEYRING]) if KEYRING in files else []
    env_text = files.get(ENV, b"").decode("utf-8", "replace")
    for line in env_text.splitlines():
        name, _, value = line.strip().partition("=")
        if name.strip() == "SECRET_KEYS":
            keys += secret_box.parse_env_keys(value.strip().strip('"').strip("'"))
    if not keys and env_secret_keys:
        keys = secret_box.parse_env_keys(env_secret_keys)
        result["warning"] = "Schlüssel nur aus der Umgebung (SECRET_KEYS), nicht aus dem Backup geprüft."
    for context, token in tokens:
        secret_box.open_with(keys, token, context)
        result["decrypted"] += 1
    return result


# --- restore probe ------------------------------------------------------------------------

def restore_probe(archive: Path | None = None, sources: Sources | None = None,
                  heartbeat: Callable[[], None] | None = None, passphrase: str | None = None) -> dict[str, Any]:
    """Restore into an isolated directory, check it, delete it; returns the logged event."""
    sources = sources or Sources.from_settings()
    started = time.monotonic()
    try:
        with _Lock(sources.root):
            event = _probe(archive, sources, _Pulse(heartbeat),
                           sources.passphrase if passphrase is None else passphrase)
    except Exception as exc:
        _record_failure(sources.root, {"event": "restore_probe", "ok": False, "error": _message(exc),
                                       "archive": archive.name if archive else None,
                                       "duration_s": round(time.monotonic() - started, 1)})
        raise
    event["duration_s"] = round(time.monotonic() - started, 1)
    return record_event(sources.root, event)


def _probe(archive: Path | None, sources: Sources, pulse: _Pulse, passphrase: str) -> dict[str, Any]:
    if archive is None:
        archives = list_archives(sources.root)
        if not archives:
            raise BackupError("Keine Vollsicherung vorhanden; zuerst eine Sicherung anlegen.")
        archive = archives[0].path
    report = verify_archive(archive, expected_sha256=_recorded_digest(sources.root, archive.name), pulse=pulse)
    if not report["ok"]:
        raise BackupError("Archivprüfung fehlgeschlagen: " + "; ".join(report["problems"][:5]))
    probe_dir = sources.root / f".probe-{secrets.token_hex(4)}"
    probe_dir.mkdir()
    checks: dict[str, Any] = {"archive_verified": True}
    warnings: list[str] = []
    try:
        manifest = _extract(archive, probe_dir, pulse)
        checks["files_restored"] = len(manifest["files"])
        database = manifest["database"]
        head = _code_head()
        if database["dialect"] == "sqlite":
            db_path = probe_dir / DB_SQLITE
            facts = _sqlite_facts(db_path, full_check=True)
            if facts["integrity"] != "ok":
                raise BackupError(f"Integritätsprüfung der Datenbank: {facts['integrity']}")
            _compare(facts, database)
            from .sqlite_backup import verify_archived_originals

            checks["archived_originals"] = verify_archived_originals(db_path)
            if facts["revision"] != head:
                from ..db.schema_state import run_migrations

                run_migrations(f"sqlite:///{db_path.resolve().as_posix()}")
                checks["upgrade_to_head_tested"] = True
                warnings.append(f"Sicherung auf Revision {facts['revision']}, Programm auf {head}: nach einer "
                                "Wiederherstellung ist python -m backend.upgrade nötig (in der Probe erfolgreich).")
        else:
            checks.update(_probe_postgres(probe_dir / DB_POSTGRES, database, sources, head, warnings))
        checks["revision"] = database["revision"]
        checks["row_counts_match"] = True
        checks["rows"] = sum(database["row_counts"].values())
        checks["uploads"] = manifest["uploads"]["files"]
        secrets_check = _check_secrets(manifest, probe_dir, passphrase, sources.env_secret_keys)
        checks["secrets"] = secrets_check
        if secrets_check.get("warning"):
            warnings.append(secrets_check["warning"])
        missing = manifest["secrets"].get("missing_key_ids") or []
        if missing:
            warnings.append(f"Schlüssel nicht im Backup enthalten: {', '.join(missing)}")
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    checks["probe_dir_removed"] = not probe_dir.exists()
    return {"event": "restore_probe", "ok": True, "archive": archive.name, "sha256": report["sha256"],
            "checks": checks, "warnings": warnings}


def _compare(facts: dict[str, Any], database: dict[str, Any]) -> None:
    if facts["revision"] != database["revision"]:
        raise BackupError(f"Revision weicht ab: {facts['revision']} statt {database['revision']}")
    expected, actual = database["row_counts"], facts["row_counts"]
    different = sorted(table for table in set(expected) | set(actual) if expected.get(table) != actual.get(table))
    if different:
        raise BackupError(f"Zeilenzahlen weichen ab: {different[:5]}")


def _probe_postgres(dump: Path, database: dict[str, Any], sources: Sources, head: str | None,
                    warnings: list[str]) -> dict[str, Any]:
    tool = _pg_tool("pg_restore", sources.pg_bin_dir)
    listing = _run([tool, "--list", str(dump)])
    checks: dict[str, Any] = {"dump_entries": sum(1 for line in listing.splitlines() if line and line[0] != ";")}
    if not sources.probe_postgres_url:
        warnings.append("PostgreSQL: Dump lesbar (pg_restore --list); vollständige Probe benötigt "
                        "RESTORE_PROBE_POSTGRES_URL (ein Wegwerf-Server).")
        checks["full_restore"] = False
        return checks
    admin_url = make_url(sources.probe_postgres_url)
    name = f"immo_restore_probe_{secrets.token_hex(6)}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target_url = admin_url.set(database=name).render_as_string(hide_password=False)
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        conninfo, env = _libpq(target_url)
        _run([tool, "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", conninfo, str(dump)], env)
        engine = create_engine(target_url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                tables = _pg_tables(connection)
                counts = {table: connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                          for table in tables}
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar() \
                    if "alembic_version" in tables else None
                if set(tables) >= {"document_versions", "document_version_chunks"}:
                    from .document_version_validation import verify_document_versions

                    checks["archived_originals"] = verify_document_versions(connection)
        finally:
            engine.dispose()
        _compare({"revision": revision, "row_counts": counts}, database)
        if revision != head:
            warnings.append(f"Sicherung auf Revision {revision}, Programm auf {head}: nach einer Wiederherstellung "
                            "ist python -m backend.upgrade nötig.")
        checks["full_restore"] = True
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()
    return checks


# --- restore (into a new directory, never over live data) ---------------------------------

def restore_archive(path: Path, target: Path, *, passphrase: str = "", pg_target_url: str = "") -> dict[str, Any]:
    """Verify, then lay the archive out as a fresh data directory (plus pg_restore when asked)."""
    report = verify_archive(path)
    if not report["ok"]:
        raise BackupError("Archivprüfung fehlgeschlagen: " + "; ".join(report["problems"][:5]))
    if target.exists() and any(target.iterdir()):
        raise BackupError(f"Zielverzeichnis ist nicht leer: {target}")
    staging = target.parent / f".{target.name}.restore-{secrets.token_hex(4)}"
    staging.mkdir(parents=True)
    try:
        manifest = _extract(path, staging, _Pulse(None))
        files, warning = _secret_files(manifest, staging, passphrase)
        if warning:
            raise BackupError("Schlüsselsicherung ist mit Passphrase geschützt: Passphrase angeben "
                              "(--passphrase-env).")
        target.mkdir(parents=True, exist_ok=True)
        database = manifest["database"]
        steps = []
        if database["dialect"] == "sqlite":
            os.replace(staging / DB_SQLITE, target / "immo_manager.db")
        else:
            os.replace(staging / DB_POSTGRES, target / "postgres.dump")
            if pg_target_url:
                _pg_restore_into(target / "postgres.dump", pg_target_url)
                steps.append("PostgreSQL-Dump in die Zieldatenbank eingespielt.")
            else:
                steps.append("PostgreSQL: pg_restore --no-owner --dbname <leere Zieldatenbank> postgres.dump")
        if (staging / "uploads").is_dir():
            os.replace(staging / "uploads", target / "uploads")
        if (staging / INTEGRATIONS).is_file():
            os.replace(staging / INTEGRATIONS, target / "integrations.json")
        if (staging / JOURNAL).is_file():
            os.replace(staging / JOURNAL, target / "integrations.json.history.sqlite3")
        if KEYRING in files:
            secret_box.write_private_file(target / "secrets" / "keyring.json", files[KEYRING])
        if ENV in files:
            secret_box.write_private_file(target / ".env.from-backup", files[ENV])
            secret_box.write_private_file(target / ".env", _relocated_env(files[ENV], database["dialect"]))
            steps.append(".env übernommen ohne Pfadangaben (DATA_DIR usw. werden neu gesetzt); Original in "
                         ".env.from-backup.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    steps.append(f"Programm stoppen, DATA_DIR auf {target} zeigen lassen (oder Verzeichnis tauschen), dann "
                 "python -m backend.upgrade und starten.")
    return {"restored_to": str(target), "revision": database["revision"], "dialect": database["dialect"],
            "uploads": manifest["uploads"]["files"], "steps": steps}


def _relocated_env(raw: bytes, dialect: str) -> bytes:
    drop = set(_PATH_KEYS) | ({"DATABASE_URL"} if dialect == "sqlite" else set())
    lines = [line for line in raw.decode("utf-8", "replace").splitlines()
             if line.strip().partition("=")[0].strip() not in drop]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _pg_restore_into(dump: Path, database_url: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            if _pg_tables(connection):
                raise BackupError("Zieldatenbank ist nicht leer; Wiederherstellung nur in eine leere Datenbank.")
    finally:
        engine.dispose()
    conninfo, env = _libpq(database_url)
    _run([_pg_tool("pg_restore", settings.pg_bin_dir), "--no-owner", "--no-privileges", "--exit-on-error",
          "--dbname", conninfo, str(dump)], env)


# --- overview -----------------------------------------------------------------------------

def _latest(events: list[dict[str, Any]], kind: str, ok: bool | None = None) -> dict[str, Any] | None:
    return next((event for event in events if event.get("event") == kind and (ok is None or event.get("ok") is ok)),
                None)


def _age_hours(event: dict[str, Any] | None, now: datetime) -> float | None:
    if not event or not event.get("at"):
        return None
    try:
        return (now - datetime.fromisoformat(event["at"])).total_seconds() / 3600
    except ValueError:
        return None


def overview(sources: Sources | None = None, *, secret_status: dict[str, Any] | None = None,
             schema: dict[str, Any] | None = None, jobs: list[dict[str, Any]] | None = None,
             now: datetime | None = None) -> dict[str, Any]:
    sources = sources or Sources.from_settings()
    now = now or _utcnow()
    events = read_events(sources.root)
    archives = list_archives(sources.root)
    second = list_archives(sources.second_target) if sources.second_target else []
    second_names = {item.name for item in second}
    archive_rows = []
    for item in archives:
        try:
            size = item.path.stat().st_size
        except OSError:
            continue
        archive_rows.append({"name": item.name, "created_at": item.created_at.isoformat(timespec="seconds"),
                             "trigger": item.trigger, "size_bytes": size, "sha256": _read_sidecar(item.path),
                             "on_second_target": item.name in second_names})
    last_backup, last_ok_backup = _latest(events, "backup"), _latest(events, "backup", True)
    last_probe, last_ok_probe = _latest(events, "restore_probe"), _latest(events, "restore_probe", True)
    warnings: list[dict[str, Any]] = []
    if not settings.backup_schedule_enabled:
        warnings.append({"code": "schedule_disabled"})
    if sources.second_target is None:
        warnings.append({"code": "no_second_target"})
    elif last_ok_backup and not (last_ok_backup.get("second_target") or {}).get("ok"):
        warnings.append({"code": "second_target_failed"})
    age = _age_hours(last_ok_backup, now)
    if age is None:
        warnings.append({"code": "no_backup"})
    elif age > 36:
        warnings.append({"code": "backup_stale", "hours": round(age)})
    if last_backup and not last_backup.get("ok"):
        warnings.append({"code": "last_backup_failed", "error": last_backup.get("error")})
    probe_age = _age_hours(last_ok_probe, now)
    if probe_age is None:
        warnings.append({"code": "no_probe"})
    elif probe_age > 24 * 35:
        warnings.append({"code": "probe_stale", "days": round(probe_age / 24)})
    if last_probe and not last_probe.get("ok"):
        warnings.append({"code": "last_probe_failed", "error": last_probe.get("error")})
    if not sources.passphrase:
        warnings.append({"code": "keys_unprotected"})
    if last_ok_backup and last_ok_backup.get("missing_key_ids"):
        warnings.append({"code": "keys_not_in_backup", "ids": last_ok_backup["missing_key_ids"]})
    if secret_status:
        if secret_status.get("plaintext"):
            warnings.append({"code": "plaintext_secrets", "count": secret_status["plaintext"]})
        if secret_status.get("error"):
            warnings.append({"code": "secrets_error", "error": secret_status["error"]})
    if schema and schema.get("state") != "current":
        warnings.append({"code": "schema_not_current", "state": schema.get("state")})
    failures = [event for event in events if event.get("ok") is False][:20]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "schema": schema,
        "database": {"dialect": sources.dialect},
        "backup": {
            "enabled": settings.backup_schedule_enabled,
            "schedule": {"daily_at": settings.backup_daily_at, "timezone": BERLIN.key},
            "directory": str(sources.root),
            "second_target": str(sources.second_target) if sources.second_target else None,
            "retention": {"daily": sources.keep_daily, "monthly": sources.keep_monthly,
                          "pre_upgrade": sources.keep_pre_upgrade},
            "passphrase_protected": bool(sources.passphrase),
            "last": last_backup, "last_success": last_ok_backup,
            "archives": archive_rows, "total_size_bytes": sum(row["size_bytes"] for row in archive_rows),
            "second_target_archives": len(second),
        },
        "restore_probe": {
            "schedule": {"day": settings.restore_probe_day, "at": settings.restore_probe_at, "timezone": BERLIN.key},
            "last": last_probe, "last_success": last_ok_probe,
        },
        "secrets": secret_status,
        "jobs": jobs or [],
        "failures": failures,
        "warnings": warnings,
    }
