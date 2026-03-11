"""Add contacts, meters, standalone_meter_readings, message_threads,
messages, and rent_charges tables.

Revision ID: c5d8f3b2a1e0
Revises: b4c7e2a1f9d0
Create Date: 2026-03-11 14:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5d8f3b2a1e0'
down_revision: Union[str, Sequence[str], None] = 'b4c7e2a1f9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tables for contacts, meters, standalone meter readings,
    message threads, messages, and rent charges."""

    op.create_table('contacts',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('contact_type', sa.String(30), nullable=False, server_default='tenant'),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('company_name', sa.String(200), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('mobile', sa.String(50), nullable=True),
        sa.Column('street', sa.String(200), nullable=True),
        sa.Column('zip_code', sa.String(20), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('country', sa.String(5), nullable=False, server_default='DE'),
        sa.Column('iban', sa.String(34), nullable=True),
        sa.Column('bic', sa.String(11), nullable=True),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('tax_id', sa.String(50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('meters',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('unit_id', sa.String(36), nullable=False),
        sa.Column('meter_type', sa.String(30), nullable=False),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('installation_date', sa.Date(), nullable=True),
        sa.Column('next_inspection', sa.Date(), nullable=True),
        sa.Column('supplier', sa.String(200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
    )

    op.create_table('standalone_meter_readings',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('meter_id', sa.String(36), nullable=False),
        sa.Column('reading_date', sa.Date(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('recorded_by', sa.String(100), nullable=True),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['meter_id'], ['meters.id'], ondelete='CASCADE'),
    )

    op.create_table('message_threads',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('subject', sa.String(300), nullable=False),
        sa.Column('participant_ids', sa.Text(), nullable=True),
        sa.Column('property_id', sa.String(36), nullable=True),
        sa.Column('unit_id', sa.String(36), nullable=True),
        sa.Column('contract_id', sa.String(36), nullable=True),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('messages',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('thread_id', sa.String(36), nullable=False),
        sa.Column('sender_name', sa.String(200), nullable=False, server_default='System'),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('attachment_ids', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ondelete='CASCADE'),
    )

    op.create_table('rent_charges',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('contract_id', sa.String(36), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('cold_rent', sa.Float(), nullable=False, server_default='0'),
        sa.Column('service_charge', sa.Float(), nullable=False, server_default='0'),
        sa.Column('heating_charge', sa.Float(), nullable=False, server_default='0'),
        sa.Column('other_charges', sa.Float(), nullable=False, server_default='0'),
        sa.Column('amount_paid', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
    )
    op.create_index('idx_rent_charges_contract_month', 'rent_charges', ['contract_id', 'month'])


def downgrade() -> None:
    op.drop_index('idx_rent_charges_contract_month', table_name='rent_charges')
    op.drop_table('rent_charges')
    op.drop_table('messages')
    op.drop_table('message_threads')
    op.drop_table('standalone_meter_readings')
    op.drop_table('meters')
    op.drop_table('contacts')
