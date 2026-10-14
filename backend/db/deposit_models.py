"""Rental deposit file (Kautionsakte): instalments, payments, interest rates, settlements.

The agreement is the existing `deposits` row (amount, form, account details; see
orm_models.DepositORM). Money moves stay bookings: `deposit_payments` names the
share of a booking that is a deposit receipt, payout or offset, so the rent account
counts every booking amount once (services/payment_allocations.py).

A settlement (final, or the later release of a retention) is a draft until it is
finalized; finalizing archives its PDF as an immutable original and creates the
payout booking or the remaining-claim receivable once. From then on the database
refuses changes of the settlement, its items and the deposit's instalments,
payments and interest rates (db/deposit_guards.py).
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base, _uuid

PAYMENT_KINDS = ("receipt", "payout", "offset")
SETTLEMENT_KINDS = ("final", "retention_release")
ITEM_KINDS = ("defect", "other", "receivable", "rent_arrears", "retention")


class DepositInstalmentORM(Base):
    __tablename__ = "deposit_instalments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deposit_id: Mapped[str] = mapped_column(String, ForeignKey("deposits.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("deposit_id", "number", name="uq_deposit_instalments_number"),
        CheckConstraint("number BETWEEN 1 AND 3", name="ck_deposit_instalments_number"),
        CheckConstraint("amount > 0", name="ck_deposit_instalments_amount"),
    )


class DepositInterestRateORM(Base):
    __tablename__ = "deposit_interest_rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deposit_id: Mapped[str] = mapped_column(String, ForeignKey("deposits.id", ondelete="CASCADE"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    # annual percent as exact decimal text (at most four places)
    rate_percent: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("deposit_id", "valid_from", name="uq_deposit_interest_rates_day"),)


class DepositSettlementORM(Base):
    __tablename__ = "deposit_settlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deposit_id: Mapped[str] = mapped_column(String, ForeignKey("deposits.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    handover_protocol_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("handover_protocols.id", ondelete="SET NULL"))
    # interest entered by hand instead of the computed one (e.g. as the bank credited it), with a reason
    interest_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    interest_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    # set once at finalization: positive payout, negative remaining claim
    result_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    payout_booking_id: Mapped[str | None] = mapped_column(String, ForeignKey("bookings.id", ondelete="RESTRICT"))
    offset_booking_id: Mapped[str | None] = mapped_column(String, ForeignKey("bookings.id", ondelete="RESTRICT"))
    offset_credit_booking_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("bookings.id", ondelete="RESTRICT"))
    claim_receivable_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("receivables.id", ondelete="RESTRICT"))
    document_id: Mapped[str | None] = mapped_column(String, ForeignKey("documents.id", ondelete="RESTRICT"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    finalized_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("deposit_id", "kind", name="uq_deposit_settlements_kind"),
        CheckConstraint("kind IN ('final', 'retention_release')", name="ck_deposit_settlements_kind"),
        CheckConstraint("status IN ('draft', 'finalized')", name="ck_deposit_settlements_status"),
    )


class DepositSettlementItemORM(Base):
    __tablename__ = "deposit_settlement_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    settlement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("deposit_settlements.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    handover_defect_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("handover_defects.id", ondelete="SET NULL"))
    receivable_id: Mapped[str | None] = mapped_column(String, ForeignKey("receivables.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_deposit_settlement_items_settlement", "settlement_id"),
        CheckConstraint("amount > 0", name="ck_deposit_settlement_items_amount"),
        CheckConstraint("kind IN ('defect', 'other', 'receivable', 'rent_arrears', 'retention')",
                        name="ck_deposit_settlement_items_kind"),
    )


class DepositPaymentORM(Base):
    __tablename__ = "deposit_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deposit_id: Mapped[str] = mapped_column(String, ForeignKey("deposits.id", ondelete="RESTRICT"), nullable=False)
    booking_id: Mapped[str] = mapped_column(String, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="receipt", server_default="receipt")
    # the share of the booking: positive receipts (a reversal of one negative), negative payouts and offsets
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    settlement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("deposit_settlements.id", ondelete="RESTRICT"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("deposit_id", "booking_id", name="uq_deposit_payments_booking"),
        Index("idx_deposit_payments_booking", "booking_id"),
        CheckConstraint("amount != 0", name="ck_deposit_payments_amount"),
        CheckConstraint("kind IN ('receipt', 'payout', 'offset')", name="ck_deposit_payments_kind"),
    )


DEPOSIT_TABLES = ("deposit_instalments", "deposit_interest_rates", "deposit_settlements",
                  "deposit_settlement_items", "deposit_payments")


def _guards_after_create(target, connection, **_):
    """create_all(): install the triggers of finalized settlements once all their tables exist."""
    from sqlalchemy import inspect

    from .deposit_guards import install_deposit_guards

    if {"deposits", *DEPOSIT_TABLES} <= set(inspect(connection).get_table_names()):
        install_deposit_guards(connection)


event.listen(Base.metadata, "after_create", _guards_after_create)
