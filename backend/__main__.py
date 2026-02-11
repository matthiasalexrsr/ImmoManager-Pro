"""CLI launcher for ImmoManager Pro.

Usage:
    python -m backend                    # Start server
    python -m backend --seed             # Seed demo data then start
    python -m backend --port 9000        # Custom port
    python -m backend --no-browser       # Don't open browser
"""

import argparse
import sys
import threading
import time
import webbrowser


def main():
    parser = argparse.ArgumentParser(
        prog="immomanager",
        description="ImmoManager Pro – Immobilienverwaltung",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--seed", action="store_true", help="Load demo data on startup")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    # Seed demo data if requested
    if args.seed:
        print("Lade Demo-Daten...")
        from seed_data import seed
        seed()
        print()

    url = f"http://{args.host}:{args.port}"

    # Auto-open browser after short delay
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)
            print(f"\nÖffne Browser: {url}")
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"ImmoManager Pro startet auf {url}")
    print("Drücke Strg+C zum Beenden.\n")

    try:
        import uvicorn
        uvicorn.run("backend.app:app", host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        print("\nServer beendet.")
        sys.exit(0)


if __name__ == "__main__":
    main()
