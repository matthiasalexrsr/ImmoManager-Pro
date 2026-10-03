"""Persistent communication templates, reusable blocks and reviewed drafts."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class CommunicationTemplateORM(Base):
    __tablename__ = "communication_templates"
    __table_args__ = (
        Index("idx_communication_templates_category", "category", "is_active"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommunicationBlockORM(Base):
    __tablename__ = "communication_blocks"
    __table_args__ = (
        UniqueConstraint("key", "locale", name="uq_communication_block_key_locale"),
        Index("idx_communication_blocks_category", "category", "is_active"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    content_template: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommunicationDraftORM(Base):
    __tablename__ = "communication_drafts"
    __table_args__ = (
        Index("idx_communication_drafts_portfolio", "portfolio_id", "updated_at", "id"),
        Index("idx_communication_drafts_recipient", "recipient_type", "recipient_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String(36))
    template_id: Mapped[str | None] = mapped_column(String(36))
    template_revision: Mapped[int | None] = mapped_column(Integer)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_subject: Mapped[str | None] = mapped_column(Text)
    rendered_body: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[str | None] = mapped_column(Text)
    context_sha256: Mapped[str | None] = mapped_column(String(64))
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    document_pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    external_reference: Mapped[str | None] = mapped_column(String(300))
    external_status: Mapped[str | None] = mapped_column(String(80))
    whatsapp_template_name: Mapped[str | None] = mapped_column(String(200))
    whatsapp_language_code: Mapped[str] = mapped_column(String(20), nullable=False, default="de")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def ensure_communication_center_schema(connection) -> None:
    """Additive create-all compatibility for local installations."""
    for model in (CommunicationTemplateORM, CommunicationBlockORM, CommunicationDraftORM):
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
