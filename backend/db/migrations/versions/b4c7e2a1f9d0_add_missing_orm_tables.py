"""Add missing ORM tables: tax_rates, rent_adjustments, handover_protocols,
meter_readings, budgets, escalation_rules, change_history, user_preferences,
insurances, entity_photos

Revision ID: b4c7e2a1f9d0
Revises: 238d3405d3e8
Create Date: 2026-03-10 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4c7e2a1f9d0'
down_revision: Union[str, Sequence[str], None] = '238d3405d3e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tables for ORM models that were missing from the initial migration."""

    op.create_table('tax_rates',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('rate', sa.Float(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('rent_adjustments',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('contract_id', sa.String(36), nullable=False),
        sa.Column('adjustment_type', sa.String(20), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('previous_rent', sa.Float(), nullable=False),
        sa.Column('new_rent', sa.Float(), nullable=False),
        sa.Column('increase_percent', sa.Float(), nullable=True),
        sa.Column('index_base_year', sa.Integer(), nullable=True),
        sa.Column('index_value', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('handover_protocols',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('contract_id', sa.String(36), nullable=False),
        sa.Column('unit_id', sa.String(36), nullable=False),
        sa.Column('protocol_type', sa.String(20), nullable=False),
        sa.Column('protocol_date', sa.Date(), nullable=False),
        sa.Column('tenant_present', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('landlord_present', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('key_count', sa.Integer(), nullable=True),
        sa.Column('key_details', sa.Text(), nullable=True),
        sa.Column('overall_condition', sa.String(20), nullable=True),
        sa.Column('damages', sa.Text(), nullable=True),
        sa.Column('photos', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('tenant_signature', sa.Text(), nullable=True),
        sa.Column('landlord_signature', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('meter_readings',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('handover_id', sa.String(36), nullable=False),
        sa.Column('meter_type', sa.String(30), nullable=False),
        sa.Column('meter_number', sa.String(50), nullable=True),
        sa.Column('reading_value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(10), nullable=False, server_default='kWh'),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['handover_id'], ['handover_protocols.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('budgets',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('property_id', sa.String(36), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('planned_amount', sa.Float(), nullable=False),
        sa.Column('actual_amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('escalation_rules',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('entity_type', sa.String(30), nullable=False),
        sa.Column('condition_field', sa.String(50), nullable=False),
        sa.Column('days_overdue', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('target_role', sa.String(50), nullable=True),
        sa.Column('notification_severity', sa.String(20), nullable=False, server_default='warning'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('change_history',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(36), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('changed_by', sa.String(36), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_change_history_entity', 'change_history', ['entity_type', 'entity_id'])

    op.create_table('user_preferences',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('theme', sa.Text(), nullable=False, server_default='light'),
        sa.Column('locale', sa.Text(), nullable=False, server_default='de-DE'),
        sa.Column('sidebar_collapsed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('items_per_page', sa.Integer(), nullable=False, server_default='25'),
        sa.Column('date_format', sa.Text(), nullable=False, server_default='DD.MM.YYYY'),
        sa.Column('currency', sa.Text(), nullable=False, server_default='EUR'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('idx_user_preferences_user', 'user_preferences', ['user_id'])

    op.create_table('insurances',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('property_id', sa.String(), nullable=False),
        sa.Column('unit_id', sa.String(), nullable=True),
        sa.Column('insurance_type', sa.Text(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('policy_number', sa.Text(), nullable=True),
        sa.Column('coverage_amount', sa.Float(), nullable=True),
        sa.Column('premium_amount', sa.Float(), nullable=True),
        sa.Column('premium_interval', sa.Text(), nullable=False, server_default='annual'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('contact_person', sa.Text(), nullable=True),
        sa.Column('contact_phone', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_insurance_property', 'insurances', ['property_id'])

    op.create_table('entity_photos',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('file_url', sa.Text(), nullable=False),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_entity_photos_entity', 'entity_photos', ['entity_type', 'entity_id'])


def downgrade() -> None:
    """Drop all tables created in this migration."""
    op.drop_index('idx_entity_photos_entity', table_name='entity_photos')
    op.drop_table('entity_photos')
    op.drop_index('idx_insurance_property', table_name='insurances')
    op.drop_table('insurances')
    op.drop_index('idx_user_preferences_user', table_name='user_preferences')
    op.drop_table('user_preferences')
    op.drop_index('idx_change_history_entity', table_name='change_history')
    op.drop_table('change_history')
    op.drop_table('escalation_rules')
    op.drop_table('budgets')
    op.drop_table('meter_readings')
    op.drop_table('handover_protocols')
    op.drop_table('rent_adjustments')
    op.drop_table('tax_rates')
