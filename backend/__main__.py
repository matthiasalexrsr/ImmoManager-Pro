"""CLI launcher for ImmoManager Pro.

Usage:
    python -m backend                    # Explicit upgrade step (backup first, if needed), then start
    python -m backend --seed             # Seed demo data then start
    python -m backend --port 9000        # Custom port
    python -m backend --no-browser       # Don't open browser
    python -m backend --no-upgrade       # Skip the upgrade step (an outdated database refuses to start)
    python -m backend upgrade [--check]  # Only the explicit upgrade (backend.upgrade)
    python -m backend ops <command>      # Backup, probe, restore (backend.ops)

Also works as PyInstaller-bundled .exe:
    ImmoManager-Pro.exe
    ImmoManager-Pro.exe --seed --port 9000
    ImmoManager-Pro.exe upgrade
    ImmoManager-Pro.exe ops backup
"""

import multiprocessing
import os
import secrets
import socket
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Frozen-bundle detection (used throughout)
# ---------------------------------------------------------------------------
IS_FROZEN = getattr(sys, "frozen", False)


def _get_base_dir():
    """Return the base directory for bundled resources.

    When running as a PyInstaller bundle, resources are extracted to a
    temporary directory referenced by sys._MEIPASS.  Otherwise, use the
    project root (parent of the backend/ package).
    """
    if IS_FROZEN and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe_dir():
    """Return the directory the .exe lives in (not _internal)."""
    if IS_FROZEN:
        return os.path.dirname(sys.executable)
    return _get_base_dir()


def _default_windows_data_dir():
    """Compatibility helper for existing Windows callers."""
    from backend.platform_paths import default_user_data_dir

    return str(default_user_data_dir(platform="win32"))


def _default_data_dir(testversion=False):
    from backend.platform_paths import default_user_data_dir

    return str(default_user_data_dir(testversion=testversion))


def _sqlite_url(db_path):
    return "sqlite:///" + os.path.abspath(db_path).replace(os.sep, "/")


def _load_env_file(path):
    """Load a simple KEY=VALUE file without overriding existing env vars."""
    if not os.path.isfile(path):
        return
    try:
        from dotenv import dotenv_values

        # PyInstaller executes this entry point without a parent package.
        # Existing .env files must load on subsequent frozen launches too.
        from backend.runtime_origins import ENV_FILE_ORIGINS
        for key, value in dotenv_values(path, interpolate=False).items():
            if key and value is not None and key not in os.environ:
                os.environ[key] = value
                ENV_FILE_ORIGINS[key.lower()] = os.path.abspath(path)
    except OSError:
        print(f"WARNUNG: Runtime-Konfiguration konnte nicht gelesen werden: {path}")


def _persist_env_default(config_file, key, value, *, force=False):
    """Set an env default and persist it for future frozen/source launches."""
    current = os.environ.get(key)
    if not force and current and current != "dev-secret-key-change-in-production":
        return current

    os.environ[key] = value
    try:
        existing = ""
        if os.path.isfile(config_file):
            with open(config_file, "r", encoding="utf-8") as fh:
                existing = fh.read()
        lines = [line for line in existing.splitlines() if not line.startswith(f"{key}=")]
        lines.append(f"{key}={value}")
        def private_config_opener(path, flags):
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)

        with open(config_file, "w", encoding="utf-8", opener=private_config_opener) as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        print(f"WARNUNG: Runtime-Konfiguration konnte nicht geschrieben werden: {config_file}")
    return value


def _is_testversion():
    return os.environ.get("IMMO_TESTVERSION", "").strip().lower() in ("1", "true", "yes", "ja")


def _configure_runtime_environment(data_dir_arg=None, testversion=False, demo=False):
    """Prepare safe local runtime defaults before importing backend.app."""
    from backend.demo import configure_environment, enabled
    if demo or enabled():
        if testversion:
            raise RuntimeError("Demo und Testversion können nicht gemeinsam gestartet werden.")
        return str(configure_environment(data_dir_arg))
    project_env = os.path.join(_exe_dir(), ".env")
    _load_env_file(project_env)
    if testversion:
        os.environ["IMMO_TESTVERSION"] = "true"

    data_dir = data_dir_arg or os.environ.get("DATA_DIR")
    if not data_dir:
        data_dir = _default_data_dir(testversion=_is_testversion())

    data_dir = os.path.abspath(os.path.expanduser(data_dir))
    uploads_dir = os.path.join(data_dir, "uploads")
    backups_dir = os.path.join(data_dir, "backups")
    logs_dir = os.path.join(data_dir, "logs")
    for path in (data_dir, uploads_dir, backups_dir, logs_dir):
        os.makedirs(path, mode=0o700, exist_ok=True)

    runtime_env = os.path.join(data_dir, ".env")
    _load_env_file(runtime_env)

    # The selected folder (CLI > environment > native default) must also be the
    # folder backend.paths sees. A copied runtime .env must not redirect it.
    _persist_env_default(runtime_env, "DATA_DIR", data_dir, force=True)
    _persist_env_default(runtime_env, "UPLOADS_DIR", uploads_dir)
    _persist_env_default(runtime_env, "BACKUP_DIR", backups_dir)
    _persist_env_default(runtime_env, "DATABASE_URL", _sqlite_url(os.path.join(data_dir, "immo_manager.db")))
    _persist_env_default(runtime_env, "LOG_FILE", os.path.join(logs_dir, "immomanager.log"))
    _persist_env_default(runtime_env, "INTEGRATION_STATE_FILE", os.path.join(data_dir, "integrations.json"))
    _persist_env_default(runtime_env, "ALLOW_INMEMORY_FALLBACK", "false")
    _persist_env_default(runtime_env, "SQLITE_PERSISTENT_STORE", "true")
    _persist_env_default(runtime_env, "CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000,http://localhost:5173")
    if IS_FROZEN:
        _persist_env_default(runtime_env, "ENVIRONMENT", "production")
        _persist_env_default(runtime_env, "CONTRACT_WIZARD_REQUIRED", "true")

    if os.environ.get("JWT_SECRET_KEY") in (None, "", "dev-secret-key-change-in-production"):
        _persist_env_default(runtime_env, "JWT_SECRET_KEY", secrets.token_urlsafe(48))

    return data_dir


def _port_available(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _setup_logging_to_file():
    """Keep startup diagnostics in writable user data, never the program folder."""
    if not IS_FROZEN:
        return None
    if "--desktop-token" in sys.argv:
        # The GUI owns an already rotating desktop.log for this child's stdout.
        return None
    explicit, _ = _pop_data_dir(sys.argv[1:])
    from backend.demo import configure_environment, enabled
    if "--demo" in sys.argv or enabled():
        directory = str(configure_environment(explicit))
        log_path = os.path.join(directory, "logs", f"immo_startup-{os.getpid()}.log")
        return _StartupLog(log_path)
    try:
        _load_env_file(os.path.join(_exe_dir(), ".env"))
    except (OSError, UnicodeError):
        # Let main() report malformed configuration through its normal error path.
        return None
    directory = explicit or os.environ.get("DATA_DIR") or _default_data_dir(
        testversion=_is_testversion() or "--testversion" in sys.argv)
    log_path = os.path.join(os.path.abspath(os.path.expanduser(directory)), "logs", f"immo_startup-{os.getpid()}.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        return _StartupLog(log_path)
    except OSError:
        return None


class _StartupLog:
    """A bounded UTF-8 stream, with separate files for concurrent CLI processes."""

    def __init__(self, path):
        import logging
        from logging.handlers import RotatingFileHandler

        class QuietFileHandler(RotatingFileHandler):
            def handleError(self, record):
                # A full/read-only disk must not recursively log through the Tee.
                pass

        self.handler = QuietFileHandler(path, mode="a", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        self.handler.terminator = ""
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def write(self, text):
        import logging

        self.handler.handle(logging.LogRecord("startup", logging.INFO, "", 0, text, (), None))
        return len(text)

    def flush(self):
        self.handler.flush()

    def close(self):
        self.handler.close()


def _pause_console():
    """Keep the console window open so the user can read output."""
    if IS_FROZEN and sys.stdin is not None and sys.stdin.isatty():
        print()
        try:
            input("Druecke Enter zum Beenden...")
        except EOFError:
            pass


class _TeeWriter:
    """Write to both the console and a log file simultaneously."""

    def __init__(self, original, log_file):
        self.original = original
        self.log_file = log_file

    def write(self, text):
        try:
            if self.original is not None:
                self.original.write(text)
        except UnicodeEncodeError as exc:
            # Legacy Windows consoles cannot represent every request/log label.
            # Escape only their copy; the UTF-8 startup log keeps the full text.
            encoding = self.encoding or exc.encoding
            self.original.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
        if self.log_file:
            try:
                self.log_file.write(text)
                self.log_file.flush()
            except OSError:
                pass

    def flush(self):
        if self.original is not None:
            self.original.flush()
        if self.log_file:
            try:
                self.log_file.flush()
            except OSError:
                pass

    # Needed so Python treats this as a valid stream
    def isatty(self):
        return getattr(self.original, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self.original, "encoding", "utf-8")


def _pop_data_dir(argv):
    """Remove `--data-dir X` from a tool's arguments; returns (data_dir, remaining)."""
    remaining, data_dir, items = [], None, iter(argv)
    for item in items:
        if item == "--data-dir":
            data_dir = next(items, None)
        elif item.startswith("--data-dir="):
            data_dir = item.split("=", 1)[1]
        else:
            remaining.append(item)
    return data_dir, remaining


def _prepare_frozen_paths():
    base_dir = _get_base_dir()
    if IS_FROZEN:
        os.chdir(base_dir)
        if base_dir not in sys.path:
            sys.path.insert(0, base_dir)
    return base_dir


def run_tool(argv):
    """`upgrade …` and `ops …` with the same runtime paths as a normal start."""
    data_dir, rest = _pop_data_dir(argv[1:])
    _prepare_frozen_paths()
    _configure_runtime_environment(data_dir)
    if argv[0] == "upgrade":
        from backend.upgrade import main as tool_main
    else:
        from backend.ops import main as tool_main
    return tool_main(rest)


def run_upgrade_step():
    """Explicit upgrade before the start: full backup first, only when the schema is behind.

    An empty database is left to the normal start (it initialises it). Returns an exit code.
    """
    from backend.upgrade import EXIT_OK, upgrade

    code = upgrade(backup=True, initialise_empty=False)
    if code != EXIT_OK:
        print()
        print("FEHLER: Das Datenbank-Upgrade wurde nicht ausgeführt; das Programm startet nicht.")
        print("Die Daten sind unverändert (bzw. das Vollbackup liegt im Sicherungsordner unter 'full').")
    return code


def main():
    import argparse

    if sys.argv[1:2] in (["upgrade"], ["ops"]):
        sys.exit(run_tool(sys.argv[1:]))

    parser = argparse.ArgumentParser(
        prog="immomanager",
        description="ImmoManager Pro – Immobilienverwaltung",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 8000; Demo: 8766)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="Open the isolated Baden-Württemberg presentation workspace")
    modes.add_argument("--seed", action="store_true", help="Load legacy seed data on startup")
    modes.add_argument("--testversion", action="store_true",
                        help="Test version: realistic data set and master logins on the first start")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--data-dir", default=None, help="Persistent data directory for SQLite, uploads, backups, and logs")
    parser.add_argument("--no-upgrade", action="store_true",
                        help="Skip the explicit upgrade step; an outdated database then refuses to start")
    parser.add_argument("--desktop-token", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    from backend.demo import enabled as demo_enabled
    if demo_enabled() and (args.seed or args.testversion):
        parser.error("Demo kann nicht mit --seed oder --testversion kombiniert werden.")
    args.demo = args.demo or demo_enabled()
    args.port = args.port if args.port is not None else (8766 if args.demo else 8000)
    if not 1 <= args.port <= 65535:
        parser.error("Der Port muss zwischen 1 und 65535 liegen.")
    if args.demo and args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Der Demobestand ist nur auf diesem Computer erreichbar.")

    # A private inherited pipe is the only desktop control channel. In
    # particular, no unauthenticated HTTP stop endpoint is added to the app.
    desktop_control = None
    if args.desktop_token is not None:
        from backend.desktop_control import DesktopControl

        desktop_control = DesktopControl(args.desktop_token, sys.stdin, sys.stdout)
        desktop_control.start()

    # When running as frozen .exe, set working directory and sys.path
    base_dir = _prepare_frozen_paths()

    data_dir = _configure_runtime_environment(args.data_dir, testversion=args.testversion, demo=args.demo)
    if args.demo:
        os.environ["CORS_ORIGINS"] = f"http://127.0.0.1:{args.port},http://localhost:{args.port}"
    if desktop_control is not None:
        from backend.desktop_control import adopt_instance_guard

        adopt_instance_guard(Path(data_dir))
    testversion = _is_testversion()

    from backend.config import _get_version

    print(f"ImmoManager Pro v{_get_version()}")
    print(f"Python {sys.version}")
    if IS_FROZEN:
        print(f"Bundle: {base_dir}")
        print(f"Exe:    {sys.executable}")
    if data_dir:
        print(f"Daten:  {data_dir}")
    print()

    if not _port_available(args.host, args.port):
        print(f"FEHLER: Port {args.port} auf {args.host} ist bereits belegt.")
        print("Starten Sie die App mit --port 9000 oder beenden Sie den anderen Prozess.")
        sys.exit(1)

    # The schema changes only here, explicitly, with a full backup first; the app itself
    # refuses an outdated database (backend.db.schema_state).
    if not args.no_upgrade:
        print("Pruefe Datenbankstand...")
        code = run_upgrade_step()
        if code:
            sys.exit(code)
        print()

    if desktop_control is not None and desktop_control.stop_requested.is_set():
        return
    if args.demo:
        from backend.demo import install_backend_guards
        install_backend_guards()

    # Import the app early so import errors are visible before uvicorn starts
    print("Lade Anwendung...")
    try:
        from backend.app import app  # noqa: F811
    except Exception as exc:
        print(f"\nFEHLER beim Laden der Anwendung:\n{exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("Anwendung geladen.")

    if testversion:
        try:
            from backend.testversion import seed_testversion
            from backend.testversion.dataset import MASTERS, PASSWORD

            if seed_testversion(app):
                print()
            print("TESTVERSION – alle Daten sind frei erfunden.")
            print("Anmelden mit:")
            for username, email, _name, _role in MASTERS:
                print(f"  {email}  (oder {username})  Passwort: {PASSWORD}")
            print()
        except Exception as exc:
            print(f"FEHLER beim Anlegen der Testdaten:\n{exc}")
            import traceback
            traceback.print_exc()

    # Seed demo data if requested
    if args.seed:
        print("Lade Demo-Daten...")
        try:
            from seed_data import seed
            seed()
        except ImportError:
            print("WARNUNG: seed_data.py nicht gefunden. Demo-Daten werden nicht geladen.")
        except Exception as exc:
            print(f"WARNUNG: Demo-Daten konnten nicht geladen werden: {exc}")
        print()

    url = f"http://{args.host}:{args.port}"

    # Auto-open browser after short delay
    if not args.no_browser:
        import threading
        import time
        import webbrowser

        def open_browser():
            time.sleep(2.0)
            print(f"\nOeffne Browser: {url}")
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Server startet auf {url}")
    print("Druecke Strg+C zum Beenden.\n")

    try:
        import uvicorn

        # Use the imported app object directly instead of string-based import.
        # String-based import ("backend.app:app") can fail in PyInstaller bundles
        # because uvicorn's module loader doesn't find frozen modules.
        server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="info"))
        if desktop_control is not None:
            desktop_control.attach(server, url)
            if desktop_control.stop_requested.is_set():
                return
        server.run()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    except Exception as exc:
        print(f"\nFEHLER beim Starten des Servers:\n{exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # freeze_support() MUST be called immediately after __name__ guard.
    # On Windows frozen bundles, child processes re-execute the script and
    # freeze_support() ensures they exit cleanly instead of re-spawning.
    multiprocessing.freeze_support()

    from backend.desktop_control import ensure_standard_streams, hold_installation_mutex

    ensure_standard_streams()
    from backend.demo import enabled as demo_enabled
    from backend.demo import install_backend_guards
    if demo_enabled() and sys.argv[1:2] in (["document-text-worker"], ["document-pdf-worker"], ["e-invoice-read-worker"], ["e-invoice-limit-worker"]):
        install_backend_guards()
    # Keep the install/update guard while any CLI/worker is using bundled code.
    _installation_mutex = hold_installation_mutex()

    # A fixed, isolated native UI acceptance entry point. It runs in this
    # executable's frozen interpreter so Qt and its helper use one bundle.
    # Dispatch before loading any live runtime configuration or logfile.
    if sys.argv[1:2] == ["desktop-runtime-check"]:
        from scripts.check_desktop_runtime import main as desktop_runtime_check_main

        raise SystemExit(desktop_runtime_check_main(sys.argv[2:]))

    if sys.argv[1:2] == ['e-invoice-limit-worker']:
        from backend.services.e_invoice.posix_worker import main as e_invoice_limit_main
        e_invoice_limit_main(sys.argv[2:])
        raise SystemExit(0)

    if sys.argv[1:2] == ["e-invoice-read-worker"]:
        if len(sys.argv) != 3:
            raise SystemExit(2)
        from backend.services.e_invoice.worker import main as e_invoice_worker_main
        e_invoice_worker_main(sys.argv[2])
        raise SystemExit(0)

    # Native PDF subprocesses must bypass the server launcher and its live
    # runtime configuration/logfile, including in a frozen Windows bundle.
    if sys.argv[1:2] == ["document-text-worker"]:
        if len(sys.argv) != 3:
            raise SystemExit(2)
        from backend.services.document_text_worker import main as document_text_worker_main

        document_text_worker_main(sys.argv[2])
        raise SystemExit(0)

    if sys.argv[1:2] == ["document-pdf-worker"]:
        if len(sys.argv) != 3:
            raise SystemExit(2)
        from backend.services.document_pdf_worker import main as document_worker_main

        document_worker_main(sys.argv[2])
        raise SystemExit(0)

    # Set up a log file next to the .exe so errors survive a closed console
    _log_fh = _setup_logging_to_file()
    if _log_fh:
        sys.stdout = _TeeWriter(sys.__stdout__, _log_fh)
        sys.stderr = _TeeWriter(sys.__stderr__, _log_fh)

    try:
        main()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    except SystemExit as exc:
        # Pause on errors (non-zero exit) so the user can read output.
        # Clean exit (code 0 or None) should close the console normally.
        if exc.code:
            _pause_console()
        raise
    except BaseException as exc:
        print(f"\nUnerwarteter Fehler:\n{exc}")
        import traceback
        traceback.print_exc()
        _pause_console()
        raise SystemExit(1) from exc
    finally:
        if _log_fh:
            try:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                _log_fh.close()
            except OSError:
                pass
