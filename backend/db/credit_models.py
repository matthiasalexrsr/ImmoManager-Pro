"""Append-only payout/offset audit records; amounts are exact integer cents."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class CreditReceiptORM(Base):
    __tablename__ = "credit_receipts"
    __table_args__ = (
        CheckConstraint("method IN ('cash', 'bank', 'offset')", name="ck_credit_method"),
        CheckConstraint("(method = 'bank' AND booking_id IS NOT NULL AND payment_id IS NULL AND target_id IS NULL AND target_type IS NULL) OR (method = 'cash' AND booking_id IS NULL AND payment_id IS NULL AND target_id IS NULL AND target_type IS NULL) OR (method = 'offset' AND booking_id IS NULL AND payment_id IS NOT NULL AND target_id IS NOT NULL AND target_type IN ('receivable', 'rent_charge'))", name="ck_credit_links"),
        Index("idx_credit_contract", "contract_id"),
        Index("idx_credit_source", "source_settlement_id"),
        Index("idx_credit_booking", "booking_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    source_settlement_id: Mapped[str] = mapped_column(ForeignKey("billing_settlements.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    amount_cents: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    booking_id: Mapped[str | None] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(String)
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


class CreditReversalORM(Base):
    __tablename__ = "credit_reversals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("credit_receipts.id", ondelete="RESTRICT"), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    amount_cents: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payment_reversal_id: Mapped[str | None] = mapped_column(ForeignKey("payment_reversals.id", ondelete="RESTRICT"), unique=True)
    actor_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
