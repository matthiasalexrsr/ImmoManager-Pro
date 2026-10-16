"""Encrypted bank originals and atomic import source links.

Revision ID: e160a1b2c301
Revises: d73f2b9a041c
"""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c301"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _table(name, *columns):
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(name):
        actual = {column['name']: column for column in inspector.get_columns(name)}
        expected = {column.name: column for column in columns if isinstance(column, sa.Column)}
        if set(actual) != set(expected) or any(actual[key]['nullable'] != value.nullable for key, value in expected.items()):
            raise RuntimeError('Existing bank table does not match this migration')
        if any(actual[key]['type']._type_affinity != value.type._type_affinity for key, value in expected.items()):
            raise RuntimeError('Existing bank column types do not match this migration')
        unique = {tuple(item['column_names']) for item in inspector.get_unique_constraints(name)}
        if name == 'bank_imports' and ('account_id', 'source_sha256', 'mapping_sha256') not in unique:
            raise RuntimeError('Existing bank uniqueness does not match this migration')
        if inspector.get_pk_constraint(name)['constrained_columns'] != ['id']:
            raise RuntimeError('Existing bank primary key does not match this migration')
        foreign = {(item['constrained_columns'][0], item['referred_table'], item['referred_columns'][0])
                   for item in inspector.get_foreign_keys(name)}
        for column in expected.values():
            for key in column.foreign_keys:
                table, target = key.target_fullname.rsplit('.', 1)
                if (column.name, table, target) not in foreign:
                    raise RuntimeError('Existing bank foreign key does not match this migration')
        return
    op.create_table(name, *columns)


def upgrade():
    _table("bank_fints_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("private_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    _table("bank_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("mapping_sha256", sa.String(64), nullable=False),
        sa.Column("original_token", sa.Text(), nullable=False),
        sa.Column("manifest_token", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "source_sha256", "mapping_sha256", name="uq_bank_source_mapping"))
    _table("bank_source_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("import_id", sa.String(36), sa.ForeignKey("bank_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("account_id", sa.String(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("booking_id", sa.String(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("semantic_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    indexes = {item['name']: item for item in sa.inspect(op.get_bind()).get_indexes('bank_source_links')}
    existing = indexes.get('ix_bank_source_links_semantic_sha256')
    if existing and (existing['column_names'] != ['semantic_sha256'] or existing['unique']):
        raise RuntimeError('Existing bank index does not match this migration')
    if not existing:
        op.create_index('ix_bank_source_links_semantic_sha256', 'bank_source_links', ['semantic_sha256'])
    history = {item['name']: item for item in sa.inspect(op.get_bind()).get_indexes('bank_imports')}.get('ix_bank_imports_history')
    if history and (history['column_names'] != ['account_id', 'created_at', 'id'] or history['unique']):
        raise RuntimeError('Existing bank history index does not match this migration')
    if not history:
        op.create_index('ix_bank_imports_history', 'bank_imports', ['account_id', 'created_at', 'id'])
    from backend.db.bank_guards import install_bank_guards
    install_bank_guards(op.get_bind())


def downgrade():
    raise RuntimeError("Bankoriginale und Quellverknüpfungen dürfen nicht durch Downgrade gelöscht werden")
