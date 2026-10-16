"""Durable communication metadata and encrypted immutable MIME/raw evidence."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class CommunicationItemORM(Base):
    __tablename__ = "communication_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey('message_threads.id', ondelete='RESTRICT'))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey('integration_connections.id', ondelete='RESTRICT'))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_token: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255))
    dedupe_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index("ix_communication_page", "kind", "thread_id", "created_at", "id"),
                      Index("ix_communication_work", "state", "lease_until", "id"),
                      Index("ix_communication_message_id", "message_id"))


class CommunicationEvidenceORM(Base):
    __tablename__ = "communication_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommunicationBlockORM(Base):
    __tablename__ = "communication_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey('communication_evidence.id', ondelete='RESTRICT'), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    data_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("evidence_id", "sequence", name="uq_communication_block"),)


class CommunicationAttachmentORM(Base):
    __tablename__ = 'communication_attachments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='RESTRICT'), nullable=False)
    version_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (Index('ix_communication_attachment_document', 'document_id', 'item_id'),)


MODELS = (CommunicationItemORM, CommunicationEvidenceORM, CommunicationBlockORM, CommunicationAttachmentORM)


def install_guards(connection):
    for name in ("communication_evidence", "communication_blocks", "communication_attachments"):
        if connection.dialect.name == "sqlite":
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {name}_{operation.lower()}_guard "
                                          f"BEFORE {operation} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable communication evidence'); END")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql("CREATE OR REPLACE FUNCTION communication_evidence_guard() RETURNS trigger "
                                      "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable communication evidence'; END; $$")
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}_guard ON {name}")
            connection.exec_driver_sql(f"CREATE TRIGGER {name}_guard BEFORE UPDATE OR DELETE ON {name} "
                                      "FOR EACH ROW EXECUTE FUNCTION communication_evidence_guard()")


@event.listens_for(Base.metadata, "after_create")
def _guards(metadata, connection, **kw):
    from sqlalchemy import inspect
    if {model.__tablename__ for model in MODELS} <= set(inspect(connection).get_table_names()):
        install_guards(connection)
