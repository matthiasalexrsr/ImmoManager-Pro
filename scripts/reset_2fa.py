"""Offline, local SQLite 2FA recovery. Requires access to the installation data dir."""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def reset_totp(data_dir: Path, user_id: str, reason: str) -> dict:
    """Reset exactly the named account and record the operation in its audit log."""
    if not user_id.strip() or not reason.strip():
        raise ValueError("Benutzer-ID und Begründung sind erforderlich")
    database = data_dir.expanduser().resolve() / "immo_manager.db"
    if not database.is_file():
        raise ValueError("Die lokale Installationsdatenbank wurde nicht gefunden")
    with sqlite3.connect(f"{database.as_uri()}?mode=rw", uri=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        user = connection.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise ValueError("Benutzer-ID wurde nicht gefunden; keine Änderung durchgeführt")
        connection.execute("UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?", (user_id,))
        connection.execute(
            "INSERT INTO audit_logs (id, user_id, username, action, entity_type, entity_id, changes, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), None, "offline_recovery", "reset_2fa", "user", user_id,
             json.dumps({"reason": reason.strip(), "target_username": user[1]}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
    return {"user_id": user[0], "username": user[1], "totp_enabled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokale 2FA-Wiederherstellung bei geschlossenem ImmoManager-Server")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        result = reset_totp(args.data_dir, args.user_id, args.reason)
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Fehler: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
