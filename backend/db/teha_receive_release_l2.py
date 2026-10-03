"""Frozen initial L2 release DDL, independent of runtime ORM registration.

This revision has never shipped. Its two-table layout is now fixed, including
the exact immutable mapping reference on receipts. Do not derive historical DDL
from current models or silently reconcile an older isolated development layout.
"""

from sqlalchemy import (
    JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    MetaData, String, Table, UniqueConstraint, text,
)

L2_TABLE_NAMES = ("teha_external_mappings", "teha_import_receipts")


def frozen_l2_tables() -> tuple[Table, Table]:
    metadata = MetaData()
    # Foreign-key compilation needs these names; only the two L2 tables below
    # are ever created/dropped by this migration, never its existing parents.
    for name in (
        "portfolios", "properties", "billing_periods", "units", "tenants",
        "tasks", "integration_runs", "operational_jobs",
        "operational_work_items", "documents", "document_versions",
    ):
        Table(name, metadata, Column("id", String, primary_key=True))

    def reference(name, target, *, nullable=True):
        return Column(name, String, ForeignKey(target + ".id", ondelete="RESTRICT"), nullable=nullable)

    mappings = Table(
        L2_TABLE_NAMES[0], metadata,
        Column("id", String, primary_key=True),
        reference("portfolio_id", "portfolios", nullable=False),
        Column("connection_key", String(200), nullable=False),
        Column("kind", String(32), nullable=False),
        Column("external_identity_hash", String(64), nullable=False),
        Column("external_identity_json", JSON, nullable=False),
        reference("internal_property_id", "properties"),
        reference("billing_period_id", "billing_periods"),
        reference("unit_id", "units"),
        reference("tenant_id", "tenants"),
        reference("task_id", "tasks"),
        Column("generation", Integer, nullable=False),
        Column("state", String(20), nullable=False),
        Column("revision", String(64), nullable=False),
        Column("confirmed_by", String, nullable=False),
        Column("confirmed_at", DateTime, nullable=False),
        reference("source_history_run_id", "integration_runs", nullable=False),
        Column("source_sha256", String(64), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        UniqueConstraint("connection_key", "kind", "external_identity_hash", "generation", name="uq_teha_mapping_generation"),
        CheckConstraint("kind IN ('property','period','unit','user','technical_order')", name="ck_teha_mapping_kind"),
        CheckConstraint("generation > 0", name="ck_teha_mapping_generation_positive"),
        CheckConstraint("state='confirmed'", name="ck_teha_mapping_state"),
        CheckConstraint("length(external_identity_hash)=64 AND external_identity_hash=lower(external_identity_hash)", name="ck_teha_mapping_identity_sha"),
        CheckConstraint("length(source_sha256)=64 AND source_sha256=lower(source_sha256)", name="ck_teha_mapping_source_sha"),
        CheckConstraint(
            "(kind='property' AND internal_property_id IS NOT NULL AND billing_period_id IS NULL AND unit_id IS NULL AND tenant_id IS NULL AND task_id IS NULL) OR "
            "(kind='period' AND internal_property_id IS NULL AND billing_period_id IS NOT NULL AND unit_id IS NULL AND tenant_id IS NULL AND task_id IS NULL) OR "
            "(kind='unit' AND internal_property_id IS NULL AND billing_period_id IS NULL AND unit_id IS NOT NULL AND tenant_id IS NULL AND task_id IS NULL) OR "
            "(kind='user' AND internal_property_id IS NULL AND billing_period_id IS NULL AND unit_id IS NULL AND tenant_id IS NOT NULL AND task_id IS NULL) OR "
            "(kind='technical_order' AND internal_property_id IS NULL AND billing_period_id IS NULL AND unit_id IS NULL AND tenant_id IS NULL AND task_id IS NOT NULL)",
            name="ck_teha_mapping_target_shape",
        ),
        Index("ix_teha_mapping_lookup", "connection_key", "kind", "external_identity_hash", "generation"),
        Index("ix_teha_mapping_portfolio", "portfolio_id", "kind", "updated_at", "id"),
    )
    receipts = Table(
        L2_TABLE_NAMES[1], metadata,
        Column("id", String, primary_key=True),
        reference("portfolio_id", "portfolios", nullable=False),
        Column("connection_key", String(200), nullable=False),
        reference("operational_job_id", "operational_jobs"),
        reference("work_item_id", "operational_work_items"),
        reference("source_history_run_id", "integration_runs", nullable=False),
        Column("source_kind", String(32), nullable=False),
        Column("external_identity_hash", String(64), nullable=False),
        Column("mapping_generation", Integer, nullable=False),
        reference("mapping_id", "teha_external_mappings", nullable=False),
        Column("mapping_sha256", String(64), nullable=False),
        Column("source_sha256", String(64), nullable=False),
        Column("content_sha256", String(64)),
        reference("document_id", "documents"),
        reference("document_version_id", "document_versions"),
        reference("task_id", "tasks"),
        Column("state", String(20), nullable=False),
        Column("command_key", String(100), nullable=False),
        Column("command_sha256", String(64), nullable=False),
        Column("imported_by", String, nullable=False),
        Column("imported_at", DateTime, nullable=False),
        UniqueConstraint("imported_by", "command_key", name="uq_teha_import_command"),
        CheckConstraint("source_kind IN ('document','technical_order')", name="ck_teha_import_source_kind"),
        CheckConstraint("mapping_generation > 0", name="ck_teha_import_mapping_generation"),
        CheckConstraint("state='imported'", name="ck_teha_import_state"),
        CheckConstraint("length(external_identity_hash)=64 AND external_identity_hash=lower(external_identity_hash)", name="ck_teha_import_identity_sha"),
        CheckConstraint("length(source_sha256)=64 AND source_sha256=lower(source_sha256)", name="ck_teha_import_source_sha"),
        CheckConstraint("length(command_sha256)=64 AND command_sha256=lower(command_sha256)", name="ck_teha_import_command_sha"),
        CheckConstraint("length(mapping_sha256)=64 AND mapping_sha256=lower(mapping_sha256)", name="ck_teha_import_mapping_sha"),
        CheckConstraint("content_sha256 IS NULL OR (length(content_sha256)=64 AND content_sha256=lower(content_sha256))", name="ck_teha_import_content_sha"),
        CheckConstraint("work_item_id IS NULL OR operational_job_id IS NOT NULL", name="ck_teha_import_work_item_job"),
        CheckConstraint(
            "(source_kind='document' AND content_sha256 IS NOT NULL AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND task_id IS NULL) OR "
            "(source_kind='technical_order' AND content_sha256 IS NULL AND document_id IS NULL AND document_version_id IS NULL AND task_id IS NOT NULL)",
            name="ck_teha_import_target_shape",
        ),
        Index("uq_teha_import_document_version", "connection_key", "external_identity_hash", "source_sha256", "content_sha256", unique=True,
              sqlite_where=text("source_kind='document'"), postgresql_where=text("source_kind='document'")),
        Index("uq_teha_import_task_version", "connection_key", "external_identity_hash", "source_sha256", unique=True,
              sqlite_where=text("source_kind='technical_order'"), postgresql_where=text("source_kind='technical_order'")),
        Index("ix_teha_import_portfolio", "portfolio_id", "imported_at", "id"),
        Index("ix_teha_import_history", "source_history_run_id", "source_kind", "id"),
    )
    return mappings, receipts
