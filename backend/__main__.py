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


def _get_base_dir():
    """Return the base directory for bundled resources.

    When running as a PyInstaller bundle, resources are extracted to a
    temporary directory referenced by sys._MEIPASS.  Otherwise, use the
    project root (parent of the backend/ package).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wait_on_error():
    """Keep the console window open on error when running as .exe on Windows."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        print()
        input("Druecke Enter zum Beenden...")


def main():
    # Required for PyInstaller on Windows to avoid multiprocessing issues
    multiprocessing.freeze_support()

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
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        os.chdir(base_dir)
        if base_dir not in sys.path:
            sys.path.insert(0, base_dir)

    print(f"ImmoManager Pro v1.0.0")
    print(f"Python {sys.version}")
    if is_frozen:
        print(f"Bundle: {base_dir}")
    print()

    # Import the app early so import errors are visible before uvicorn starts
    print("Lade Anwendung...")
    try:
        from backend.app import app  # noqa: F811
    except Exception as exc:
        print(f"\nFEHLER beim Laden der Anwendung:\n{exc}")
        import traceback
        traceback.print_exc()
        _wait_on_error()
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
        _wait_on_error()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nUnerwarteter Fehler:\n{exc}")
        import traceback
        traceback.print_exc()
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            input("\nDruecke Enter zum Beenden...")
        sys.exit(1)
