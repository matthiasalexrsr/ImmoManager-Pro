"""Backup scheduler for ImmoManager Pro.

Creates automatic backups and can register itself as a Windows Scheduled Task.

Usage:
    python scripts/backup_scheduler.py run          # Run backup now
    python scripts/backup_scheduler.py schedule      # Create Windows Task (daily 2 AM)
    python scripts/backup_scheduler.py unschedule    # Remove Windows Task
    python scripts/backup_scheduler.py cleanup       # Remove backups older than 30 days
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "ImmoManagerPro-Backup"
MAX_BACKUPS = 30  # Keep last 30 days


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "ImmoManagerPro"
        return Path.home() / "AppData" / "Local" / "ImmoManagerPro"
    return ROOT


def _sqlite_path_from_url(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///"))


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or _default_data_dir()).expanduser().resolve()


def _backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR") or (_data_dir() / "backups")).expanduser().resolve()


def _db_path() -> Path:
    configured = os.environ.get("DATABASE_URL", "")
    from_url = _sqlite_path_from_url(configured)
    if from_url is not None:
        return from_url.expanduser().resolve()
    appdata_db = _data_dir() / "immo_manager.db"
    if appdata_db.exists():
        return appdata_db
    return ROOT / "immo_manager.db"


def run_backup() -> bool:
    """Create a timestamped backup of the database. Returns False on failure."""
    backup_dir = _backup_dir()
    db_path = _db_path()
    backup_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        print(f"FEHLER: Datenbank nicht gefunden: {db_path}")
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"backup_{timestamp}.db"
    # SQLite online backup API: consistent even while the server is running
    # in WAL mode. A plain file copy would miss commits still in the -wal file,
    # so there is deliberately no file-copy fallback.
    try:
        source = sqlite3.connect(str(db_path))
        try:
            target = sqlite3.connect(str(backup_file))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    except sqlite3.Error as exc:
        backup_file.unlink(missing_ok=True)
        print(f"FEHLER: Backup fehlgeschlagen: {exc}")
        return False
    size_mb = backup_file.stat().st_size / (1024 * 1024)
    print(f"Backup erstellt: {backup_file} ({size_mb:.1f} MB)")
    return True


def cleanup():
    """Remove backups older than MAX_BACKUPS days."""
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        print("Kein Backup-Verzeichnis vorhanden.")
        return

    cutoff = datetime.now() - timedelta(days=MAX_BACKUPS)
    removed = 0
    for f in sorted(backup_dir.glob("backup_*.db")):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            removed += 1
            print(f"Gelöscht: {f.name}")

    print(f"{removed} alte Backups entfernt.")


def schedule():
    """Register a daily backup task in Windows Task Scheduler."""
    python = sys.executable
    script = str(Path(__file__).resolve())

    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python}" "{script}" run',
        "/sc", "daily",
        "/st", "02:00",
        "/f",  # Force overwrite
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"Geplante Aufgabe '{TASK_NAME}' erstellt (täglich 02:00 Uhr).")
    except FileNotFoundError:
        print("schtasks nicht gefunden. Nur unter Windows verfügbar.")
    except subprocess.CalledProcessError as exc:
        print(f"Fehler beim Erstellen der Aufgabe: {exc}")


def unschedule():
    """Remove the Windows Scheduled Task."""
    try:
        subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], check=True)
        print(f"Geplante Aufgabe '{TASK_NAME}' entfernt.")
    except FileNotFoundError:
        print("schtasks nicht gefunden.")
    except subprocess.CalledProcessError as exc:
        print(f"Fehler: {exc}")


def main():
    if len(sys.argv) < 2:
        print("Verwendung: python scripts/backup_scheduler.py [run|schedule|unschedule|cleanup|info]")
        sys.exit(1)

    def info():
        print(f"Datenbank: {_db_path()}")
        print(f"Backups:   {_backup_dir()}")

    commands = {
        "run": run_backup,
        "schedule": schedule,
        "unschedule": unschedule,
        "cleanup": cleanup,
        "info": info,
    }
    cmd = sys.argv[1].lower()
    if cmd not in commands:
        print(f"Unbekannter Befehl: {cmd}")
        sys.exit(1)

    # Non-zero exit code so Windows Task Scheduler records failed runs.
    if commands[cmd]() is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
