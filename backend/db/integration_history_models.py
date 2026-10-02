"""Private installation telemetry. It is never a payment or delivery receipt."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class IntegrationHistoryHeadORM(Base):
    __tablename__ = "integration_history_heads"
    integration_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    clear_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active_runs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    history_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (CheckConstraint("run_sequence >= 0 AND event_sequence >= 0 AND clear_epoch >= 0 AND active_runs >= 0", name="ck_history_head_counts"),)


class IntegrationRunORM(Base):
    __tablename__ = "integration_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integration_history_heads.integration_id", ondelete="RESTRICT"), nullable=False)
    run_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    scope_kind: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metadata_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("integration_id", "run_sequence", name="uq_history_run_sequence"),
        UniqueConstraint("id", "integration_id", name="uq_history_run_binding"),
        CheckConstraint("run_sequence > 0 AND scope_kind='installation'", name="ck_history_run_scope"),
        CheckConstraint("origin IN ('authenticated_request','internal_service')", name="ck_history_run_origin"),
        Index("ix_history_runs_page", "integration_id", "run_sequence"),
    )


class IntegrationRunEventORM(Base):
    __tablename__ = "integration_run_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    integration_id: Mapped[str] = mapped_column(String, nullable=False)
    event_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    journal_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    success: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    metadata_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "event_number", name="uq_history_event_number"),
        UniqueConstraint("integration_id", "journal_sequence", name="uq_history_journal_sequence"),
        ForeignKeyConstraint(["run_id", "integration_id"], ["integration_runs.id", "integration_runs.integration_id"], ondelete="RESTRICT"),
        CheckConstraint("event_number > 0 AND journal_sequence > 0", name="ck_history_event_sequence"),
        CheckConstraint("state IN ('accepted','execution_started','completed','rejected','observation_failed','outcome_uncertain')", name="ck_history_event_state"),
        Index("ix_history_event_snapshot", "run_id", "journal_sequence"),
    )


class IntegrationRunChunkORM(Base):
    __tablename__ = "integration_run_chunks"
    event_id: Mapped[str] = mapped_column(ForeignKey("integration_run_events.id", ondelete="RESTRICT"), primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("position >= 0", name="ck_history_chunk_position"),)


class IntegrationHistoryClearORM(Base):
    __tablename__ = "integration_history_clears"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integration_history_heads.integration_id", ondelete="RESTRICT"), nullable=False)
    clear_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cleared: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("integration_id", "clear_epoch", name="uq_history_clear_epoch"), CheckConstraint("clear_epoch > 0 AND cleared >= 0", name="ck_history_clear_counts"))


HISTORY_MODELS = (IntegrationHistoryHeadORM, IntegrationRunORM, IntegrationRunEventORM, IntegrationRunChunkORM, IntegrationHistoryClearORM)
TABLES = tuple(model.__tablename__ for model in HISTORY_MODELS)
