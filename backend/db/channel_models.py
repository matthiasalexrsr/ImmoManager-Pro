"""Durable frozen channel cases and encrypted original evidence (no financial ledger)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ChannelCaseORM(Base):
    __tablename__ = "channel_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_token: Mapped[str] = mapped_column(Text, nullable=False)
    progress_token: Mapped[str] = mapped_column(Text, nullable=False)
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"))
    connection_revision: Mapped[int | None] = mapped_column(Integer)
    external_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        Index("ix_channel_source", "source_kind", "source_id", "id"),
        CheckConstraint("source_kind = entity_type AND source_id = entity_id", name="ck_channel_source_binding"),
    )


class ChannelEvidenceORM(Base):
    __tablename__ = "channel_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("channel_cases.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data_token: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("case_id", "name", "sequence", name="uq_channel_evidence_block"),)


class ChannelEventORM(Base):
    __tablename__ = "channel_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("channel_cases.id", ondelete="RESTRICT"), nullable=False)
    replay_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("case_id", "replay_hash", name="uq_channel_event_replay"),
        Index("ix_channel_event_page", "case_id", "id"),
    )


class ChannelWebhookORM(Base):
    __tablename__ = "channel_webhooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("connection_id", "sha256", name="uq_channel_webhook_replay"),
        Index("ix_channel_webhook_page", "connection_id", "id"),
    )
