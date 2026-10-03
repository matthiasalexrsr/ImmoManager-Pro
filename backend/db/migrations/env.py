"""Alembic environment configuration.

Configured to use our ORM models for autogenerate support and DATABASE_URL from env.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.db.access_models import UserAccessORM  # noqa: F401 — register access metadata
from backend.db.auth_models import AuthSetupORM  # noqa: F401 — register auth metadata
from backend.db.bank_import_models import BankImportORM  # noqa: F401 — register retained bank import provenance
from backend.db.booking_indexes import BOOKING_INDEXES  # noqa: F401 — register scaled booking indexes
from backend.db.contract_correspondence_models import (
    CorrespondenceDraftORM,  # noqa: F401 — register retained correspondence
)
from backend.db.contract_lifecycle_models import (
    ContractLifecycleDraftORM,  # noqa: F401 — register retained lifecycle evidence
)
from backend.db.contract_wizard_models import ContractDraftORM  # noqa: F401 — register reviewed contract metadata
from backend.db.credit_models import CreditReceiptORM  # noqa: F401 — register immutable credit metadata
from backend.db.datev_models import DatevProfileORM  # noqa: F401 — register DATEV metadata
from backend.db.document_version_models import DocumentVersionORM  # noqa: F401 — register immutable document originals
from backend.db.form_draft_models import FormDraftORM  # noqa: F401 — register private draft metadata
from backend.db.integration_history_models import HISTORY_MODELS  # noqa: F401 — register independent private journal
from backend.db.measurement_history_models import MEASUREMENT_MODELS  # noqa: F401 — register historical sources
from backend.db.operational_job_models import OperationalJobORM  # noqa: F401 — register resumable jobs
from backend.db.operational_models import OperationalTickORM  # noqa: F401 — register scheduler metadata
from backend.db.operational_scheduler_models import OperationalSchedulerORM  # noqa: F401 — register durable coordinator
from backend.db.orm_models import Base
from backend.db.outbox_models import OutboxMessageORM  # noqa: F401 — register durable SMTP metadata
from backend.db.rent_batch_models import RentBatchORM  # noqa: F401 — register durable rental metadata
from backend.db.session_models import AuthSessionORM  # noqa: F401 — register account security metadata
from backend.db.tax_models import AnnualTaxProfileORM  # noqa: F401 — register retained annual evidence
from backend.db.tenancy_workflow_models import TenancyChangeORM  # noqa: F401 — register frozen workflows

config = context.config

# Override sqlalchemy.url from environment if set
database_url = os.getenv("DATABASE_URL")
if database_url:
    # ConfigParser interprets percent signs. Preserve encoded credentials and
    # connection options such as PostgreSQL's isolated search_path verbatim.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # sqlite3 legacy mode does not begin transactions for DDL. Start
            # before table rebuilding so failures also undo CREATE/DROP.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(
            connection=connection, target_metadata=target_metadata,
            transactional_ddl=True if sqlite else None,
        )

        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
