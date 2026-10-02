"""Append-only document originals; registered by application bootstrap."""

from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class DocumentVersionORM(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    predecessor_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    restored_from_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("document_id", "number", name="uq_document_version_number"),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_document_version_command"),
        CheckConstraint("number > 0 AND size_bytes >= 0", name="ck_document_version_values"),
        CheckConstraint("operation IN ('archive_original','upload','restore')", name="ck_document_version_operation"),
        Index("ix_document_versions_subject", "tenant_id", "document_id", "number"),
        Index("ix_document_versions_portfolio", "portfolio_id", "document_id", "number"),
    )


class DocumentVersionChunkORM(Base):
    __tablename__ = "document_version_chunks"
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (CheckConstraint("position >= 0 AND length(data) BETWEEN 1 AND 65536", name="ck_document_chunk_values"),)


DOCUMENT_VERSION_MODELS = (DocumentVersionORM, DocumentVersionChunkORM)


def ensure_document_version_schema(connection):
    for model in DOCUMENT_VERSION_MODELS:
        cast(Table, model.__table__).create(connection, checkfirst=True)
    from importlib import import_module
    import_module("backend.db.migrations.versions.y1a2b3c4d5e6_document_versions").install_guards(connection)
