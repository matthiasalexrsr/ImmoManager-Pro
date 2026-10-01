"""Versioned templates, durable reviewed drafts and immutable command evidence."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ContractTemplateORM(Base):
    __tablename__ = "contract_template_versions"
    __table_args__ = (UniqueConstraint("root_id", "version", name="uq_contract_template_version"),
                     UniqueConstraint("actor_id", "create_key", name="uq_contract_template_create"),
                     Index("idx_contract_templates_portfolio", "portfolio_id", "created_at", "id"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    root_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    create_key: Mapped[str] = mapped_column(String(100), nullable=False)
    create_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractDraftORM(Base):
    __tablename__ = "contract_wizard_drafts"
    __table_args__ = (UniqueConstraint("actor_id", "create_key", name="uq_contract_draft_create"),
                     Index("idx_contract_drafts_actor", "actor_id", "created_at", "id"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    create_key: Mapped[str] = mapped_column(String(100), nullable=False)
    create_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    review: Mapped[dict | None] = mapped_column(JSON)
    review_hash: Mapped[str | None] = mapped_column(String(64))
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    published_tenant_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractWizardCommandORM(Base):
    __tablename__ = "contract_wizard_commands"
    __table_args__ = (UniqueConstraint("actor_id", "command_key", name="uq_contract_wizard_command"),
                     Index("idx_contract_commands_draft", "draft_id", "created_at", "id"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_wizard_drafts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    command_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractSignatureORM(Base):
    __tablename__ = "contract_signature_evidence"
    __table_args__ = (Index("idx_contract_signatures_draft", "draft_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_wizard_drafts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    signed_date: Mapped[date] = mapped_column(Date, nullable=False)
    tenant_signer: Mapped[str] = mapped_column(Text, nullable=False)
    landlord_signer: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    signed_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractAttachmentORM(Base):
    __tablename__ = "contract_attachment_evidence"
    __table_args__ = (UniqueConstraint("draft_id", "source_document_id", name="uq_contract_attachment_source"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_wizard_drafts.id", ondelete="RESTRICT"), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String, nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)


class ContractAttachmentChunkORM(Base):
    __tablename__ = "contract_attachment_chunks"
    attachment_id: Mapped[str] = mapped_column(ForeignKey("contract_attachment_evidence.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


WIZARD_MODELS = (ContractTemplateORM, ContractDraftORM, ContractWizardCommandORM, ContractSignatureORM,
                ContractAttachmentORM, ContractAttachmentChunkORM)


def ensure_contract_wizard_schema(connection):
    for model in WIZARD_MODELS:
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
    from .migrations.versions.v1a2b3c4d5e6_reviewed_contract_workflow import install_evidence_guards
    install_evidence_guards(connection)
