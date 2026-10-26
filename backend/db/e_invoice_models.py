"""Durable structured receipts and immutable validation evidence.

Originals are database bytes, not arbitrary filesystem paths. Business references
remain restricted on delete. These records are included by the full backup and
the dedicated customer portability service, never by a credentials-only export.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class EInvoiceIntakeORM(Base):
    __tablename__ = "e_invoice_intakes"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_e_invoice_upload_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    validation_actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    original: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    xml: Mapped[bytes | None] = mapped_column(LargeBinary)
    container: Mapped[str] = mapped_column(String(8), nullable=False)
    format: Mapped[str | None] = mapped_column(String(20))
    reading: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    blockers: Mapped[list] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), unique=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    accept_key: Mapped[str | None] = mapped_column(String(100))
    accept_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EInvoiceValidationORM(Base):
    __tablename__ = "e_invoice_validations"
    __table_args__ = (UniqueConstraint("intake_id", "number", name="uq_e_invoice_validation_run"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intake_id: Mapped[str] = mapped_column(ForeignKey("e_invoice_intakes.id", ondelete="RESTRICT"), index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[str] = mapped_column(String(30), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    messages: Mapped[list] = mapped_column(JSON, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
