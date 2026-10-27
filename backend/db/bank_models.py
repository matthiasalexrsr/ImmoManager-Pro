"""Bank staging and source links, separate from the existing financial ledger."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class BankImportORM(Base):
    __tablename__ = "bank_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_token: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_token: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "source_sha256", "mapping_sha256", name="uq_bank_source_mapping"),
                      Index('ix_bank_imports_history', 'account_id', 'created_at', 'id'))


class BankSourceLinkORM(Base):
    __tablename__ = "bank_source_links"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("bank_imports.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FinTSSessionORM(Base):
    __tablename__ = "bank_fints_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    private_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def _guards(target, connection, **kwargs):
    from .bank_guards import install_bank_guards
    install_bank_guards(connection)


event.listen(Base.metadata, 'after_create', _guards)
