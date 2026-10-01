"""Database session management with connection pooling.

Supports PostgreSQL (prod) and SQLite (dev/test) via settings.database_url.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
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
    Base.metadata.create_all(bind=engine)
    # Local installations historically used create_all without Alembic stamping.
    # Apply this additive column upgrade there as well, preserving existing data.
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            if "amount_paid" not in {column["name"] for column in inspect(connection).get_columns("receivables")}:
                connection.execute(text("ALTER TABLE receivables ADD COLUMN amount_paid NUMERIC(12, 2) NOT NULL DEFAULT 0"))
                connection.execute(text("UPDATE receivables SET amount_paid = amount_due WHERE status = 'paid'"))


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
