"""Persistent identities for local schedules and notifications, without cascades.

An instance can be moved, completed or deleted without losing its occurrence
identity. These tables intentionally do not cascade when business rows disappear.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class OperationalLockORM(Base):
    __tablename__ = "operational_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (CheckConstraint("id = 1", name="ck_operational_singleton"),)


class OperationalScheduleORM(Base):
    __tablename__ = "operational_schedules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    recurrence_rule: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    full_catch_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("source_kind", "source_id", name="uq_operational_source"),)


class OperationalOccurrenceORM(Base):
    __tablename__ = "operational_occurrences"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(String, nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_kind: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    __table_args__ = (UniqueConstraint("schedule_id", "occurrence_date", name="uq_operational_occurrence"),)


class OperationalDispatchORM(Base):
    __tablename__ = "operational_dispatches"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    notification_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    target_role: Mapped[str | None] = mapped_column(String)
    family: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String)
    archived_by_tick: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OperationalTickORM(Base):
    __tablename__ = "operational_ticks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
