"""Durable job runs and the occurrence ledger (installation-scoped, no portfolio)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base

JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class JobRunORM(Base):
    __tablename__ = "job_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    # one run per key: a second worker enqueuing the same slot gets the existing run
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="installation")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    checkpoint: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        CheckConstraint("scope = 'installation'", name="ck_job_runs_scope"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_runs_status"),
        Index("ix_job_runs_due", "status", "available_at"),
        Index("ix_job_runs_lease", "status", "lease_expires_at"),
    )


class JobOccurrenceORM(Base):
    """One row per processed occurrence of a rule version: the primary key is the dedupe."""
    __tablename__ = "job_occurrences"
    rule_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    rule_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    occurrence_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36))   # no FK: finished runs may be pruned
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    __table_args__ = (Index("ix_job_occurrences_latest", "rule_key", "occurrence_key"),)


JOB_MODELS = (JobRunORM, JobOccurrenceORM)
