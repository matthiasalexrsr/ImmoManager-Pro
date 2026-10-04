"""Durable dispute originals; only the case's derived revision/state may change."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class BillingDisputeCaseORM(Base):
    __tablename__ = "billing_dispute_cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"))
    period_id: Mapped[str] = mapped_column(ForeignKey("billing_periods.id", ondelete="RESTRICT"))
    statement_id: Mapped[str | None] = mapped_column(ForeignKey("utility_statements.id", ondelete="RESTRICT"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    case_kind: Mapped[str] = mapped_column(String(30))
    statement_revision: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    original_snapshot: Mapped[dict] = mapped_column(JSON)
    original_hash: Mapped[str] = mapped_column(String(64))
    party_binding: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("statement_id", name="uq_dispute_statement_case"),
        CheckConstraint("revision > 0", name="ck_dispute_case_revision"),
        CheckConstraint("state IN ('open','in_review','withdrawn','closed')", name="ck_dispute_case_state"),
        CheckConstraint("(case_kind = 'tenant_statement' AND statement_id IS NOT NULL AND contract_id IS NOT NULL AND tenant_id IS NOT NULL AND unit_id IS NOT NULL AND statement_revision > 0) OR (case_kind = 'property_review' AND statement_id IS NULL AND contract_id IS NULL AND tenant_id IS NULL AND unit_id IS NULL AND statement_revision IS NULL)", name="ck_dispute_case_binding"),
        Index("ix_dispute_case_property", "property_id", "state", "id"),
        Index("ix_dispute_case_period", "period_id", "id"),
        Index("ix_dispute_case_subject", "tenant_id", "id"),
    )


class BillingDisputeCommandORM(Base):
    __tablename__ = "billing_dispute_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("billing_dispute_cases.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(BigInteger)
    request_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_dispute_command_key"),
        UniqueConstraint("case_id", "revision", name="uq_dispute_command_revision"),
        CheckConstraint("revision > 0", name="ck_dispute_command_revision"),
    )


class BillingDisputeEventORM(Base):
    __tablename__ = "billing_dispute_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("billing_dispute_cases.id", ondelete="RESTRICT"))
    command_id: Mapped[str] = mapped_column(ForeignKey("billing_dispute_commands.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(BigInteger)
    actor_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    observed_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    corrects_event_id: Mapped[str | None] = mapped_column(ForeignKey("billing_dispute_events.id", ondelete="RESTRICT"))
    statement_revision: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    line_item_refs: Mapped[list] = mapped_column(JSON)
    correction_statement_id: Mapped[str | None] = mapped_column(ForeignKey("utility_statements.id", ondelete="RESTRICT"))
    correction_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_dispute_event_revision"),
        CheckConstraint("revision > 0 AND length(trim(reason)) > 0", name="ck_dispute_event_reason"),
        CheckConstraint("kind IN ('opened','note','in_review','correction','withdrawn','closed','reopened','correction_link')", name="ck_dispute_event_kind"),
    )


class BillingDisputeEvidenceORM(Base):
    __tablename__ = "billing_dispute_evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("billing_dispute_events.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("event_id", "version_id", name="uq_dispute_evidence_version"),)


DISPUTE_MODELS = (BillingDisputeCaseORM, BillingDisputeCommandORM, BillingDisputeEventORM, BillingDisputeEvidenceORM)
DISPUTE_TABLES = tuple(model.__tablename__ for model in DISPUTE_MODELS)
