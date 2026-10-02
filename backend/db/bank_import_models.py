"""Immutable bank import source, checked rows and publication provenance."""
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class BankImportORM(Base):
    __tablename__ = "bank_imports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String, nullable=False)
    creator_id: Mapped[str] = mapped_column(String, nullable=False)
    scope_snapshot: Mapped[dict | None] = mapped_column(JSON)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mapping: Mapped[dict] = mapped_column(JSON, nullable=False)
    mapping_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("account_id", "source_sha256", "mapping_hash", name="uq_bank_import_source_mapping"),
        Index("idx_bank_import_account_created", "account_id", "created_at", "id"),
    )


class BankImportSourceORM(Base):
    __tablename__ = "bank_import_source_chunks"
    import_id: Mapped[str] = mapped_column(ForeignKey("bank_imports.id", ondelete="CASCADE"), primary_key=True)
    chunk_no: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class BankImportRowORM(Base):
    __tablename__ = "bank_import_rows"
    import_id: Mapped[str] = mapped_column(ForeignKey("bank_imports.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_line: Mapped[int] = mapped_column(BigInteger, nullable=False)
    booking_date: Mapped[date | None] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    payment_text: Mapped[str] = mapped_column(Text, nullable=False)
    bank_reference: Mapped[str | None] = mapped_column(Text)
    identity_base: Mapped[str | None] = mapped_column(String(64))
    identity_occurrence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    duplicate_booking_id: Mapped[str | None] = mapped_column(String)
    __table_args__ = (Index("idx_bank_import_row_identity", "import_id", "identity_base", "ordinal"),)


class BankImportReceiptORM(Base):
    __tablename__ = "bank_import_receipts"
    import_id: Mapped[str] = mapped_column(ForeignKey("bank_imports.id", ondelete="RESTRICT"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    booking_id: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "fingerprint", name="uq_bank_import_account_fingerprint"),)


BANK_IMPORT_TABLES = (BankImportORM.__table__, BankImportSourceORM.__table__, BankImportRowORM.__table__, BankImportReceiptORM.__table__)
