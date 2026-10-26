"""Reviewed customer migration and portability; additive and retained."""
import sqlalchemy as sa
from alembic import op

revision = "b4c6d8e0f2a5"
down_revision = "a3b5d7f9c1e4"
branch_labels = None
depends_on = None
NAMES = ('data_import_batches', 'data_import_files', 'data_external_references', 'data_portability_exports', 'data_imported_evidence')


def tables():
    metadata = sa.MetaData()
    sa.Table("portfolios", metadata, sa.Column("id", sa.String(), primary_key=True))
    result = []
    result.append(sa.Table('data_import_batches', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('portfolio_id', sa.String(), sa.ForeignKey('portfolios.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('source_system', sa.String(length=100), nullable=False),
        sa.Column('format', sa.String(length=24), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False, index=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('mappings', sa.JSON(), nullable=False),
        sa.Column('preview', sa.JSON(), nullable=False),
        sa.Column('target_sha256', sa.String(length=64), nullable=False),
        sa.Column('plan_sha256', sa.String(length=64), nullable=False),
        sa.Column('accepted_key', sa.String(length=100), nullable=True),
        sa.Column('accepted_sha256', sa.String(length=64), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_data_import_command'),
    ))
    result.append(sa.Table('data_import_files', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('batch_id', sa.String(length=36), sa.ForeignKey('data_import_batches.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('filename', sa.String(length=200), nullable=False),
        sa.Column('entity', sa.String(length=40), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint('batch_id', 'filename', name='uq_data_import_filename'),
    ))
    result.append(sa.Table('data_external_references', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('portfolio_id', sa.String(), sa.ForeignKey('portfolios.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_system', sa.String(length=100), nullable=False),
        sa.Column('entity', sa.String(length=40), nullable=False),
        sa.Column('external_ref', sa.String(length=200), nullable=False),
        sa.Column('record_id', sa.String(length=100), nullable=False, index=True),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('batch_id', sa.String(length=36), sa.ForeignKey('data_import_batches.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'source_system', 'entity', 'external_ref', name='uq_data_external_reference'),
    ))
    result.append(sa.Table('data_portability_exports', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False, index=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=True),
        sa.Column('sha256', sa.String(length=64), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('manifest', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_portability_export_command'),
    ))
    result.append(sa.Table('data_imported_evidence', metadata,
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('source_type', sa.String(length=100), nullable=False, index=True),
        sa.Column('record_id', sa.String(length=100), nullable=False, index=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('batch_id', sa.String(length=36), sa.ForeignKey('data_import_batches.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
    ))
    return result

def upgrade():
    from backend.db.migrations.additive_validation import verify_table
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial data transfer schema; verify retained sources before upgrading")
    for table in tables():
        if existing:
            verify_table(connection, table)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, NAMES, "Migration evidence must not be discarded; restore a verified pre-upgrade full backup")
    for name in reversed(NAMES):
        op.drop_table(name)
