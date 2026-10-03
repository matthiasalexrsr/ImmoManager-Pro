"""Offline recovery CLI. Passwords are read interactively, never from argv."""

import argparse
import getpass
import io
import json
import math
import os
import sqlite3
import stat
import sys
import time
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from .backup_operations.plan import BackupOperationError
from .backup_operations.runtime import ManagedRuntime, runtime_directory
from .backup_operations.state import FileLease, private_directory
from .services.full_recovery import (
    RecoveryLimits,
    RecoveryPlan,
    _configuration,
    _json,
    _remaining,
    create_full_backup,
    load_recovered_environment,
    restore_full_backup,
)
from .services.recovery_archive import RecoveryError


def _configuration_identity(info):
    # Windows lstat/fstat ctime can describe different native timestamps.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _configuration_fingerprint(info):
    # Compare ctime only within the same stat API, retaining change detection.
    return (*_configuration_identity(info), info.st_ctime_ns)


def _regular_configuration(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise RecoveryError("Konfiguration muss eine reguläre lokale Datei ohne Verknüpfungen sein.")


def _configuration_bytes(path: Path, maximum: int, deadline: float) -> bytes | None:
    """Capture optional source bytes under a bound and its actual file identity."""
    _remaining(deadline)
    descriptor = None
    try:
        try:
            before = path.lstat()
        except FileNotFoundError:
            return None
        _regular_configuration(before)
        if before.st_size > maximum:
            raise RecoveryError("Konfiguration überschreitet das gewählte Größenbudget.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        # Avoid blocking if a non-cooperating process substitutes a FIFO.
        descriptor = os.open(path, flags | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            opened = os.fstat(source.fileno())
            _regular_configuration(opened)
            if _configuration_identity(before) != _configuration_identity(opened):
                raise RecoveryError("Konfiguration wurde während der Auswahl verändert.")
            raw = bytearray()
            while True:
                _remaining(deadline)
                chunk = source.read(min(1024**2, maximum + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > maximum:
                    raise RecoveryError("Konfiguration überschreitet das gewählte Größenbudget.")
            final = os.fstat(source.fileno())
            named = path.lstat()
            _regular_configuration(final)
            _regular_configuration(named)
            if (len(raw) != opened.st_size
                    or _configuration_fingerprint(opened) != _configuration_fingerprint(final)
                    or _configuration_fingerprint(before) != _configuration_fingerprint(named)
                    or _configuration_identity(final) != _configuration_identity(named)):
                raise RecoveryError("Konfiguration wurde während der Auswahl verändert.")
    except OSError:
        raise RecoveryError("Konfiguration konnte nicht unverändert gelesen werden. Auswahl und Dateirechte prüfen.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _remaining(deadline)
    return bytes(raw)


def _planner_deadline(limits: RecoveryLimits, deadline: float | None) -> float:
    if deadline is None:
        deadline = time.monotonic() + limits.timeout_seconds
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise RecoveryError("Das Zeitlimit muss endlich sein.")
    _remaining(deadline)
    return deadline


def _plan(args, *, limits: RecoveryLimits | None = None, deadline: float | None = None):
    """Select stored configuration with an explicit adjustable capacity profile."""
    limits = limits if limits is not None else RecoveryLimits()
    deadline = _planner_deadline(limits, deadline)
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    from .settings import ExplicitSettings, Settings
    root = args.data_dir.resolve()
    runtime = root / ".env"
    maximum = min(limits.metadata_bytes, limits.file_bytes)
    runtime_raw = _configuration_bytes(runtime, maximum, deadline)
    persisted: dict[str, str | None] = {}
    if runtime_raw is not None:
        _remaining(deadline)
        try:
            with io.TextIOWrapper(io.BytesIO(runtime_raw), encoding="utf-8", newline=None) as source:
                persisted = dotenv_values(stream=source, interpolate=False)
        except UnicodeError:
            raise RecoveryError("Die gespeicherte Konfiguration muss gültiger UTF-8-Text sein.") from None
        _remaining(deadline)
    recovered_config = root / "configuration.json"
    recovered_raw = _configuration_bytes(recovered_config, maximum, deadline)
    if recovered_raw is not None:
        _remaining(deadline)
        # Recovery JSON preserves quotes/newlines that a convenience .env cannot.
        decoded = _json(recovered_raw)
        _remaining(deadline)
        persisted.update(_configuration(decoded))
        _remaining(deadline)
    url = make_url(persisted.get("DATABASE_URL") or "sqlite:///" + (root / "immo_manager.db").as_posix())
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RecoveryError("Vollsicherung unterstuetzt derzeit nur dateibasierte SQLite-Installationen.")
    database = args.database or Path(url.database)
    if not database.is_absolute():
        raise RecoveryError("Relative Datenbankpfade erfordern eine explizite absolute --database Angabe.")
    uploads = args.uploads or Path(persisted.get("UPLOADS_DIR") or root / "uploads")
    integrations = args.integrations or Path(persisted.get("INTEGRATION_STATE_FILE") or root / "integrations.json")
    if not uploads.is_absolute() or not integrations.is_absolute():
        raise RecoveryError("Upload- und Integrationspfade muessen absolut sein.")
    if not root.is_dir():
        raise RecoveryError("Der ausgewählte Datenordner existiert nicht.")
    if not persisted.get("JWT_SECRET_KEY"):
        raise RecoveryError("Der Schlüssel der ausgewählten Installation muss in deren .env vorliegen.")
    options: dict[str, Any] = {key.lower(): value for key, value in persisted.items()
                              if key.lower() in Settings.model_fields and value is not None}
    options.update({"data_dir": str(root),
                               "database_url": "sqlite:///" + database.as_posix(), "uploads_dir": str(uploads),
                               "integration_state_file": str(integrations)})
    _remaining(deadline)
    settings = ExplicitSettings(**options)
    _remaining(deadline)
    values = {key.upper(): value if isinstance(value, str) else json.dumps(value)
              for key, value in settings.model_dump(mode="json").items() if value is not None}
    if args.integrations is not None and not integrations.is_file():
        raise RecoveryError("Die ausdrücklich gewählte Integrationsdatei fehlt.")
    _remaining(deadline)
    return RecoveryPlan(database, uploads, values, runtime if runtime_raw is not None else None,
                        integrations if integrations.exists() else None)


def _run_recovered(args):
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    with ManagedRuntime(args.data_dir.expanduser().resolve(), app_root=root, host="127.0.0.1", port=args.port) as runtime:
        load_recovered_environment(args.data_dir)
        from .app import app
        from .config import settings
        runtime.bind_configuration(settings)
        runtime.run(app)


@contextmanager
def _offline_backup(args, *, limits: RecoveryLimits | None = None, deadline: float | None = None):
    """Supported writers/startups are excluded before plan/SQL/archive work."""
    directory = args.data_dir.expanduser().resolve()
    if not directory.is_dir():
        raise RecoveryError("Der ausgewählte Datenordner existiert nicht.")
    try:
        with FileLease(private_directory(runtime_directory(directory)) / "installation.lock"):
            plan = _plan(args, limits=limits, deadline=deadline)
            # URI rw prevents accidentally creating an absent selected database.
            with closing(sqlite3.connect(plan.database.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)) as writer:
                try:
                    writer.execute("BEGIN IMMEDIATE")
                    yield plan
                finally:
                    writer.rollback()
    except BackupOperationError:
        raise RecoveryError("Die ausgewählte Installation wird verwendet. Anwendung vollständig beenden und den Offline-Sicherungsbefehl erneut ausführen.") from None
    except sqlite3.OperationalError:
        raise RecoveryError("Die ausgewählte Datenbank ist nicht verfügbar oder wird noch beschrieben. Datenbankpfad prüfen, Schreibvorgang beenden und Sicherung erneut ausführen.") from None


def main():
    parser = argparse.ArgumentParser(description="Vollsicherung und Wiederherstellung von ImmoManager")
    commands = parser.add_subparsers(dest="operation", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--data-dir", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)
    backup.add_argument("--database", type=Path)
    backup.add_argument("--uploads", type=Path)
    backup.add_argument("--integrations", type=Path)
    backup.add_argument("--offline", action="store_true", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    for command in (backup, restore):
        command.add_argument("--capacity-file", type=Path, help="JSON-Kapazitätsprofil für große Installationen")
        command.add_argument("--timeout-seconds", type=float)
    run = commands.add_parser("run")
    run.add_argument("--data-dir", required=True, type=Path)
    run.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.operation == "run":
            _run_recovered(args)
            return
        from .services.capacity_settings import CapacityProfileError, load_capacity
        try:
            limits = load_capacity(args.capacity_file, "sqlite_recovery", RecoveryLimits,
                                   overrides={"timeout_seconds": args.timeout_seconds} if args.timeout_seconds is not None else None)
        except CapacityProfileError as exc:
            raise RecoveryError(str(exc)) from None
        password = getpass.getpass("Passphrase der Vollsicherung: ")
        if args.operation == "backup":
            if getpass.getpass("Passphrase wiederholen: ") != password:
                raise RecoveryError("Die Passphrasen stimmen nicht ueberein.")
            deadline = time.monotonic() + limits.timeout_seconds
            with _offline_backup(args, limits=limits, deadline=deadline) as plan:
                result = create_full_backup(plan, args.output, password, offline=args.offline,
                                           limits=replace(limits, timeout_seconds=_remaining(deadline)))
        else:
            result = restore_full_backup(args.archive, args.destination, password, limits=limits)
        print(json.dumps(result, ensure_ascii=False))
    except RecoveryError as exc:
        parser.exit(2, f"Fehler: {exc}\n")
    except BackupOperationError as exc:
        parser.exit(2, f"Start der ausgewählten Installation nicht möglich ({exc.code}); Auswahl prüfen und erneut versuchen.\n")
    except Exception as exc:
        parser.exit(2, f"Vollsicherung abgebrochen ({type(exc).__name__}); Details nicht ausgegeben.\n")


if __name__ == "__main__":
    main()
