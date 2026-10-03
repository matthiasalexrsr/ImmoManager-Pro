"""Encrypted, offline application + PostgreSQL backup for compose.private-server.yml.

Run on the Docker host (Windows Docker Desktop or POSIX/WSL), never through HTTP.
The four fixed ZIP members are authenticated together using the application's
AES-GCM/PBKDF2 envelope. Plaintext exists only in an exclusively owned private
workspace: mode 0700 on POSIX, verified SID/System/Administrators ACL on Windows.
No shell command is constructed on the host and no password is accepted in argv.

backup --project EXISTING --destination NEW_FILE [--password-stdin]
restore --project NEW --source FILE [--env-output NEW_FILE] [--password-stdin]

A restore retains its new project and protected environment file on failure for
inspection. It never removes volumes or replaces an existing installation. Stop
the original app before restoring with the same port; backup resumes it only if
it was running. The environment includes database/JWT secrets: keep the encrypted
package and its passphrase separately. Restoring an older package also restores
older users, TOTP credentials and the permanent first-owner marker.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator, NoReturn
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ocr_configuration import OCR_DEFAULTS, OCR_PATH_KEYS, validate_ocr_environment  # noqa: E402
from backend.services.recovery_archive import (  # noqa: E402
    HEADER_SIZE,
    MAGIC,
    check_zip_budget,
    encrypted_zip,
)

CHUNK = 1024 * 1024
MEMBERS = ("database.dump", "appdata.tar.gz", "server.env", "manifest.json")
REQUIRED_ENV_KEYS = frozenset({"APP_ORIGIN", "APP_HOST", "APP_HTTP_PORT", "POSTGRES_USER",
                      "POSTGRES_DB", "POSTGRES_PASSWORD", "JWT_SECRET_KEY"})
ENCRYPTION_ENV_KEYS = frozenset({"ENCRYPTION_KEY", "ENCRYPTION_KEYRING", "ENCRYPTION_ACTIVE_KEY_ID",
                                 "ENCRYPTION_INDEX_KEY", "ENCRYPTION_LEGACY_JWT_KEYS"})
DRAFT_ENV_KEYS = frozenset({"FORM_DRAFT_TTL_DAYS", "FORM_DRAFT_MAX_BYTES"})
CONTRACT_WORKSPACE_ENV_KEYS = frozenset({"CONTRACT_WORKSPACE_PAGE_MAX_SIZE", "CONTRACT_WORKSPACE_SEARCH_MAX_CHARS",
                                            "CONTRACT_CORRESPONDENCE_PAGE_MAX_SIZE",
                                      "CONTRACT_CORRESPONDENCE_PAGE_MAX_SIZE"})
OCR_ENV_KEYS = frozenset(OCR_DEFAULTS)
ENV_KEYS = REQUIRED_ENV_KEYS | ENCRYPTION_ENV_KEYS | DRAFT_ENV_KEYS | CONTRACT_WORKSPACE_ENV_KEYS | OCR_ENV_KEYS | {"OPERATIONAL_SCHEDULER_ACTOR_ID"}
PG_DUMP = 'exec pg_dump -Fc --no-owner --no-acl --no-password -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
PG_LIST = 'exec pg_restore --list'
PG_RESTORE = ('exec pg_restore --exit-on-error --no-owner --no-privileges --no-password '
              '-U "$POSTGRES_USER" -d "$POSTGRES_DB"')
PG_CONNECTIONS = ("exec psql --no-password -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -tAc "
                  "\"SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                  "AND pid<>pg_backend_pid() AND backend_type='client backend'\"")


class BackupError(ValueError):
    """A fixed, non-secret failure suitable for the CLI."""


@dataclass(frozen=True)
class Limits:
    package_bytes: int = 18 * 1024**3
    dump_bytes: int = 8 * 1024**3
    tar_bytes: int = 8 * 1024**3
    expanded_data_bytes: int = 8 * 1024**3
    entries: int = 100_000
    metadata_bytes: int = 16 * 1024**2
    small_bytes: int = 64 * 1024
    command_output_bytes: int = 1024 * 1024
    timeout_seconds: float = 900

    def __post_init__(self):
        for key, value in vars(self).items():
            if key == "timeout_seconds":
                if not math.isfinite(value) or value <= 0:
                    raise BackupError("Ungültiges Zeitlimit.")
            elif type(value) is not int or value <= 0:
                raise BackupError("Ungültige Archivgrenze.")


class Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise BackupError("Zeitlimit überschritten; kein Erfolg bestätigt.")
        return remaining

    def check(self) -> None:
        self.remaining()


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _safe_path(path: Path, *, existing: bool = True, directory: bool = False) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise BackupError("Symlink-/Reparse-Pfade werden nicht unterstützt.")
    if existing:
        if directory and not path.is_dir() or not directory and not path.is_file():
            raise BackupError("Erforderliche Datei oder Verzeichnis fehlt.")
    elif path.exists():
        raise BackupError("Ziel existiert bereits; es wird nichts überschrieben.")
    if not path.parent.is_dir():
        raise BackupError("Zielverzeichnis fehlt.")
    return path


def _acl_command(argv: list[str]) -> bytes:
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=15, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError("Private Windows-Dateiberechtigungen konnten nicht geprüft werden.") from exc
    if result.returncode or len(result.stdout) + len(result.stderr) > 64 * 1024:
        raise BackupError("Private Windows-Dateiberechtigungen konnten nicht eingerichtet werden.")
    return result.stdout


def _windows_sid() -> str:
    output = _acl_command(["whoami", "/user", "/fo", "csv", "/nh"]).decode("utf-8", errors="replace")
    try:
        sid = next(csv.reader(io.StringIO(output)))[1]
    except (IndexError, StopIteration, csv.Error) as exc:
        raise BackupError("Windows-Benutzeridentität konnte nicht geprüft werden.") from exc
    if not re.fullmatch(r"S-1-5-21-(?:\d+-){3}\d+", sid):
        # Domain and local user SIDs share this shape. Refuse service identities:
        # this is an interactive Docker-host administration tool.
        raise BackupError("Nicht unterstützte Windows-Benutzeridentität.")
    return sid


def _verify_sddl(sddl: str, sid: str, *, protected: bool) -> None:
    prefix, separator, entries = sddl.partition("(")
    if not separator or not prefix.startswith("D:") or protected and "P" not in prefix[2:]:
        raise BackupError("Windows-Datei ist nicht ausreichend geschützt.")
    aces = re.findall(r"\(([^()]*)\)", "(" + entries)
    if "(" + entries != "".join("(" + ace + ")" for ace in aces):
        raise BackupError("Windows-Dateiberechtigungen sind nicht prüfbar.")
    allowed = {sid, "SY", "BA", "S-1-5-18", "S-1-5-32-544"}
    seen = set()
    for ace in aces:
        fields = ace.split(";")
        if len(fields) != 6 or fields[0] != "A" or fields[2] not in {"FA", "0x1f01ff"} or fields[5] not in allowed:
            raise BackupError("Windows-Datei ist für weitere Identitäten zugänglich.")
        seen.add(fields[5])
    if sid not in seen:
        raise BackupError("Windows-Datei ist für den aktuellen Benutzer nicht freigegeben.")


def _verify_private(path: Path, workspace: Path, sid: str | None, *, protected: bool = True) -> None:
    if os.name != "nt":
        expected = 0o700 if path.is_dir() else 0o600
        info = path.stat()
        if stat.S_IMODE(info.st_mode) != expected or info.st_uid != getattr(os, "getuid")():
            raise BackupError("Datei benötigt private Eigentümerberechtigungen (0700/0600).")
        return
    if sid is None:
        raise BackupError("Windows-Benutzeridentität fehlt.")
    audit = workspace / ("acl-" + uuid4().hex + ".txt")
    try:
        _acl_command(["icacls", str(path), "/save", str(audit), "/q"])
        text = audit.read_text(encoding="utf-16-le").lstrip("\ufeff")
        lines = text.splitlines()
        if len(lines) != 2:
            raise BackupError("Windows-Dateiberechtigungen sind nicht prüfbar.")
        _verify_sddl(lines[1], sid, protected=protected)
    finally:
        audit.unlink(missing_ok=True)


def _protect(path: Path, workspace: Path, sid: str | None) -> None:
    if os.name == "nt":
        suffix = "(OI)(CI)F" if path.is_dir() else "F"
        _acl_command(["icacls", str(path), "/inheritance:r", "/grant:r",
                      f"*{sid}:{suffix}", f"*S-1-5-18:{suffix}", f"*S-1-5-32-544:{suffix}"])
        # Python 3.13+ mode-0700 creation can add OWNER RIGHTS. Remove it from
        # our own new object so the verified ACL contains only explicit SIDs.
        _acl_command(["icacls", str(path), "/remove:g", "*S-1-3-4"])
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)
    _verify_private(path, workspace, sid)


@contextmanager
def private_workspace(parent: Path | None = None) -> Iterator[tuple[Path, str | None]]:
    base = _safe_path(parent or Path(tempfile.gettempdir()), directory=True)
    path = Path(tempfile.mkdtemp(prefix="immomanager-server-", dir=base))
    owned = path.stat().st_dev, path.stat().st_ino
    try:
        sid = _windows_sid() if os.name == "nt" else None
        _protect(path, path, sid)
        yield path, sid
    finally:
        # Only our exact, non-reparse directory may be removed recursively.
        info = path.lstat()
        if (path.parent == base and path.name.startswith("immomanager-server-")
                and not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400
                and (info.st_dev, info.st_ino) == owned):
            shutil.rmtree(path)
        else:
            raise BackupError("Arbeitsverzeichnis wurde verändert; automatische Bereinigung verweigert.")


@contextmanager
def _new_file(path: Path) -> Iterator[BinaryIO]:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        yield stream
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def protected_new_file(path: Path) -> Iterator[BinaryIO]:
    """Create a NEW file, protect/verify it before accepting any secret bytes.

    Reusable by configure_private_server.py on Windows and POSIX. This changes
    permissions only on the file created by this call and on its own temporary
    directory. Existing files and ancestor directory ACLs are never modified.
    Binary stream: with protected_new_file(path) as output: output.write(data).
    """
    path = _safe_path(path, existing=False)
    with private_workspace() as (workspace, sid):
        owned = None
        try:
            with _new_file(path) as stream:
                info = os.fstat(stream.fileno())
                owned = info.st_dev, info.st_ino
                _protect(path, workspace, sid)
                if (path.stat().st_dev, path.stat().st_ino) != owned:
                    raise BackupError("Neu angelegte Datei wurde vor dem Schreiben ersetzt.")
                yield stream
                _verify_private(path, workspace, sid)
                if (path.stat().st_dev, path.stat().st_ino) != owned:
                    raise BackupError("Neu angelegte Datei wurde beim Schreiben ersetzt.")
        except BaseException:
            if owned is not None and path.exists():
                info = path.lstat()
                if not stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) == owned:
                    path.unlink()
            raise


def _read_file(path: Path, maximum: int, deadline: Deadline) -> bytes:
    path = _safe_path(path)
    with path.open("rb") as stream:
        initial = _identity(os.fstat(stream.fileno()))
        if initial[2] > maximum:
            raise BackupError("Dateigröße überschreitet die Grenze.")
        deadline.check()
        data = stream.read(maximum + 1)
        deadline.check()
        if len(data) > maximum or _identity(os.fstat(stream.fileno())) != initial or _identity(path.stat()) != initial:
            raise BackupError("Datei wurde verändert oder überschreitet die Grenze.")
        return data


def _digest(path: Path, maximum: int, deadline: Deadline) -> dict[str, int | str]:
    path = _safe_path(path)
    hasher, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        initial = _identity(os.fstat(stream.fileno()))
        while block := stream.read(CHUNK):
            deadline.check()
            count += len(block)
            if count > maximum:
                raise BackupError("Dateigröße überschreitet die Grenze.")
            hasher.update(block)
        if _identity(os.fstat(stream.fileno())) != initial or _identity(path.stat()) != initial:
            raise BackupError("Datei wurde während der Prüfung verändert.")
    deadline.check()
    return {"size_bytes": count, "sha256": hasher.hexdigest()}


def _parse_env(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise BackupError("Serverkonfiguration ist kein gültiger UTF-8-Text.") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, equal, value = line.partition("=")
        if (not equal or key not in ENV_KEYS or key in values or (not value and key not in OCR_PATH_KEYS) or any(c in value for c in "\x00$\\")
                or key not in ENCRYPTION_ENV_KEYS and any(c in value for c in "\"'")):
            raise BackupError("Serverkonfiguration enthält unbekannte, doppelte oder unsichere Werte.")
        values[key] = value
    if not REQUIRED_ENV_KEYS <= set(values):
        raise BackupError("Serverkonfiguration ist unvollständig.")
    try:
        origin = urlsplit(values["APP_ORIGIN"])
        port = int(values["APP_HTTP_PORT"])
    except ValueError as exc:
        raise BackupError("Serveradresse ist ungültig.") from exc
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in {"", "/"} or origin.query or origin.fragment
            or origin.hostname.lower() != values["APP_HOST"].lower() or not 1 <= port <= 65535):
        raise BackupError("Serveradresse ist ungültig.")
    if any(not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", values[key]) for key in ("POSTGRES_USER", "POSTGRES_DB")):
        raise BackupError("Nicht unterstützter PostgreSQL-Datenbank-/Benutzername.")
    if any(not re.fullmatch(r"[0-9a-fA-F]{64,256}", values[key]) for key in ("POSTGRES_PASSWORD", "JWT_SECRET_KEY")):
        raise BackupError("Serverkonfiguration benötigt die generierten hexadezimalen Schlüssel.")
    if values.keys() & ENCRYPTION_ENV_KEYS:
        from backend.services.iban_encryption import IBANEncryptionError, keyring_from_configuration
        try:
            keyring_from_configuration(values)
        except IBANEncryptionError:
            raise BackupError("Serverkonfiguration enthält ungültige IBAN-Schlüssel. Schlüsselkonfiguration prüfen.") from None
    for name, minimum, maximum in (("FORM_DRAFT_TTL_DAYS", 1, 365), ("FORM_DRAFT_MAX_BYTES", 1024, 16777216)):
        if name in values:
            try:
                valid = re.fullmatch(r"[0-9]+", values[name]) and minimum <= int(values[name]) <= maximum
            except ValueError:
                valid = False
            if not valid:
                raise BackupError("Serverkonfiguration enthält ungültige Formularentwurfsbudgets. Konfiguration korrigieren.")
    for name in CONTRACT_WORKSPACE_ENV_KEYS & values.keys():
        try:
            valid = re.fullmatch(r"[0-9]+", values[name]) and int(values[name]) > 0
        except ValueError:
            valid = False
        if not valid:
            raise BackupError("Serverkonfiguration enthält ungültige Vertragsarbeitsplatzbudgets. Positive Werte einstellen.")
    try:
        validate_ocr_environment(values)
    except ValueError:
        raise BackupError("Serverkonfiguration enthält ungültige OCR-Einstellungen. Sprache und Budgets korrigieren.") from None
    return values


def _project(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", value):
        raise BackupError("Projektname muss klein geschrieben sein und mindestens zwei Zeichen enthalten.")
    return value


def _compose_digest(path: Path, limits: Limits, deadline: Deadline) -> str:
    # Git's Windows CRLF checkout must remain portable to a Linux/WSL restore.
    return hashlib.sha256(_read_file(path, limits.small_bytes * 4, deadline).replace(b"\r\n", b"\n")).hexdigest()


def _kill_owned_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        # Docker invokes the Compose plugin as a child. Killing just docker.exe
        # could leave that child holding our pipes and continuing an operation.
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


class Docker:
    """Bounded binary subprocesses; stderr is retained privately, never displayed."""

    def __init__(self, compose: Path, env: Path, project: str, workspace: Path, limits: Limits, deadline: Deadline):
        # Snapshot the profile, retaining its original build-context base. An
        # editor changing the original file cannot alter commands mid-operation.
        copied = workspace / "compose-profile.yml"
        profile_data = _read_file(compose, limits.small_bytes * 4, deadline)
        with _new_file(copied) as output:
            output.write(profile_data)
        self.compose_digest = hashlib.sha256(profile_data.replace(b"\r\n", b"\n")).hexdigest()
        self.base = ["docker", "compose", "--project-name", _project(project), "--project-directory", str(compose.parent),
                     "--file", str(copied), "--env-file", str(env)]
        self.workspace, self.limits, self.deadline, self.project = workspace, limits, deadline, project
        self.environment = {k: v for k, v in os.environ.items()
                            if k not in ENV_KEYS and k not in {"COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES",
                                                              "COMPOSE_PROFILES", "COMPOSE_DISABLE_ENV_FILE"}}

    def run(self, args: list[str], *, compose: bool = True, output: Path | None = None,
            input_file: Path | None = None, maximum: int | None = None, stage: str = "Docker-Befehl") -> bytes:
        maximum = maximum or self.limits.command_output_bytes
        argv = self.base + args if compose else ["docker", *args]
        with tempfile.TemporaryFile(dir=self.workspace) as errors, tempfile.TemporaryFile(dir=self.workspace) as capture:
            source = input_file.open("rb") if input_file else None
            target = output.open("xb") if output else capture
            process = None
            readers: list[threading.Thread] = []
            problems: list[str] = []
            def bounded_copy(pipe: BinaryIO, sink: BinaryIO, budget: int) -> None:
                count = 0
                try:
                    while block := pipe.read(min(CHUNK, budget + 1)):
                        count += len(block)
                        if count > budget:
                            problems.append("Ausgabe überschreitet die Grenze")
                            return
                        sink.write(block)
                    sink.flush()
                except Exception:
                    problems.append("Ausgabe konnte nicht vollständig gespeichert werden")
            try:
                process = subprocess.Popen(argv, stdin=source or subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           env=self.environment, shell=False,
                                           start_new_session=os.name != "nt",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                if process.stdout is None or process.stderr is None:
                    raise BackupError(f"{stage}: Prozessausgabe fehlt.")
                for pipe, sink, budget in ((process.stdout, target, maximum),
                                           (process.stderr, errors, self.limits.command_output_bytes)):
                    reader = threading.Thread(target=bounded_copy, args=(pipe, sink, budget), daemon=True)
                    readers.append(reader)
                    reader.start()
                while process.poll() is None or any(reader.is_alive() for reader in readers):
                    self.deadline.check()
                    if problems:
                        raise BackupError(f"{stage}: {problems[0]}.")
                    time.sleep(min(0.05, self.deadline.remaining()))
                self.deadline.check()
                if (process.returncode or problems or os.fstat(target.fileno()).st_size > maximum
                        or os.fstat(errors.fileno()).st_size > self.limits.command_output_bytes):
                    raise BackupError(f"{stage} fehlgeschlagen; kein Erfolg bestätigt.")
                target.flush()
                os.fsync(target.fileno())
                if output:
                    return b""
                capture.seek(0)
                return capture.read(maximum + 1)
            except OSError as exc:
                raise BackupError(f"{stage} konnte nicht ausgeführt werden.") from exc
            finally:
                if process is not None and process.poll() is None:
                    _kill_owned_process(process)
                for reader in readers:
                    reader.join(timeout=2)
                if process is not None:
                    if process.stdout:
                        process.stdout.close()
                    if process.stderr:
                        process.stderr.close()
                if source:
                    source.close()
                if output:
                    target.close()

    def running(self, service: str) -> bool:
        data = self.run(["ps", "--filter", f"label=com.docker.compose.project={self.project}",
                         "--filter", f"label=com.docker.compose.service={service}", "--filter", "status=running",
                         "--format", "{{.ID}}"], compose=False, stage="Containerstatus")
        lines = data.decode("ascii", errors="strict").splitlines()
        if any(not re.fullmatch(r"[a-f0-9]{12,64}", line) for line in lines):
            raise BackupError("Containerstatus ist nicht prüfbar.")
        return bool(lines)

    def require_new_project(self) -> None:
        containers = self.run(["ps", "-a", "--filter", f"label=com.docker.compose.project={self.project}",
                               "--format", "{{.ID}}"], compose=False, stage="Zielprojektprüfung")
        named = self.run(["ps", "-a", "--format", "{{.Names}}"], compose=False, stage="Zielprojektprüfung")
        labelled = self.run(["volume", "ls", "--filter", f"label=com.docker.compose.project={self.project}",
                             "--format", "{{.Name}}"], compose=False, stage="Zielvolumeprüfung")
        volumes = self.run(["volume", "ls", "--format", "{{.Name}}"], compose=False, stage="Zielvolumeprüfung")
        names = (named + b"\n" + volumes).decode("utf-8", errors="strict").splitlines()
        if containers.strip() or labelled.strip() or any(name.startswith((self.project + "_", self.project + "-")) for name in names):
            raise BackupError("Zielprojekt besitzt bereits Container oder Volumes; Wiederherstellung verweigert.")

    def require_private_volumes(self) -> None:
        # Hash equality alone cannot make a custom external/bind volume safe:
        # reject profiles that could restore into another installation's files.
        # Compose interpolation occurs locally; its secret-bearing result stays
        # in our bounded private capture and is never printed to the terminal.
        config = _json(self.run(["config", "--format", "json"], stage="Compose-Datenisolation prüfen"))
        services, volumes = config.get("services"), config.get("volumes")
        if not isinstance(services, dict) or set(services) != {"app", "db"} or not isinstance(volumes, dict) or set(volumes) != {"appdata", "pgdata"}:
            raise BackupError("Compose-Profil benötigt ausschließlich die privaten app/db-Services und Datenvolumes.")
        for key in ("appdata", "pgdata"):
            volume = volumes[key]
            if (not isinstance(volume, dict) or volume.get("name") != self.project + "_" + key
                    or set(volume) - {"name", "labels", "driver"} or volume.get("driver", "local") != "local"):
                raise BackupError("Externe, fremde oder spezielle Datenvolumes werden nicht unterstützt.")
        for service, source, target in (("app", "appdata", "/data"), ("db", "pgdata", "/var/lib/postgresql/data")):
            info = services[service]
            mounts = info.get("volumes") if isinstance(info, dict) else None
            if (not isinstance(mounts, list) or len(mounts) != 1 or not isinstance(mounts[0], dict)
                    or mounts[0].get("type") != "volume" or mounts[0].get("source") != source
                    or mounts[0].get("target") != target):
                raise BackupError("Compose-Profil verwendet fremde/bind-Datenpfade; Vorgang verweigert.")
        if services["app"].get("image", self.project + "-app") != self.project + "-app":
            raise BackupError("Compose-Profil benötigt sein eigenes gebautes Serverimage.")


def _tar_number(field: bytes) -> int:
    # Reject base-256/signed sizes: our bounded profile never needs them.
    value = field.strip(b"\x00 ")
    if not value:
        return 0
    if not re.fullmatch(b"[0-7]+", value):
        raise BackupError("TAR enthält eine ungültige numerische Größe.")
    return int(value, 8)


def _tar_path(name: str, *, directory: bool) -> str:
    if (not name or len(name.encode("utf-8")) > 1024 or "\\" in name or ":" in name
            or name.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise BackupError("TAR enthält einen unsicheren Pfad.")
    parts = name.split("/")
    if ".." in parts:
        raise BackupError("TAR enthält einen unsicheren Pfad.")
    canonical = "/".join(part for part in parts if part not in {"", "."})
    if not canonical and not directory:
        raise BackupError("TAR enthält einen ungültigen Dateipfad.")
    return canonical


def check_tar(path: Path, limits: Limits, deadline: Deadline) -> None:
    """Stream raw TAR headers before tarfile can allocate unbounded PAX metadata.

    GNU long names and local PAX names are supported; links, special files,
    sparse files, global PAX and duplicate/type-conflicting paths are rejected.
    The entire gzip stream is consumed to verify its CRC, including padding.
    """
    initial = _identity(path.stat())
    if initial[2] > limits.tar_bytes:
        raise BackupError("Appdatenarchiv überschreitet die Grenze.")
    total = metadata = count = 0
    seen: dict[str, bool] = {}
    descendants: set[str] = set()
    pending: dict[str, str] = {}

    def read(stream, size: int) -> bytes:
        nonlocal total
        deadline.check()
        data = stream.read(size)
        total += len(data)
        if total > limits.expanded_data_bytes + limits.metadata_bytes + limits.entries * 1024:
            raise BackupError("Entpackte Appdaten überschreiten die Grenze.")
        return data

    def consume(stream, size: int) -> None:
        while size:
            block = read(stream, min(CHUNK, size))
            if not block:
                raise BackupError("TAR ist unvollständig.")
            size -= len(block)

    try:
        with path.open("rb") as raw, gzip.GzipFile(fileobj=raw) as stream:
            data_bytes = 0
            while True:
                header = read(stream, 512)
                if len(header) != 512:
                    raise BackupError("TAR-Endmarkierung fehlt.")
                if not any(header):
                    if pending or read(stream, 512) != b"\0" * 512:
                        raise BackupError("TAR-Endmarkierung ist ungültig.")
                    while block := read(stream, CHUNK):
                        if any(block):
                            raise BackupError("TAR enthält Daten nach der Endmarkierung.")
                    break
                checksum = sum(header[:148]) + 8 * 32 + sum(header[156:])
                if _tar_number(header[148:156]) != checksum:
                    raise BackupError("TAR-Headerprüfsumme ist ungültig.")
                count += 1
                if count > limits.entries:
                    raise BackupError("TAR enthält zu viele Einträge.")
                size = _tar_number(header[124:136])
                kind = header[156:157]
                name = header[:100].split(b"\0", 1)[0]
                if header[257:263] == b"ustar\0":
                    prefix = header[345:500].split(b"\0", 1)[0]
                    if prefix:
                        name = prefix + b"/" + name
                if kind in {b"L", b"x"}:
                    metadata += size
                    if size > limits.small_bytes or metadata > limits.metadata_bytes or pending:
                        raise BackupError("TAR-Metadaten überschreiten die Grenze oder sind mehrdeutig.")
                    content = read(stream, size)
                    if len(content) != size:
                        raise BackupError("TAR-Metadaten sind unvollständig.")
                    if kind == b"L":
                        pending["path"] = content.rstrip(b"\0").decode("utf-8")
                    else:
                        cursor = 0
                        while cursor < len(content):
                            space = content.find(b" ", cursor, min(len(content), cursor + 21))
                            if space < 0 or not content[cursor:space].isdigit():
                                raise BackupError("Ungültige PAX-Metadaten.")
                            length = int(content[cursor:space])
                            end = cursor + length
                            if length <= space - cursor + 2 or end > len(content) or content[end - 1:end] != b"\n":
                                raise BackupError("Ungültige PAX-Recordgrenzen.")
                            key, equal, value = content[space + 1:end - 1].decode("utf-8").partition("=")
                            if not equal or key not in {"path", "mtime", "atime", "ctime", "uid", "gid", "uname", "gname", "size"} or key in pending:
                                raise BackupError("Nicht unterstützte oder doppelte PAX-Metadaten.")
                            if (key in {"uid", "gid", "size"} and not re.fullmatch(r"\d{1,20}", value)
                                    or key in {"mtime", "atime", "ctime"} and not re.fullmatch(r"-?\d{1,20}(?:\.\d{1,20})?", value)
                                    or key in {"uname", "gname"} and (len(value.encode("utf-8")) > 255 or any(ord(c) < 32 for c in value))):
                                raise BackupError("PAX-Metadatenwerte sind ungültig.")
                            pending[key] = value
                            cursor = end
                    consume(stream, (-size) % 512)
                    continue
                if kind not in {b"0", b"\0", b"5"}:
                    raise BackupError("TAR-Links, Spezialdateien oder Sparse-Dateien sind nicht erlaubt.")
                if "size" in pending:
                    if not re.fullmatch(r"\d{1,20}", pending["size"]) or int(pending["size"]) != size:
                        raise BackupError("TAR- und PAX-Größen widersprechen sich.")
                directory = kind == b"5"
                canonical = _tar_path(pending.get("path", name.decode("utf-8")), directory=directory)
                pending = {}
                if directory and size or canonical in seen:
                    raise BackupError("TAR enthält doppelte oder widersprüchliche Einträge.")
                parts = canonical.split("/")
                if any(seen.get("/".join(parts[:i])) is False for i in range(1, len(parts))):
                    raise BackupError("TAR-Datei wird als Verzeichnis verwendet.")
                if not directory and canonical in descendants:
                    raise BackupError("TAR-Verzeichnis wird als Datei verwendet.")
                seen[canonical] = directory
                metadata += len(canonical.encode("utf-8"))
                for i in range(1, len(parts)):
                    parent = "/".join(parts[:i])
                    if parent not in descendants:
                        metadata += len(parent.encode("utf-8"))
                        descendants.add(parent)
                if metadata > limits.metadata_bytes:
                    raise BackupError("TAR-Pfadmetadaten überschreiten die Grenze.")
                data_bytes += size
                if data_bytes > limits.expanded_data_bytes:
                    raise BackupError("Entpackte Appdaten überschreiten die Grenze.")
                consume(stream, size + (-size) % 512)
            if _identity(os.fstat(raw.fileno())) != initial or _identity(path.stat()) != initial:
                raise BackupError("Appdatenarchiv wurde während der Prüfung verändert.")
    except (OSError, EOFError, UnicodeError) as exc:
        raise BackupError("Appdatenarchiv ist beschädigt oder nicht unterstützt.") from exc


def _decrypt(source: Path, destination: Path, password: str, limits: Limits, deadline: Deadline) -> None:
    source = _safe_path(source)
    with source.open("rb") as stream:
        initial = _identity(os.fstat(stream.fileno()))
        size = initial[2]
        if not HEADER_SIZE + 16 <= size <= limits.package_bytes:
            raise BackupError("Verschlüsseltes Paket ist unvollständig oder zu groß.")
        header = stream.read(HEADER_SIZE)
        if not header.startswith(MAGIC):
            raise BackupError("Unbekanntes verschlüsseltes Paketformat.")
        stream.seek(-16, 2)
        tag = stream.read(16)
        salt, nonce = header[len(MAGIC):len(MAGIC) + 16], header[-12:]
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=32)
        deadline.check()
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        stream.seek(HEADER_SIZE)
        remaining = size - HEADER_SIZE - 16
        try:
            with _new_file(destination) as output:
                while remaining:
                    deadline.check()
                    block = stream.read(min(CHUNK, remaining))
                    if not block:
                        raise BackupError("Verschlüsseltes Paket wurde verändert.")
                    output.write(decryptor.update(block))
                    remaining -= len(block)
                output.write(decryptor.finalize())
                if _identity(os.fstat(stream.fileno())) != initial or _identity(source.stat()) != initial:
                    raise BackupError("Verschlüsseltes Paket wurde während des Lesens verändert.")
                deadline.check()
        except InvalidTag as exc:
            raise BackupError("Passphrase falsch oder Paket beschädigt; Docker wurde nicht verändert.") from exc


def _json(data: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise BackupError("Manifest enthält doppelte Schlüssel.")
            value[key] = item
        return value
    try:
        result = json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BackupError("Manifest ist ungültig.") from exc
    if not isinstance(result, dict):
        raise BackupError("Manifest ist ungültig.")
    return result


def verify_package(source: Path, password: str, workspace: Path, limits: Limits, deadline: Deadline) -> dict:
    decoded = workspace / "decoded.zip"
    _decrypt(source, decoded, password, limits, deadline)
    check_zip_budget(decoded, maximum_entries=4, maximum_directory_bytes=16 * 1024,
                     timeout_seconds=deadline.remaining())
    maxima = {"database.dump": limits.dump_bytes, "appdata.tar.gz": limits.tar_bytes,
              "server.env": limits.small_bytes, "manifest.json": limits.small_bytes}
    try:
        with ZipFile(decoded) as archive:
            infos = archive.infolist()
            if len(infos) != 4 or {info.filename for info in infos} != set(MEMBERS):
                raise BackupError("Paket enthält nicht die vier erwarteten Dateien.")
            for info in infos:
                mode = info.external_attr >> 16
                if (info.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.flag_bits & 1
                        or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED} or info.file_size > maxima[info.filename]):
                    raise BackupError("ZIP-Dateityp oder Größe wird nicht unterstützt.")
                with archive.open(info) as member, _new_file(workspace / info.filename) as output:
                    count = 0
                    while block := member.read(CHUNK):
                        deadline.check()
                        count += len(block)
                        if count > maxima[info.filename]:
                            raise BackupError("ZIP-Datei überschreitet die Grenze.")
                        output.write(block)
                    if count != info.file_size:
                        raise BackupError("ZIP-Dateigröße ist widersprüchlich.")
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("Authentifiziertes ZIP-Paket ist beschädigt.") from exc
    manifest = _json(_read_file(workspace / "manifest.json", limits.small_bytes, deadline))
    if (set(manifest) != {"format", "version", "source_project", "created_utc", "postgres_major", "origin", "compose_sha256", "files"}
            or manifest["format"] != "immomanager-private-server" or type(manifest["version"]) is not int or manifest["version"] != 1
            or type(manifest["postgres_major"]) is not int or manifest["postgres_major"] != 16
            or not isinstance(manifest["files"], dict) or set(manifest["files"]) != set(MEMBERS[:-1])):
        raise BackupError("Paketmanifest hat ein unbekanntes Format.")
    _project(manifest["source_project"] if isinstance(manifest["source_project"], str) else "")
    if not isinstance(manifest["compose_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", manifest["compose_sha256"]):
        raise BackupError("Compose-Prüfsumme im Manifest ist ungültig.")
    try:
        date = datetime.fromisoformat(manifest["created_utc"])
        if date.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise BackupError("Manifest-Zeitpunkt ist ungültig.") from exc
    for name in MEMBERS[:-1]:
        actual = _digest(workspace / name, maxima[name], deadline)
        expected = manifest["files"][name]
        if (not isinstance(expected, dict) or set(expected) != {"size_bytes", "sha256"}
                or type(expected["size_bytes"]) is not int or expected != actual):
            raise BackupError("Paketdatei stimmt nicht mit Manifestgröße oder Prüfsumme überein.")
    values = _parse_env(_read_file(workspace / "server.env", limits.small_bytes, deadline))
    if manifest["origin"] != values["APP_ORIGIN"]:
        raise BackupError("Serveradresse und Manifest widersprechen sich.")
    with (workspace / "database.dump").open("rb") as dump:
        if dump.read(5) != b"PGDMP":
            raise BackupError("Datenbankdatei ist kein PostgreSQL-Custom-Dump.")
    check_tar(workspace / "appdata.tar.gz", limits, deadline)
    decoded.unlink()
    return manifest


def _password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise BackupError("Passphrase muss zwischen 12 und 1024 Zeichen enthalten.")
    return password


def _wait_writers(docker: Docker) -> None:
    while True:
        data = docker.run(["exec", "-T", "db", "/bin/sh", "-c", PG_CONNECTIONS], stage="Datenbank-Ruhezustand")
        if not re.fullmatch(rb"\s*\d{1,9}\s*", data):
            raise BackupError("Datenbank-Ruhezustand ist nicht prüfbar.")
        if int(data) == 0:
            return
        time.sleep(min(0.2, docker.deadline.remaining()))


def _publish_new(partial: Path, destination: Path) -> None:
    if os.name == "nt":
        # Windows rename fails atomically if the destination exists; also works
        # on encrypted-backup destinations (e.g. exFAT USB) without hard links.
        os.rename(partial, destination)
    else:
        # POSIX rename would overwrite. Link creates atomically and exclusively.
        os.link(partial, destination, follow_symlinks=False)
        partial.unlink()


def backup(*, project: str, destination: Path, compose_file: Path, env_file: Path,
           password: str, limits: Limits = Limits(), docker_factory=Docker) -> dict:
    project, password = _project(project), _password(password)
    destination = _safe_path(destination, existing=False)
    compose_file, env_file = _safe_path(compose_file), _safe_path(env_file)
    deadline = Deadline(limits.timeout_seconds)
    with private_workspace() as (workspace, sid):
        _verify_private(env_file, workspace, sid, protected=False)
        env_data = _read_file(env_file, limits.small_bytes, deadline)
        values = _parse_env(env_data)
        env_fingerprint = _digest(env_file, limits.small_bytes, deadline)
        if env_fingerprint != {"size_bytes": len(env_data), "sha256": hashlib.sha256(env_data).hexdigest()}:
            raise BackupError("Serverkonfiguration wurde während des Lesens verändert.")
        compose_digest = _compose_digest(compose_file, limits, deadline)
        # All Docker commands use our fixed snapshot, so changing the live .env
        # while offline cannot silently change the credentials/target mid-backup.
        with _new_file(workspace / "server.env") as output:
            output.write(env_data)
        docker = docker_factory(compose_file, workspace / "server.env", project, workspace, limits, deadline)
        if getattr(docker, "compose_digest", compose_digest) != compose_digest:
            raise BackupError("Compose-Profil wurde während des Lesens verändert.")
        docker.require_private_volumes()
        if not docker.running("db"):
            raise BackupError("PostgreSQL-Container läuft nicht; Sicherung verweigert.")
        was_running = docker.running("app")
        partial = destination.parent / ("." + destination.name + "." + uuid4().hex + ".partial")
        resume_failed = False
        try:
            if was_running:
                docker.run(["stop", "--timeout", "30", "app"], stage="App anhalten")
            if docker.running("app"):
                raise BackupError("App läuft noch; Sicherung verweigert.")
            _wait_writers(docker)
            docker.run(["exec", "-T", "db", "/bin/sh", "-c", PG_DUMP], output=workspace / "database.dump",
                       maximum=limits.dump_bytes, stage="PostgreSQL-Sicherung")
            docker.run(["exec", "-T", "db", "/bin/sh", "-c", PG_LIST], input_file=workspace / "database.dump",
                       stage="PostgreSQL-Dumpprüfung")
            docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "app", "-C", "/data", "-czf-", "."],
                       output=workspace / "appdata.tar.gz", maximum=limits.tar_bytes, stage="Appdaten-Sicherung")
            check_tar(workspace / "appdata.tar.gz", limits, deadline)
            if docker.running("app") or _digest(env_file, limits.small_bytes, deadline) != env_fingerprint:
                raise BackupError("Installation wurde während der Sicherung verändert.")
            manifest = {"format": "immomanager-private-server", "version": 1, "source_project": project,
                        "created_utc": datetime.now(timezone.utc).isoformat(), "postgres_major": 16,
                        "origin": values["APP_ORIGIN"], "compose_sha256": compose_digest,
                        "files": {name: _digest(workspace / name, limits.dump_bytes if name == "database.dump" else
                                                limits.tar_bytes if name == "appdata.tar.gz" else limits.small_bytes, deadline)
                                  for name in MEMBERS[:-1]}}
            with _new_file(workspace / "manifest.json") as output:
                output.write(json.dumps(manifest, sort_keys=True, ensure_ascii=True).encode("utf-8"))
            with encrypted_zip(partial, password) as archive:
                for name in MEMBERS:
                    info = ZipInfo(name)
                    info.compress_type, info.external_attr = ZIP_DEFLATED, (stat.S_IFREG | 0o600) << 16
                    with archive.open(info, "w", force_zip64=True) as output, (workspace / name).open("rb") as source:
                        while block := source.read(CHUNK):
                            deadline.check()
                            output.write(block)
                            if partial.stat().st_size > limits.package_bytes:
                                raise BackupError("Verschlüsseltes Paket überschreitet die Grenze.")
            if os.name != "nt":
                partial.chmod(0o600)
            package_identity = _identity(partial.stat())
            with private_workspace() as (verification, _):
                verify_package(partial, password, verification, limits, deadline)
            _safe_path(destination, existing=False)
            _safe_path(partial)
            if _identity(partial.stat()) != package_identity:
                raise BackupError("Verschlüsseltes Paket wurde vor der Veröffentlichung verändert.")
            _publish_new(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
            if was_running:
                # The primary deadline might be exhausted. Reserve a separate,
                # bounded recovery attempt, rather than skip restarting the app.
                docker.deadline = Deadline(min(120, limits.timeout_seconds))
                try:
                    docker.run(["up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", "app"], stage="App wieder starten")
                    if not docker.running("app"):
                        raise BackupError("App ist nach der Sicherung nicht gestartet.")
                except Exception:
                    resume_failed = True
            if resume_failed:
                raise BackupError("Sicherung/Wiederanlauf nicht vollständig; App muss manuell geprüft und gestartet werden.")
        return {"scope": "postgresql-and-appdata-and-server-configuration", "encrypted": True,
                "size_bytes": destination.stat().st_size, "project": project}


def restore(*, project: str, source: Path, compose_file: Path, env_output: Path,
            password: str, limits: Limits = Limits(), docker_factory=Docker) -> dict:
    project, password = _project(project), _password(password)
    source, compose_file = _safe_path(source), _safe_path(compose_file)
    env_output = _safe_path(env_output, existing=False)
    deadline = Deadline(limits.timeout_seconds)
    with private_workspace() as (workspace, sid):
        manifest = verify_package(source, password, workspace, limits, deadline)
        if project == manifest["source_project"]:
            raise BackupError("Wiederherstellung benötigt einen neuen Projektnamen.")
        if _compose_digest(compose_file, limits, deadline) != manifest["compose_sha256"]:
            raise BackupError("Compose-Profil stimmt nicht mit dem Sicherungsmanifest überein.")
        docker = docker_factory(compose_file, workspace / "server.env", project, workspace, limits, deadline)
        if getattr(docker, "compose_digest", manifest["compose_sha256"]) != manifest["compose_sha256"]:
            raise BackupError("Compose-Profil wurde während des Lesens verändert.")
        docker.require_new_project()
        docker.require_private_volumes()
        from backend.services.recovery_sessions import SessionRestoreError, rotated_configuration
        original_values = _parse_env(_read_file(workspace / "server.env", limits.small_bytes, deadline))
        try:
            restored_values = rotated_configuration(original_values)
        except SessionRestoreError as exc:
            raise BackupError(str(exc)) from None
        restored_env = "".join(key + "=" + value + "\n" for key, value in restored_values.items()).encode("utf-8")
        _parse_env(restored_env)
        # A new exclusive configuration file is retained for subsequent local
        # administration, including when a later Docker operation fails.
        with protected_new_file(env_output) as output:
            # A failed target can never retain the original valid JWT signer.
            output.write(restored_env)
        docker.base[-1] = str(env_output)
        docker.run(["build", "app"], stage="Serverimage bauen")
        # Check again after the potentially lengthy build before any volume is
        # created; existing target projects are never taken over or cleaned up.
        docker.require_new_project()
        # An atomic, empty Docker container reserves the project against another
        # simultaneous restore on the same daemon, including another host. It has
        # no mounts, credentials or running process. On failure keep it along with
        # the fresh project for inspection; never remove somebody else's object.
        guard = docker.run(["create", "--name", project + "-restore-guard", "--label",
                            "com.docker.compose.project=" + project, "--label", "immomanager.restore.guard=" + uuid4().hex,
                            "--entrypoint", "/bin/true", project + "-app"], compose=False, stage="Neues Projekt reservieren")
        guard_id = guard.decode("ascii", errors="strict").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", guard_id):
            raise BackupError("Neue Projektreservierung ist nicht prüfbar.")
        docker.run(["up", "-d", "--wait", "--wait-timeout", "120", "db"], stage="Neue PostgreSQL-Instanz starten")
        docker.run(["exec", "-T", "db", "/bin/sh", "-c", PG_RESTORE], input_file=workspace / "database.dump",
                   stage="PostgreSQL-Wiederherstellung")
        docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "app", "-C", "/data",
                    "-xzf", "-", "--no-same-owner", "--no-same-permissions"], input_file=workspace / "appdata.tar.gz",
                   stage="Appdaten-Wiederherstellung")
        with _new_file(workspace / "restore-key-configuration.json") as output:
            output.write(json.dumps(original_values, separators=(",", ":")).encode("utf-8"))
        report_data = docker.run(["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "app", "-m",
            "scripts.restore_session_security", "--configuration-stdin", "--timeout-seconds", str(deadline.remaining())],
            input_file=workspace / "restore-key-configuration.json", stage="Restaurierte Sitzungen widerrufen")
        report = _json(report_data)
        if (set(report) != {"revoked_session_count", "legacy_iban_present"}
                or type(report["revoked_session_count"]) is not int or report["revoked_session_count"] < 0
                or type(report["legacy_iban_present"]) is not bool):
            raise BackupError("Sicherheitsabschluss der Wiederherstellung ist nicht bestätigt; Appstart verweigert.")
        if report["legacy_iban_present"]:
            final_values = rotated_configuration(original_values, legacy_iban_present=True)
            final_values["JWT_SECRET_KEY"] = restored_values["JWT_SECRET_KEY"]
            final_env = "".join(key + "=" + value + "\n" for key, value in final_values.items()).encode("utf-8")
            _parse_env(final_env)
            temporary_env = env_output.with_name("." + env_output.name + "." + uuid4().hex + ".tmp")
            try:
                with protected_new_file(temporary_env) as output:
                    output.write(final_env)
                if _read_file(env_output, limits.small_bytes, deadline) != restored_env:
                    raise BackupError("Zielkonfiguration wurde verändert; Appstart verweigert.")
                os.replace(temporary_env, env_output)
                restored_env = final_env
            finally:
                temporary_env.unlink(missing_ok=True)
        if _read_file(env_output, limits.small_bytes, deadline) != restored_env:
            raise BackupError("Zielkonfiguration wurde verändert; Appstart verweigert.")
        docker.run(["up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", "app"], stage="Wiederhergestellte App starten")
        if not docker.running("app"):
            raise BackupError("Wiederhergestellte App läuft nicht; Zielprojekt zur Prüfung erhalten.")
        docker.run(["rm", guard_id], compose=False, stage="Eigene leere Projektreservierung freigeben")
        return {"scope": "postgresql-and-appdata-and-server-configuration", "encrypted": True, "project": project,
                "sessions_revoked": report["revoked_session_count"], "signing_key_rotated": True}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, "Ungültige Argumente. Unterstützte Optionen mit --help anzeigen.\n")


def _read_password(from_stdin: bool, *, confirm: bool) -> str:
    if from_stdin:
        if sys.stdin.isatty():
            raise BackupError("Passphrase-stdin benötigt eine geschützte Pipe, kein Terminal.")
        password = sys.stdin.readline(1026).rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise BackupError("Interaktives Terminal oder geschützte --password-stdin-Pipe erforderlich.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Sicherungspassphrase (mindestens 12 Zeichen): ")
            if confirm and password != getpass.getpass("Sicherungspassphrase wiederholen: "):
                raise BackupError("Passphrasen stimmen nicht überein.")
    return _password(password)


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Verschlüsseltes privates Serverbackup (PostgreSQL + Appdaten + Serverkonfiguration)")
    parser.add_argument("--compose-file", type=Path, default=ROOT / "compose.private-server.yml")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--capacity-file", type=Path, help="JSON-Kapazitätsprofil für große Installationen")
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("backup", help="App kurz anhalten und ein neues verschlüsseltes Paket erstellen")
    save.add_argument("--project", required=True)
    save.add_argument("--destination", type=Path, required=True)
    save.add_argument("--env-file", type=Path, default=ROOT / ".env.server")
    load = commands.add_parser("restore", help="In ein ausdrücklich neues Docker-Compose-Projekt wiederherstellen")
    load.add_argument("--project", required=True)
    load.add_argument("--source", type=Path, required=True)
    load.add_argument("--env-output", type=Path)
    for command in (save, load):
        command.add_argument("--compose-file", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--timeout-seconds", type=float, default=argparse.SUPPRESS)
        command.add_argument("--capacity-file", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--password-stdin", action="store_true", help="Passphrase aus einer geschützten stdin-Pipe lesen")
    args = parser.parse_args(argv)
    try:
        from backend.services.capacity_settings import CapacityProfileError, load_capacity
        try:
            limits = load_capacity(args.capacity_file, "private_server_backup", Limits,
                                   overrides={"timeout_seconds": args.timeout_seconds} if args.timeout_seconds is not None else None)
        except CapacityProfileError as exc:
            raise BackupError(str(exc)) from None
        password = _read_password(args.password_stdin, confirm=args.command == "backup")
        if args.command == "backup":
            backup(project=args.project, destination=args.destination, compose_file=args.compose_file,
                   env_file=args.env_file, password=password, limits=limits)
            print("Verschlüsseltes Gesamtbackup geprüft und gespeichert; App-Wiederanlauf berücksichtigt.")
        else:
            env_output = args.env_output or args.compose_file.parent / (".env.server." + _project(args.project))
            restore(project=args.project, source=args.source, compose_file=args.compose_file,
                    env_output=env_output, password=password, limits=limits)
            print("Neues Serverprojekt vollständig wiederhergestellt und gestartet; geschützte Serverkonfiguration erhalten.")
        return 0
    except (BackupError, EOFError, KeyboardInterrupt, getpass.GetPassWarning) as exc:
        message = str(exc) if isinstance(exc, BackupError) else "Vorgang abgebrochen; kein Erfolg bestätigt."
        print(message, file=sys.stderr)
        return 1
    except Exception:
        # Docker stderr, environment values and filesystem exceptions may contain
        # credentials, personal filenames or DSNs. Never echo them to the terminal.
        print("Serversicherung fehlgeschlagen; kein Erfolg bestätigt. Neue Ressourcen gegebenenfalls manuell prüfen.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
