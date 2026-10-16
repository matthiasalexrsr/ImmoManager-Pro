"""Persistent session inventory and never-recycled contract number reservations."""
import sqlalchemy as sa
from alembic import op

revision = 'e180a1b2c307'
down_revision = 'e170a1b2c306'
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.daily_models import DailySessionORM, NumberReservationORM
    from backend.db.migrations.adopt_existing import adopt_exact_family

    if adopt_exact_family(op.get_bind(), (DailySessionORM, NumberReservationORM)):
        return
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
    raise RuntimeError('Sitzungswiderrufe und Nummernreservierungen bleiben erhalten.')
