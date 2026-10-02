"""Durable private drafts and immutable, tenant-bound lifecycle confirmations."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, inspect
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class ContractLifecycleDraftORM(Base):
    __tablename__ = "contract_lifecycle_drafts"
    __table_args__ = (
        UniqueConstraint("actor_id", "create_key", name="uq_contract_lifecycle_create"),
        Index("ix_contract_lifecycle_parent", "portfolio_id", "contract_id", "created_at", "id"),
        Index("ix_contract_lifecycle_actor", "actor_id", "contract_id", "created_at", "id"),
        Index("ix_contract_lifecycle_contract", "contract_id", "id"),
        CheckConstraint("state IN ('draft','reviewed','confirmed','pending_effective','completed','superseded')",
                        name="ck_contract_lifecycle_state"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    create_key: Mapped[str] = mapped_column(String(100), nullable=False)
    create_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_contract_etag: Mapped[str] = mapped_column(String, nullable=False)
    review: Mapped[dict | None] = mapped_column(JSON)
    review_hash: Mapped[str | None] = mapped_column(String(64))
    applied_contract_etag: Mapped[str | None] = mapped_column(String)
    finalized_contract_etag: Mapped[str | None] = mapped_column(String)
    successor_contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"))
    supersedes_draft_id: Mapped[str | None] = mapped_column(ForeignKey("contract_lifecycle_drafts.id", ondelete="RESTRICT"))
    superseded_by_draft_id: Mapped[str | None] = mapped_column(ForeignKey("contract_lifecycle_drafts.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractLifecycleCommandORM(Base):
    __tablename__ = "contract_lifecycle_commands"
    __table_args__ = (
        UniqueConstraint("actor_id", "command_key", name="uq_contract_lifecycle_command"),
        Index("ix_contract_lifecycle_history", "portfolio_id", "contract_id", "created_at", "id"),
        Index("ix_contract_lifecycle_commands_draft", "draft_id", "created_at", "id"),
        Index("ix_contract_lifecycle_command_contract", "contract_id", "id"),
        CheckConstraint("operation IN ('create','edit','review','confirm','finalize')",
                        name="ck_contract_lifecycle_command_operation"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("contract_lifecycle_drafts.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    command_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


LIFECYCLE_MODELS = (ContractLifecycleDraftORM, ContractLifecycleCommandORM)


def ensure_contract_lifecycle_schema(connection):
    present = set(inspect(connection).get_table_names())
    names = {model.__tablename__ for model in LIFECYCLE_MODELS}
    if present & names and not names <= present:
        raise RuntimeError("Incomplete contract lifecycle journal schema; explicit schema recovery is required")
    for model in LIFECYCLE_MODELS:
        table: Any = model.__table__
        table.create(connection, checkfirst=True)
        actual = {column["name"] for column in inspect(connection).get_columns(model.__tablename__)}
        if not set(table.c.keys()) <= actual:
            raise RuntimeError("Incomplete contract lifecycle journal columns; explicit schema recovery is required")
        for index in table.indexes:
            index.create(connection, checkfirst=True)
    from .migrations.versions.z1a2b3c4d5e6_contract_lifecycle import install_guards
    install_guards(connection)
