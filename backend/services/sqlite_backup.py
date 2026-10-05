"""Consistent SQLite copies via SQLite's online backup API.

Plain file copies are wrong for a database in WAL mode that the server
keeps open: a copy of the main file misses commits still in the -wal file,
and copying over the live file lets the old WAL be replayed on top of the
restored data (the restore silently does nothing, or corrupts pages).
"""

import sqlite3
from pathlib import Path


def sqlite_path_from_url(database_url: str) -> Path | None:
    """Return the file path of a sqlite:/// URL, or None for other databases."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url[len(prefix):])


def copy_database(source: Path, target: Path) -> None:
    """Copy source into target page by page, safe while either is in use."""
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    from ..concurrency import note_change

    note_change()      # written past the sessions: nothing read before is valid


def is_sqlite_database(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False
