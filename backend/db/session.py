"""Database session management with connection pooling.

Supports PostgreSQL (prod) and SQLite (dev/test) via settings.database_url.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .orm_models import Base

DATABASE_URL = settings.database_url

_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

# Enable WAL mode and foreign keys for SQLite
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_tables() -> None:
    """Create all tables (dev/test convenience). Use Alembic for production."""
    from .document_version_models import ARCHIVE_TABLES, install_guards

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        # also for archive tables that existed before (create_all skipped them)
        if set(ARCHIVE_TABLES) <= set(inspect(connection).get_table_names()):
            install_guards(connection)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
