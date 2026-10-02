"""Offline update entry point. Stop the application before running this command."""

import argparse
import json
import socket
from pathlib import Path
from typing import Any, cast


def _listener_running(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Confirm that the application was stopped")
    parser.add_argument("--data-dir", required=True, type=Path, help="Existing application data directory")
    parser.add_argument("--port", type=int, default=8000, help="Port previously used by the application")
    parser.add_argument("--target-version", default=None)
    args = parser.parse_args(argv)
    if not args.offline:
        parser.error("--offline ist erforderlich; zuerst die Anwendung stoppen")
    if not 1 <= args.port <= 65535:
        parser.error("Ungültiger Port")
    if _listener_running(args.port):
        print("Auf diesem Port läuft noch eine Anwendung. Bitte zuerst stoppen.")
        return 1
    if not args.data_dir.is_dir():
        print("Datenordner existiert nicht. Bitte den vorhandenen ImmoManager-Datenordner angeben.")
        return 1
    # Load the same configuration as the normal launcher before importing the
    # updater/store. This does not start the web server or seed business data.
    from .__main__ import _configure_runtime_environment
    _configure_runtime_environment(str(args.data_dir.resolve()))
    from dotenv import dotenv_values

    from . import config
    root = args.data_dir.resolve()
    runtime_env = root / ".env"
    persisted = dotenv_values(runtime_env, interpolate=False) if runtime_env.is_file() else {}
    # The explicitly selected installation wins over a terminal's inherited
    # DATA_DIR/DATABASE_URL/JWT_SECRET_KEY from another running installation.
    selected = {
        "data_dir": str(root),
        "database_url": persisted.get("DATABASE_URL") or "sqlite:///" + (root / "immo_manager.db").as_posix(),
        "uploads_dir": persisted.get("UPLOADS_DIR") or str(root / "uploads"),
        "backup_dir": persisted.get("BACKUP_DIR") or str(root / "backups"),
        "integration_state_file": persisted.get("INTEGRATION_STATE_FILE") or str(root / "integrations.json"),
    }
    if persisted.get("JWT_SECRET_KEY"):
        selected["jwt_secret_key"] = persisted["JWT_SECRET_KEY"]
    config.settings = cast(Any, config.Settings)(_env_file=runtime_env if runtime_env.exists() else None, **selected)
    from . import updater
    updater.settings = config.settings
    updater.configure_runtime_paths()
    # --offline is an explicit maintenance invocation. The web API still obeys
    # the production guard and never runs updates against a live application.
    updater.settings.update_allow_in_production = True
    if not updater.settings.update_repo_url:
        remote = updater._run_git("config", "--get", "remote.origin.url")
        if remote.returncode == 0 and updater._extract_owner_repo(remote.stdout.strip()):
            updater.settings.update_repo_url = remote.stdout.strip()
    result = updater.apply_update(target_version=args.target_version, offline=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
