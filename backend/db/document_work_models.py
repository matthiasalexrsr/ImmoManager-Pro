"""Append-only application events, included in normal business snapshots."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class DocumentWorkEventORM(Base):
    __tablename__ = "document_work_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    protocol_id: Mapped[str | None] = mapped_column(ForeignKey("handover_protocols.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_key: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    __table_args__ = (
        UniqueConstraint("actor_id", "command_key", name="uq_document_work_command"),
        UniqueConstraint("resource_id", "revision", name="uq_document_work_revision"),
        Index("ix_document_work_page", "document_id", "kind", "created_at", "id"),
    )


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_document_work_{operation.lower()} "
                f"BEFORE {operation} ON document_work_events BEGIN SELECT RAISE(ABORT, 'document work history is immutable'); END")
        connection.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS immo_handover_evidence_binding BEFORE UPDATE OF contract_id, unit_id "
            "ON handover_protocols WHEN (OLD.contract_id IS NOT NEW.contract_id OR OLD.unit_id IS NOT NEW.unit_id) "
            "AND EXISTS (SELECT 1 FROM document_work_events WHERE protocol_id=OLD.id) "
            "BEGIN SELECT RAISE(ABORT, 'handover evidence binding is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE OR REPLACE FUNCTION immo_document_work_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'document work history is immutable'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_document_work_immutable ON document_work_events")
        connection.exec_driver_sql("CREATE TRIGGER immo_document_work_immutable BEFORE UPDATE OR DELETE ON document_work_events "
            "FOR EACH ROW EXECUTE FUNCTION immo_document_work_immutable()")
        connection.exec_driver_sql("CREATE OR REPLACE FUNCTION immo_handover_evidence_binding() RETURNS trigger AS $$ "
            "BEGIN IF (OLD.contract_id IS DISTINCT FROM NEW.contract_id OR OLD.unit_id IS DISTINCT FROM NEW.unit_id) "
            "AND EXISTS (SELECT 1 FROM document_work_events WHERE protocol_id=OLD.id) THEN "
            "RAISE EXCEPTION 'handover evidence binding is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_handover_evidence_binding ON handover_protocols")
        connection.exec_driver_sql("CREATE TRIGGER immo_handover_evidence_binding BEFORE UPDATE ON handover_protocols "
            "FOR EACH ROW EXECUTE FUNCTION immo_handover_evidence_binding()")


def _after_create(table, connection, **kwargs):
    install_guards(connection)


event.listen(DocumentWorkEventORM.__table__, "after_create", _after_create)
