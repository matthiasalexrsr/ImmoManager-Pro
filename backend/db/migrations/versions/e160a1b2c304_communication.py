"""Add durable communication, retaining all existing messages and manual dunning entries."""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c304"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("communication_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("thread_id", sa.String(), sa.ForeignKey('message_threads.id', ondelete='RESTRICT')),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey('integration_connections.id', ondelete='RESTRICT')),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_token", sa.Text(), nullable=False), sa.Column("message_id", sa.String(255)),
        sa.Column("dedupe_key", sa.String(64), unique=True), sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_communication_page", "communication_items", ["kind", "thread_id", "created_at", "id"])
    op.create_index("ix_communication_work", "communication_items", ["state", "lease_until", "id"])
    op.create_index("ix_communication_message_id", "communication_items", ["message_id"])
    op.create_table("communication_evidence", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("communication_blocks", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey('communication_evidence.id', ondelete='RESTRICT'), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("evidence_id", "sequence", name="uq_communication_block"))
    op.create_table('communication_attachments', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version_id', sa.String(120), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_communication_attachment_document', 'communication_attachments', ['document_id', 'item_id'])
    from backend.db.communication_models import install_guards
    install_guards(op.get_bind())


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    names = require_empty(connection, ('communication_attachments', 'communication_blocks', 'communication_evidence', 'communication_items'),
                          'Communication originals must be retained; restore a complete pre-upgrade backup instead.')
    for name in names:
        op.drop_table(name)
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('DROP FUNCTION IF EXISTS communication_evidence_guard()')
