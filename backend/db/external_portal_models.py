"""External identities are never internal users or holders of internal JWTs."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class PortalIdentityORM(Base):
    __tablename__ = "external_portal_identities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalGrantORM(Base):
    __tablename__ = "external_portal_grants"
    __table_args__ = (CheckConstraint("(kind = 'tenant' AND tenant_id IS NOT NULL AND contract_id IS NOT NULL AND contact_id IS NULL AND ownership_id IS NULL) OR (kind = 'owner' AND contact_id IS NOT NULL AND ownership_id IS NOT NULL AND tenant_id IS NULL AND contract_id IS NULL)", name="ck_portal_party_relation"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("external_portal_identities.id", ondelete="RESTRICT"), index=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    ownership_id: Mapped[str | None] = mapped_column(ForeignKey("ownership_shares.id", ondelete="RESTRICT"))
    binding: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_by: Mapped[str] = mapped_column(String(36), nullable=False)
    verification: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalInvitationORM(Base):
    __tablename__ = "external_portal_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("external_portal_grants.id", ondelete="RESTRICT"), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalSessionORM(Base):
    __tablename__ = "external_portal_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("external_portal_identities.id", ondelete="RESTRICT"), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    identity_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalPublicationORM(Base):
    __tablename__ = "external_portal_publications"
    __table_args__ = (UniqueConstraint("grant_id", "version_id", name="uq_portal_published_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("external_portal_grants.id", ondelete="RESTRICT"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    published_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalCaseORM(Base):
    __tablename__ = "external_portal_cases"
    __table_args__ = (UniqueConstraint("grant_id", "case_id", name="uq_portal_case_grant"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("external_portal_grants.id", ondelete="RESTRICT"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("maintenance_cases.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalMessageORM(Base):
    __tablename__ = "external_portal_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_link_id: Mapped[str] = mapped_column(ForeignKey("external_portal_cases.id", ondelete="RESTRICT"), index=True)
    sender_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(50), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalAttachmentORM(Base):
    __tablename__ = "external_portal_attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("external_portal_messages.id", ondelete="RESTRICT"), index=True)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(60), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalCommandORM(Base):
    __tablename__ = "external_portal_commands"
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key", name="uq_portal_command"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalEventORM(Base):
    __tablename__ = "external_portal_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("external_portal_grants.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortalAttemptORM(Base):
    __tablename__ = "external_portal_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    times: Mapped[list] = mapped_column(JSON, nullable=False)
