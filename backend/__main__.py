"""CLI launcher for ImmoManager Pro.

Usage:
    python -m backend                    # Start server
    python -m backend --seed             # Seed demo data then start
    python -m backend --port 9000        # Custom port
    python -m backend --no-browser       # Don't open browser

Also works as PyInstaller-bundled .exe:
    ImmoManager-Pro.exe
    ImmoManager-Pro.exe --seed --port 9000
"""

import multiprocessing
import os
import secrets
import socket
import sys

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
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return os.path.join(base, "ImmoManagerPro")
    return os.path.join(os.path.expanduser("~"), "AppData", "Local", "ImmoManagerPro")


def _sqlite_url(db_path):
    return "sqlite:///" + os.path.abspath(db_path).replace(os.sep, "/")


def _load_env_file(path):
    """Load a simple KEY=VALUE file without overriding existing env vars."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        print(f"WARNUNG: Runtime-Konfiguration konnte nicht gelesen werden: {path}")


def _persist_env_default(config_file, key, value):
    """Set an env default and persist it for future frozen/source launches."""
    current = os.environ.get(key)
    if current and current != "dev-secret-key-change-in-production":
        return current

    os.environ[key] = value
    try:
        existing = ""
        if os.path.isfile(config_file):
            with open(config_file, "r", encoding="utf-8") as fh:
                existing = fh.read()
        lines = [line for line in existing.splitlines() if not line.startswith(f"{key}=")]
        lines.append(f"{key}={value}")
        with open(config_file, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        print(f"WARNUNG: Runtime-Konfiguration konnte nicht geschrieben werden: {config_file}")
    return value


def _configure_runtime_environment(data_dir_arg=None):
    """Prepare safe local runtime defaults before importing backend.app."""
    project_env = os.path.join(_exe_dir(), ".env")
    _load_env_file(project_env)

    data_dir = data_dir_arg or os.environ.get("DATA_DIR")
    if not data_dir and (IS_FROZEN or os.name == "nt"):
        data_dir = _default_windows_data_dir()

    if not data_dir:
        return None

    data_dir = os.path.abspath(os.path.expanduser(data_dir))
    uploads_dir = os.path.join(data_dir, "uploads")
    backups_dir = os.path.join(data_dir, "backups")
    logs_dir = os.path.join(data_dir, "logs")
    for path in (data_dir, uploads_dir, backups_dir, logs_dir):
        os.makedirs(path, exist_ok=True)

    runtime_env = os.path.join(data_dir, ".env")
    _load_env_file(runtime_env)

    _persist_env_default(runtime_env, "DATA_DIR", data_dir)
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
    """Write a startup log next to the .exe so errors survive a closed console."""
    if not IS_FROZEN:
        return None
    log_path = os.path.join(_exe_dir(), "immo_startup.log")
    try:
        fh = open(log_path, "w", encoding="utf-8")
        return fh
    except OSError:
        return None


def _pause_console():
    """Keep the console window open so the user can read output."""
    if IS_FROZEN:
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
        self.original.write(text)
        if self.log_file:
            try:
                self.log_file.write(text)
                self.log_file.flush()
            except OSError:
                pass

    def flush(self):
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


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="immomanager",
        description="ImmoManager Pro – Immobilienverwaltung",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--seed", action="store_true", help="Load demo data on startup")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--data-dir", default=None, help="Persistent data directory for SQLite, uploads, backups, and logs")
    args = parser.parse_args()

    # When running as frozen .exe, set working directory and sys.path
    base_dir = _get_base_dir()

    if IS_FROZEN:
        os.chdir(base_dir)
        if base_dir not in sys.path:
            sys.path.insert(0, base_dir)

    data_dir = _configure_runtime_environment(args.data_dir)

    print("ImmoManager Pro v1.0.0")
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
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
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
    except BaseException as exc:
        print(f"\nUnerwarteter Fehler:\n{exc}")
        import traceback
        traceback.print_exc()
        _pause_console()
    finally:
        if _log_fh:
            try:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                _log_fh.close()
            except OSError:
                pass
