"""Durable, shared office history and recoverable commands."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ConversationNoteORM(Base):
    __tablename__ = "business_conversation_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_business_notes_context", "entity_type", "entity_id", "occurred_at", "id"),)


class BusinessCommandORM(Base):
    __tablename__ = "business_qol_commands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inverse: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    post_revision: Mapped[str | None] = mapped_column(String(200))
    undone_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_business_commands_actor", "actor_id", "id"),)


class DocumentIntakeORM(Base):
    __tablename__ = "business_document_intake"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    source_file_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    sha256: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("document_id", name="uq_business_intake_document"),
                      Index("ix_business_intake_hash", "sha256", "document_id"),
                      Index("ix_business_intake_status", "status", "id"))


class DuplicateExceptionORM(Base):
    __tablename__ = "business_duplicate_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    duplicate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    source_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    duplicate_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_business_duplicate_pair", "entity_type", "entity_id", "duplicate_id"),)
