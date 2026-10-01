"""Local private-server bootstrap: python scripts/server_admin.py initial-owner.

Run inside the server container/installation after database migration. Passwords
are read using getpass (twice), or from a protected, non-terminal stdin pipe with
--password-stdin. No password argument/environment variable is supported. This
tool never launches the application, seeds demo data, or falls back to memory.
"""

import argparse
import getpass
import sys
import warnings
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # Unknown arguments can themselves contain a misplaced secret. Show
        # fixed usage without argparse echoing their original values.
        self.print_usage(sys.stderr)
        self.exit(2, "Ungültige Argumente. Mit --help die unterstützten Optionen anzeigen.\n")


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        if sys.stdin.isatty():
            raise ValueError("Passwort-stdin benötigt eine geschützte Eingabepipe, kein Terminal")
        password = sys.stdin.readline(1026).rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise ValueError("Interaktives Terminal erforderlich; alternativ geschütztes --password-stdin verwenden")
        with warnings.catch_warnings():
            # getpass may otherwise silently fall back to an echoed input on
            # an unsupported terminal. Refuse that fallback before reading.
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Passwort (mindestens 12 Zeichen): ")
            confirmation = getpass.getpass("Passwort wiederholen: ")
        if password != confirmation:
            raise ValueError("Die Passwörter stimmen nicht überein")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Das Passwort muss zwischen 12 und 1024 Zeichen enthalten")
    return password


def bootstrap_owner(username: str, email: str, full_name: str, password: str) -> None:
    """Use the application's SQL marker against its configured existing database."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from backend import auth
    from backend.config import settings
    from backend.models import UserCreate

    payload = UserCreate(username=username, email=email, full_name=full_name, password=password)
    if not username.strip() or not full_name.strip() or not 12 <= len(password) <= 1024:
        raise ValueError("Ungültige Benutzerangaben")
    url = make_url(settings.database_url)
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("Die konfigurierte Datenbank wird nicht unterstützt")
    if url.get_backend_name() == "sqlite":
        # A typo must never create a second, empty installation database.
        if not url.database or url.database == ":memory:" or not Path(url.database).is_file():
            raise ValueError("Die konfigurierte SQLite-Installationsdatenbank fehlt")
        if url.query:
            raise ValueError("SQLite-URI-Optionen werden für die Ersteinrichtung nicht unterstützt")
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    try:
        schema = inspect(engine)
        if not all(schema.has_table(table) for table in ("users", "auth_setup")):
            raise ValueError("Datenbankschema fehlt; zuerst die Servermigrationen ausführen")
        # This deliberately ignores development fallback/seed flags. Importing
        # app/dependencies here would allow a different persistence backend.
        auth.enable_sql_users(sessionmaker(bind=engine))
        auth.create_initial_owner(payload.username, payload.email, payload.full_name,
                                  payload.password, server_password=True)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Lokale Verwaltung des privaten ImmoManager-Servers")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("initial-owner", help="Genau einen ersten Eigentümer in der konfigurierten SQL-Datenbank erstellen")
    owner.add_argument("--username", required=True)
    owner.add_argument("--email", required=True)
    owner.add_argument("--full-name", required=True)
    owner.add_argument("--password-stdin", action="store_true", help="Passwort aus geschützter stdin-Pipe statt getpass lesen")
    args = parser.parse_args(argv)
    try:
        password = _read_password(args.password_stdin)
        bootstrap_owner(args.username, args.email, args.full_name, password)
    except (EOFError, KeyboardInterrupt):
        print("Ersteinrichtung abgebrochen; kein Erfolg bestätigt.", file=sys.stderr)
        return 1
    except Exception as error:
        # Driver/config/validation exceptions can include DSNs and input values.
        # Only our fixed messages or a fixed conflict message may reach stdout.
        from fastapi import HTTPException

        if isinstance(error, HTTPException) and error.status_code == 409:
            message = "Ersteinrichtung wurde bereits abgeschlossen. Keine neue Eigentümeranlage."
        elif type(error) is ValueError and str(error) in {
            "Passwort-stdin benötigt eine geschützte Eingabepipe, kein Terminal",
            "Interaktives Terminal erforderlich; alternativ geschütztes --password-stdin verwenden",
            "Die Passwörter stimmen nicht überein", "Das Passwort muss zwischen 12 und 1024 Zeichen enthalten",
            "Ungültige Benutzerangaben", "Die konfigurierte Datenbank wird nicht unterstützt",
            "Die konfigurierte SQLite-Installationsdatenbank fehlt",
            "SQLite-URI-Optionen werden für die Ersteinrichtung nicht unterstützt",
            "Datenbankschema fehlt; zuerst die Servermigrationen ausführen",
        }:
            message = str(error)
        else:
            message = "Ersteinrichtung fehlgeschlagen. Datenbankkonfiguration, Migrationen und Benutzerangaben lokal prüfen."
        print(message, file=sys.stderr)
        return 1
    print("Initialer Eigentümer erfolgreich in der konfigurierten SQL-Datenbank erstellt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
