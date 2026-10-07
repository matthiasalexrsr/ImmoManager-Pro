"""Append-only document originals: a manifest per version and its bytes in 64 KiB blocks.

An archived original is evidence (a Wohnungsgeberbestätigung, for example): once
written it is never changed or deleted. The database refuses UPDATE and DELETE on
both tables with triggers. They are installed wherever the tables are created:
by Base.metadata.create_all() (desktop installs, tests) through the after_create
events below, and by the migration e5f1a7c3b9d2 for Alembic-managed databases.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base

CHUNK_BYTES = 65536
ARCHIVE_TABLES = ("document_versions", "document_version_chunks")


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
        Index("ix_document_versions_contract", "contract_id", "created_at"),
    )


class DocumentVersionChunkORM(Base):
    __tablename__ = "document_version_chunks"
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (
        CheckConstraint("position >= 0 AND length(data) BETWEEN 1 AND 65536", name="ck_document_chunk_values"),
    )


DOCUMENT_VERSION_MODELS = (DocumentVersionORM, DocumentVersionChunkORM)


def install_guards(connection) -> None:
    """Refuse UPDATE and DELETE on the archive tables (idempotent)."""
    if connection.dialect.name == "sqlite":
        for table in ARCHIVE_TABLES:
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS immo_{table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'document originals are immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_document_original_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'document originals are immutable'; END; $$ LANGUAGE plpgsql")
        for table in ARCHIVE_TABLES:
            trigger = f"immo_{table}_immutable"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION immo_document_original_immutable()")


def _guard_after_create(table, connection, **_):
    install_guards(connection)


# create_all() creates the versions before their chunks: install once both exist
event.listen(DocumentVersionChunkORM.__table__, "after_create", _guard_after_create)
