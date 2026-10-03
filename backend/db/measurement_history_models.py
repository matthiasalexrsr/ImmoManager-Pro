"""Versioned measurement evidence. Migration-owned; no request-time DDL."""

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


class MeasurementLedgerORM(Base):
    __tablename__ = "measurement_ledgers"
    id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_measurement_ledger_revision"),)


class MeasurementCommandORM(Base):
    __tablename__ = "measurement_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ledger_id: Mapped[str] = mapped_column(ForeignKey("measurement_ledgers.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(BigInteger)
    request_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key", name="uq_measurement_command_key"),
        UniqueConstraint("ledger_id", "revision", name="uq_measurement_command_revision"),
        CheckConstraint("revision > 0", name="ck_measurement_command_revision"))


class MeasurementFactORM(Base):
    __tablename__ = "measurement_facts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ledger_id: Mapped[str] = mapped_column(ForeignKey("measurement_ledgers.id", ondelete="RESTRICT"))
    command_id: Mapped[str] = mapped_column(ForeignKey("measurement_commands.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"))
    source_key: Mapped[str] = mapped_column(Text)
    predecessor_id: Mapped[str | None] = mapped_column(ForeignKey("measurement_facts.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    meter_id: Mapped[str | None] = mapped_column(ForeignKey("meters.id", ondelete="RESTRICT"))
    allocation_key_id: Mapped[str | None] = mapped_column(ForeignKey("allocation_keys.id", ondelete="RESTRICT"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    withdrawn: Mapped[bool]
    reason: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("predecessor_id", name="uq_measurement_fact_successor"),
        UniqueConstraint("ledger_id", "revision", "position", name="uq_measurement_fact_position"),
        CheckConstraint("revision > 0 AND position >= 0 AND valid_until >= valid_from", name="ck_measurement_fact_values"),
        CheckConstraint("kind IN ('assignment','reading','occupancy','selection','proration')", name="ck_measurement_fact_kind"),
        Index("ix_measurement_fact_period", "property_id", "valid_from", "valid_until", "ledger_id"),
        Index("ix_measurement_fact_source", "ledger_id", "source_key", "revision"),
        Index("ix_measurement_fact_subject", "tenant_id", "ledger_id", "revision"),
        Index("ix_measurement_fact_key", "allocation_key_id", "valid_from", "valid_until"))


class MeasurementEvidenceORM(Base):
    __tablename__ = "measurement_evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("measurement_facts.id", ondelete="RESTRICT"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("fact_id", "version_id", name="uq_measurement_evidence"),)


MEASUREMENT_MODELS = (MeasurementLedgerORM, MeasurementCommandORM, MeasurementFactORM, MeasurementEvidenceORM)
MEASUREMENT_TABLES = tuple(model.__tablename__ for model in MEASUREMENT_MODELS)
