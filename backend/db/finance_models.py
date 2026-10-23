"""Financial source links and private, versioned report definitions."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ReceivableSettlementORM(Base):
    __tablename__ = "receivable_settlements"
    __table_args__ = (Index("ix_receivable_settlement_claim", "receivable_id", "effective_date"),
                      Index("ix_receivable_settlement_booking", "booking_id"),
                      Index("ix_receivable_settlement_credit", "credit_id"),
                      CheckConstraint("(amount > 0 AND reverses_id IS NULL) OR (amount < 0 AND reverses_id IS NOT NULL)", name="ck_settlement_direction"),
                      CheckConstraint("(booking_id IS NULL) <> (credit_id IS NULL)", name="ck_settlement_one_source"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id", ondelete="RESTRICT"))
    booking_id: Mapped[str | None] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    credit_id: Mapped[str | None] = mapped_column(ForeignKey("receivables.id", ondelete="RESTRICT"))
    reverses_id: Mapped[str | None] = mapped_column(ForeignKey("receivable_settlements.id", ondelete="NO ACTION"), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedFinanceReportORM(Base):
    __tablename__ = "saved_finance_reports"
    __table_args__ = (Index("ix_saved_finance_owner", "owner_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(160))
    definition: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
