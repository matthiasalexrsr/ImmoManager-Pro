"""A private profile fence that a database/configuration rollback cannot undo.

Restore code must generate a NEW file for the destination profile, never copy a
historical fence. It is independent of JWT signing material and AES key rings.
"""

import hashlib
import json
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

from .filesystem_paths import filesystem_path
from .secret_box import write_private_file

AUTO = object()
MAX_BYTES = 512


class EpochUnavailable(RuntimeError):
    """The existing profile fence could not be read or published safely."""


class EpochMismatch(ValueError):
    """A token belongs to a previous or different profile generation."""


def path_for(data_dir: Path) -> Path:
    return Path(data_dir) / "auth" / "session-epoch.json"


def _checked_path(data_dir: Path) -> Path:
    root = Path(data_dir).resolve()
    path = path_for(root)
    if path.parent.resolve() != root / "auth" or path.is_symlink():
        raise EpochUnavailable("Die private Sitzungsgrenze ist nicht verfügbar.")
    return path


def current() -> str | None:
    from ..paths import get_data_dir

    try:
        path = _checked_path(get_data_dir())
        local = filesystem_path(path)
        details = local.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_BYTES:
            raise ValueError("Invalid fence file")
        with local.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Oversized fence file")
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {"version", "epoch"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["epoch"], str) or re.fullmatch(r"[0-9a-f]{64}", value["epoch"]) is None):
            raise ValueError("Invalid fence record")
        return value["epoch"]
    except FileNotFoundError:
        return None  # Deliberate compatibility before this profile's first restore.
    except (OSError, ValueError, TypeError, EpochUnavailable):
        raise EpochUnavailable("Die private Sitzungsgrenze ist nicht verfügbar.") from None


def for_issue(expected=AUTO) -> str | None:
    selected = current()
    if expected is not AUTO and selected != expected:
        raise EpochMismatch()
    return selected


def validate(provided) -> None:
    selected = current()
    if provided != selected or (provided is not None and not isinstance(provided, str)):
        raise EpochMismatch()


def rotate_for_restore(data_dir: Path) -> dict:
    """Publish a fresh destination fence; no historical signing/AES key changes."""
    try:
        path = _checked_path(data_dir)
        filesystem_path(path.parent).mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = (json.dumps({"version": 1, "epoch": secrets.token_hex(32)}, separators=(",", ":")) + "\n").encode()
        write_private_file(path, raw)
        return {"status": "rotated", "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError, EpochUnavailable):
        raise EpochUnavailable("Die private Sitzungsgrenze konnte nicht erneuert werden.") from None


def close_restored_sessions(connection) -> int:
    """Mark restored SQLite families revoked, inside the caller's transaction.

    Older snapshots without the inventory remain supported: their legacy JWTs
    are rejected by the freshly published profile fence. Do not commit here.
    """
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_auth_sessions'").fetchone()
    if not exists:
        return 0
    columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_auth_sessions)")}
    if not {"revoked_at", "revision"}.issubset(columns):
        raise EpochUnavailable("Die wiederhergestellten Sitzungen konnten nicht geschlossen werden.")
    result = connection.execute("UPDATE daily_auth_sessions SET revoked_at=?, revision=revision+1 WHERE revoked_at IS NULL",
                                (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" "),))
    return result.rowcount
