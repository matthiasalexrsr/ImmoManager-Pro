"""Account security families and irreversible refresh consumption fingerprints."""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class AuthSessionORM(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("idx_auth_sessions_user_created", "user_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    device_label: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoke_reason: Mapped[str | None] = mapped_column(String(32))
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    current_refresh_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    legacy_refresh_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class AuthRefreshORM(Base):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (UniqueConstraint("session_id", "generation", name="uq_auth_refresh_generation"),
                     Index("idx_auth_refresh_session", "session_id"))
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


def ensure_session_schema(connection):
    """Repeatable additive create_all compatibility; no token history rewriting."""
    for model in (AuthSessionORM, AuthRefreshORM):
        table: Any = model.__table__
        table.create(connection, checkfirst=True)


def invalidate_restored_sessions(connection):
    """Offline full-restore hook; preserve consumed fingerprints and audit rows.

    Recovery callers must invoke before starting writers. Ordinary startup must
    never call this. Legacy JWTs also require signing-key rotation at recovery.
    """
    result = connection.execute(update(AuthSessionORM).where(AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=func.current_timestamp(), revoke_reason="database_restore"))
    return cast(CursorResult, result).rowcount
