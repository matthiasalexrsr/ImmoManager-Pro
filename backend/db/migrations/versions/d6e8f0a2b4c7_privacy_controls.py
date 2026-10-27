"""Reviewed privacy decisions and restoration gate; additive retained evidence."""
import sqlalchemy as sa
from alembic import op

revision = "d6e8f0a2b4c7"
down_revision = "c5d7e9f1a3b6"
branch_labels = None
depends_on = None
NAMES = ('privacy_controls', 'privacy_decisions', 'privacy_requests', 'privacy_restore_reviews')

def tables():
    metadata = sa.MetaData()
    result = []
    result.append(sa.Table('privacy_controls', metadata,
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('record_id', sa.String(length=100), nullable=False),
        sa.Column('held', sa.Boolean(), nullable=False),
        sa.Column('restricted', sa.Boolean(), nullable=False),
        sa.Column('erased_at', sa.DateTime(), nullable=True),
        sa.Column('erasure_due', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('actor_id', sa.String(length=50), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('kind', 'record_id', name='uq_privacy_resource'),
    ))
    result.append(sa.Table('privacy_decisions', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('record_id', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('actor_id', sa.String(length=50), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('actor_id', 'idempotency_key', name='uq_privacy_command'),
    ))
    result.append(sa.Table('privacy_requests', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('subject_kind', sa.String(length=12), nullable=False),
        sa.Column('subject_id', sa.String(length=100), nullable=False),
        sa.Column('request_type', sa.String(length=12), nullable=False),
        sa.Column('verification', sa.Text(), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('due_on', sa.Date(), nullable=False),
        sa.Column('outcome', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_privacy_request'),
    ))
    result.append(sa.Table('privacy_restore_reviews', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('pending', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('actor_id', sa.String(length=50), nullable=True),
        sa.Column('journal_sha256', sa.String(length=64), nullable=True),
        sa.Column('restore_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ))
    return result

def upgrade():
    from backend.db.migrations.additive_validation import verify_table
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial privacy schema; verify retained sources before upgrading")
    for table in tables():
        if existing:
            # A metadata-created current schema may already contain the later,
            # explicitly reviewed additive file tombstones. Verify them too.
            if table.name == 'privacy_controls' and any(column['name'] == 'file_keys_sha256'
                    for column in inspector.get_columns(table.name)):
                table.append_column(sa.Column('file_keys_sha256', sa.JSON, nullable=True))
            verify_table(connection, table)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, NAMES, "Privacy decisions must not be discarded; restore a verified pre-upgrade full backup")
    for name in reversed(NAMES):
        op.drop_table(name)
