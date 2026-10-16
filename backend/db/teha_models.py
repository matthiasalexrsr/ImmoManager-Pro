"""TEHA-local receive checkpoints and immutable publication evidence.

Private source and mapping values are encrypted. ConnectionRuns owns transport
claims and source blocks; these tables never store credentials or sessions.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class TehaBatchORM(Base):
    __tablename__ = "teha_receive_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    next_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (CheckConstraint("state IN ('receiving','ready','cancelled','revoked')", name="ck_teha_batch_state"),
        CheckConstraint("next_index >= 0 AND next_index <= total AND revision > 0", name="ck_teha_checkpoint"),
        Index("ix_teha_batches_page", "connection_id", "created_at", "id"))


class TehaItemORM(Base):
    __tablename__ = "teha_receive_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("teha_receive_batches.id", ondelete="RESTRICT"), nullable=False)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    source_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("batch_id", "position", name="uq_teha_item_position"),
        UniqueConstraint("batch_id", "identity_sha256", name="uq_teha_item_identity"),
        Index("ix_teha_items_page", "batch_id", "created_at", "id"))


class TehaMappingORM(Base):
    __tablename__ = "teha_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("connection_id", "identity_sha256", name="uq_teha_mapping_identity"),)


class TehaReceiptORM(Base):
    __tablename__ = "teha_publication_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("teha_receive_items.id", ondelete="RESTRICT"), nullable=False)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    mapping_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    predecessor_id: Mapped[str | None] = mapped_column(ForeignKey("teha_publication_receipts.id", ondelete="RESTRICT"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("maintenance_cases.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_teha_receipts_identity", "connection_id", "identity_sha256", "created_at", "id"),
        UniqueConstraint("item_id", name="uq_teha_publication_item"))


class TehaReturnDraftORM(Base):
    __tablename__ = "teha_return_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("teha_receive_items.id", ondelete="RESTRICT"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (CheckConstraint("kind IN ('cost_user_data','maintenance_order')", name="ck_teha_return_kind"),
                     Index("ix_teha_return_page", "connection_id", "created_at", "id"))


def install_guards(connection):
    """Receipts and received item snapshots cannot be rewritten by ordinary SQL."""
    for table in ("teha_publication_receipts", "teha_receive_items", "teha_return_drafts"):
        if connection.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable TEHA evidence'); END")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql("CREATE OR REPLACE FUNCTION teha_immutable_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable TEHA evidence'; END $$")
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION teha_immutable_evidence()")


def _after_create(target, connection, **kw):
    from sqlalchemy import inspect
    if {"teha_publication_receipts", "teha_receive_items", "teha_return_drafts"} <= set(inspect(connection).get_table_names()):
        install_guards(connection)


event.listen(Base.metadata, "after_create", _after_create)
