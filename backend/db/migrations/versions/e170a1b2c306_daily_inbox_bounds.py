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
    raise RuntimeError('Kein automatischer Downgrade; vollständigen gesicherten Stand wiederherstellen.')
