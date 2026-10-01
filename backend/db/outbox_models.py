"""Durable SMTP snapshots, append-only events, and idempotent command results."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class OutboxMessageORM(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("idx_outbox_messages_portfolio", "portfolio_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    wire: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wire_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OutboxEventORM(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("idx_outbox_events_message", "message_id", "revision"),
        Index("idx_outbox_events_portfolio", "portfolio_id", "id"),
        UniqueConstraint("message_id", "revision", name="uq_outbox_event_revision"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    message_id: Mapped[str] = mapped_column(ForeignKey("outbox_messages.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class OutboxCommandORM(Base):
    __tablename__ = "outbox_commands"
    __table_args__ = (Index("idx_outbox_commands_message", "message_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    message_id: Mapped[str] = mapped_column(ForeignKey("outbox_messages.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    claim_token: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def ensure_outbox_schema(connection):
    """Additive local create_all compatibility; no historical-row rewrites."""
    for model in (OutboxMessageORM, OutboxEventORM, OutboxCommandORM):
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
