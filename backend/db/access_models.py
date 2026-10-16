"""Indexed portfolio grants and explicit ownership of unanchored resources."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class RegistrationQuotaORM(Base):
    __tablename__ = "registration_quotas"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[list] = mapped_column(JSON, nullable=False)


class PluginInstallationORM(Base):
    __tablename__ = "plugin_installations"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    backups: Mapped[list] = mapped_column(JSON, nullable=False)
    commands: Mapped[dict] = mapped_column(JSON, nullable=False)


class StorageBindingORM(Base):
    __tablename__ = "storage_bindings"
    storage_key: Mapped[str] = mapped_column(Text, primary_key=True)
    bucket: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
