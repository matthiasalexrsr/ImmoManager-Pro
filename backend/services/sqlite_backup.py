"""Consistent SQLite copies via SQLite's online backup API.

Plain file copies are wrong for a database in WAL mode that the server
keeps open: a copy of the main file misses commits still in the -wal file,
and copying over the live file lets the old WAL be replayed on top of the
restored data (the restore silently does nothing, or corrupts pages).
"""

import sqlite3
from pathlib import Path
from typing import cast

from sqlalchemy import Table

from .document_version_validation import verify_document_versions


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


def verify_archived_originals(path: Path) -> int:
    """Prove the archived originals in a database file without changing it (ArchiveIntegrityError)."""
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return verify_document_versions(connection)
    finally:
        connection.close()


def ensure_archive_schema(engine) -> None:
    """After a restore from a backup older than the archive: add its tables and guards."""
    from ..db.document_version_models import DOCUMENT_VERSION_MODELS, install_guards

    with engine.begin() as connection:
        for model in DOCUMENT_VERSION_MODELS:
            cast(Table, model.__table__).create(connection, checkfirst=True)
        install_guards(connection)


def ensure_access_schema(engine) -> None:
    """After a restore from a backup older than portfolio access: its accounts keep seeing everything."""
    from sqlalchemy import inspect

    from ..db.access_models import ResourcePortfolioORM, UploadAccessORM, UserAccessORM, UserPortfolioORM
    from ..db.session import adopt_legacy_access

    with engine.begin() as connection:
        before = set(inspect(connection).get_table_names())
        for model in (UserAccessORM, UserPortfolioORM, ResourcePortfolioORM, UploadAccessORM):
            cast(Table, model.__table__).create(connection, checkfirst=True)
        if "users" in before and "user_portfolio_access" not in before:
            adopt_legacy_access(connection)
