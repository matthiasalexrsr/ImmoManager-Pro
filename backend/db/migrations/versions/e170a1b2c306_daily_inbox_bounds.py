"""Bounded inbox indexes and transactional notification generation; no legacy rewrites."""
import sqlalchemy as sa
from alembic import op

revision = 'e170a1b2c306'
down_revision = 'e160a1b2c305'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('daily_inbox_epoch', sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('revision', sa.Integer(), nullable=False))
    op.create_index('idx_notifications_inbox_order', 'notifications', ['created_at', 'id'])
    op.create_index('idx_notifications_inbox_filter', 'notifications', ['entity_type', 'severity', 'created_at', 'id'])
    from backend.db.daily_models import install_inbox_epoch
    install_inbox_epoch(op.get_bind())


def downgrade():
    # Only a derived cache generation and indexes live in this revision. The
    # actual personal receipts are preserved by their own parent guard.
    connection = op.get_bind()
    if connection.dialect.name == 'sqlite':
        for action in ('insert', 'update', 'delete'):
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS daily_notice_{action}')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS daily_notice_change ON notifications')
        connection.exec_driver_sql('DROP FUNCTION IF EXISTS daily_notice_epoch()')
    op.drop_index('idx_notifications_inbox_filter', table_name='notifications')
    op.drop_index('idx_notifications_inbox_order', table_name='notifications')
    op.drop_table('daily_inbox_epoch')
