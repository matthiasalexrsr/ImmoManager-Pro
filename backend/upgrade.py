"""Explicit upgrade: full backup first, then the migrations to the Alembic head.

    python -m backend.upgrade              backup + upgrade when the database is behind
    python -m backend.upgrade --check      report only
    python -m backend.upgrade --no-backup  skip the backup (only with a verified backup elsewhere)

Windows package: ``ImmoManager-Pro.exe upgrade``; the launcher runs this step before every
start. Normal start never changes an existing schema (backend.db.schema_state).

Exit codes: 0 done or nothing to do, 2 backup failed (schema unchanged), 3 upgrade failed
(the pre-upgrade backup exists), 4 database newer than this program, 5 upgrade needed (--check).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

EXIT_OK, EXIT_BACKUP_FAILED, EXIT_UPGRADE_FAILED, EXIT_NEWER, EXIT_NEEDS_UPGRADE = 0, 2, 3, 4, 5


def _in_memory(url: str) -> bool:
    return url.startswith("sqlite") and (url.endswith(":memory:") or url.rstrip("/") in ("sqlite:", "sqlite:/"))


def upgrade(*, backup: bool = True, check_only: bool = False, initialise_empty: bool = True,
            out: Callable[[str], None] = print) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from .config import settings
    from .db import schema_state
    from .services import full_backup

    url = settings.database_url
    if _in_memory(url):
        out("Datenbank im Arbeitsspeicher: kein Upgrade nötig.")
        return EXIT_OK
    try:
        status = schema_state.inspect_url(url)
    except Exception as exc:
        out(f"FEHLER: Datenbank nicht erreichbar: {type(exc).__name__}: {exc}")
        return EXIT_UPGRADE_FAILED
    out(status.describe())
    if status.state == schema_state.NEWER:
        return EXIT_NEWER
    if check_only:
        return EXIT_NEEDS_UPGRADE if status.needs_upgrade else EXIT_OK
    if status.state == schema_state.CURRENT:
        return EXIT_OK
    if status.state == schema_state.EMPTY:
        if initialise_empty:
            engine = create_engine(url, poolclass=NullPool)
            try:
                schema_state.initialise_empty(engine)
            finally:
                engine.dispose()
            out(f"Neue Datenbank angelegt (Revision {status.head}).")
        return EXIT_OK

    sources = full_backup.Sources.from_settings()
    archive = None
    if backup:
        out("Vollbackup vor dem Upgrade …")
        try:
            event = full_backup.create_full_backup("pre-upgrade", sources)
        except Exception as exc:
            out(f"FEHLER: Vollbackup fehlgeschlagen, das Schema bleibt unverändert: {exc}")
            return EXIT_BACKUP_FAILED
        archive = event["archive"]
        out(f"Vollbackup: {sources.root / archive} ({event['size'] / 1024 / 1024:.1f} MB, geprüft)")
    else:
        out("WARNUNG: Upgrade ohne Vollbackup (--no-backup).")
    try:
        before, after = schema_state.run_migrations(url)
    except Exception as exc:
        full_backup.record_event(sources.root, {"event": "upgrade", "ok": False, "backup": archive,
                                                "from": status.revision or status.state,
                                                "error": f"{type(exc).__name__}: {exc}"})
        out(f"FEHLER: Upgrade fehlgeschlagen: {type(exc).__name__}: {exc}")
        if archive:
            out(f"Die Sicherung {archive} enthält den Stand vor dem Upgrade "
                "(Wiederherstellung: python -m backend.ops restore <Archiv> --target <neues Verzeichnis>).")
        return EXIT_UPGRADE_FAILED
    full_backup.record_event(sources.root, {"event": "upgrade", "ok": True, "backup": archive,
                                            "from": before.revision or before.state, "to": after.revision})
    out(f"Upgrade abgeschlossen: {before.revision or before.state} → {after.revision}.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.upgrade",
                                     description="Explizites Datenbank-Upgrade mit Vollbackup")
    parser.add_argument("--check", action="store_true", help="nur prüfen, nichts ändern")
    parser.add_argument("--no-backup", action="store_true", help="ohne vorheriges Vollbackup (nicht empfohlen)")
    args = parser.parse_args(argv)
    return upgrade(backup=not args.no_backup, check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
