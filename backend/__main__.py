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
    args = parser.parse_args()

    # When running as frozen .exe, set working directory and sys.path
    base_dir = _get_base_dir()

    if IS_FROZEN:
        os.chdir(base_dir)
        if base_dir not in sys.path:
            sys.path.insert(0, base_dir)

    print(f"ImmoManager Pro v1.0.0")
    print(f"Python {sys.version}")
    if IS_FROZEN:
        print(f"Bundle: {base_dir}")
        print(f"Exe:    {sys.executable}")
    print()

    # Import the app early so import errors are visible before uvicorn starts
    print("Lade Anwendung...")
    try:
        from backend.app import app  # noqa: F811
    except Exception as exc:
        print(f"\nFEHLER beim Laden der Anwendung:\n{exc}")
        import traceback
        traceback.print_exc()
        _pause_console()
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
        _pause_console()
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
    except BaseException as exc:
        # Catch *everything* (SystemExit, KeyboardInterrupt, etc.) so the
        # console window stays open long enough for the user to read errors.
        if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
            print(f"\nUnerwarteter Fehler:\n{exc}")
            import traceback
            traceback.print_exc()
        _pause_console()
    finally:
        if _log_fh:
            try:
                _log_fh.close()
            except OSError:
                pass
