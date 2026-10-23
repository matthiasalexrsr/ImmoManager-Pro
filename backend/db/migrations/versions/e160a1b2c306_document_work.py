"""Document sessions, recoverable commands, OCR reviews and evidence links.

Revision ID: e160a1b2c306
Revises: d73f2b9a041c
"""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c306"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("document_work_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("protocol_id", sa.String(), sa.ForeignKey("handover_protocols.id", ondelete="RESTRICT")),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("command_key", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "command_key", name="uq_document_work_command"),
        sa.UniqueConstraint("resource_id", "revision", name="uq_document_work_revision"))
    op.create_index("ix_document_work_page", "document_work_events", ["document_id", "kind", "created_at", "id"])
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(f"CREATE TRIGGER immo_document_work_{operation.lower()} BEFORE {operation} "
                "ON document_work_events BEGIN SELECT RAISE(ABORT, 'document work history is immutable'); END")
        connection.exec_driver_sql("CREATE TRIGGER immo_handover_evidence_binding BEFORE UPDATE OF contract_id, unit_id "
            "ON handover_protocols WHEN (OLD.contract_id IS NOT NEW.contract_id OR OLD.unit_id IS NOT NEW.unit_id) "
            "AND EXISTS (SELECT 1 FROM document_work_events WHERE protocol_id=OLD.id) "
            "BEGIN SELECT RAISE(ABORT, 'handover evidence binding is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE FUNCTION immo_document_work_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'document work history is immutable'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("CREATE TRIGGER immo_document_work_immutable BEFORE UPDATE OR DELETE ON document_work_events "
            "FOR EACH ROW EXECUTE FUNCTION immo_document_work_immutable()")
        connection.exec_driver_sql("CREATE FUNCTION immo_handover_evidence_binding() RETURNS trigger AS $$ "
            "BEGIN IF (OLD.contract_id IS DISTINCT FROM NEW.contract_id OR OLD.unit_id IS DISTINCT FROM NEW.unit_id) "
            "AND EXISTS (SELECT 1 FROM document_work_events WHERE protocol_id=OLD.id) THEN "
            "RAISE EXCEPTION 'handover evidence binding is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("CREATE TRIGGER immo_handover_evidence_binding BEFORE UPDATE ON handover_protocols "
            "FOR EACH ROW EXECUTE FUNCTION immo_handover_evidence_binding()")


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, ('document_work_events',),
                  'Document recovery and evidence history must be retained; restore a complete backup instead.')
    if connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS immo_handover_evidence_binding')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS immo_handover_evidence_binding ON handover_protocols')
        connection.exec_driver_sql('DROP FUNCTION IF EXISTS immo_handover_evidence_binding()')
    op.drop_table('document_work_events')
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('DROP FUNCTION IF EXISTS immo_document_work_immutable()')
