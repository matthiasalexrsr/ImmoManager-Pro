"""User-owned workspace rows. Services always include owner_user_id in their queries."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base

WORKSPACE_TABLES = (
    "workspace_drafts", "workspace_views", "workspace_recents", "workspace_favorites",
    "workspace_view_states", "workspace_deferrals", "workspace_commands",
)


class WorkspaceRow:
    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    context: Mapped[str] = mapped_column(String(240), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkspaceDraftORM(WorkspaceRow, Base):
    __tablename__ = "workspace_drafts"
    __table_args__ = (Index("ix_workspace_drafts_owner_page", "owner_user_id", "created_at", "id"),)


class WorkspaceViewORM(WorkspaceRow, Base):
    __tablename__ = "workspace_views"
    name_key: Mapped[str] = mapped_column(String(240), nullable=False)
    __table_args__ = (
        UniqueConstraint("owner_user_id", "context", "name_key", name="uq_workspace_view_name"),
        Index("ix_workspace_views_owner_page", "owner_user_id", "created_at", "id"),
    )


class WorkspaceRecentORM(WorkspaceRow, Base):
    __tablename__ = "workspace_recents"
    __table_args__ = (Index("ix_workspace_recents_owner_page", "owner_user_id", "updated_at", "id"),)


class WorkspaceFavoriteORM(WorkspaceRow, Base):
    __tablename__ = "workspace_favorites"
    __table_args__ = (Index("ix_workspace_favorites_owner_page", "owner_user_id", "created_at", "id"),)


class WorkspaceViewStateORM(WorkspaceRow, Base):
    __tablename__ = "workspace_view_states"
    __table_args__ = (Index("ix_workspace_view_states_owner", "owner_user_id", "context"),)


class WorkspaceDeferralORM(WorkspaceRow, Base):
    __tablename__ = "workspace_deferrals"
    __table_args__ = (Index("ix_workspace_deferrals_owner_page", "owner_user_id", "created_at", "id"),)


class WorkspaceCommandORM(Base):
    __tablename__ = "workspace_commands"
    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("owner_user_id", "idempotency_key", name="uq_workspace_command_key"),)
