"""Property service and energy contracts (Objektverträge) and their links.

A contract belongs to the portfolios of its locations (service_contract_locations):
see services/portfolio_scope.py. Money columns are cent amounts like the rest of the
schema; unit prices keep up to six decimals as text inside ``unit_prices``.
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base, _uuid


class ServiceContractORM(Base):
    __tablename__ = "service_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # the shared address book; a provider in use cannot be deleted (deletion_guard)
    provider_contact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False)
    contract_number: Mapped[str | None] = mapped_column(Text)
    customer_number: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    minimum_term_months: Mapped[int | None] = mapped_column(Integer)
    renewal_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="none", server_default="none")
    renewal_months: Mapped[int | None] = mapped_column(Integer)
    notice_period_value: Mapped[int | None] = mapped_column(Integer)
    notice_period_unit: Mapped[str | None] = mapped_column(String(10))
    notice_to: Mapped[str] = mapped_column(String(20), nullable=False, default="term_end", server_default="term_end")
    reminder_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    cancelled_on: Mapped[date | None] = mapped_column(Date)
    cancellation_effective: Mapped[date | None] = mapped_column(Date)
    recoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    recoverable_percent: Mapped[float] = mapped_column(
        Numeric(5, 2, asdecimal=False), nullable=False, default=100.0, server_default="100")
    cost_category: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_service_contracts_provider", "provider_contact_id"),
        CheckConstraint("renewal_mode IN ('none', 'fixed', 'indefinite')", name="ck_service_contracts_renewal"),
        CheckConstraint("notice_period_unit IS NULL OR notice_period_unit IN ('day', 'week', 'month')",
                        name="ck_service_contracts_notice_unit"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_service_contracts_dates"),
        CheckConstraint("recoverable_percent >= 0 AND recoverable_percent <= 100",
                        name="ck_service_contracts_recoverable_percent"),
    )


class ServiceContractLocationORM(Base):
    """One place a contract covers: a property, optionally a unit and a meter of it."""

    __tablename__ = "service_contract_locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)
    property_id: Mapped[str] = mapped_column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(String, ForeignKey("units.id", ondelete="CASCADE"))
    meter_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("meters.id", ondelete="SET NULL"))
    supply_point: Mapped[str | None] = mapped_column(Text)     # Zählpunkt / Marktlokation
    share_weight: Mapped[float] = mapped_column(
        Numeric(12, 4, asdecimal=False), nullable=False, default=1.0, server_default="1")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_service_contract_locations_contract", "service_contract_id"),
        Index("idx_service_contract_locations_property", "property_id"),
        CheckConstraint("share_weight > 0", name="ck_service_contract_locations_weight"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
                        name="ck_service_contract_locations_dates"),
    )


class ServiceContractTariffORM(Base):
    """A tariff from a date on; it applies until the next one starts."""

    __tablename__ = "service_contract_tariffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    base_price_period: Mapped[str] = mapped_column(String(10), nullable=False, default="month",
                                                   server_default="month")
    unit_prices: Mapped[list | None] = mapped_column(JSON)
    price_guarantee_until: Mapped[date | None] = mapped_column(Date)
    advance_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    advance_interval: Mapped[str | None] = mapped_column(String(12))
    advance_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    prices_include_vat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    vat_rate: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), nullable=False, default=19.0,
                                            server_default="19")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("service_contract_id", "valid_from", name="uq_service_contract_tariffs_contract_date"),
        CheckConstraint("advance_day BETWEEN 1 AND 31", name="ck_service_contract_tariffs_day"),
    )


class ServiceContractInvoiceORM(Base):
    """A provider's bill (an existing invoice) for a service period of the contract."""

    __tablename__ = "service_contract_invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)
    # one bill belongs to one contract: it is never counted twice
    invoice_id: Mapped[str] = mapped_column(
        String, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="regular", server_default="regular")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    advances_credited: Mapped[float] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=False, default=0.0, server_default="0")
    consumption: Mapped[float | None] = mapped_column(Numeric(14, 3, asdecimal=False))
    consumption_unit: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_service_contract_invoices_contract", "service_contract_id"),
        CheckConstraint("kind IN ('regular', 'settlement')", name="ck_service_contract_invoices_kind"),
        CheckConstraint("period_end >= period_start", name="ck_service_contract_invoices_period"),
    )


class ServiceContractPaymentORM(Base):
    """The part of a booking that pays (positive) or refunds (negative) the contract."""

    __tablename__ = "service_contract_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)
    booking_id: Mapped[str] = mapped_column(String, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    service_contract_invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("service_contract_invoices.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("service_contract_id", "booking_id", name="uq_service_contract_payments_booking"),
        Index("idx_service_contract_payments_booking", "booking_id"),
        CheckConstraint("amount != 0", name="ck_service_contract_payments_amount"),
    )


class ServiceContractDocumentORM(Base):
    __tablename__ = "service_contract_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("service_contract_id", "document_id", name="uq_service_contract_documents"),
        Index("idx_service_contract_documents_document", "document_id"),
    )


SERVICE_CONTRACT_TABLES = (
    "service_contracts", "service_contract_locations", "service_contract_tariffs", "service_contract_invoices",
    "service_contract_payments", "service_contract_documents",
)
