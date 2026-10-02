"""Offline recovery CLI. Passwords are read interactively, never from argv."""

import argparse
import getpass
import json
from pathlib import Path
from typing import Any

from .services.full_recovery import (
    RecoveryLimits,
    RecoveryPlan,
    _configuration,
    _json,
    create_full_backup,
    load_recovered_environment,
    restore_full_backup,
)
from .services.recovery_archive import RecoveryError


def _plan(args):
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    from .settings import ExplicitSettings, Settings
    root = args.data_dir.resolve()
    runtime = root / ".env"
    persisted: dict[str, str | None] = dotenv_values(runtime, interpolate=False) if runtime.exists() else {}
    recovered_config = root / "configuration.json"
    if recovered_config.exists():
        if recovered_config.stat().st_size > 16 * 1024**2:
            raise RecoveryError("Die wiederhergestellte Konfiguration ist zu groß.")
        # Recovery JSON preserves quotes/newlines that a convenience .env cannot.
        persisted.update(_configuration(_json(recovered_config.read_bytes())))
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
    settings = ExplicitSettings(**options)
    values = {key.upper(): value if isinstance(value, str) else json.dumps(value)
              for key, value in settings.model_dump(mode="json").items() if value is not None}
    if args.integrations is not None and not integrations.is_file():
        raise RecoveryError("Die ausdrücklich gewählte Integrationsdatei fehlt.")
    return RecoveryPlan(database, uploads, values, runtime if runtime.exists() else None,
                        integrations if integrations.exists() else None)


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
            load_recovered_environment(args.data_dir)
            import uvicorn

            from .app import app
            uvicorn.run(app, host="127.0.0.1", port=args.port)
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
            result = create_full_backup(_plan(args), args.output, password, offline=args.offline, limits=limits)
        else:
            result = restore_full_backup(args.archive, args.destination, password, limits=limits)
        print(json.dumps(result, ensure_ascii=False))
    except RecoveryError as exc:
        parser.exit(2, f"Fehler: {exc}\n")
    except Exception as exc:
        parser.exit(2, f"Vollsicherung abgebrochen ({type(exc).__name__}); Details nicht ausgegeben.\n")


if __name__ == "__main__":
    main()
