"""Bounded inbox indexes and transactional notification generation; no legacy rewrites."""
import sqlalchemy as sa
from alembic import op

revision = 'e170a1b2c306'
down_revision = 'e160a1b2c305'
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.daily_models import InboxEpochORM, install_inbox_epoch
    from backend.db.migrations.adopt_existing import adopt_exact_family

    connection = op.get_bind()
    if not adopt_exact_family(connection, (InboxEpochORM,)):
        op.create_table('daily_inbox_epoch', sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('revision', sa.Integer(), nullable=False))
    existing = {idx['name']: (tuple(idx['column_names']), idx['unique'])
                for idx in sa.inspect(connection).get_indexes('notifications')}
    for index_name, columns in (
        ('idx_notifications_inbox_order', ('created_at', 'id')),
        ('idx_notifications_inbox_filter', ('entity_type', 'severity', 'created_at', 'id')),
    ):
        if index_name in existing:
            if existing[index_name] != (columns, 0):
                raise RuntimeError('Existing inbox index does not match authenticated pagination order')
        else:
            op.create_index(index_name, 'notifications', list(columns))
    install_inbox_epoch(connection)


def downgrade():
    raise RuntimeError('Kein automatischer Downgrade; vollständigen gesicherten Stand wiederherstellen.')
