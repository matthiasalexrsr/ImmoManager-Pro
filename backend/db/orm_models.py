"""SQLAlchemy 2.0 declarative ORM models.

Maps to the PostgreSQL schema in db/schema.sql. Also works with SQLite for dev/test.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class PortfolioORM(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="EUR")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Berlin")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    properties: Mapped[list["PropertyORM"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    accounts: Mapped[list["AccountORM"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    categories: Mapped[list["CategoryORM"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class PropertyORM(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    property_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    year_built: Mapped[int | None] = mapped_column(Integer)
    living_area_sqm: Mapped[float | None] = mapped_column(Float)
    usable_area_sqm: Mapped[float | None] = mapped_column(Float)
    plot_area_sqm: Mapped[float | None] = mapped_column(Float)
    ownership_share: Mapped[float | None] = mapped_column(Float)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    market_value: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    valuation_date: Mapped[date | None] = mapped_column(Date)
    address_line: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    portfolio: Mapped["PortfolioORM"] = relationship(back_populates="properties")
    units: Mapped[list["UnitORM"]] = relationship(back_populates="property", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_properties_portfolio", "portfolio_id"),)


class UnitORM(Base):
    __tablename__ = "units"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    unit_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="vacant")
    area_sqm: Mapped[float | None] = mapped_column(Float)
    rooms: Mapped[float | None] = mapped_column(Float)
    person_count: Mapped[int | None] = mapped_column(Integer)
    floor: Mapped[str | None] = mapped_column(Text)
    cold_rent: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    service_charge_advance: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    heating_advance: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    features: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    property: Mapped["PropertyORM"] = relationship(back_populates="units")

    __table_args__ = (
        Index("idx_units_property", "property_id"),
        Index("idx_units_property_status", "property_id", "status"),
        CheckConstraint("area_sqm IS NULL OR area_sqm > 0", name="ck_units_area_positive"),
    )


class TenantORM(Base):
    __tablename__ = "tenants"
    __table_args__ = (Index("idx_tenants_archived", "archived"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    address_line: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(Text)
    sepa_mandate: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class ContractORM(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    contract_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    notice_period: Mapped[str | None] = mapped_column(Text)
    deposit_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    index_rent: Mapped[str | None] = mapped_column(Text)
    service_charge_settlement: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_contracts_unit", "unit_id"),
        Index("idx_contracts_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_contracts_dates",
        ),
    )


class AccountORM(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    bank_name: Mapped[str | None] = mapped_column(Text)
    iban: Mapped[str | None] = mapped_column(Text)
    bic: Mapped[str | None] = mapped_column(Text)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    opening_balance: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    balance: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    portfolio: Mapped["PortfolioORM"] = relationship(back_populates="accounts")

    __table_args__ = (
        Index("idx_accounts_portfolio", "portfolio_id"),
        UniqueConstraint("iban", name="uq_accounts_iban"),
    )


class CategoryORM(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    portfolio: Mapped["PortfolioORM"] = relationship(back_populates="categories")


class BookingORM(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    payment_text: Mapped[str | None] = mapped_column(Text)
    receipt_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_bookings_account", "account_id"),
        Index("idx_bookings_account_date", "account_id", "booking_date"),
        CheckConstraint("amount != 0", name="ck_bookings_amount_nonzero"),
    )


class ReceivableORM(Base):
    __tablename__ = "receivables"
    __table_args__ = (
        Index("idx_receivables_contract", "contract_id"),
        Index("idx_receivables_status", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    dunning_level: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    statement_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class InvoiceORM(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_property", "property_id"),
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_date", "invoice_date"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    supplier: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    net_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    vat_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    gross_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    vat_rate: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=19.0)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class MaintenanceCaseORM(Base):
    __tablename__ = "maintenance_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    reported_by: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    contractor: Mapped[str | None] = mapped_column(Text)
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_maintenance_property", "property_id"),)


class DocumentORM(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_property", "property_id"),
        Index("idx_documents_contract", "contract_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str | None] = mapped_column(Text)
    document_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class TaskORM(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_property", "property_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    recurrence_rule: Mapped[str | None] = mapped_column(Text)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class CalendarEventORM(Base):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[str | None] = mapped_column(Text)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_calendar_property", "property_id"),)


class ListingORM(Base):
    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    portal: Mapped[str | None] = mapped_column(Text)
    listing_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    target_rent: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    service_charge: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    available_from: Mapped[date | None] = mapped_column(Date)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    photos: Mapped[list["ListingPhotoORM"]] = relationship(back_populates="listing", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_listings_unit", "unit_id"),)


class ListingPhotoORM(Base):
    __tablename__ = "listing_photos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    listing: Mapped["ListingORM"] = relationship(back_populates="photos")

    __table_args__ = (Index("idx_listing_photos_listing", "listing_id"),)


class LeadORM(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    listing_id: Mapped[str | None] = mapped_column(ForeignKey("listings.id", ondelete="SET NULL"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_leads_listing", "listing_id"),
        Index("idx_leads_unit", "unit_id"),
        Index("idx_leads_status", "status"),
    )


class ViewingAppointmentORM(Base):
    __tablename__ = "viewing_appointments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled")
    agent: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_viewings_lead", "lead_id"),
        Index("idx_viewings_unit", "unit_id"),
    )


class BillingPeriodORM(Base):
    __tablename__ = "billing_periods"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_billing_periods_property", "property_id"),)


class AllocationKeyORM(Base):
    __tablename__ = "allocation_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_allocation_keys_property", "property_id"),)


class CostItemORM(Base):
    __tablename__ = "cost_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    billing_period_id: Mapped[str] = mapped_column(ForeignKey("billing_periods.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    allocation_key_id: Mapped[str] = mapped_column(ForeignKey("allocation_keys.id", ondelete="CASCADE"), nullable=False)
    is_recoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cost_category: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[str | None] = mapped_column(String)
    vat_rate: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    net_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    gross_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_cost_items_period", "billing_period_id"),
        Index("idx_cost_items_key", "allocation_key_id"),
    )


class UtilityStatementORM(Base):
    __tablename__ = "utility_statements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    billing_period_id: Mapped[str] = mapped_column(ForeignKey("billing_periods.id", ondelete="CASCADE"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    total_cost: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    advance_paid: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    revision: Mapped[int] = mapped_column(default=1)
    revision_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    line_items: Mapped[list | None] = mapped_column(JSON)
    delivery_status: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivery_channel: Mapped[str | None] = mapped_column(Text)
    snapshot_hash: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_utility_statements_period", "billing_period_id"),
        Index("idx_utility_statements_contract", "contract_id"),
    )


class DepositORM(Base):
    __tablename__ = "deposits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="held")
    held_date: Mapped[date | None] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date)
    deductions: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    deduction_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_deposits_contract", "contract_id"),)


class NotificationORM(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="info")
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unread")
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_notifications_status", "status"),
        Index("idx_notifications_type", "notification_type"),
    )


class NotificationTemplateORM(Base):
    __tablename__ = "notification_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    content_template: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class TaxRateORM(Base):
    __tablename__ = "tax_rates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    rate: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(default=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RentAdjustmentORM(Base):
    __tablename__ = "rent_adjustments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String(36), ForeignKey("contracts.id"))
    adjustment_type: Mapped[str] = mapped_column(String(20))
    effective_date: Mapped[date] = mapped_column(Date)
    previous_rent: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    new_rent: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    increase_percent: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    index_base_year: Mapped[int | None] = mapped_column(Integer)
    index_value: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class HandoverProtocolORM(Base):
    __tablename__ = "handover_protocols"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String(36), ForeignKey("contracts.id"))
    unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("units.id"))
    protocol_type: Mapped[str] = mapped_column(String(20))
    protocol_date: Mapped[date] = mapped_column(Date)
    tenant_present: Mapped[bool] = mapped_column(default=True)
    landlord_present: Mapped[bool] = mapped_column(default=True)
    key_count: Mapped[int | None] = mapped_column(Integer)
    key_details: Mapped[str | None] = mapped_column(Text)
    overall_condition: Mapped[str | None] = mapped_column(String(20))
    damages: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    tenant_signature: Mapped[str | None] = mapped_column(Text)
    landlord_signature: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MeterReadingORM(Base):
    __tablename__ = "meter_readings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    handover_id: Mapped[str] = mapped_column(String(36), ForeignKey("handover_protocols.id", ondelete="CASCADE"))
    meter_type: Mapped[str] = mapped_column(String(30))
    meter_number: Mapped[str | None] = mapped_column(String(50))
    reading_value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="kWh")
    photo_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BudgetORM(Base):
    __tablename__ = "budgets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    year: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(50))
    planned_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    actual_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EscalationRuleORM(Base):
    __tablename__ = "escalation_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[str] = mapped_column(String(30))
    condition_field: Mapped[str] = mapped_column(String(50))
    days_overdue: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    target_role: Mapped[str | None] = mapped_column(String(50))
    notification_severity: Mapped[str] = mapped_column(String(20), default="warning")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChangeHistoryORM(Base):
    __tablename__ = "change_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(36))
    field_name: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str | None] = mapped_column(String(36))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    reason: Mapped[str | None] = mapped_column(Text)


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="readonly")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
    )


class UserPreferencesORM(Base):
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    theme: Mapped[str] = mapped_column(Text, nullable=False, default="light")
    locale: Mapped[str] = mapped_column(Text, nullable=False, default="de-DE")
    sidebar_collapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    items_per_page: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    date_format: Mapped[str] = mapped_column(Text, nullable=False, default="DD.MM.YYYY")
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="EUR")
    default_due_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    email_notifications: Mapped[str] = mapped_column(Text, nullable=False, default="important")
    reminder_days: Mapped[str] = mapped_column(Text, nullable=False, default="7")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_user_preferences_user", "user_id"),)


class InsuranceORM(Base):
    __tablename__ = "insurances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    insurance_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    policy_number: Mapped[str | None] = mapped_column(Text)
    coverage_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    premium_amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False))
    premium_interval: Mapped[str] = mapped_column(Text, nullable=False, default="annual")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    contact_person: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_insurance_property", "property_id"),)


class EntityPhotoORM(Base):
    __tablename__ = "entity_photos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    __table_args__ = (Index("idx_entity_photos_entity", "entity_type", "entity_id"),)


class ContactORM(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_type: Mapped[str] = mapped_column(String(30), default="tenant")
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    company_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    street: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(5), default="DE")
    iban: Mapped[str | None] = mapped_column(String(34))
    bic: Mapped[str | None] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    tax_id: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MeterORM(Base):
    __tablename__ = "meters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("units.id"))
    meter_type: Mapped[str] = mapped_column(String(30))
    serial_number: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(200))
    installation_date: Mapped[date | None] = mapped_column(Date)
    next_inspection: Mapped[date | None] = mapped_column(Date)
    supplier: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StandaloneMeterReadingORM(Base):
    __tablename__ = "standalone_meter_readings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meter_id: Mapped[str] = mapped_column(String(36), ForeignKey("meters.id", ondelete="CASCADE"))
    reading_date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    recorded_by: Mapped[str | None] = mapped_column(String(100))
    photo_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MessageThreadORM(Base):
    __tablename__ = "message_threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject: Mapped[str] = mapped_column(String(300))
    participant_ids: Mapped[str | None] = mapped_column(Text)
    property_id: Mapped[str | None] = mapped_column(String(36))
    unit_id: Mapped[str | None] = mapped_column(String(36))
    contract_id: Mapped[str | None] = mapped_column(String(36))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MessageORM(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("message_threads.id", ondelete="CASCADE"))
    sender_name: Mapped[str] = mapped_column(String(200), default="System")
    body: Mapped[str] = mapped_column(Text)
    attachment_ids: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RentChargeORM(Base):
    __tablename__ = "rent_charges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(String(36), ForeignKey("contracts.id"))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    cold_rent: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    service_charge: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    heating_charge: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    other_charges: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    amount_paid: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (Index("idx_rent_charges_contract_month", "contract_id", "month"),)


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String)
    username: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_timestamp", "timestamp"),
    )


class RevokedTokenORM(Base):
    """Persisted token blacklist for cross-restart / multi-instance revocation."""
    __tablename__ = "revoked_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    token_jti: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_revoked_tokens_jti", "token_jti"),
        Index("idx_revoked_tokens_expires", "expires_at"),
    )


class LoginAttemptORM(Base):
    """Persisted login attempt records for cross-restart rate limiting."""
    __tablename__ = "login_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_login_attempts_username", "username"),
        Index("idx_login_attempts_time", "attempted_at"),
    )
