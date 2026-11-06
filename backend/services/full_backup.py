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
import importlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import time
import unicodedata
import zipfile
from collections.abc import Callable, Iterator
from contextlib import closing
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
from .filesystem_paths import filesystem_path
from .sqlite_backup import file_url, readonly_uri

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

FORMAT = "immomanager-full-backup"
FORMAT_VERSION = 1
LOG_NAME = "ops-log.jsonl"
_NAME = re.compile(r"^immomanager-full-(\d{8}T\d{6})Z-([a-z-]+)-([0-9a-f]{4,16})\.zip$")
_CHUNK = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_EXPANDED_BYTES = 1024 ** 4  # 1 TiB; reject before allocating/extracting declared payloads
_STORED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".zip", ".gz", ".7z", ".docx", ".xlsx",
                    ".pptx", ".odt", ".ods", ".mp4", ".mov", ".dump"}
# Paths in .env that point at the old installation; dropped when restoring elsewhere.
_PATH_KEYS = ("DATA_DIR", "UPLOADS_DIR", "BACKUP_DIR", "LOG_FILE", "INTEGRATION_STATE_FILE", "SECRET_KEY_FILE")
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
    runtime_manifest: dict | None = None
    runtime_bytes: bytes | None = None
    file_storage: Any = None
    plugin_dirs: list[str] = field(default_factory=list)

    @classmethod
    def from_settings(cls) -> Sources:
        data_dir = get_data_dir()
        state = settings.integration_state_file or str(data_dir / "integrations.json")
        second, _ = configured_second_target(data_dir)
        from .file_storage import get_file_storage
        from .portable_runtime import capture
        runtime_manifest, runtime_bytes = capture(settings)
        return cls(
            database_url=settings.database_url, data_dir=data_dir, uploads_dir=get_uploads_dir(),
            root=get_backup_dir() / "full", integration_state=Path(state).expanduser(),
            key_file=secret_box.default_key_file(), env_file=data_dir / ".env",
            second_target=Path(second).expanduser() if second else None, passphrase=settings.backup_passphrase,
            keep_daily=settings.backup_keep_daily, keep_monthly=settings.backup_keep_monthly,
            keep_pre_upgrade=settings.backup_keep_pre_upgrade, pg_bin_dir=settings.pg_bin_dir,
            probe_postgres_url=settings.restore_probe_postgres_url, env_secret_keys=settings.secret_keys,
            runtime_manifest={**runtime_manifest, "status": "sealed" if settings.backup_passphrase else "passphrase_required"},
            runtime_bytes=runtime_bytes if settings.backup_passphrase else None, file_storage=get_file_storage(),
            plugin_dirs=settings.plugin_dirs,
        )

    @property
    def dialect(self) -> str:
        return make_url(self.database_url).get_backend_name()

    @property
    def journal(self) -> Path:
        return self.integration_state.with_suffix(self.integration_state.suffix + ".history.sqlite3")


# --- second target set in the app ---------------------------------------------------------
# BACKUP_SECOND_TARGET (environment or .env) wins. Without it, the owner sets the folder under
# Einstellungen → Betrieb; it is kept in the data folder, not in the archives, because it names
# a drive of this computer.

TARGET_FILE = "backup-settings.json"


def configured_second_target(data_dir: Path | None = None) -> tuple[str, str | None]:
    """The second target and where it is set: ("…", "env"), ("…", "app") or ("", None)."""
    from_env = settings.backup_second_target.strip()
    if from_env:
        return from_env, "env"
    path = filesystem_path((data_dir or get_data_dir()) / TARGET_FILE)
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("second_target")
    except FileNotFoundError:
        return "", None
    except (OSError, ValueError, AttributeError):
        logger.warning("Ignoring the unreadable backup settings in %s", path, exc_info=True)
        return "", None
    value = value.strip() if isinstance(value, str) else ""
    return (value, "app") if value else ("", None)


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _same_device(a: Path, b: Path) -> bool | None:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return None


def set_second_target(raw: str, data_dir: Path | None = None, backup_root: Path | None = None) -> dict[str, Any]:
    """Check and keep the folder every full backup is copied to; an empty value removes it.

    Raises ValueError with a sentence for the user; nothing is kept then.
    """
    data_dir = data_dir or get_data_dir()
    backup_root = backup_root or get_backup_dir() / "full"
    if settings.backup_second_target.strip():
        raise ValueError("Das zweite Ziel ist in der Konfiguration festgelegt (BACKUP_SECOND_TARGET) "
                         "und lässt sich hier nicht ändern.")
    text = (raw or "").strip()
    # "Als Pfad kopieren" in the Windows Explorer puts the path in quotes
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    settings_file = data_dir / TARGET_FILE
    if not text:
        settings_file.unlink(missing_ok=True)
        return {"second_target": None, "source": None, "same_device": None}
    if len(text) > 500 or "\0" in text:
        raise ValueError("Der Pfad ist zu lang oder enthält ungültige Zeichen.")
    target = Path(text).expanduser()
    if not target.is_absolute():
        raise ValueError("Bitte den vollständigen Pfad angeben, z. B. E:\\ImmoManager-Sicherung "
                         "oder \\\\NAS\\Sicherung.")
    resolved = target.resolve(strict=False)
    if _inside(resolved, data_dir.resolve()):
        raise ValueError("Das zweite Ziel liegt im Datenordner des Programms. Es muss außerhalb liegen, "
                         "am besten auf einem anderen Laufwerk.")
    if _inside(resolved, backup_root.resolve()):
        raise ValueError("Das zweite Ziel ist der Sicherungsordner selbst. Bitte einen anderen Ordner wählen.")
    if _inside(resolved, get_uploads_dir().resolve()):
        # every later backup would carry the earlier archives along with the attachments
        raise ValueError("Das zweite Ziel liegt im Ordner der Anhänge. Bitte einen anderen Ordner wählen.")
    if target.exists() and not target.is_dir():
        raise ValueError("Unter diesem Pfad liegt eine Datei, kein Ordner.")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Der Ordner lässt sich nicht anlegen: {exc.strerror or exc}. "
                         "Ist das Laufwerk angeschlossen?") from None
    probe = target / f".immomanager-schreibtest-{secrets.token_hex(4)}"
    try:
        with probe.open("wb") as handle:
            handle.write(b"ok")
            handle.flush()
            os.fsync(handle.fileno())
        if probe.read_bytes() != b"ok":
            raise OSError("Inhalt weicht ab")
    except OSError as exc:
        raise ValueError(f"In den Ordner lässt sich nicht schreiben: {exc.strerror or exc}.") from None
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove the write test %s", probe)
    data_dir.mkdir(parents=True, exist_ok=True)
    temporary = settings_file.with_name(settings_file.name + ".partial")
    temporary.write_text(json.dumps({"second_target": str(target), "set_at": _utcnow().isoformat(timespec="seconds")},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, settings_file)
    return {"second_target": str(target), "source": "app", "same_device": _same_device(target, data_dir),
            "archives": len(list_archives(target))}


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
    with filesystem_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
            if pulse:
                pulse.beat()
    return digest.hexdigest()


def _fsync(path: Path) -> None:
    with filesystem_path(path).open("rb+") as handle:
        os.fsync(handle.fileno())


def _write_sidecar(archive: Path, digest: str) -> None:
    sidecar = filesystem_path(archive.with_name(archive.name + ".sha256"))
    secret_box.write_private_file(sidecar, f"{digest}  {archive.name}\n".encode("utf-8"))


def _read_sidecar(archive: Path) -> str | None:
    sidecar = filesystem_path(archive.with_name(archive.name + ".sha256"))
    try:
        with sidecar.open("rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            return ""
        digest = raw.decode("utf-8").split()[0].lower()
        return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else ""
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError):
        return ""


def _safe_member(name: str) -> bool:
    if not isinstance(name, str) or not name or any(ord(character) < 32 for character in name):
        return False
    path = PurePosixPath(name)
    if str(path) != name or "\\" in name or path.is_absolute() or not path.parts:
        return False
    for part in path.parts:
        if part in {".", ".."} or ":" in part or part.endswith((".", " ")):
            return False
        if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".", 1)[0], re.I):
            return False
    return True


def _sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if not url.database or url.database == ":memory:":
        raise BackupError("Die SQLite-Datenbank liegt nur im Arbeitsspeicher; kein Vollbackup möglich.")
    return Path(url.database)


def sqlite_online_copy(source: Path, target: Path) -> None:
    """Consistent copy of a live (WAL) SQLite file; never creates a missing source."""
    source, target = filesystem_path(source), filesystem_path(target)
    if not source.is_file():
        raise BackupError(f"Datenbankdatei nicht gefunden: {source}")
    src = sqlite3.connect(readonly_uri(source), uri=True, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _sqlite_facts(path: Path, *, full_check: bool) -> dict[str, Any]:
    connection = sqlite3.connect(readonly_uri(path), uri=True)
    try:
        check = connection.execute("PRAGMA integrity_check" if full_check else "PRAGMA quick_check").fetchone()[0]
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # table names come from sqlite_master of the backup itself and are quoted (bandit B608 reviewed)
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}  # nosec B608
        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None
        from .bank_backup import key_ids
        from .communication_backup import needed_key_ids as communication_key_ids
        return {"integrity": check, "row_counts": counts, "revision": revision,
                "bank_key_ids": key_ids(connection, tables),
                "communication_key_ids": communication_key_ids(connection, tables)}
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
    # URL.set treats None as "leave unchanged"; explicitly replace this field
    # so credentials never appear in pg_dump/pg_restore command-line arguments.
    plain = url.set(drivername="postgresql")._replace(password=None)
    return plain.render_as_string(hide_password=False), env


def _run(command: list[str], env: dict[str, str] | None = None, timeout: float = 6 * 3600) -> str:
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, env=env, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-800:]
        raise BackupError(f"{Path(command[0]).name} fehlgeschlagen: {tail}")
    return result.stdout


def _pg_tables(connection) -> list[str]:
    return sorted(inspect(connection).get_table_names())


def _pg_dump(sources: Sources, target: Path, private_keys: list[secret_box.Key] | None = None) -> dict[str, Any]:
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
                from .communication_backup import needed_key_ids as communication_key_ids
                communication_keys = communication_key_ids(connection, tables)
                server = connection.execute(text("SHOW server_version")).scalar()
                from .bank_backup import key_ids
                bank_keys = key_ids(connection, tables)

                from .tax_archive_validation import needed_key_ids
                tax_keys = sorted(needed_key_ids(connection))
                from .portable_runtime import inventory
                references, database_key_ids = inventory(connection)
                from .assistant_backup import inventory as assistant_inventory
                try:
                    assistant_snapshot = assistant_inventory(connection, private_keys or [])
                    references.update(assistant_snapshot["references"])
                except Exception:
                    raise BackupError("Geschützte KI-Quellen konnten im Datenbanksnapshot nicht vollständig geprüft werden.") from None
                _run([tool, "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}",
                      f"--file={target}", "--dbname", conninfo], env)
    finally:
        engine.dispose()
    return {"integrity": "pg_dump ok", "row_counts": counts, "revision": revision, "server_version": server,
            "bank_key_ids": bank_keys, "tax_needed_key_ids": tax_keys, "communication_key_ids": communication_keys,
            "references": references, "key_ids": database_key_ids, "assistant_originals": assistant_snapshot["originals"]}


class _Lock:
    """Kernel-owned lifetime; a long backup never expires and crash releases it."""

    _HEADER = b"IMMO-BACKUP-LOCK-2\n"

    def __init__(self, root: Path):
        self.path = filesystem_path(root / ".lock")
        self.fd: int | None = None

    @staticmethod
    def _change(fd: int, *, release: bool = False) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            module = importlib.import_module("msvcrt")
            getattr(module, "locking")(fd, getattr(module, "LK_UNLCK" if release else "LK_NBLCK"), 1)
        else:
            module = importlib.import_module("fcntl")
            mode = getattr(module, "LOCK_UN") if release else getattr(module, "LOCK_EX") | getattr(module, "LOCK_NB")
            getattr(module, "flock")(fd, mode)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BackupError("Die Sicherungssperre ist keine eigene reguläre Datei")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise BackupError("Die Sicherungssperre gehört einem anderen Benutzer")
            os.set_inheritable(fd, False)
            self._change(fd)
            raw = os.read(fd, 4096)
            if raw and not raw.startswith(self._HEADER):
                # A PID/hostname is not proof of ownership across namespaces or
                # machines. Legacy/unknown markers require explicit inspection.
                raise BackupError("Eine ältere Sicherungssperre benötigt Prüfung; sie wird nicht durch Zeitablauf entfernt")
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, self._HEADER + f"{socket.gethostname()}:{os.getpid()}\n".encode("utf-8"))
            os.fsync(fd)
            self.fd = fd
            return self
        except BackupError:
            os.close(fd)
            raise
        except OSError:
            os.close(fd)
            raise BackupError("Eine andere Sicherung oder Wiederherstellungsprobe läuft, oder die Sperre ist nicht zugänglich.") from None
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                self._change(self.fd, release=True)
            finally:
                os.close(self.fd)
                self.fd = None


# --- ops log ------------------------------------------------------------------------------

def record_event(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    root = filesystem_path(root)
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
    root = filesystem_path(root)
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
    directory = filesystem_path(directory)
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
    return f"immomanager-full-{now.strftime('%Y%m%dT%H%M%S')}Z-{trigger}-{secrets.token_hex(8)}.zip"


# --- writing ------------------------------------------------------------------------------

@dataclass
class _Writer:
    zf: zipfile.ZipFile
    pulse: _Pulse
    files: list[dict[str, Any]] = field(default_factory=list)

    def add_file(self, source: Path, arcname: str, kind: str) -> None:
        source = filesystem_path(source)
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
    directory = filesystem_path(directory)
    if not directory.is_dir():
        return
    for current, dirs, files in os.walk(directory, followlinks=False):
        if any((Path(current) / name).is_symlink() for name in dirs):
            raise BackupError("Symbolischer Anhangordner kann nicht vollständig gesichert werden")
        dirs.sort()
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                raise BackupError("Anhang ist keine reguläre Datei und wurde nicht gesichert")
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
    filesystem_path(sources.root).mkdir(parents=True, exist_ok=True)
    work = filesystem_path(sources.root / f".work-{secrets.token_hex(4)}")
    filesystem_path(work).mkdir(mode=0o700)
    name = _archive_name(trigger, now)
    final = filesystem_path(sources.root / name)
    partial = filesystem_path(sources.root / (name + ".partial"))
    partial_created = False
    try:
        if final.exists():
            raise BackupError("Der neue Archivname ist bereits belegt")
        # These exact bytes both decrypt the snapshot inventory and enter the
        # archive. Never use an ambient/default keyring for private AI sources.
        key_file, env_file = filesystem_path(sources.key_file), filesystem_path(sources.env_file)
        keyring_bytes = key_file.read_bytes() if key_file.is_file() else None
        env_bytes = env_file.read_bytes() if env_file.is_file() else None
        from .portable_runtime import RUNTIME
        runtime_bytes = sources.runtime_bytes
        if sources.env_secret_keys:
            runtime = json.loads(runtime_bytes) if runtime_bytes else {}
            runtime["secret_keys"] = ",".join(value for value in (runtime.get("secret_keys", ""), sources.env_secret_keys) if value)
            runtime_bytes = json.dumps(runtime, ensure_ascii=False).encode("utf-8")
        captured_secrets = {name: raw for name, raw in ((KEYRING, keyring_bytes), (ENV, env_bytes), (RUNTIME, runtime_bytes)) if raw is not None}
        private_keys = _archived_connection_keys(captured_secrets)
        from .assistant_backup import VAULT_PREFIX, capture_vaults
        try:
            vault_files, vault_keys = capture_vaults(sources.uploads_dir, private_keys)
        except Exception:
            raise BackupError("Geschützte KI-Kontozugänge konnten mit den gesicherten Schlüsseln nicht geprüft werden.") from None
        if dialect == "sqlite":
            db_copy = work / "db.sqlite3"
            sqlite_online_copy(_sqlite_path(sources.database_url), db_copy)
            facts = _sqlite_facts(db_copy, full_check=False)
            if facts["integrity"] != "ok":
                raise BackupError(f"Datenbank-Prüfung fehlgeschlagen: {facts['integrity']}")
            db_entry = DB_SQLITE
        else:
            db_copy = work / "postgres.dump"
            facts = _pg_dump(sources, db_copy, private_keys)
            db_entry = DB_POSTGRES
        pulse.beat()

        journal_copy = None
        if filesystem_path(sources.journal).is_file():
            journal_copy = work / "journal.sqlite3"
            sqlite_online_copy(sources.journal, journal_copy)
        state_file = filesystem_path(sources.integration_state)
        state_bytes = state_file.read_bytes() if state_file.is_file() else None

        from .backup_extensions import extensions
        from .portable_runtime import RUNTIME, inventory
        references, database_keys = inventory(db_copy) if dialect == "sqlite" else (facts["references"], facts["key_ids"])
        if dialect == "sqlite":
            from .assistant_backup import inventory as assistant_inventory
            try:
                assistant_snapshot = assistant_inventory(db_copy, private_keys)
                references.update(assistant_snapshot["references"])
            except Exception:
                raise BackupError("Geschützte KI-Quellen konnten im Datenbanksnapshot nicht vollständig geprüft werden.") from None
            assistant_originals = assistant_snapshot["originals"]
        else:
            assistant_originals = facts["assistant_originals"]

        needed = sorted(set(_needed_key_ids(state_bytes)) | set(facts.get('bank_key_ids', [])) | set(facts.get('communication_key_ids', [])))
        if dialect == "sqlite":
            from .tax_archive_validation import needed_key_ids
            tax_engine = create_engine(file_url(db_copy), poolclass=NullPool)
            try:
                with tax_engine.connect() as connection:
                    needed = sorted(set(needed) | needed_key_ids(connection))
            finally:
                tax_engine.dispose()
        else:
            needed = sorted(set(needed) | set(facts.get("tax_needed_key_ids", [])))
        needed = sorted(set(needed) | set(database_keys) | vault_keys)
        included_ids = {key.id for key in private_keys}
        included = sorted(included_ids)
        missing = sorted(set(needed) - included_ids)
        if missing:
            raise BackupError("Vollsicherung unvollständig: benötigte Entschlüsselungsschlüssel fehlen")
        from .plugin_packages import inventory as plugin_inventory
        packages = plugin_inventory(sources.plugin_dirs)

        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        partial_created = True
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            writer = _Writer(zf, pulse)
            writer.add_file(db_copy, db_entry, "database")
            for declaration, package_files in packages:
                for relative, path in package_files:
                    writer.add_file(path, "plugins/" + declaration["name"] + "/" + relative, "plugin")
            upload_count = upload_bytes = 0
            uploaded = set()
            for path, arcname in _iter_uploads(sources.uploads_dir):
                if arcname[len("uploads/"):].startswith(VAULT_PREFIX):
                    # Snapshot the credential envelope once; never archive a
                    # concurrent login's replacement or transient .tmp file.
                    continue
                # Selected remote storage is authoritative for referenced remote originals.
                from .file_storage import S3Storage
                if isinstance(sources.file_storage, S3Storage) and arcname[len("uploads/"):] in references:
                    continue
                writer.add_file(path, arcname, "upload")
                uploaded.add(arcname[len("uploads/"):])
                upload_count += 1
                upload_bytes += writer.files[-1]["size"]
            for key, raw in vault_files.items():
                writer.add_bytes(raw, "uploads/" + key, "upload")
                uploaded.add(key)
                upload_count += 1
                upload_bytes += len(raw)
            for key in sorted(references - uploaded):
                if sources.file_storage is None:
                    raise BackupError("Vollsicherung unvollständig: referenziertes Original fehlt")
                content = sources.file_storage.get(key)
                if content is None:
                    raise BackupError("Vollsicherung unvollständig: referenziertes Original fehlt")
                writer.add_bytes(content, "uploads/" + key, "upload")
                upload_count += 1
                upload_bytes += len(content)
            written = {entry["path"]: entry for entry in writer.files}
            for key, expected in assistant_originals.items():
                original = written.get("uploads/" + key)
                if original is None or original["sha256"] != expected["sha256"] or original["size"] != expected["byte_length"]:
                    raise BackupError("KI-Anhangoriginal fehlt oder wurde verändert; die Vollsicherung wurde nicht veröffentlicht.")
            if state_bytes is not None:
                writer.add_bytes(state_bytes, INTEGRATIONS, "config")
            if journal_copy is not None:
                writer.add_file(journal_copy, JOURNAL, "config")
            protected: list[dict[str, Any]] = []
            plain = {KEYRING: keyring_bytes, ENV: env_bytes}
            if runtime_bytes:
                if not sources.passphrase:
                    raise BackupError("Portabler Runtime-Export benötigt eine Backup-Passphrase")
                plain[RUNTIME] = runtime_bytes
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
                "runtime": sources.runtime_manifest,
                "attachments": {"checked": True, "references": sorted(references)},
                "extensions": {ext.name: ext.version for ext in extensions()},
                "plugin_packages": [declaration for declaration, _ in packages],
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
        if partial_created:
            partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(filesystem_path(work), ignore_errors=True)

    event: dict[str, Any] = {
        "event": "backup", "ok": True, "trigger": trigger, "archive": name, "size": final.stat().st_size,
        "sha256": digest, "revision": facts["revision"], "dialect": dialect, "uploads": upload_count,
        "secrets_protection": "passphrase" if sources.passphrase else "none", "missing_key_ids": missing,
        "readiness": "portable_data" if sources.runtime_bytes and dialect == "sqlite" else "archive_verified",
        "self_contained_runtime": bool(sources.runtime_bytes),
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
    archive, directory = filesystem_path(archive), filesystem_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / (archive.name + ".partial")
    created = False
    try:
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as target, archive.open("rb") as source:
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
        if created:
            partial.unlink(missing_ok=True)


# --- verification -------------------------------------------------------------------------

def _recorded_digest(root: Path, name: str) -> str | None:
    for event in read_events(root, limit=2000):
        if event.get("event") == "backup" and event.get("archive") == name and event.get("sha256"):
            return str(event["sha256"])
    return None


def _hash_stream(handle, pulse: _Pulse) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(_CHUNK), b""):
        digest.update(chunk)
        pulse.beat()
    return digest.hexdigest()


def _validated_manifest(zf: zipfile.ZipFile) -> tuple[dict[str, Any], dict[str, dict]]:
    """Validate the envelope before reading any declared backup payload."""
    from .portable_runtime import RUNTIME
    infos = zf.infolist()
    if not 1 <= len(infos) <= _MAX_ARCHIVE_MEMBERS:
        raise BackupError("Zu viele oder keine Archiveinträge")
    names = [info.filename for info in infos]
    aliases = [unicodedata.normalize("NFC", name).casefold() for name in names]
    if len(names) != len(set(names)) or len(aliases) != len(set(aliases)):
        raise BackupError("Doppelte oder auf anderen Betriebssystemen gleiche Archivpfade")
    all_names = set(names)
    for info in infos:
        if not _safe_member(info.filename) or info.is_dir():
            raise BackupError("Unsicherer oder nicht portabler Archivpfad")
        if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
            raise BackupError("Nur reguläre Dateien sind im Archiv erlaubt")
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BackupError("Nicht unterstützte ZIP-Verschlüsselung oder Kompression")
        if any(str(parent) in all_names for parent in PurePosixPath(info.filename).parents if str(parent) != "."):
            raise BackupError("Ein Archivpfad überschattet ein Verzeichnis")
    if sum(info.file_size for info in infos) > _MAX_EXPANDED_BYTES:
        raise BackupError("Die entpackte Sicherung überschreitet das Größenlimit von 1 TiB")
    try:
        metadata = zf.getinfo("manifest.json")
    except KeyError:
        raise BackupError("Manifest fehlt") from None
    if metadata.file_size > _MAX_MANIFEST_BYTES:
        raise BackupError("Das Manifest überschreitet das Größenlimit von 16 MiB")
    manifest = json.loads(zf.read("manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("Kein gültiges Vollbackup von ImmoManager Pro")
    version = manifest.get("format_version")
    if type(version) is not int or version != FORMAT_VERSION:
        raise BackupError("Unbekannte oder ungültige Version des Backupformats")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) > _MAX_ARCHIVE_MEMBERS - 1:
        raise BackupError("Ungültige Dateiliste im Manifest")
    allowed = {DB_SQLITE, DB_POSTGRES, INTEGRATIONS, JOURNAL, KEYRING, ENV, SEALED, RUNTIME}
    entries: dict[str, dict] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise BackupError("Ungültiger Dateieintrag im Manifest")
        name, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
        if not isinstance(name, str) or not _safe_member(name) or name in entries:
            raise BackupError("Ungültiger oder doppelter Manifestpfad")
        if name not in allowed and not name.startswith(("uploads/", "plugins/")):
            raise BackupError("Nicht unterstützter Restore-Pfad im Manifest")
        if type(size) is not int or not 0 <= size <= _MAX_EXPANDED_BYTES:
            raise BackupError("Ungültige Dateigröße im Manifest")
        if name in {INTEGRATIONS, KEYRING, ENV, SEALED, RUNTIME} and size > _MAX_CONFIG_BYTES:
            raise BackupError("Eine Konfigurations- oder Schlüsseldatei überschreitet 16 MiB")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError("Ungültige Dateiprüfsumme im Manifest")
        if name not in all_names or zf.getinfo(name).file_size != size:
            raise BackupError("ZIP-Dateigröße oder Dateiliste weicht vom Manifest ab")
        entries[name] = entry
    if all_names != set(entries) | {"manifest.json"}:
        raise BackupError("Nicht im Manifest aufgeführte Dateien")
    database, uploads, protected = manifest.get("database"), manifest.get("uploads"), manifest.get("secrets")
    if not isinstance(database, dict) or not isinstance(uploads, dict) or not isinstance(protected, dict):
        raise BackupError("Ungültige Datenbank-, Anhang- oder Geheimnismetadaten")
    dialect = database.get("dialect")
    database_path = {"sqlite": DB_SQLITE, "postgresql": DB_POSTGRES}.get(dialect) if isinstance(dialect, str) else None
    if database_path is None or database.get("path") != database_path or database_path not in entries:
        raise BackupError("Datenbank fehlt oder verwendet ein unbekanntes Format")
    if {DB_SQLITE, DB_POSTGRES} & set(entries) != {database_path}:
        raise BackupError("Widersprüchliche Datenbankdateien im Archiv")
    counts = database.get("row_counts")
    if not isinstance(counts, dict) or any(not isinstance(key, str) or type(value) is not int or value < 0
                                           for key, value in counts.items()):
        raise BackupError("Ungültige Datenbankzählwerte")
    if any(type(uploads.get(name)) is not int or uploads[name] < 0 for name in ("files", "bytes")):
        raise BackupError("Ungültige Anhangszählwerte")
    if protected.get("protection") not in {"none", "passphrase"} or not isinstance(protected.get("protected_files"), list):
        raise BackupError("Ungültiger Schutzstatus im Manifest")
    for item in protected["protected_files"]:
        if (not isinstance(item, dict) or item.get("path") not in {KEYRING, ENV, RUNTIME}
                or type(item.get("size")) is not int or not 0 <= item["size"] <= _MAX_CONFIG_BYTES
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise BackupError("Ungültiger geschützter Dateieintrag")
    return manifest, entries


def verify_archive(path: Path, *, expected_sha256: str | None = None, pulse: _Pulse | None = None) -> dict[str, Any]:
    """Hash and ZIP parsing use the same descriptor; invalid envelopes fail closed."""
    path = filesystem_path(path)
    pulse = pulse or _Pulse(None)
    problems: list[str] = []
    manifest: dict[str, Any] = {}
    digest = None
    try:
        with path.open("rb") as raw:
            digest = _hash_stream(raw, pulse)
            sidecar = _read_sidecar(path)
            if sidecar is not None and sidecar != digest:
                raise BackupError("SHA-256 des Archivs stimmt nicht mit der .sha256-Datei überein")
            if expected_sha256 is not None and expected_sha256 != digest:
                raise BackupError("SHA-256 des Archivs weicht vom protokollierten Wert ab")
            raw.seek(0)
            with zipfile.ZipFile(raw) as zf:
                manifest, entries = _validated_manifest(zf)
                for name, entry in entries.items():
                    file_digest, size = hashlib.sha256(), 0
                    with zf.open(name) as handle:
                        for chunk in iter(lambda: handle.read(_CHUNK), b""):
                            size += len(chunk)
                            if size > entry["size"]:
                                raise BackupError("Datei überschreitet ihre geprüfte Größe")
                            file_digest.update(chunk)
                            pulse.beat()
                    if file_digest.hexdigest() != entry["sha256"] or size != entry["size"]:
                        raise BackupError("Prüfsumme oder Größe einer Datei stimmt nicht")
    except BackupError as exc:
        problems.append(str(exc))
    except Exception as exc:
        problems.append("Archiv nicht lesbar: " + type(exc).__name__)
    return {"ok": not problems, "problems": problems, "archive": path.name, "sha256": digest,
            "files": len(manifest.get("files", [])), "manifest": _manifest_summary(manifest)}


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    database = manifest.get("database", {})
    if not isinstance(database, dict):
        database = {}
    return {"created_at": manifest.get("created_at"), "trigger": manifest.get("trigger"),
            "app_version": manifest.get("app_version"), "alembic_head": manifest.get("alembic_head"),
            "revision": database.get("revision"), "dialect": database.get("dialect"),
            "uploads": manifest.get("uploads"), "secrets": manifest.get("secrets")}


def _extract(path: Path, target: Path, pulse: _Pulse, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Only validated portable entries; source stays open from hash to extraction."""
    with filesystem_path(path).open("rb") as raw:
        if expected_sha256 is not None:
            if _hash_stream(raw, pulse) != expected_sha256:
                raise BackupError("Das Archiv wurde nach der Prüfung verändert")
            raw.seek(0)
        with zipfile.ZipFile(raw) as zf:
            manifest, entries = _validated_manifest(zf)
            if sum(entry["size"] for entry in entries.values()) + 16 * 1024 * 1024 > shutil.disk_usage(filesystem_path(target)).free:
                raise BackupError("Zu wenig freier Speicher für die geprüfte Wiederherstellung")
            for name, entry in entries.items():
                destination = target.joinpath(*PurePosixPath(name).parts)
                if not destination.resolve().is_relative_to(target.resolve()):
                    raise BackupError("Pfad außerhalb des Zielverzeichnisses")
                destination = filesystem_path(destination)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                count, digest = 0, hashlib.sha256()
                with os.fdopen(fd, "wb") as out, zf.open(name) as source:
                    for chunk in iter(lambda: source.read(_CHUNK), b""):
                        count += len(chunk)
                        if count > entry["size"]:
                            raise BackupError("Extraktion überschreitet die geprüfte Dateigröße")
                        out.write(chunk)
                        digest.update(chunk)
                        pulse.beat()
                    out.flush()
                    os.fsync(out.fileno())
                if count != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupError("Wiederhergestellte Datei weicht vom Manifest ab")
    return manifest


def _secret_files(manifest: dict[str, Any], extracted: Path, passphrase: str) -> tuple[dict[str, bytes], str | None]:
    """Key file and .env of the archive (decrypted with the passphrase); (files, warning)."""
    extracted = filesystem_path(extracted)
    if manifest["secrets"]["protection"] == "passphrase":
        sealed = extracted / SEALED
        if not sealed.is_file():
            if manifest["secrets"].get("protected_files"):
                raise BackupError("Geschütztes Geheimnisbundle fehlt")
            return {}, None
        if not passphrase:
            return {}, "Schlüsselsicherung ist mit Passphrase geschützt; ohne Passphrase nicht geprüft."
        bundle = json.loads(secret_box.open_with_passphrase(sealed.read_bytes(), passphrase))
        from .portable_runtime import RUNTIME
        if not isinstance(bundle, dict) or set(bundle) - {KEYRING, ENV, RUNTIME} or any(not isinstance(value, str) for value in bundle.values()):
            raise BackupError("Unbekannte Datei im Geheimnisbundle")
        files = {arc: base64.b64decode(data, validate=True) for arc, data in bundle.items()}
        for entry in manifest["secrets"]["protected_files"]:
            raw = files.get(entry["path"], b"")
            if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise BackupError(f"Geschützte Datei weicht ab: {entry['path']}")
        return files, None
    from .portable_runtime import RUNTIME

    files = {}
    for arc in (KEYRING, ENV, RUNTIME):
        if (extracted / arc).is_file():
            files[arc] = (extracted / arc).read_bytes()
    return files, None


def _check_secrets(manifest: dict[str, Any], extracted: Path, passphrase: str, env_secret_keys: str,
                   extra_key_ids=()) -> dict:
    extracted = filesystem_path(extracted)
    files, warning = _secret_files(manifest, extracted, passphrase)
    state_path = extracted / INTEGRATIONS
    tokens = []
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for integration_id, values in (state.get("config") or {}).items():
            for key, value in (values or {}).items():
                if secret_box.is_sealed(value):
                    tokens.append((f"integrations/{integration_id}/{key}", value))
    bank_path = extracted / DB_SQLITE
    if bank_path.is_file():
        from .bank_backup import tokens as bank_tokens
        with closing(sqlite3.connect(readonly_uri(bank_path), uri=True)) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            tokens.extend(bank_tokens(connection, tables))
    result: dict[str, Any] = {"sealed_values": len(tokens), "decrypted": 0, "warning": warning}
    communication_database = extracted / DB_SQLITE
    if warning:
        return result
    keys = secret_box.keys_from_bytes(files[KEYRING]) if KEYRING in files else []
    from .portable_runtime import RUNTIME
    if RUNTIME in files:
        keys += secret_box.parse_env_keys(json.loads(files[RUNTIME]).get("secret_keys", ""))
    env_text = files.get(ENV, b"").decode("utf-8", "replace")
    for line in env_text.splitlines():
        name, _, value = line.strip().partition("=")
        if name.strip() == "SECRET_KEYS":
            keys += secret_box.parse_env_keys(value.strip().strip('"').strip("'"))
    missing = (set(manifest["secrets"].get("needed_key_ids", [])) | set(extra_key_ids)) - {key.id for key in keys}
    if missing:
        raise BackupError("Benötigte Entschlüsselungsschlüssel fehlen im Archiv")
    for context, token in tokens:
        secret_box.open_with(keys, token, context)
        result["decrypted"] += 1
    if bank_path.is_file():
        from .bank_backup import verify as verify_bank
        with closing(sqlite3.connect(readonly_uri(bank_path), uri=True)) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result['bank_originals'] = verify_bank(connection, tables, keys)

    if manifest.get("database", {}).get("dialect") == "sqlite":
        from .tax_archive_validation import verify_tax_archive
        database_path = extracted / manifest["database"]["path"]
        engine = create_engine(file_url(database_path), poolclass=NullPool)
        try:
            with engine.connect() as tax_connection:
                result["tax_receipts_verified"] = verify_tax_archive(tax_connection,
                    lambda token, context: secret_box.open_with(keys, token, context))
        finally:
            engine.dispose()

    if communication_database.is_file():
        from .communication_backup import verify
        connection = sqlite3.connect(readonly_uri(communication_database), uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result["communication"] = verify(connection, keys, tables)
        finally:
            connection.close()
    return result


def _archived_connection_keys(files: dict[str, bytes]) -> list[secret_box.Key]:
    """Only keys actually bundled in the archive, never ambient process secrets."""
    keys = secret_box.keys_from_bytes(files[KEYRING]) if KEYRING in files else []
    from .portable_runtime import RUNTIME
    if RUNTIME in files:
        keys.extend(secret_box.parse_env_keys(json.loads(files[RUNTIME]).get("secret_keys", "")))
    for line in files.get(ENV, b"").decode("utf-8", "replace").splitlines():
        field, _, value = line.strip().partition("=")
        if field.strip() == "SECRET_KEYS":
            keys.extend(secret_box.parse_env_keys(value.strip().strip('"').strip("'")))
    return keys


def _assistant_vault_proof(uploads: Path, keys: list[secret_box.Key]) -> dict:
    from .assistant_backup import capture_vaults
    try:
        files, identifiers = capture_vaults(uploads, keys)
        return {"verified": len(files), "key_ids": sorted(identifiers)}
    except Exception:
        raise BackupError("Geschützte KI-Kontozugänge konnten mit den archivierten Schlüsseln nicht geprüft werden.") from None


def _restored_pg_attachments(connection, uploads: Path, keys: list[secret_box.Key]) -> dict:
    from .assistant_backup import references as assistant_references
    from .file_storage import validate_key
    from .portable_runtime import inventory
    references, key_ids = inventory(connection)
    references.update(assistant_references(connection, keys))
    for key in references:
        if not filesystem_path(uploads / validate_key(key)).is_file():
            raise BackupError("Referenziertes Original fehlt im Archiv")
    return {"checked": True, "references": len(references), "key_ids": sorted(key_ids)}


def _private_connection_proof(connection, keys: list[secret_box.Key], *, normalize: bool = False,
                              uploads_dir: Path | None = None) -> dict:
    """Verify all saved connection evidence before publishing an offline restore.

    A recovery transition is performed in the CALLER'S fresh-target transaction.
    It never calls auth, the runtime keyring, integrations or provider transports.
    """
    from .integrations.connection_archive import (
        ConnectionArchiveError,
        mark_restored_connections_unconfirmed,
        verify_connection_state,
    )

    try:
        if normalize:
            recovered = mark_restored_connections_unconfirmed(connection, keys)
        else:
            recovered = 0
        proof = verify_connection_state(connection, keys)
    except ConnectionArchiveError:
        # No private ciphertext, source values or driver parameters in user logs.
        raise BackupError("Geschützte Verbindungsnachweise konnten nicht vollständig geprüft werden.") from None
    from .bank_backup import tokens as bank_tokens
    from .bank_backup import verify as verify_bank
    from .tax_archive_validation import verify_tax_archive
    tables = set(inspect(connection).get_table_names())
    for context, token in bank_tokens(connection, tables):
        secret_box.open_with(keys, token, context)
    bank_proof = verify_bank(connection, tables, keys)
    tax_proof = verify_tax_archive(connection, lambda token, context: secret_box.open_with(keys, token, context))
    from .communication_backup import verify as verify_communication
    communication_proof = verify_communication(connection, keys, tables)
    # TEHA snapshots and publication receipts are private, immutable evidence.
    # Verify them with *archived* keys before the restored data is published.
    from types import SimpleNamespace

    from .teha_restore import verify_teha_restore

    try:
        teha_proof = verify_teha_restore(connection, SimpleNamespace(
            open=lambda token, context: secret_box.open_with(keys, token, context)))
    except Exception:
        raise BackupError("Geschützte TEHA-Quellen und Originalnachweise konnten nicht vollständig geprüft werden.") from None
    from .channel_restore import verify_channel_restore

    try:
        channel_proof = verify_channel_restore(connection, SimpleNamespace(
            open=lambda token, context: secret_box.open_with(keys, token, context)))
    except Exception:
        raise BackupError("Geschützte Kanalquellen und Originalnachweise konnten nicht vollständig geprüft werden.") from None
    from .assistant_backup import verify as verify_assistant
    try:
        assistant_proof = verify_assistant(connection, keys, uploads=uploads_dir, normalize=normalize)
        # Public checks contain counts, never private file locators or key material.
        assistant_proof.pop("references", None)
        assistant_proof.pop("originals", None)
        assistant_proof["vault_key_ids"] = sorted(assistant_proof["vault_key_ids"])
    except Exception:
        raise BackupError("Geschützte KI-Gespräche, Anhänge und Kontozugänge konnten nicht vollständig geprüft werden.") from None
    from .data_transfer.backup import verify as verify_data_transfer
    from .e_invoice.backup import verify as verify_e_invoices
    from .external_portal.backup import verify as verify_portal
    from .payment_security_backup import verify as verify_payment_security
    from .privacy.backup import verify as verify_privacy
    try:
        e_invoice_proof = verify_e_invoices(connection)
        payment_proof = verify_payment_security(connection)
        data_transfer_proof = verify_data_transfer(connection)
        portal_proof = verify_portal(connection, normalize=normalize)
        privacy_proof = verify_privacy(connection, normalize=normalize)
    except Exception:
        raise BackupError("E-Rechnungsoriginale, Zuordnungen und Prüfnachweise konnten nicht vollständig geprüft werden.") from None
    return {
        "e_invoices": e_invoice_proof,
        "payment_security": payment_proof,
        "data_transfer": data_transfer_proof,
        "external_portal": portal_proof,
        "privacy": privacy_proof,
        "assistant": assistant_proof,
        "channels": channel_proof,
        "teha": teha_proof,
        "communication": communication_proof,
        "bank_originals": bank_proof, "tax_receipts_verified": tax_proof,
        "present": proof["present"], "verified_rows": proof["rows"],
        "verified_result_bytes": proof["verified_result_bytes"],
        "legacy_id_only_records": proof["legacy_id_only_records"],
        "restored_unconfirmed": recovered,
    }


def _sqlite_private_connections(path: Path, keys: list[secret_box.Key], *, normalize: bool = False,
                                uploads_dir: Path | None = None) -> dict:
    from sqlalchemy.pool import NullPool

    if normalize:
        engine = create_engine(file_url(path), poolclass=NullPool)
    else:
        # Probe the extracted copy read-only: even a benign SQL transaction
        # must not rewrite the archived evidence before its verification.
        uri = readonly_uri(path)
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True), poolclass=NullPool)
    try:
        if normalize:
            with engine.begin() as connection:
                return _private_connection_proof(connection, keys, normalize=True, uploads_dir=uploads_dir)
        with engine.connect() as connection:
            return _private_connection_proof(connection, keys, uploads_dir=uploads_dir)
    finally:
        engine.dispose()


def _check_attachments(manifest: dict, extracted: Path) -> dict:
    extracted = filesystem_path(extracted)
    from .backup_extensions import extensions
    from .file_storage import validate_key
    from .portable_runtime import inventory
    declared = manifest.get("extensions", {})
    registered = {extension.name: extension for extension in extensions()}
    from .plugin_packages import package
    for declaration in manifest.get("plugin_packages", []):
        name = validate_key(declaration["name"])
        if "/" in name:
            raise BackupError("Ungültiger Pluginpaketname im Archiv")
        actual, _ = package(extracted / "plugins" / name)
        if actual != declaration:
            raise BackupError("Pluginpaket stimmt nicht mit dem Archivmanifest überein")
    for name, version in declared.items():
        if name not in registered or registered[name].version != version:
            raise BackupError("Benötigte Backup-Erweiterung fehlt oder ist inkompatibel: " + name)
    references = set(manifest.get("attachments", {}).get("references", []))
    key_ids: set[str] = set()
    if manifest["database"]["dialect"] == "sqlite":
        current, key_ids = inventory(extracted / DB_SQLITE)
        references.update(current)
    for key in references:
        path = filesystem_path(extracted / "uploads" / validate_key(key))
        if not path.is_file():
            raise BackupError("Referenziertes Original fehlt im Archiv")
    for extension in registered.values():
        if extension.name in declared:
            extension.validate(extracted / manifest["database"]["path"], extracted)
    return {"checked": manifest["database"]["dialect"] == "sqlite", "references": len(references),
            "key_ids": sorted(key_ids)}


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
    probe_dir = filesystem_path(sources.root / f".probe-{secrets.token_hex(4)}")
    probe_dir.mkdir(mode=0o700)
    checks: dict[str, Any] = {"archive_verified": True}
    warnings: list[str] = []
    try:
        manifest = _extract(archive, probe_dir, pulse, expected_sha256=report["sha256"])
        checks["files_restored"] = len(manifest["files"])
        checks["attachments"] = _check_attachments(manifest, probe_dir)
        database = manifest["database"]
        secret_files, secret_warning = _secret_files(manifest, probe_dir, passphrase)
        # A warning can remain for unrelated runtime secrets, but private SQL
        # evidence MUST decrypt using the keys actually archived here.
        private_keys = _archived_connection_keys(secret_files) if not secret_warning else []
        checks["assistant_vaults"] = _assistant_vault_proof(probe_dir / "uploads", private_keys)
        head = _code_head()
        if database["dialect"] == "sqlite":
            db_path = probe_dir / DB_SQLITE
            facts = _sqlite_facts(db_path, full_check=True)
            if facts["integrity"] != "ok":
                raise BackupError(f"Integritätsprüfung der Datenbank: {facts['integrity']}")
            _compare(facts, database)
            from .sqlite_backup import verify_archived_originals

            checks["archived_originals"] = verify_archived_originals(db_path)
            checks["private_connections"] = _sqlite_private_connections(db_path, private_keys, uploads_dir=probe_dir / "uploads")
            if facts["revision"] != head:
                from ..db.schema_state import run_migrations

                run_migrations(file_url(db_path))
                checks["upgrade_to_head_tested"] = True
                warnings.append(f"Sicherung auf Revision {facts['revision']}, Programm auf {head}: nach einer "
                                "Wiederherstellung ist python -m backend.upgrade nötig (in der Probe erfolgreich).")
        else:
            checks.update(_probe_postgres(probe_dir / DB_POSTGRES, database, sources, head, warnings, private_keys))
        checks["revision"] = database["revision"]
        checks["row_counts_match"] = True
        checks["rows"] = sum(database["row_counts"].values())
        checks["uploads"] = manifest["uploads"]["files"]
        secrets_check = _check_secrets(manifest, probe_dir, passphrase, "", checks["attachments"]["key_ids"])
        checks["secrets"] = secrets_check
        if secrets_check.get("warning"):
            warnings.append(secrets_check["warning"])
        missing = manifest["secrets"].get("missing_key_ids") or []
        if missing:
            warnings.append(f"Schlüssel nicht im Backup enthalten: {', '.join(missing)}")
    finally:
        shutil.rmtree(filesystem_path(probe_dir), ignore_errors=True)
    checks["probe_dir_removed"] = not probe_dir.exists()
    runtime_ready = not manifest.get("runtime") or manifest["runtime"].get("status") != "passphrase_required"
    ready = not missing and not secrets_check.get("warning") and checks["attachments"]["checked"] and runtime_ready
    if not runtime_ready:
        warnings.append("Effektive Runtime-Konfiguration fehlt: Backup-Passphrase für portablen Export einrichten.")
    return {"event": "restore_probe", "ok": ready,
            "readiness": "data_verified" if ready else "archive_only",
            "application_gate": "not_run", "archive": archive.name, "sha256": report["sha256"],
            "checks": checks, "warnings": warnings}


def _compare(facts: dict[str, Any], database: dict[str, Any]) -> None:
    if facts["revision"] != database["revision"]:
        raise BackupError(f"Revision weicht ab: {facts['revision']} statt {database['revision']}")
    expected, actual = database["row_counts"], facts["row_counts"]
    different = sorted(table for table in set(expected) | set(actual) if expected.get(table) != actual.get(table))
    if different:
        raise BackupError(f"Zeilenzahlen weichen ab: {different[:5]}")


def _probe_postgres(dump: Path, database: dict[str, Any], sources: Sources, head: str | None,
                    warnings: list[str], private_keys: list[secret_box.Key]) -> dict[str, Any]:
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
                restored_uploads = dump.parent.parent / "uploads"
                checks["private_connections"] = _private_connection_proof(connection, private_keys, uploads_dir=restored_uploads)
                checks['communication'] = checks['private_connections']['communication']
                checks['communication_verified'] = True
                # A readable pg_dump does not prove that its referenced files
                # survived extraction. Rebuild the inventory from the restored
                # native database, using the same rules as SQLite and backup.
                checks['attachments'] = _restored_pg_attachments(connection, restored_uploads, private_keys)
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
    if target.is_symlink():
        raise BackupError("Das Restore-Ziel darf kein symbolischer Link sein")
    target = filesystem_path(target.resolve())
    final_target = target
    report = verify_archive(path)
    if not report["ok"]:
        raise BackupError("Archivprüfung fehlgeschlagen: " + "; ".join(report["problems"][:5]))
    if target.exists() and any(target.iterdir()):
        raise BackupError(f"Zielverzeichnis ist nicht leer: {target}")
    staging = target.parent / f".{target.name}.restore-{secrets.token_hex(4)}"
    filesystem_path(staging).mkdir(mode=0o700, parents=True)
    try:
        manifest = _extract(path, staging, _Pulse(None), expected_sha256=report["sha256"])
        files, warning = _secret_files(manifest, staging, passphrase)
        if warning:
            raise BackupError("Schlüsselsicherung ist mit Passphrase geschützt: Passphrase angeben "
                              "(--passphrase-env).")
        archived_keys = _archived_connection_keys(files)
        _assistant_vault_proof(staging / "uploads", archived_keys)
        attachments = _check_attachments(manifest, staging)
        secret_check = _check_secrets(manifest, staging, passphrase, "", attachments["key_ids"])
        if secret_check.get("warning") or manifest["secrets"].get("missing_key_ids"):
            raise BackupError("Geheimnisse sind nicht unabhängig wiederherstellbar")
        target = staging / "installation"
        target.mkdir(parents=True, exist_ok=True)
        database = manifest["database"]
        steps = []
        restored_sessions_closed = None
        if database["dialect"] == "sqlite":
            from ..db.schema_state import NEWER, inspect_sqlite_file
            restored_database = staging / DB_SQLITE
            facts = _sqlite_facts(restored_database, full_check=True)
            if facts["integrity"] != "ok":
                raise BackupError("Die wiederhergestellte Datenbank besteht die Integritätsprüfung nicht")
            _compare(facts, database)
            status, application_tables = inspect_sqlite_file(restored_database)
            if not application_tables:
                raise BackupError("Die Sicherung enthält keine ImmoManager-Datenbank")
            if status.state == NEWER:
                raise BackupError("Die Sicherung stammt aus einer neueren Programmversion; zuerst das passende Programm installieren")
            private = _sqlite_private_connections(staging / DB_SQLITE, archived_keys, normalize=True, uploads_dir=staging / "uploads")
            from . import auth_epoch
            try:
                with closing(sqlite3.connect(filesystem_path(restored_database))) as restored_connection, restored_connection:
                    restored_sessions_closed = auth_epoch.close_restored_sessions(restored_connection)
            except auth_epoch.EpochUnavailable:
                raise BackupError("Wiederhergestellte Sitzungen konnten nicht sicher beendet werden") from None
            steps.append(f"Geschützte Verbindungen vor Publikation geprüft ({private['verified_rows']} Datensätze); "
                         f"{private['restored_unconfirmed']} unterbrochene Vorgänge gesperrt.")
            os.replace(staging / DB_SQLITE, target / "immo_manager.db")
        else:
            os.replace(staging / DB_POSTGRES, target / "postgres.dump")
            if pg_target_url:
                _pg_restore_into(target / "postgres.dump", pg_target_url)
                from sqlalchemy.pool import NullPool
                verify_engine = create_engine(pg_target_url, poolclass=NullPool)
                try:
                    with verify_engine.begin() as connection:
                        private = _private_connection_proof(connection, archived_keys, normalize=True, uploads_dir=staging / "uploads")
                        attachments = _restored_pg_attachments(connection, staging / "uploads", archived_keys)
                    steps.append(f"Geschützte PostgreSQL-Verbindungen geprüft ({private['verified_rows']} Datensätze); "
                                 f"{private['restored_unconfirmed']} unterbrochene Vorgänge gesperrt.")
                finally:
                    verify_engine.dispose()
                steps.append("PostgreSQL-Dump in die Zieldatenbank eingespielt.")
            else:
                steps.append("PostgreSQL: pg_restore --no-owner --dbname <leere Zieldatenbank> postgres.dump")
        if (staging / "uploads").is_dir():
            os.replace(staging / "uploads", target / "uploads")
        if (staging / "plugins").is_dir():
            os.replace(staging / "plugins", target / "plugins")
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
        from .portable_runtime import RUNTIME, relocated
        if RUNTIME in files:
            secret_box.write_private_file(target / ".env", relocated(files[RUNTIME]))
            if manifest.get("plugin_packages"):
                with (target / ".env").open("a", encoding="utf-8") as env_handle:
                    env_handle.write("PLUGIN_DIRS=" + json.dumps(json.dumps([str(final_target / "plugins")])) + "\n")
            secret_box.write_private_file(target / "runtime.from-backup.json", files[RUNTIME])
        if manifest.get("runtime"):
            (target / "runtime-manifest.json").write_text(json.dumps(manifest["runtime"], indent=2), encoding="utf-8")
        # Always fence a restored installation, even a PostgreSQL dump which the
        # operator loads later. Each restore has a new epoch, so an older completed
        # review cannot reopen search/AI/portal access.
        restored_env = target / ".env"
        lines = restored_env.read_text(encoding="utf-8").splitlines() if restored_env.exists() else []
        lines = [line for line in lines if line.strip().partition("=")[0].strip() != "PRIVACY_RESTORE_ID"]
        lines.append("PRIVACY_RESTORE_ID=" + secrets.token_hex(24))
        secret_box.write_private_file(restored_env, ("\n".join(lines) + "\n").encode())
        from . import auth_epoch
        try:
            auth_epoch.rotate_for_restore(target)
        except auth_epoch.EpochUnavailable:
            raise BackupError("Eine neue private Sitzungsgrenze konnte nicht angelegt werden; das Ziel wird nicht freigegeben") from None
        steps.append("Alle alten Anmelde- und Erneuerungstoken sind im neuen Datenprofil ungültig. Nach dem Start erneut anmelden.")
        steps.append("Vor Freigabe von Portal, Suche und KI: aktuelles Datenschutzjournal importieren, Löschungen/Sperren abgleichen und die Wiederherstellungsprüfung in Einstellungen → Datenschutz bestätigen.")
        if final_target.exists():
            final_target.rmdir()  # only the previously empty target; refuses a concurrent new file
        os.replace(filesystem_path(target), filesystem_path(final_target))
    except OSError as exc:
        raise BackupError("Wiederherstellung wegen eines Dateisystemfehlers abgebrochen; das neue Ziel wurde nicht freigegeben.") from exc
    finally:
        shutil.rmtree(filesystem_path(staging), ignore_errors=True)
    target = final_target
    steps.append(f"Programm stoppen, DATA_DIR auf {target} zeigen lassen (oder Verzeichnis tauschen), dann "
                 "python -m backend.upgrade und starten.")
    return {"restored_to": str(target), "revision": database["revision"], "dialect": database["dialect"],
            "readiness": "data_verified" if attachments["checked"] else "archive_only",
            "application_gate": "not_run",
            "sessions": {"generation": "renewed", "restored_sessions_closed": restored_sessions_closed},
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
    _run([_pg_tool("pg_restore", settings.pg_bin_dir), "--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction",
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
    _, target_source = configured_second_target(sources.data_dir)
    same_device = None
    if sources.second_target is None:
        warnings.append({"code": "no_second_target"})
    else:
        copy = (last_ok_backup or {}).get("second_target")
        if last_ok_backup and copy and copy.get("path") == str(sources.second_target) and not copy.get("ok"):
            warnings.append({"code": "second_target_failed", "error": copy.get("error")})
        elif last_ok_backup and not (copy and copy.get("path") == str(sources.second_target)):
            # the newest backup was made before this target was set
            warnings.append({"code": "second_target_pending"})
        same_device = _same_device(sources.second_target, sources.data_dir)
        if same_device:
            warnings.append({"code": "second_target_same_device"})
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
        warnings.append({"code": "keys_unprotected", "file": str(sources.env_file)})
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
            "second_target_source": target_source if sources.second_target else None,
            "second_target_same_device": same_device,
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
