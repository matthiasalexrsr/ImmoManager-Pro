"""Indexed portfolio grants and explicit ownership of unanchored resources."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class UserAccessORM(Base):
    __tablename__ = "user_portfolio_access"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="owner_assignment")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    __table_args__ = (CheckConstraint("mode IN ('all', 'selected')", name="ck_user_access_mode"),)


class UserPortfolioORM(Base):
    __tablename__ = "user_portfolio_grants"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("ix_portfolio_grants_portfolio", "portfolio_id", "user_id"),)


class ResourcePortfolioORM(Base):
    __tablename__ = "resource_portfolio_grants"
    resource_type: Mapped[str] = mapped_column(String(80), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (Index("ix_resource_grants_portfolio", "portfolio_id", "resource_type", "resource_id"),)


class UploadAccessORM(Base):
    __tablename__ = "upload_portfolio_grants"
    storage_key: Mapped[str] = mapped_column(Text, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (Index("ix_upload_grants_portfolio", "portfolio_id", "storage_key"),)
