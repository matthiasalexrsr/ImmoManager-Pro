"""Versioned payees and decisions tied to the exact payable invoice state."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class PaymentRecipientORM(Base):
    __tablename__ = "payment_recipient_versions"
    __table_args__ = (UniqueConstraint("invoice_id", "number", name="uq_payment_recipient_number"),
                      UniqueConstraint("created_by", "idempotency_key", name="uq_payment_recipient_command"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    iban: Mapped[str] = mapped_column(String(34), nullable=False)
    bic: Mapped[str | None] = mapped_column(String(11))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentAuthorizationORM(Base):
    __tablename__ = "payment_authorizations"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_payment_authorization_command"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("payment_recipient_versions.id", ondelete="RESTRICT"))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    verification: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentSecuritySettingsORM(Base):
    __tablename__ = "payment_security_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    single_user_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentTotpUseORM(Base):
    __tablename__ = "payment_totp_uses"
    __table_args__ = (UniqueConstraint("user_id", "counter", name="uq_payment_totp_counter"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    counter: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentSecurityEventORM(Base):
    __tablename__ = "payment_security_events"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_payment_mode_command"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    single_user_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    totp_use_id: Mapped[str | None] = mapped_column(ForeignKey("payment_totp_uses.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentTotpAttemptORM(Base):
    __tablename__ = "payment_totp_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
