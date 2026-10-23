"""Operator commands: full backup, verification, restore probe, restore, key rotation.

    python -m backend.ops backup                      full backup now (as the daily job does)
    python -m backend.ops verify <archive>            check digests and manifest, change nothing
    python -m backend.ops probe [<archive>]           isolated restore probe (latest archive by default)
    python -m backend.ops restore <archive> --target <new directory> [--passphrase-env VAR]
                                                      [--pg-target-url URL]
    python -m backend.ops status                      operations overview as JSON
    python -m backend.ops rotate-key                  new active key; secrets are sealed again

Windows package: ``ImmoManager-Pro.exe ops <command> …``. Restore never writes over live
data: it builds a new data directory; switch to it while the program is stopped.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path


def _passphrase(args, required: bool) -> str:
    from .config import settings

    if getattr(args, "passphrase_env", None):
        value = os.environ.get(args.passphrase_env, "")
        if not value:
            raise SystemExit(f"Umgebungsvariable {args.passphrase_env} ist leer.")
        return value
    if settings.backup_passphrase or not required or not sys.stdin.isatty():
        return settings.backup_passphrase
    return getpass.getpass("Passphrase der Schlüsselsicherung: ")


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _archive_path(value: str) -> Path:
    from .services import full_backup

    path = Path(value)
    if not path.is_absolute() and not path.exists():
        path = full_backup.Sources.from_settings().root / value
    return path


def main(argv: list[str] | None = None) -> int:
    from .services import full_backup

    parser = argparse.ArgumentParser(prog="python -m backend.ops", description="Betrieb: Sicherung und Probe")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="Vollbackup jetzt")
    verify = sub.add_parser("verify", help="Archiv prüfen")
    verify.add_argument("archive")
    probe = sub.add_parser("probe", help="Isolierte Wiederherstellungsprobe")
    probe.add_argument("archive", nargs="?")
    probe.add_argument("--passphrase-env")
    restore = sub.add_parser("restore", help="In ein neues Verzeichnis wiederherstellen")
    restore.add_argument("archive")
    restore.add_argument("--target", required=True)
    restore.add_argument("--passphrase-env")
    restore.add_argument("--pg-target-url", default="")
    sub.add_parser("status", help="Betriebsübersicht")
    sub.add_parser("rotate-key", help="Neuen Schlüssel aktivieren und Geheimnisse neu verschlüsseln")
    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            _print(full_backup.create_full_backup("cli"))
        elif args.command == "verify":
            report = full_backup.verify_archive(_archive_path(args.archive))
            _print(report)
            return 0 if report["ok"] else 1
        elif args.command == "probe":
            archive = _archive_path(args.archive) if args.archive else None
            _print(full_backup.restore_probe(archive, passphrase=_passphrase(args, required=False)))
        elif args.command == "restore":
            _print(full_backup.restore_archive(_archive_path(args.archive), Path(args.target).expanduser(),
                                               passphrase=_passphrase(args, required=True),
                                               pg_target_url=args.pg_target_url))
        elif args.command == "status":
            from .config import settings
            from .db.schema_state import inspect_url
            from .services.integrations.manager import integration_manager

            _print(full_backup.overview(secret_status=integration_manager.secret_status(),
                                        schema=inspect_url(settings.database_url).as_dict()))
        elif args.command == "rotate-key":
            from .services.integrations.manager import integration_manager
            from .services.secret_box import default_secret_box

            key_id = default_secret_box().rotate()
            count = integration_manager.reseal()
            _print({"active_key_id": key_id, "resealed": count,
                    "hint": "Alte Schlüssel bleiben in der Schlüsseldatei; nach dem nächsten Vollbackup sichern."})
    except (full_backup.BackupError, OSError, RuntimeError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
