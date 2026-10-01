"""Consistent DATABASE-ONLY SQLite snapshots and Windows task scheduling.

These snapshots do not contain attachments or runtime configuration/secrets.
Use ``python -m backend.recovery backup --offline`` for a full recovery archive.
"""

import argparse
import math
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "ImmoManagerPro-Backup"
MAX_BACKUPS = 30  # Retention in days; only this scheduler's database snapshots.
DEFAULT_TIMEOUT = 300.0
OWN_SNAPSHOT = re.compile(r"(?:database_snapshot_[0-9]{8}_[0-9]{6}_[0-9a-f]{32}|backup_[0-9]{8}_[0-9]{6})\.db\Z")


class SnapshotError(RuntimeError):
    """A snapshot or task could not be completed safely."""


@dataclass(frozen=True)
class SnapshotPaths:
    data_dir: Path
    database: Path
    backups: Path


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "ImmoManagerPro"
    return ROOT


def _relative_to_data(value: str | Path, data_dir: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else data_dir / path).resolve()


def _sqlite_path_from_url(url: str, data_dir: Path) -> Path:
    prefix = next((value for value in ("sqlite:///", "sqlite+pysqlite:///") if url.startswith(value)), None)
    if prefix is None:
        # Never include the URL: an unsupported server URL can contain credentials.
        raise SnapshotError("DATABASE-ONLY unterstützt nur eine vorhandene SQLite-Datei; keine PostgreSQL-/Serverdatenbank.")
    filename = url[len(prefix):]
    if not filename or filename == ":memory:" or filename.startswith("file:") or "?" in filename or "#" in filename:
        raise SnapshotError("SQLite-Speicher- und URI-Datenbanken werden nicht unterstützt. Eine SQLite-Datei konfigurieren.")
    return _relative_to_data(filename, data_dir)


def configuration(data_dir: str | Path | None = None) -> SnapshotPaths:
    explicit = data_dir is not None
    root = Path(data_dir or os.environ.get("DATA_DIR") or _default_data_dir()).expanduser().resolve()
    if not root.is_dir():
        raise SnapshotError("Der ausgewählte Datenordner existiert nicht. Den vorhandenen Installationsordner angeben.")
    # Do not import backend settings/startup: neither JWT defaults nor directories
    # should be written by a scheduler. The dependency already comes with settings.
    from dotenv import dotenv_values
    env_file = root / ".env"
    persisted = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
    database_url = persisted.get("DATABASE_URL")
    backup_dir = persisted.get("BACKUP_DIR")
    if not explicit:
        database_url = os.environ.get("DATABASE_URL") or database_url
        backup_dir = os.environ.get("BACKUP_DIR") or backup_dir
    database = _sqlite_path_from_url(database_url or "sqlite:///immo_manager.db", root)
    backups = _relative_to_data(backup_dir or "backups", root)
    return SnapshotPaths(root, database, backups)


def _validate_source(paths: SnapshotPaths) -> None:
    if not paths.database.is_file() or paths.database.stat().st_size == 0:
        raise SnapshotError("Die konfigurierte SQLite-Datenbank fehlt oder ist leer. Kein anderes Backup wurde versucht.")


def _deadline_check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise SnapshotError("SQLite-Snapshot hat das Zeitlimit überschritten; kein Snapshot wurde veröffentlicht.")


def _remove_temporary(path: Path, directory: Path) -> None:
    # Every candidate is a file owned by this invocation, never a recursive path.
    if path.parent != directory or not path.name.startswith(".database_snapshot_"):
        raise SnapshotError("Unerwarteter temporärer Snapshot-Pfad.")
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        candidate.unlink(missing_ok=True)


def run_backup(paths: SnapshotPaths | None = None, *, timeout: float = DEFAULT_TIMEOUT,
               now: datetime | None = None) -> Path:
    """Publish one integrity-checked WAL-consistent snapshot, or raise an error."""
    paths = paths or configuration()
    if not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise SnapshotError("Das Snapshot-Zeitlimit muss zwischen 0 und 3600 Sekunden liegen.")
    _validate_source(paths)
    paths.backups.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    destination = paths.backups / f"database_snapshot_{timestamp}_{uuid4().hex}.db"
    deadline = time.monotonic() + timeout
    descriptor, filename = tempfile.mkstemp(prefix=".database_snapshot_", suffix=".tmp", dir=paths.backups)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        # Read-only URI avoids accidentally creating a missing source; as_uri
        # escapes spaces, '#' and '?' in real Windows/Unix filesystem paths.
        source = sqlite3.connect(paths.database.as_uri() + "?mode=ro", uri=True, timeout=0)
        try:
            target = sqlite3.connect(temporary, timeout=0)
            try:
                source.backup(target, pages=64, sleep=0.05,
                              progress=lambda status, remaining, total: _deadline_check(deadline))
                # The copied header can retain the source's WAL mode. Publish a
                # standalone snapshot whose readers need no adjacent WAL/SHM.
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
        finally:
            source.close()
        _deadline_check(deadline)
        verification = sqlite3.connect(temporary.as_uri() + "?mode=ro", uri=True, timeout=0)
        try:
            verification.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            if verification.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise SnapshotError("SQLite-Integritätsprüfung fehlgeschlagen; kein Snapshot wurde veröffentlicht.")
        finally:
            verification.close()
        _deadline_check(deadline)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        _deadline_check(deadline)
        # A same-directory hard link publishes the complete file atomically and
        # fails if the name exists. Unlike POSIX rename, it cannot overwrite it.
        os.link(temporary, destination)
    finally:
        _remove_temporary(temporary, paths.backups)
    print(f"DATABASE-ONLY Snapshot erstellt: {destination} ({destination.stat().st_size / (1024 * 1024):.1f} MB)")
    print("Enthält alle SQLite-Tabellen; keine Anhänge oder externe Runtime-Konfiguration (.env).")
    return destination


def cleanup(paths: SnapshotPaths | None = None, *, now: datetime | None = None) -> int:
    """Remove only regular owned snapshots older than 30 days; skip all links."""
    paths = paths or configuration()
    if not paths.backups.exists():
        print("Kein Snapshot-Verzeichnis vorhanden.")
        return 0
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=MAX_BACKUPS)).timestamp()
    removed = 0
    for candidate in sorted(paths.backups.iterdir()):
        if not OWN_SNAPSHOT.fullmatch(candidate.name) or candidate == paths.database:
            continue
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            continue
        if metadata.st_mtime < cutoff:
            candidate.unlink()
            removed += 1
    print(f"{removed} alte DATABASE-ONLY Snapshots entfernt (Aufbewahrung: {MAX_BACKUPS} Tage).")
    return removed


def _project_python() -> Path:
    candidate = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate.resolve() if candidate.is_file() else Path(sys.executable).resolve()


def schedule(paths: SnapshotPaths | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> None:
    paths = paths or configuration()
    _validate_source(paths)
    # The scheduled command must select the same installation even when launched
    # by Windows without this shell's environment or working directory.
    if configuration(paths.data_dir) != paths:
        raise SnapshotError("Die Task-Konfiguration ist nicht reproduzierbar. --data-dir angeben und DATABASE_URL/BACKUP_DIR in dessen .env speichern.")
    command = subprocess.list2cmdline([str(_project_python()), str(Path(__file__).resolve()), "run",
                                      "--data-dir", str(paths.data_dir), "--timeout", str(timeout)])
    subprocess.run(["schtasks", "/create", "/tn", TASK_NAME, "/tr", command,
                    "/sc", "daily", "/st", "02:00", "/f"],
                   check=True, capture_output=True, text=True, timeout=30)
    print(f"DATABASE-ONLY Aufgabe '{TASK_NAME}' erstellt (täglich 02:00 Uhr).")


def unschedule() -> None:
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                   check=True, capture_output=True, text=True, timeout=30)
    print(f"Geplante Aufgabe '{TASK_NAME}' entfernt.")


def info(paths: SnapshotPaths) -> None:
    print("DATABASE-ONLY: alle SQLite-Tabellen; keine Anhänge oder externe Runtime-Konfiguration (.env).")
    print(f"Datenordner: {paths.data_dir}\nDatenbank:   {paths.database}\nSnapshots:  {paths.backups}")
    print("Vollständiges, passwortverschlüsseltes Recovery-Archiv bei gestoppter Anwendung:")
    print(subprocess.list2cmdline([str(_project_python()), "-m", "backend.recovery", "backup", "--offline",
                                  "--data-dir", str(paths.data_dir), "--output", "<Archivdatei>"]))
    print(f"Im Projektordner ausführen: {ROOT}")


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Zeitlimit muss eine positive Zahl sein") from exc
    if not math.isfinite(seconds) or not 0 < seconds <= 3600:
        raise argparse.ArgumentTypeError("Zeitlimit muss zwischen 0 und 3600 Sekunden liegen")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "schedule", "unschedule", "cleanup", "info"])
    parser.add_argument("--data-dir", type=Path, help="Vorhandene Installation; deren .env hat Vorrang vor fremden Umgebungsvariablen")
    parser.add_argument("--timeout", type=_positive_seconds, default=DEFAULT_TIMEOUT, help="Snapshot-Zeitlimit in Sekunden (Standard: 300)")
    args = parser.parse_args(argv)
    try:
        if args.command == "unschedule":
            unschedule()
        else:
            paths = configuration(args.data_dir)
            if args.command == "run":
                run_backup(paths, timeout=args.timeout)
            elif args.command == "schedule":
                schedule(paths, timeout=args.timeout)
            elif args.command == "cleanup":
                cleanup(paths)
            else:
                info(paths)
        return 0
    except SnapshotError as exc:
        print(f"Fehlgeschlagen: {exc}", file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        print(f"Windows-Aufgabenplanung fehlgeschlagen (Exitcode {exc.returncode}).", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("Windows-Aufgabenplanung hat das Zeitlimit überschritten.", file=sys.stderr)
    except FileNotFoundError:
        print("Datei oder Windows-Aufgabenplanung nicht gefunden; keine erfolgreiche Sicherung/Aufgabe.", file=sys.stderr)
    except (sqlite3.Error, OSError, ImportError):
        # Do not echo raw configuration, subprocess output or URLs/credentials.
        print("SQLite-/Dateisystemfehler: Vorgang fehlgeschlagen; keine erfolgreiche Sicherung/Aufgabe.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
