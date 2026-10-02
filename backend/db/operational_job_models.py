"""Durable packet jobs. Business deduplication stays in the existing journals."""

from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class OperationalJobORM(Base):
    __tablename__ = "operational_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    create_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "create_key", name="uq_operational_job_create"),
        CheckConstraint("revision > 0 AND turn >= 0", name="ck_operational_job_versions"),
        CheckConstraint("state IN ('queued','running','completed','attention','cancelled')", name="ck_operational_job_state"),
        Index("ix_operational_job_actor", "actor_id", "created_at", "id"),
    )


class OperationalJobLaneORM(Base):
    __tablename__ = "operational_job_lanes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("operational_jobs.id", ondelete="RESTRICT"), nullable=False)
    family: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    cursor: Mapped[str | None] = mapped_column(String)
    upper: Mapped[str | None] = mapped_column(String)
    exhausted: Mapped[bool] = mapped_column(nullable=False)
    served: Mapped[int] = mapped_column(Integer, nullable=False)
    fence: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String)
    lease_owner: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String)
    scanned: Mapped[int] = mapped_column(Integer, nullable=False)
    created: Mapped[int] = mapped_column(Integer, nullable=False)
    updated: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("job_id", "family", name="uq_operational_job_lane"),
        CheckConstraint("state IN ('ready','completed','attention','cancelled')", name="ck_operational_lane_state"),
        CheckConstraint("served >= 0 AND fence >= 0 AND scanned >= 0 AND created >= 0 AND updated >= 0 AND skipped >= 0", name="ck_operational_lane_counts"),
        Index("ix_operational_lane_claim", "job_id", "state", "served", "id"),
    )


class OperationalWorkItemORM(Base):
    __tablename__ = "operational_work_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("operational_jobs.id", ondelete="RESTRICT"), nullable=False)
    lane_id: Mapped[str | None] = mapped_column(ForeignKey("operational_job_lanes.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    action_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String)
    planned_revision: Mapped[str | None] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("job_id", "action_key", name="uq_operational_work_action"),
        CheckConstraint("kind IN ('source','command')", name="ck_operational_item_kind"),
        CheckConstraint("state IN ('ready','done','attention')", name="ck_operational_item_state"),
        CheckConstraint("revision > 0 AND attempts >= 0", name="ck_operational_item_counts"),
        Index("ix_operational_item_pending", "lane_id", "state", "id"),
        Index("ix_operational_item_page", "job_id", "kind", "id"),
    )


JOB_MODELS = (OperationalJobORM, OperationalJobLaneORM, OperationalWorkItemORM)


def ensure_operational_job_schema(connection):
    """Explicit setup helper; registration/migration is owned by the runtime."""
    for model in JOB_MODELS:
        cast(Table, model.__table__).create(connection, checkfirst=True)
    install_job_guards(connection)


def install_job_guards(connection):
    """CAS command receipts cannot be rewritten or removed by generic resets."""
    if connection.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS immo_operational_command_" + action.lower()
                + " BEFORE " + action + " ON operational_work_items WHEN OLD.kind='command' "
                "BEGIN SELECT RAISE(ABORT,'operational command receipt is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_operational_command_guard() RETURNS trigger AS $$
            BEGIN IF OLD.kind='command' THEN RAISE EXCEPTION 'operational command receipt is immutable'; END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_operational_command_immutable ON operational_work_items")
        connection.exec_driver_sql("CREATE TRIGGER immo_operational_command_immutable BEFORE UPDATE OR DELETE ON operational_work_items "
            "FOR EACH ROW EXECUTE FUNCTION immo_operational_command_guard()")
