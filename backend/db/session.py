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
from .billing_dispute_models import (
    DISPUTE_MODELS,  # noqa: F401 — register retained dispute originals before fresh setup
)
from .booking_indexes import BOOKING_INDEXES  # noqa: F401 — register scaled booking indexes
from .contract_correspondence_models import CorrespondenceDraftORM  # noqa: F401 — register retained correspondence
from .contract_lifecycle_models import ContractLifecycleDraftORM  # noqa: F401 — register retained lifecycle evidence
from .contract_wizard_models import ContractDraftORM  # noqa: F401 — register reviewed contract metadata
from .credit_models import CreditReceiptORM  # noqa: F401 — register immutable credit metadata
from .datev_models import DatevProfileORM  # noqa: F401 — register DATEV metadata
from .document_version_models import DocumentVersionORM  # noqa: F401 — register immutable document originals
from .form_draft_models import FormDraftORM  # noqa: F401 — register private draft metadata
from .integration_history_models import HISTORY_MODELS
from .measurement_history_models import MEASUREMENT_MODELS  # noqa: F401 — register historical sources before create_all
from .operational_job_models import JOB_MODELS
from .operational_models import OperationalTickORM  # noqa: F401 — register scheduler metadata
from .operational_scheduler_models import OperationalSchedulerORM  # noqa: F401 — register durable coordinator
from .orm_models import Base
from .outbox_models import OutboxMessageORM  # noqa: F401 — register durable SMTP metadata
from .rent_batch_models import RentBatchORM  # noqa: F401 — register durable rental metadata
from .session_models import AuthSessionORM  # noqa: F401 — register account security metadata
from .tax_models import AnnualTaxProfileORM  # noqa: F401 — register retained annual evidence before create_all
from .tenancy_workflow_models import TENANCY_WORKFLOW_MODELS

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


def create_history_tables() -> None:
    """Explicit fresh setup on the existing engine, also for Memory domain."""
    from typing import cast

    from sqlalchemy import Table

    from .integration_history_schema import ensure_history_schema, install_history_guards

    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        if ensure_history_schema(connection):
            return  # Existing complete journals require no startup DDL/repair.
        Base.metadata.create_all(bind=connection, tables=[cast(Table, model.__table__) for model in HISTORY_MODELS])
        install_history_guards(connection)


def create_tables() -> None:
    """Create all tables (dev/test convenience). Use Alembic for production."""
    if settings.is_production:
        raise RuntimeError("Production schema changes require the explicit Alembic maintenance command.")
    # Do not let create_all silently repair one half of a damaged retained pair.
    present = set(inspect(engine).get_table_names())
    from .retained_family_schema import require_complete_family

    require_complete_family(engine, TENANCY_WORKFLOW_MODELS, "tenancy workflow")
    require_complete_family(engine, JOB_MODELS, "operational job")
    from .billing_dispute_schema import validate_dispute_guards, validate_dispute_schema
    from .measurement_history_schema import validate_measurement_guards, validate_measurement_schema
    with engine.connect() as connection:
        dispute_present = validate_dispute_schema(connection)
        if dispute_present:
            validate_dispute_guards(connection)
        measurement_present = validate_measurement_schema(connection)
        if measurement_present:
            validate_measurement_guards(connection)
    from .integration_history_schema import ensure_history_schema
    with engine.connect() as connection:
        ensure_history_schema(connection)
    correspondence_tables = {"contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events"}
    if present & correspondence_tables and not correspondence_tables <= present:
        raise RuntimeError("Incomplete contract correspondence journal schema; explicit schema recovery is required")
    for name in correspondence_tables & present:
        columns = {column["name"] for column in inspect(engine).get_columns(name)}
        if not set(Base.metadata.tables[name].c.keys()) <= columns:
            raise RuntimeError("Incomplete contract correspondence columns; explicit schema recovery is required")
    lifecycle_tables = {"contract_lifecycle_drafts", "contract_lifecycle_commands"}
    if present & lifecycle_tables and not lifecycle_tables <= present:
        raise RuntimeError("Incomplete contract lifecycle journal schema; explicit schema recovery is required")
    bootstrap_legacy_access = not inspect(engine).has_table("user_portfolio_access")
    create_history_tables()
    Base.metadata.create_all(bind=engine)
    from ..services.invoice_payment_schema import ensure_invoice_payment_columns, ensure_invoice_payment_immutability
    from ..services.portfolio_scope import ensure_portfolio_access_schema
    from .bank_import_schema import ensure_bank_import_schema
    from .contract_correspondence_models import ensure_contract_correspondence_schema
    from .contract_lifecycle_models import ensure_contract_lifecycle_schema
    from .contract_wizard_models import ensure_contract_wizard_schema
    from .document_version_models import ensure_document_version_schema
    from .form_draft_models import ensure_form_draft_schema
    from .operational_job_models import ensure_operational_job_schema
    from .outbox_models import ensure_outbox_schema
    from .rent_batch_schema import ensure_rent_batch_schema
    from .session_models import ensure_session_schema
    from .tenancy_workflow_schema import ensure_tenancy_workflow_schema
    with engine.begin() as connection:
        if not dispute_present:
            from .billing_dispute_schema import install_dispute_guards
            install_dispute_guards(connection)  # Explicit fresh dev/test setup only.
        if not measurement_present:
            from .measurement_history_schema import install_measurement_guards
            install_measurement_guards(connection)  # Explicit dev/test convenience; never production.
        ensure_portfolio_access_schema(connection, bootstrap_legacy=bootstrap_legacy_access)
        ensure_rent_batch_schema(connection)
        ensure_outbox_schema(connection)
        ensure_session_schema(connection)
        ensure_bank_import_schema(connection)
        ensure_contract_wizard_schema(connection)
        ensure_contract_lifecycle_schema(connection)
        ensure_contract_correspondence_schema(connection)
        ensure_document_version_schema(connection)
        ensure_invoice_payment_columns(connection)
        ensure_invoice_payment_immutability(connection)
        ensure_form_draft_schema(connection)
        ensure_tenancy_workflow_schema(connection)
        ensure_operational_job_schema(connection)
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
