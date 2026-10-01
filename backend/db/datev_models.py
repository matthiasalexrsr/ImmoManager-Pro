"""Immutable mapping versions and reproducible export references, scoped by portfolio."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class DatevProfileORM(Base):
    __tablename__ = "datev_profiles"
    __table_args__ = (Index("idx_datev_profiles_portfolio", "portfolio_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("datev_profiles.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())


class DatevExportORM(Base):
    __tablename__ = "datev_exports"
    __table_args__ = (Index("idx_datev_exports_portfolio", "portfolio_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("datev_profiles.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
