"""Narrow offline container hook. Configuration enters through a private pipe."""

import argparse
import json
import os
import sys
import time


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Ungültige Argumente; Konfiguration ausschließlich über geschützte stdin-Pipe.\n")


def main(argv=None):
    parser = _ArgumentParser(description="Offline-Sitzungen vor Restore-Appstart beenden")
    parser.add_argument("--configuration-stdin", action="store_true", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    if not 0 < args.timeout_seconds <= 86400 or sys.stdin.isatty():
        parser.error("Geschützte Konfigurationspipe und positives Zeitlimit erforderlich")
    try:
        raw = sys.stdin.buffer.read(16 * 1024**2 + 1)
        if len(raw) > 16 * 1024**2:
            raise ValueError()
        original = json.loads(raw)
        if not isinstance(original, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in original.items()):
            raise ValueError()
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError()
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url

        from backend.services.recovery_sessions import invalidate_and_inspect

        url = make_url(database_url)
        if url.get_backend_name() not in {"postgresql", "sqlite"}:
            raise ValueError()
        deadline = time.monotonic() + args.timeout_seconds
        engine = create_engine(url, connect_args={"connect_timeout": max(1, int(args.timeout_seconds))} if url.get_backend_name() == "postgresql" else {})
        try:
            with engine.begin() as connection:
                if url.get_backend_name() == "postgresql":
                    connection.exec_driver_sql("SET LOCAL statement_timeout = " + str(max(1, int(args.timeout_seconds * 1000))))
                report = invalidate_and_inspect(connection, original, deadline=deadline)
        finally:
            engine.dispose()
        print(json.dumps(report, separators=(",", ":")))
        return 0
    except Exception:
        print("restore_session_security_failed: Appstart verweigert; neues Ziel zur Prüfung erhalten", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
