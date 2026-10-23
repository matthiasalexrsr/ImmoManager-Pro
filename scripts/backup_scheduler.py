"""Backup scheduler for ImmoManager Pro (Windows Task Scheduler, also while the program is closed).

Every run makes a verified full backup (database, uploads, configuration, keys) through
`python -m backend ops backup`, i.e. the same code as the in-app daily job, including the
second target and retention (see docs/OPERATIONS_BACKUP_SECRETS_20261008.md).

Usage:
    python scripts/backup_scheduler.py run          # Full backup now
    python scripts/backup_scheduler.py schedule     # Create Windows Task (daily 02:00)
    python scripts/backup_scheduler.py unschedule   # Remove Windows Task
    python scripts/backup_scheduler.py cleanup      # Remove old database-only backups (backup_*.db, 30 days)
    python scripts/backup_scheduler.py info         # Show paths
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "ImmoManagerPro-Backup"
MAX_BACKUPS = 30  # days for the old database-only copies


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "ImmoManagerPro"
        return Path.home() / "AppData" / "Local" / "ImmoManagerPro"
    return ROOT


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or _default_data_dir()).expanduser().resolve()


def _backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR") or (_data_dir() / "backups")).expanduser().resolve()


def run_backup() -> bool:
    """Full backup with the launcher's runtime paths (.env of the data directory). False on failure."""
    command = [sys.executable, "-m", "backend", "ops", "backup", "--data-dir", str(_data_dir())]
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("FEHLER: Vollbackup fehlgeschlagen (Details oben und im Betriebsprotokoll ops-log.jsonl).")
        return False
    return True


def cleanup():
    """Remove database-only backups (backup_*.db) older than MAX_BACKUPS days; full backups have their own retention."""
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
        print(f"Daten:     {_data_dir()}")
        print(f"Backups:   {_backup_dir() / 'full'}")

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
