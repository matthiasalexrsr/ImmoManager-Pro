"""Persistent TEHA mapping generations and immutable import receipts.

Private/raw provider payloads never belong in these tables. They remain in the
encrypted integration history. external_identity_json contains only the opaque
identity components needed to bind a mapping.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .document_version_models import DocumentVersionORM  # noqa: F401
from .integration_history_models import IntegrationRunORM  # noqa: F401
from .operational_job_models import OperationalJobORM, OperationalWorkItemORM  # noqa: F401
from .orm_models import (
    Base,
    BillingPeriodORM,  # noqa: F401
    DocumentORM,  # noqa: F401
    PropertyORM,  # noqa: F401
    TaskORM,  # noqa: F401
    TenantORM,  # noqa: F401
    UnitORM,  # noqa: F401
)

_SHA_CHECK = (
    "length(external_identity_hash)=64 "
    "AND external_identity_hash=lower(external_identity_hash)"
)
_SOURCE_SHA_CHECK = (
    "length(source_sha256)=64 AND source_sha256=lower(source_sha256)"
)
_COMMAND_SHA_CHECK = (
    "length(command_sha256)=64 AND command_sha256=lower(command_sha256)"
)
_MAPPING_SHA_CHECK = (
    "length(mapping_sha256)=64 AND mapping_sha256=lower(mapping_sha256)"
)


class TehaExternalMappingORM(Base):
    __tablename__ = "teha_external_mappings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    connection_key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_identity_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    internal_property_id: Mapped[str | None] = mapped_column(
        ForeignKey("properties.id", ondelete="RESTRICT")
    )
    billing_period_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_periods.id", ondelete="RESTRICT")
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT")
    )
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT")
    )

    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_history_run_id: Mapped[str] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "connection_key",
            "kind",
            "external_identity_hash",
            "generation",
            name="uq_teha_mapping_generation",
        ),
        CheckConstraint(
            "kind IN ('property','period','unit','user','technical_order')",
            name="ck_teha_mapping_kind",
        ),
        CheckConstraint("generation > 0", name="ck_teha_mapping_generation_positive"),
        CheckConstraint("state='confirmed'", name="ck_teha_mapping_state"),
        CheckConstraint(_SHA_CHECK, name="ck_teha_mapping_identity_sha"),
        CheckConstraint(_SOURCE_SHA_CHECK, name="ck_teha_mapping_source_sha"),
        CheckConstraint(
            "("
            "kind='property' AND internal_property_id IS NOT NULL "
            "AND billing_period_id IS NULL AND unit_id IS NULL "
            "AND tenant_id IS NULL AND task_id IS NULL"
            ") OR ("
            "kind='period' AND internal_property_id IS NULL "
            "AND billing_period_id IS NOT NULL AND unit_id IS NULL "
            "AND tenant_id IS NULL AND task_id IS NULL"
            ") OR ("
            "kind='unit' AND internal_property_id IS NULL "
            "AND billing_period_id IS NULL AND unit_id IS NOT NULL "
            "AND tenant_id IS NULL AND task_id IS NULL"
            ") OR ("
            "kind='user' AND internal_property_id IS NULL "
            "AND billing_period_id IS NULL AND unit_id IS NULL "
            "AND tenant_id IS NOT NULL AND task_id IS NULL"
            ") OR ("
            "kind='technical_order' AND internal_property_id IS NULL "
            "AND billing_period_id IS NULL AND unit_id IS NULL "
            "AND tenant_id IS NULL AND task_id IS NOT NULL"
            ")",
            name="ck_teha_mapping_target_shape",
        ),
        Index(
            "ix_teha_mapping_lookup",
            "connection_key",
            "kind",
            "external_identity_hash",
            "generation",
        ),
        Index(
            "ix_teha_mapping_portfolio",
            "portfolio_id",
            "kind",
            "updated_at",
            "id",
        ),
    )


class TehaImportReceiptORM(Base):
    __tablename__ = "teha_import_receipts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    connection_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operational_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("operational_jobs.id", ondelete="RESTRICT")
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("operational_work_items.id", ondelete="RESTRICT")
    )
    source_history_run_id: Mapped[str] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_id: Mapped[str] = mapped_column(
        ForeignKey("teha_external_mappings.id", ondelete="RESTRICT"), nullable=False
    )
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))

    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT")
    )
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT")
    )

    state: Mapped[str] = mapped_column(String(20), nullable=False)
    command_key: Mapped[str] = mapped_column(String(100), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_by: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "imported_by",
            "command_key",
            name="uq_teha_import_command",
        ),
        CheckConstraint(
            "source_kind IN ('document','technical_order')",
            name="ck_teha_import_source_kind",
        ),
        CheckConstraint("mapping_generation > 0", name="ck_teha_import_mapping_generation"),
        CheckConstraint("state='imported'", name="ck_teha_import_state"),
        CheckConstraint(_SHA_CHECK, name="ck_teha_import_identity_sha"),
        CheckConstraint(_SOURCE_SHA_CHECK, name="ck_teha_import_source_sha"),
        CheckConstraint(_COMMAND_SHA_CHECK, name="ck_teha_import_command_sha"),
        CheckConstraint(_MAPPING_SHA_CHECK, name="ck_teha_import_mapping_sha"),
        CheckConstraint(
            "content_sha256 IS NULL OR "
            "(length(content_sha256)=64 AND content_sha256=lower(content_sha256))",
            name="ck_teha_import_content_sha",
        ),
        CheckConstraint(
            "work_item_id IS NULL OR operational_job_id IS NOT NULL",
            name="ck_teha_import_work_item_job",
        ),
        CheckConstraint(
            "("
            "source_kind='document' AND content_sha256 IS NOT NULL "
            "AND document_id IS NOT NULL AND document_version_id IS NOT NULL "
            "AND task_id IS NULL"
            ") OR ("
            "source_kind='technical_order' AND content_sha256 IS NULL "
            "AND document_id IS NULL AND document_version_id IS NULL "
            "AND task_id IS NOT NULL"
            ")",
            name="ck_teha_import_target_shape",
        ),
        Index(
            "uq_teha_import_document_version",
            "connection_key",
            "external_identity_hash",
            "source_sha256",
            "content_sha256",
            unique=True,
            sqlite_where=text("source_kind='document'"),
            postgresql_where=text("source_kind='document'"),
        ),
        Index(
            "uq_teha_import_task_version",
            "connection_key",
            "external_identity_hash",
            "source_sha256",
            unique=True,
            sqlite_where=text("source_kind='technical_order'"),
            postgresql_where=text("source_kind='technical_order'"),
        ),
        Index(
            "ix_teha_import_portfolio",
            "portfolio_id",
            "imported_at",
            "id",
        ),
        Index(
            "ix_teha_import_history",
            "source_history_run_id",
            "source_kind",
            "id",
        ),
    )


TEHA_RECEIVE_MODELS = (
    TehaExternalMappingORM,
    TehaImportReceiptORM,
)

TEHA_RECEIVE_TABLES = tuple(model.__tablename__ for model in TEHA_RECEIVE_MODELS)
