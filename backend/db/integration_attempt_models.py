"""Individual provider attempts and cursor visits; facts survive lease replacement."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class IntegrationActionAttemptORM(Base):
    __tablename__ = "integration_action_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_token: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    success: Mapped[bool | None] = mapped_column(Boolean)
    manifest_token: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    result_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_blocks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("run_id", "number", name="uq_integration_attempt_number"),
        UniqueConstraint("lease_sha256", name="uq_integration_attempt_lease"),
        Index("ix_integration_attempt_page", "run_id", "created_at", "id"),
        Index("ix_integration_attempt_review", "run_id", "detached", "reviewed_at"),
    )


class IntegrationRunCursorORM(Base):
    __tablename__ = "integration_run_cursors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False)
    cursor_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    first_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "cursor_sha256", name="uq_integration_run_cursor"),)
