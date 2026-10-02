"""Durable, reviewable rental-generation snapshots and progress."""
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class RentSourceRevisionORM(Base):
    __tablename__ = "rent_source_revisions"
    entity_type: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class RentBatchORM(Base):
    __tablename__ = "rent_generation_batches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    creator_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    scope_snapshot: Mapped[dict | None] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String, nullable=False, default="preparing")
    phase: Mapped[str] = mapped_column(String, nullable=False, default="contracts")
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    preparation: Mapped[dict] = mapped_column(JSON, nullable=False)
    planner_cursor: Mapped[str | None] = mapped_column(String)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    contract_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    examined_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    existing_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("creator_id", "idempotency_key", name="uq_rent_batch_creator_key"),
        Index("idx_rent_batch_creator_created", "creator_id", "created_at", "id"))


class RentBatchSelectionORM(Base):
    __tablename__ = "rent_generation_selections"
    batch_id: Mapped[str] = mapped_column(ForeignKey("rent_generation_batches.id", ondelete="CASCADE"), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String, primary_key=True)


class RentBatchContractORM(Base):
    __tablename__ = "rent_generation_contracts"
    batch_id: Mapped[str] = mapped_column(ForeignKey("rent_generation_batches.id", ondelete="CASCADE"), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    contract_number: Mapped[str] = mapped_column(String, nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String, nullable=False)
    property_id: Mapped[str] = mapped_column(String, nullable=False)
    unit_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, nullable=False)
    cold_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    service_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    heating_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contract_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    property_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    basis_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    price_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prices_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RentBatchPriceORM(Base):
    __tablename__ = "rent_generation_prices"
    batch_id: Mapped[str] = mapped_column(ForeignKey("rent_generation_batches.id", ondelete="CASCADE"), primary_key=True)
    adjustment_id: Mapped[str] = mapped_column(String, primary_key=True)
    contract_id: Mapped[str] = mapped_column(String, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("batch_id", "contract_id", "effective_date", name="uq_rent_batch_price_date"),
        Index("idx_rent_batch_prices_contract_date", "batch_id", "contract_id", "effective_date", "adjustment_id"))


class RentBatchResultORM(Base):
    __tablename__ = "rent_generation_results"
    batch_id: Mapped[str] = mapped_column(ForeignKey("rent_generation_batches.id", ondelete="CASCADE"), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    charge_id: Mapped[str] = mapped_column(String, nullable=False)
    was_created: Mapped[bool] = mapped_column(Boolean, nullable=False)
    basis_revision: Mapped[str] = mapped_column(String(64), nullable=False)


RENT_BATCH_TABLES = (RentSourceRevisionORM.__table__, RentBatchORM.__table__, RentBatchSelectionORM.__table__,
    RentBatchContractORM.__table__, RentBatchPriceORM.__table__, RentBatchResultORM.__table__)
