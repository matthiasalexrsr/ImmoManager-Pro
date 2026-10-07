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

    with engine.connect() as connection:
        before = set(inspect(connection).get_table_names())
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        if "users" in before and "user_portfolio_access" not in before:
            # first start after the update: existing accounts keep what they could see
            adopt_legacy_access(connection)
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


def adopt_legacy_access(connection) -> None:
    """Give every account without an access row its previous installation-wide access."""
    from sqlalchemy import text

    connection.execute(text(
        "INSERT INTO user_portfolio_access (user_id, mode, origin, updated_at) "
        "SELECT id, 'all', 'legacy_all', CURRENT_TIMESTAMP FROM users "
        "WHERE NOT EXISTS (SELECT 1 FROM user_portfolio_access a WHERE a.user_id = users.id)"))
