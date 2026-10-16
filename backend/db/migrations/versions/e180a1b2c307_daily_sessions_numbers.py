"""Persistent session inventory and never-recycled contract number reservations."""
import sqlalchemy as sa
from alembic import op

revision = 'e180a1b2c307'
down_revision = 'e170a1b2c306'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('daily_auth_sessions',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('owner_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime()))
    op.create_index('ix_daily_auth_sessions_owner_id', 'daily_auth_sessions', ['owner_id'])
    op.create_table('daily_number_reservations',
        sa.Column('domain', sa.String(80), primary_key=True), sa.Column('number', sa.String(120), primary_key=True),
        sa.Column('owner_id', sa.String(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    from backend.db.migrations.retained import require_empty
    names = require_empty(op.get_bind(), ('daily_auth_sessions', 'daily_number_reservations'),
                          'Sitzungswiderrufe und Nummernreservierungen bleiben erhalten.')
    for name in names:
        op.drop_table(name)
