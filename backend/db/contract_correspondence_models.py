"""Private current drafts, frozen approvals and append-only manual evidence."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class CorrespondenceDraftORM(Base):
    __tablename__ = "contract_correspondence_drafts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    create_key: Mapped[str] = mapped_column(String(100), nullable=False)
    create_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    deadline_date: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_contract_etag: Mapped[str] = mapped_column(String, nullable=False)
    review: Mapped[dict | None] = mapped_column(JSON)
    review_hash: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "create_key", name="uq_correspondence_create"),
        CheckConstraint("state IN ('draft','reviewed','approved')", name="ck_correspondence_state"),
        Index("ix_correspondence_parent", "portfolio_id", "contract_id", "created_at", "id"),
        Index("ix_correspondence_actor", "actor_id", "contract_id", "created_at", "id"),
        Index("ix_correspondence_deadline", "portfolio_id", "state", "deadline_date", "id"),
    )


class CorrespondenceCommandORM(Base):
    __tablename__ = "contract_correspondence_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_correspondence_drafts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    command_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "command_key", name="uq_correspondence_command"),
        CheckConstraint("operation IN ('create','edit','review','approve','event')", name="ck_correspondence_operation"),
        Index("ix_correspondence_commands", "portfolio_id", "contract_id", "draft_id", "created_at", "id"),
    )


class CorrespondenceEventORM(Base):
    __tablename__ = "contract_correspondence_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_correspondence_drafts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    event_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False)
    review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("draft_id", "event_revision", name="uq_correspondence_event_revision"),
        CheckConstraint("event_revision > 0", name="ck_correspondence_event_revision"),
        Index("ix_correspondence_events", "portfolio_id", "contract_id", "draft_id", "event_revision"),
    )


CORRESPONDENCE_MODELS = (CorrespondenceDraftORM, CorrespondenceCommandORM, CorrespondenceEventORM)


def ensure_contract_correspondence_schema(connection):
    names = {model.__tablename__ for model in CORRESPONDENCE_MODELS}
    present = set(inspect(connection).get_table_names())
    if present & names and not names <= present:
        raise RuntimeError("Incomplete contract correspondence journal; explicit schema recovery required")
    for model in CORRESPONDENCE_MODELS:
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
        if not set(table.c.keys()) <= {column["name"] for column in inspect(connection).get_columns(table.name)}:
            raise RuntimeError("Incomplete contract correspondence columns; explicit schema recovery required")
        for index in table.indexes:
            index.create(connection, checkfirst=True)
    from .migrations.versions.a2a2b3c4d5e6_contract_correspondence import install_guards
    install_guards(connection)
