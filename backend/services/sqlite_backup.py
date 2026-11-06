"""Consistent SQLite copies via SQLite's online backup API.

Plain file copies are wrong for a database in WAL mode that the server
keeps open: a copy of the main file misses commits still in the -wal file,
and copying over the live file lets the old WAL be replayed on top of the
restored data (the restore silently does nothing, or corrupts pages).
"""

import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.engine import URL

from .document_version_validation import verify_document_versions
from .filesystem_paths import filesystem_path


def readonly_uri(path: Path) -> str:
    """Opaque SQLite URI, including extended Win32 paths without a URI host."""
    absolute = filesystem_path(path.expanduser().resolve())
    return "file:" + quote(os.fspath(absolute), safe="/:") + "?mode=ro"


def file_url(path: Path) -> URL:
    """A URL object keeps Win32 '?' out of SQLAlchemy string parsing."""
    return URL.create("sqlite", database=os.fspath(filesystem_path(path.expanduser().resolve())))


def sqlite_path_from_url(database_url: str) -> Path | None:
    """Return the file path of a sqlite:/// URL, or None for other databases."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url[len(prefix):])


def copy_database(source: Path, target: Path) -> None:
    """Copy source into target page by page, safe while either is in use."""
    source, target = filesystem_path(source), filesystem_path(target)
    if not source.is_file():
        raise FileNotFoundError("Die zu kopierende SQLite-Datenbank fehlt")
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("Quelle und Ziel der SQLite-Kopie dürfen nicht dieselbe Datei sein")
    if not is_sqlite_database(source):
        raise ValueError("Die Quelle ist keine SQLite-Datenbank")
    src = sqlite3.connect(readonly_uri(source), uri=True)
    try:
        if src.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("Die SQLite-Quelle ist beschädigt")
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
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
        with filesystem_path(path).open("rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def verify_archived_originals(path: Path) -> int:
    """Prove the archived originals in a database file without changing it (ArchiveIntegrityError)."""
    connection = sqlite3.connect(readonly_uri(path), uri=True)
    try:
        return verify_document_versions(connection)
    finally:
        connection.close()


# A restored backup older than the code is brought to the head by the explicit
# upgrade (backend.db.schema_state.run_migrations), never patched table by table.
