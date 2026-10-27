"""Project file of a maintenance case (Schaden → Projektakte).

Every table hangs off the existing case (`maintenance_cases`), so the portfolio
boundary follows the case's property. Craftsmen are contacts of the shared
address book: `contact_id` is a reference without a foreign key, because the
address book is readable by every account and must not decide the visibility
of a project row.

Money is NUMERIC(12,2): the project keeps no ledger of its own. Ordered amounts
come from orders and approved change orders, invoiced amounts from the existing
invoices linked to an order, paid amounts from bookings allocated to those
invoices (`invoice_payments`).

A finalized protocol is evidence: its PDF is an archived original
(document_versions) and the database refuses any UPDATE of the row once its
status is 'final' (guards below, installed by create_all() and by migration
b6d4f1a8c2e7).
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
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


def _case() -> Mapped[str]:
    return mapped_column(ForeignKey("maintenance_cases.id", ondelete="CASCADE"), nullable=False, index=True)


class MaintenanceWorkPackageORM(Base):
    __tablename__ = "maintenance_work_packages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="work")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    contact_id: Mapped[str | None] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('work','milestone')", name="ck_mwp_kind"),
        CheckConstraint("status IN ('planned','in_progress','done','cancelled')", name="ck_mwp_status"),
        CheckConstraint("planned_start IS NULL OR planned_end IS NULL OR planned_end >= planned_start",
                        name="ck_mwp_dates"),
    )


class MaintenanceDependencyORM(Base):
    """The successor starts when the predecessor is done (finish to start); never a cycle."""

    __tablename__ = "maintenance_dependencies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    predecessor_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_work_packages.id", ondelete="CASCADE"), nullable=False)
    successor_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_work_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("predecessor_id", "successor_id", name="uq_maintenance_dependency"),
        CheckConstraint("predecessor_id <> successor_id", name="ck_maintenance_dependency_self"),
    )


class MaintenanceParticipantORM(Base):
    """A craftsman (or expert) of the address book assigned to the case."""

    __tablename__ = "maintenance_participants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    contact_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="contractor")
    trade: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("case_id", "contact_id", name="uq_maintenance_participant"),
        CheckConstraint("role IN ('contractor','expert','other')", name="ck_maintenance_participant_role"),
    )


class MaintenanceQuoteORM(Base):
    __tablename__ = "maintenance_quotes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    contact_id: Mapped[str | None] = mapped_column(String)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    work_package_id: Mapped[str | None] = mapped_column(
        ForeignKey("maintenance_work_packages.id", ondelete="SET NULL"))
    quote_number: Mapped[str | None] = mapped_column(Text)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    net_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    gross_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String)
    decision_note: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("net_amount > 0 AND gross_amount >= net_amount", name="ck_maintenance_quote_amounts"),
        CheckConstraint("status IN ('received','accepted','rejected')", name="ck_maintenance_quote_status"),
    )


class MaintenanceOrderORM(Base):
    """An order (Auftrag) is always the accepted quote: one order per quote, amounts frozen."""

    __tablename__ = "maintenance_orders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    quote_id: Mapped[str] = mapped_column(ForeignKey("maintenance_quotes.id"), nullable=False, unique=True)
    contact_id: Mapped[str | None] = mapped_column(String)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    order_number: Mapped[str | None] = mapped_column(Text)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    net_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    gross_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("net_amount > 0 AND gross_amount >= net_amount", name="ck_maintenance_order_amounts"),
        CheckConstraint("status IN ('active','completed','cancelled')", name="ck_maintenance_order_status"),
    )


class MaintenanceChangeOrderORM(Base):
    """A Nachtrag: extra (or less) work on an order; counts once approved."""

    __tablename__ = "maintenance_change_orders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    order_id: Mapped[str] = mapped_column(ForeignKey("maintenance_orders.id", ondelete="CASCADE"), nullable=False,
                                          index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    net_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    gross_amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String)
    decision_note: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("(net_amount > 0 AND gross_amount >= net_amount) OR "
                        "(net_amount < 0 AND gross_amount <= net_amount)", name="ck_maintenance_change_amounts"),
        CheckConstraint("status IN ('proposed','approved','rejected')", name="ck_maintenance_change_status"),
    )


class MaintenanceOrderInvoiceORM(Base):
    """An existing invoice billed against an order; an invoice belongs to at most one order."""

    __tablename__ = "maintenance_order_invoices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    order_id: Mapped[str] = mapped_column(ForeignKey("maintenance_orders.id", ondelete="CASCADE"), nullable=False,
                                          index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False,
                                            unique=True)
    linked_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InvoicePaymentORM(Base):
    """Which outgoing booking pays (part of) which invoice."""

    __tablename__ = "invoice_payments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    amount: Mapped[float] = mapped_column(MONEY, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("invoice_id", "booking_id", name="uq_invoice_payment"),
        CheckConstraint("amount > 0", name="ck_invoice_payment_amount"),
    )


class MaintenanceProtocolORM(Base):
    __tablename__ = "maintenance_protocols"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    work_package_id: Mapped[str | None] = mapped_column(ForeignKey("maintenance_work_packages.id"))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("maintenance_orders.id"))
    protocol_type: Mapped[str] = mapped_column(String(20), nullable=False)
    protocol_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    defects: Mapped[list] = mapped_column(JSON, nullable=False)
    photo_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    finalized_by: Mapped[str | None] = mapped_column(String)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    version_id: Mapped[str | None] = mapped_column(String)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("protocol_type IN ('acceptance','inspection','site_visit')", name="ck_mprot_type"),
        CheckConstraint("status IN ('draft','final')", name="ck_mprot_status"),
        CheckConstraint("result IS NULL OR result IN ('accepted','accepted_with_defects','refused')",
                        name="ck_mprot_result"),
        CheckConstraint("status = 'draft' OR (document_id IS NOT NULL AND content_sha256 IS NOT NULL)",
                        name="ck_mprot_final_evidence"),
        Index("ix_maintenance_protocols_document", "document_id"),
    )


class MaintenanceAppointmentORM(Base):
    """A calendar event of the case; the date lives in the calendar, only the link here."""

    __tablename__ = "maintenance_appointments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    calendar_event_id: Mapped[str] = mapped_column(ForeignKey("calendar_events.id", ondelete="CASCADE"),
                                                   nullable=False, unique=True)
    work_package_id: Mapped[str | None] = mapped_column(
        ForeignKey("maintenance_work_packages.id", ondelete="SET NULL"))
    contact_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('inspection','execution','acceptance','other')", name="ck_mappt_kind"),
    )


class MaintenanceCaseDocumentORM(Base):
    __tablename__ = "maintenance_case_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = _case()
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
                                             index=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("case_id", "document_id", name="uq_maintenance_case_document"),)


PROJECT_TABLES = (
    "maintenance_work_packages", "maintenance_dependencies", "maintenance_participants", "maintenance_quotes",
    "maintenance_orders", "maintenance_change_orders", "maintenance_order_invoices", "invoice_payments",
    "maintenance_protocols", "maintenance_appointments", "maintenance_case_documents",
)

PROTOCOL_GUARD_MESSAGE = "final maintenance protocols are immutable"


def install_protocol_guard(connection) -> None:
    """Refuse every UPDATE of a final protocol (idempotent). Deleting is refused by the application."""
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS immo_maintenance_protocols_final BEFORE UPDATE ON maintenance_protocols "
            f"WHEN OLD.status = 'final' BEGIN SELECT RAISE(ABORT, '{PROTOCOL_GUARD_MESSAGE}'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_maintenance_protocol_final() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{PROTOCOL_GUARD_MESSAGE}'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_maintenance_protocols_final ON maintenance_protocols")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_maintenance_protocols_final BEFORE UPDATE ON maintenance_protocols "
            "FOR EACH ROW WHEN (OLD.status = 'final') EXECUTE FUNCTION immo_maintenance_protocol_final()")


def _guard_after_create(table, connection, **_):
    install_protocol_guard(connection)


event.listen(MaintenanceProtocolORM.__table__, "after_create", _guard_after_create)
