"""Where a database schema stands against the Alembic head, and the two ways it may change.

Normal start never changes the schema of an existing database: an empty database is
initialised (create_all, then stamped at the head), a database at the head starts, and
everything else is refused with the explicit command. The explicit upgrade
(``python -m backend.upgrade``) takes a full backup first and runs the migrations,
including the adoption of unversioned desktop databases (see migrations/env.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
UPGRADE_COMMAND = "python -m backend.upgrade"
UPGRADE_COMMAND_WINDOWS = "ImmoManager-Pro.exe upgrade"
# tables that do not make a database "in use"
_BOOKKEEPING = frozenset({"alembic_version", "sqlite_sequence", "sqlite_stat1", "sqlite_stat4"})

EMPTY, CURRENT, OUTDATED, UNVERSIONED, NEWER = "empty", "current", "outdated", "unversioned", "newer"


@dataclass(frozen=True)
class SchemaStatus:
    state: str
    revision: str | None
    head: str
    table_count: int

    @property
    def can_start(self) -> bool:
        return self.state in (EMPTY, CURRENT)

    @property
    def needs_upgrade(self) -> bool:
        return self.state in (OUTDATED, UNVERSIONED)

    def describe(self) -> str:
        if self.state == EMPTY:
            return "Leere Datenbank; der erste Start legt das Schema an."
        if self.state == CURRENT:
            return f"Datenbank ist aktuell (Revision {self.head})."
        if self.state == NEWER:
            return (f"Die Datenbank stammt aus einer neueren Programmversion (Revision {self.revision}, dieses "
                    f"Programm kennt höchstens {self.head}). Programm aktualisieren oder eine passende Sicherung "
                    "einspielen; ein Downgrade erfolgt nie automatisch.")
        what = ("wurde ohne Versionsstand angelegt (ältere Desktop-Installation)" if self.state == UNVERSIONED
                else f"hat den Schemastand {self.revision}, dieses Programm erwartet {self.head}")
        return (f"Die Datenbank {what}. Der normale Start ändert das Schema nicht. Upgrade ausdrücklich ausführen "
                f"(legt zuerst ein Vollbackup an): {UPGRADE_COMMAND} – im Windows-Paket: "
                f"{UPGRADE_COMMAND_WINDOWS}.")

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "revision": self.revision, "head": self.head,
                "table_count": self.table_count, "message": self.describe()}


class SchemaUpgradeRequired(RuntimeError):
    """The database is not at the head; normal start refuses instead of changing it."""

    def __init__(self, status: SchemaStatus):
        self.status = status
        super().__init__(status.describe())


def alembic_config(database_url: str | None = None) -> Config:
    """A Config without ini file: never reconfigures the running process's logging."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        config.attributes["database_url"] = database_url
    return config


@lru_cache(maxsize=1)
def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def head_revision() -> str:
    head = _script().get_current_head()
    assert head is not None
    return head


@lru_cache(maxsize=1)
def known_revisions() -> frozenset[str]:
    return frozenset(revision.revision for revision in _script().walk_revisions())


def inspect_connection(connection: Connection) -> SchemaStatus:
    tables = set(inspect(connection).get_table_names())
    in_use = tables - _BOOKKEEPING
    revisions: list[str] = []
    if "alembic_version" in tables:
        revisions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
    head = head_revision()
    if not revisions:
        return SchemaStatus(UNVERSIONED if in_use else EMPTY, None, head, len(in_use))
    revision = revisions[0] if len(revisions) == 1 else ",".join(sorted(revisions))
    if any(item not in known_revisions() for item in revisions):
        return SchemaStatus(NEWER, revision, head, len(in_use))
    return SchemaStatus(CURRENT if revisions == [head] else OUTDATED, revision, head, len(in_use))


def inspect_engine(engine: Engine) -> SchemaStatus:
    with engine.connect() as connection:
        return inspect_connection(connection)


def inspect_url(database_url: str) -> SchemaStatus:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        return inspect_engine(engine)
    finally:
        engine.dispose()


def inspect_sqlite_file(path: Path) -> tuple[SchemaStatus, bool]:
    """Read-only look at a SQLite file (a backup): (status, has the application tables)."""
    import sqlite3

    uri = f"{path.resolve().as_uri()}?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return inspect_connection(connection), inspect(connection).has_table("portfolios")
    finally:
        engine.dispose()


def initialise_empty(engine: Engine) -> None:
    """Create the current schema in an empty database and record it as the head."""
    from ..compat.ui_contracts import ensure_ui_contracts
    from . import (  # noqa: F401  (register the tables)
        access_models,
        document_version_models,
        job_models,
        service_contract_models,
    )
    from .orm_models import Base

    ensure_ui_contracts()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        if set(document_version_models.ARCHIVE_TABLES) <= set(inspect(connection).get_table_names()):
            document_version_models.install_guards(connection)
        MigrationContext.configure(connection).stamp(_script(), "head")


def ensure_current(engine: Engine) -> SchemaStatus:
    """Normal start: initialise an empty database, accept the head, refuse anything else."""
    status = inspect_engine(engine)
    if status.state == EMPTY:
        initialise_empty(engine)
        return inspect_engine(engine)
    if status.state != CURRENT:
        raise SchemaUpgradeRequired(status)
    return status


def run_migrations(database_url: str) -> tuple[SchemaStatus, SchemaStatus]:
    """Bring the database to the head with its own connection (no app pragmas, no pool)."""
    before = inspect_url(database_url)
    if before.state == NEWER:
        raise SchemaUpgradeRequired(before)
    if before.state != CURRENT:
        command.upgrade(alembic_config(database_url), "head")
    after = inspect_url(database_url)
    if after.state != CURRENT:
        raise RuntimeError(f"Upgrade unvollständig: {after.describe()}")
    return before, after
