"""Invoice review (Rechnungsprüfung): receipt → factual and arithmetic check → decision →
payment → dispute → result, on top of the existing invoices.

No competing invoice model and no ledger of its own:

* the invoice is the existing `invoices` row; a review row is added beside it only when
  the review starts (invoices without one stay "not reviewed / legacy" and behave as before);
* the order an invoice bills is the existing `maintenance_order_invoices` link, the contract
  it belongs to the existing `service_contract_invoices` link;
* payments are the existing `invoice_payments` (outgoing bookings allocated to the invoice);
* a transfer into the utility billing creates an ordinary `cost_items` row; the transfer row
  only remembers that it happened (once per invoice).

The review history (`invoice_review_events`) is append-only: the database refuses every
UPDATE of a history row (guards below, installed by create_all() and by migration
c9f4a2e7b1d5); deleting is refused by the application (an invoice with history is not
deleted, the foreign key is RESTRICT).
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base

MONEY = Numeric(12, 2, asdecimal=False)
REVIEW_STATUSES = ("received", "query", "approved", "partially_approved", "rejected")
EVENT_GUARD_MESSAGE = "invoice review history is immutable"


class InvoiceReviewORM(Base):
    """The review of one existing invoice (or credit note)."""

    __tablename__ = "invoice_reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False,
                                            unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="invoice")
    # a credit note (Gutschrift) names the invoice it reduces
    credit_for_invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"),
                                                              index=True)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    # the original (uploaded PDF or image) and its SHA-256 at receipt
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    document_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    # factual check (sachlich): delivered and ordered?
    factual_result: Mapped[str | None] = mapped_column(String(20))
    factual_note: Mapped[str | None] = mapped_column(Text)
    factual_by: Mapped[str | None] = mapped_column(String)
    factual_at: Mapped[datetime | None] = mapped_column(DateTime)
    # arithmetic check (rechnerisch): amounts, VAT per rate, § 14 UStG
    arithmetic_result: Mapped[str | None] = mapped_column(String(20))
    arithmetic_note: Mapped[str | None] = mapped_column(Text)
    arithmetic_by: Mapped[str | None] = mapped_column(String)
    arithmetic_at: Mapped[datetime | None] = mapped_column(DateTime)
    checklist: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    vat_lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # payment terms: Skonto and due date, fixed at receipt (the inbox filters on them)
    skonto_percent: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    skonto_days: Mapped[int | None] = mapped_column(Integer)
    skonto_until: Mapped[date | None] = mapped_column(Date, index=True)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    # free cost assignment (when no order and no contract carries the invoice)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    cost_category: Mapped[str | None] = mapped_column(Text)
    recoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # refinement of an order link: the invoice bills this change order (Nachtrag)
    change_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("maintenance_change_orders.id", ondelete="SET NULL"))
    # a suspected duplicate the receipt went ahead with, acknowledged with a reason
    duplicate_of_invoice_id: Mapped[str | None] = mapped_column(String)
    # decision
    approved_amount: Mapped[float | None] = mapped_column(MONEY)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    # dispute with the supplier (Widerspruch/Reklamation) about the part not approved
    dispute_status: Mapped[str | None] = mapped_column(String(20))
    dispute_outcome: Mapped[str | None] = mapped_column(String(20))
    dispute_settled_amount: Mapped[float | None] = mapped_column(MONEY)
    dispute_written_off: Mapped[float | None] = mapped_column(MONEY)
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    dispute_resolved_by: Mapped[str | None] = mapped_column(String)
    dispute_resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        Index("ix_invoice_reviews_status", "status"),
        CheckConstraint("kind IN ('invoice','credit_note')", name="ck_invoice_review_kind"),
        CheckConstraint("status IN ('received','query','approved','partially_approved','rejected')",
                        name="ck_invoice_review_status"),
        CheckConstraint("factual_result IS NULL OR factual_result IN ('confirmed','objected')",
                        name="ck_invoice_review_factual"),
        CheckConstraint("arithmetic_result IS NULL OR arithmetic_result IN ('confirmed','objected')",
                        name="ck_invoice_review_arithmetic"),
        CheckConstraint("dispute_status IS NULL OR dispute_status IN ('open','resolved')",
                        name="ck_invoice_review_dispute"),
        CheckConstraint("dispute_outcome IS NULL OR dispute_outcome IN ('credit','partial_payment','written_off')",
                        name="ck_invoice_review_dispute_outcome"),
        CheckConstraint("kind = 'invoice' OR credit_for_invoice_id IS NOT NULL",
                        name="ck_invoice_review_credit_target"),
        CheckConstraint("credit_for_invoice_id IS NULL OR credit_for_invoice_id <> invoice_id",
                        name="ck_invoice_review_credit_self"),
        CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="ck_invoice_review_approved"),
        CheckConstraint("skonto_percent IS NULL OR (skonto_percent > 0 AND skonto_percent < 100)",
                        name="ck_invoice_review_skonto"),
    )


class InvoiceReviewEventORM(Base):
    """One step of a review, written once and never changed."""

    __tablename__ = "invoice_review_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    status_after: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[float | None] = mapped_column(MONEY)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String)
    actor_name: Mapped[str | None] = mapped_column(Text)
    actor_role: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("invoice_id", "seq", name="uq_invoice_review_event_seq"),)


class InvoiceCostTransferORM(Base):
    """A recoverable approved invoice entered the utility billing as this cost item (once)."""

    __tablename__ = "invoice_cost_transfers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False,
                                            unique=True)
    cost_item_id: Mapped[str] = mapped_column(ForeignKey("cost_items.id", ondelete="CASCADE"), nullable=False,
                                              unique=True)
    billing_period_id: Mapped[str] = mapped_column(ForeignKey("billing_periods.id", ondelete="CASCADE"),
                                                   nullable=False)
    amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InvoiceReviewSettingsORM(Base):
    """Installation settings of the review (one row, id 'default'); every account reads them."""

    __tablename__ = "invoice_review_settings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    # above this gross amount the approver must be a second person (None: four-eyes off)
    four_eyes_limit: Mapped[float | None] = mapped_column(MONEY)
    # § 33 UStDV: invoices up to this gross amount need fewer mandatory fields
    small_invoice_limit: Mapped[float] = mapped_column(MONEY, nullable=False, default=250.0)
    duplicate_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    updated_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


REVIEW_TABLES = ("invoice_reviews", "invoice_review_events", "invoice_cost_transfers", "invoice_review_settings")


def install_event_guard(connection) -> None:
    """Refuse every UPDATE of a history row (idempotent). Deleting is refused by the application."""
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS immo_invoice_review_events_immutable BEFORE UPDATE ON invoice_review_events "
            f"BEGIN SELECT RAISE(ABORT, '{EVENT_GUARD_MESSAGE}'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_invoice_review_event_immutable() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{EVENT_GUARD_MESSAGE}'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_invoice_review_events_immutable ON invoice_review_events")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_invoice_review_events_immutable BEFORE UPDATE ON invoice_review_events "
            "FOR EACH ROW EXECUTE FUNCTION immo_invoice_review_event_immutable()")


def _guard_after_create(table, connection, **_):
    install_event_guard(connection)


event.listen(InvoiceReviewEventORM.__table__, "after_create", _guard_after_create)
