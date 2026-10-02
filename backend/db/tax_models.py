"""Self-contained immutable annual tax evidence, directly bound to a portfolio."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class AnnualTaxProfileORM(Base):
    __tablename__ = "annual_tax_profiles"
    __table_args__ = (Index("idx_tax_profiles_portfolio_year", "portfolio_id", "tax_year", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnnualTaxProjectionORM(Base):
    __tablename__ = "annual_tax_projections"
    __table_args__ = (Index("idx_tax_projections_portfolio_year", "portfolio_id", "tax_year", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT"), nullable=False)
    # One annual root and one successor per snapshot: revisions replace their
    # predecessor in reports; they must never be added as another cash receipt.
    annual_root_key: Mapped[str | None] = mapped_column(String, unique=True)
    previous_projection_id: Mapped[str | None] = mapped_column(ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnnualTaxSourceORM(Base):
    __tablename__ = "annual_tax_sources"
    __table_args__ = (Index("idx_tax_sources_projection_sequence", "projection_id", "sequence_number", unique=True),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    projection_id: Mapped[str] = mapped_column(ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), nullable=False)
    # This is evidence copied at the projection's snapshot, not a mutable join to
    # today's booking. Retaining the exact source ID/hash permits corrections
    # without making old projections depend on today's label/classification.
    booking_id: Mapped[str] = mapped_column(String, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
