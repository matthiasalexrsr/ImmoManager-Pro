"""Database session management with connection pooling.

Supports PostgreSQL (prod) and SQLite (dev/test) via settings.database_url.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .access_models import UserAccessORM  # noqa: F401 — register access metadata before create_all
from .auth_models import AuthSetupORM  # noqa: F401 — register auth metadata before create_all
from .bank_import_models import BankImportORM  # noqa: F401 — register retained bank import provenance
from .booking_indexes import BOOKING_INDEXES  # noqa: F401 — register scaled booking indexes
from .credit_models import CreditReceiptORM  # noqa: F401 — register immutable credit metadata
from .datev_models import DatevProfileORM  # noqa: F401 — register DATEV metadata
from .operational_models import OperationalTickORM  # noqa: F401 — register scheduler metadata
from .orm_models import Base
from .outbox_models import OutboxMessageORM  # noqa: F401 — register durable SMTP metadata
from .rent_batch_models import RentBatchORM  # noqa: F401 — register durable rental metadata
from .session_models import AuthSessionORM  # noqa: F401 — register account security metadata
from .tax_models import AnnualTaxProfileORM  # noqa: F401 — register retained annual evidence before create_all

DATABASE_URL = settings.database_url

_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    hide_parameters=True,
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
    bootstrap_legacy_access = not inspect(engine).has_table("user_portfolio_access")
    Base.metadata.create_all(bind=engine)
    from ..services.portfolio_scope import ensure_portfolio_access_schema
    from .bank_import_schema import ensure_bank_import_schema
    from .outbox_models import ensure_outbox_schema
    from .rent_batch_schema import ensure_rent_batch_schema
    from .session_models import ensure_session_schema
    with engine.begin() as connection:
        ensure_portfolio_access_schema(connection, bootstrap_legacy=bootstrap_legacy_access)
        ensure_rent_batch_schema(connection)
        ensure_outbox_schema(connection)
        ensure_session_schema(connection)
        ensure_bank_import_schema(connection)
    # Local installations historically used create_all without Alembic stamping.
    # Apply this additive column upgrade there as well, preserving existing data.
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            from ..compat.ui_contracts import ensure_ui_contract_schema
            ensure_ui_contract_schema(connection)
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
            from ..services.operational_schedule import ensure_operational_schema
            ensure_operational_schema(connection)
            from ..services.rent_adjustments import ensure_rent_adjustment_schema
            ensure_rent_adjustment_schema(connection)
            from ..services.iban_schema import ensure_account_encryption_schema
            ensure_account_encryption_schema(connection)
            from .booking_indexes import ensure_booking_indexes
            ensure_booking_indexes(connection)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
