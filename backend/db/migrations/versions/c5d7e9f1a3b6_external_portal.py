"""Invited external portals; additive schema with retained evidence."""
import sqlalchemy as sa
from alembic import op

revision = "c5d7e9f1a3b6"
down_revision = "b4c6d8e0f2a5"
branch_labels = None
depends_on = None
NAMES = ('external_portal_identities', 'external_portal_grants', 'external_portal_invitations', 'external_portal_sessions', 'external_portal_publications', 'external_portal_cases', 'external_portal_messages', 'external_portal_attachments', 'external_portal_commands', 'external_portal_events', 'external_portal_attempts')


def tables():
    metadata = sa.MetaData()
    sa.Table('contacts', metadata, sa.Column("id", sa.String(length=36), primary_key=True))
    sa.Table('contracts', metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table('document_versions', metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table('maintenance_cases', metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table('ownership_shares', metadata, sa.Column("id", sa.String(length=36), primary_key=True))
    sa.Table('portfolios', metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table('tenants', metadata, sa.Column("id", sa.String(), primary_key=True))
    result = []
    result.append(sa.Table('external_portal_identities', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('password_hash', sa.String(length=300), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('email', name=None),
    ))
    result.append(sa.Table('external_portal_grants', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('identity_id', sa.String(length=36), sa.ForeignKey('external_portal_identities.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('portfolio_id', sa.String(), sa.ForeignKey('portfolios.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('tenant_id', sa.String(), sa.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('contact_id', sa.String(length=36), sa.ForeignKey('contacts.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('contract_id', sa.String(), sa.ForeignKey('contracts.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('ownership_id', sa.String(length=36), sa.ForeignKey('ownership_shares.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('binding', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('verified_by', sa.String(length=36), nullable=False),
        sa.Column('verification', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("(kind = 'tenant' AND tenant_id IS NOT NULL AND contract_id IS NOT NULL AND contact_id IS NULL AND ownership_id IS NULL) OR (kind = 'owner' AND contact_id IS NOT NULL AND ownership_id IS NOT NULL AND tenant_id IS NULL AND contract_id IS NULL)", name='ck_portal_party_relation'),
    ))
    result.append(sa.Table('external_portal_invitations', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('grant_id', sa.String(length=36), sa.ForeignKey('external_portal_grants.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('token_sha256', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('consumed_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('token_sha256', name=None),
    ))
    result.append(sa.Table('external_portal_sessions', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('identity_id', sa.String(length=36), sa.ForeignKey('external_portal_identities.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('token_sha256', sa.String(length=64), nullable=False),
        sa.Column('identity_revision', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('token_sha256', name=None),
    ))
    result.append(sa.Table('external_portal_publications', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('grant_id', sa.String(length=36), sa.ForeignKey('external_portal_grants.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('version_id', sa.String(), sa.ForeignKey('document_versions.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('published_by', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('grant_id', 'version_id', name='uq_portal_published_version'),
    ))
    result.append(sa.Table('external_portal_cases', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('grant_id', sa.String(length=36), sa.ForeignKey('external_portal_grants.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('case_id', sa.String(), sa.ForeignKey('maintenance_cases.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('grant_id', 'case_id', name='uq_portal_case_grant'),
    ))
    result.append(sa.Table('external_portal_messages', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('case_link_id', sa.String(length=36), sa.ForeignKey('external_portal_cases.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('sender_kind', sa.String(length=12), nullable=False),
        sa.Column('sender_id', sa.String(length=50), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    ))
    result.append(sa.Table('external_portal_attachments', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('message_id', sa.String(length=36), sa.ForeignKey('external_portal_messages.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('filename', sa.String(length=200), nullable=False),
        sa.Column('media_type', sa.String(length=60), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    ))
    result.append(sa.Table('external_portal_commands', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('actor_id', sa.String(length=50), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('operation', sa.String(length=200), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('actor_id', 'idempotency_key', name='uq_portal_command'),
    ))
    result.append(sa.Table('external_portal_events', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('grant_id', sa.String(length=36), sa.ForeignKey('external_portal_grants.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('actor_id', sa.String(length=50), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    ))
    result.append(sa.Table('external_portal_attempts', metadata,
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('times', sa.JSON(), nullable=False),
    ))
    return result

def upgrade():
    from backend.db.migrations.additive_validation import verify_table
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial external portal schema; verify retained sources before upgrading")
    for table in tables():
        if existing:
            verify_table(connection, table)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, NAMES, "Portal evidence must not be discarded; restore a verified pre-upgrade full backup")
    for name in reversed(NAMES):
        op.drop_table(name)
