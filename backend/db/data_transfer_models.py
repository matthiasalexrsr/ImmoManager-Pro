"""Durable import previews and portability jobs, distinct from restore operations."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ImportBatchORM(Base):
    __tablename__ = "data_import_batches"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_data_import_command"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    source_system: Mapped[str] = mapped_column(String(100), nullable=False)
    format: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mappings: Mapped[dict] = mapped_column(JSON, nullable=False)
    preview: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_key: Mapped[str | None] = mapped_column(String(100))
    accepted_sha256: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ImportFileORM(Base):
    __tablename__ = "data_import_files"
    __table_args__ = (UniqueConstraint("batch_id", "filename", name="uq_data_import_filename"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("data_import_batches.id", ondelete="RESTRICT"), index=True)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class ExternalReferenceORM(Base):
    __tablename__ = "data_external_references"
    __table_args__ = (UniqueConstraint("portfolio_id", "source_system", "entity", "external_ref", name="uq_data_external_reference"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    source_system: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("data_import_batches.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortabilityExportORM(Base):
    __tablename__ = "data_portability_exports"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_portability_export_command"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ImportedEvidenceORM(Base):
    """Historical business proofs; importing a proof never grants authority."""
    __tablename__ = "data_imported_evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("data_import_batches.id", ondelete="RESTRICT"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
