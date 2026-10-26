"""Versioned recipients and bank approval evidence; additive, retained on downgrade."""
import sqlalchemy as sa
from alembic import op

revision = "a3b5d7f9c1e4"
down_revision = "f2a4c6e8b0d3"
branch_labels = None
depends_on = None
NAMES = ('payment_recipient_versions', 'payment_authorizations', 'payment_security_settings', 'payment_totp_uses', 'payment_security_events', 'payment_totp_attempts')


def tables():
    metadata = sa.MetaData()
    sa.Table("invoices", metadata, sa.Column("id", sa.String(), primary_key=True))
    result = []
    result.append(sa.Table('payment_recipient_versions', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('invoice_id', sa.String(), sa.ForeignKey('invoices.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=300), nullable=False),
        sa.Column('iban', sa.String(length=34), nullable=False),
        sa.Column('bic', sa.String(length=11), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_payment_recipient_command'),
        sa.UniqueConstraint('invoice_id', 'number', name='uq_payment_recipient_number'),
    ))
    result.append(sa.Table('payment_authorizations', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('invoice_id', sa.String(), sa.ForeignKey('invoices.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('recipient_id', sa.String(length=36), sa.ForeignKey('payment_recipient_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2, asdecimal=False), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('verification', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_payment_authorization_command'),
    ))
    result.append(sa.Table('payment_security_settings', metadata,
        sa.Column('id', sa.String(length=20), nullable=False, primary_key=True),
        sa.Column('single_user_mode', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('updated_by', sa.String(length=36), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ))
    result.append(sa.Table('payment_totp_uses', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('counter', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'counter', name='uq_payment_totp_counter'),
    ))
    result.append(sa.Table('payment_security_events', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('single_user_mode', sa.Boolean(), nullable=False),
        sa.Column('totp_use_id', sa.String(length=36), sa.ForeignKey('payment_totp_uses.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('revision', name=None),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_payment_mode_command'),
    ))
    result.append(sa.Table('payment_totp_attempts', metadata,
        sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
    ))
    return result

def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial payment security schema; verify private records before upgrading")
    for table in tables():
        if existing:
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            if set(columns) != set(table.c.keys()) or any(
                    columns[c.name]["type"].compile(dialect=connection.dialect).upper() != c.type.compile(dialect=connection.dialect).upper()
                    or bool(columns[c.name]["nullable"]) != bool(c.nullable) for c in table.c):
                raise RuntimeError("Payment security table mismatch: " + table.name)
            indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
            if any(index.name not in indexes or indexes[index.name]["column_names"] != [c.name for c in index.columns]
                   for index in table.indexes):
                raise RuntimeError("Payment security index mismatch: " + table.name)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, NAMES, "Payment authorization history must not be discarded; restore a verified pre-upgrade full backup")
    for name in reversed(NAMES):
        op.drop_table(name)
