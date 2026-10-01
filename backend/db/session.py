"""Database session management with connection pooling.

Supports PostgreSQL (prod) and SQLite (dev/test) via settings.database_url.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .auth_models import AuthSetupORM  # noqa: F401 — register auth metadata before create_all
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
            if "allocated_amount" not in {column["name"] for column in inspect(connection).get_columns("bookings")}:
                connection.execute(text("ALTER TABLE bookings ADD COLUMN allocated_amount NUMERIC(12, 2) NOT NULL DEFAULT 0"))
            if "booking_id" not in {column["name"] for column in inspect(connection).get_columns("payments")}:
                connection.execute(text("ALTER TABLE payments ADD COLUMN booking_id VARCHAR REFERENCES bookings(id) ON DELETE RESTRICT"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS idx_payments_booking ON payments (booking_id)"))
            # Older local databases had cascading receipt FKs. Preserve audit history
            # without rebuilding these tables and their existing data.
            for table, column in (("receivables", "receivable_id"), ("rent_charges", "rent_charge_id"), ("bookings", "booking_id")):
                connection.execute(text(f"""CREATE TRIGGER IF NOT EXISTS preserve_payments_{table}
                    BEFORE DELETE ON {table} WHEN EXISTS(SELECT 1 FROM payments WHERE {column} = OLD.id)
                    BEGIN SELECT RAISE(ABORT, 'Payment history must be preserved'); END"""))
            from ..services.rent_ledger import ensure_unique_month_schema
            ensure_unique_month_schema(connection)
            from ..services.billing_settlement import ensure_billing_schema
            ensure_billing_schema(connection)
            from ..services.billing_settlement import ensure_owner_share_schema
            ensure_owner_share_schema(connection)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
