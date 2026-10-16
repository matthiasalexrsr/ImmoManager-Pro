"""Add durable communication, retaining all existing messages and manual dunning entries."""
from typing import cast

import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c304"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _verify_adopted_schema(connection):
    """Accept a pre-existing ORM-created family only if every constraint matches.

    Desktop databases sometimes have all current tables but no Alembic
    version. Do not issue duplicate CREATE TABLE, and do not silently stamp
    a partial or less constrained schema as current.
    """
    from backend.db.communication_models import MODELS

    inspector = sa.inspect(connection)
    for model in MODELS:
        table = cast(sa.Table, model.__table__)
        name = table.name
        found = {column["name"]: column for column in inspector.get_columns(name)}
        expected = set(table.columns.keys())
        if set(found) != expected:
            raise RuntimeError(f"Unsafe communication schema adoption: {name} columns differ")
        for column in table.columns:
            actual = found[column.name]
            if bool(actual["primary_key"]) != bool(column.primary_key):
                raise RuntimeError(f"Unsafe communication schema adoption: {name} primary key differs")
            if not column.primary_key and bool(actual["nullable"]) != bool(column.nullable):
                raise RuntimeError(f"Unsafe communication schema adoption: {name} nullability differs")
            actual_type = actual["type"].compile(dialect=connection.dialect).upper()
            mapped_type = column.type.compile(dialect=connection.dialect).upper()
            if actual_type != mapped_type:
                raise RuntimeError(f"Unsafe communication schema adoption: {name} SQL type differs")
        declared_indexes = {index.name: (tuple(col.name for col in index.columns), index.unique)
                            for index in table.indexes}
        stored_indexes = {index["name"]: (tuple(index["column_names"]), index["unique"])
                          for index in inspector.get_indexes(name)}
        if declared_indexes != stored_indexes:
            raise RuntimeError(f"Unsafe communication schema adoption: {name} indexes differ")
        declared_uniques = {tuple(col.name for col in constraint.columns)
                            for constraint in table.constraints if isinstance(constraint, sa.UniqueConstraint)}
        stored_uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
        if declared_uniques != stored_uniques:
            raise RuntimeError(f"Unsafe communication schema adoption: {name} uniqueness differs")
        declared_fks = {(tuple(col.name for col in fk.columns),
                         next(iter(fk.elements)).column.table.name,
                         tuple(element.column.name for element in fk.elements),
                         (next(iter(fk.elements)).ondelete or "").upper())
                        for fk in table.constraints if isinstance(fk, sa.ForeignKeyConstraint)}
        stored_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"],
                       tuple(fk["referred_columns"]), (fk.get("options", {}).get("ondelete") or "").upper())
                      for fk in inspector.get_foreign_keys(name)}
        if declared_fks != stored_fks:
            raise RuntimeError(f"Unsafe communication schema adoption: {name} references differ")


def upgrade():
    from backend.db.communication_models import MODELS, install_guards

    connection = op.get_bind()
    present = {model.__tablename__ for model in MODELS} & set(sa.inspect(connection).get_table_names())
    if present:
        if present != {model.__tablename__ for model in MODELS}:
            raise RuntimeError("Unsafe partial communication schema; restore a full backup before upgrade")
        _verify_adopted_schema(connection)
        install_guards(connection)
        return
    op.create_table("communication_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("thread_id", sa.String(), sa.ForeignKey('message_threads.id', ondelete='RESTRICT')),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey('integration_connections.id', ondelete='RESTRICT')),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_token", sa.Text(), nullable=False), sa.Column("message_id", sa.String(255)),
        sa.Column("dedupe_key", sa.String(64), unique=True), sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_communication_page", "communication_items", ["kind", "thread_id", "created_at", "id"])
    op.create_index("ix_communication_work", "communication_items", ["state", "lease_until", "id"])
    op.create_index("ix_communication_message_id", "communication_items", ["message_id"])
    op.create_table("communication_evidence", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("communication_blocks", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey('communication_evidence.id', ondelete='RESTRICT'), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("evidence_id", "sequence", name="uq_communication_block"))
    op.create_table('communication_attachments', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version_id', sa.String(120), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_communication_attachment_document', 'communication_attachments', ['document_id', 'item_id'])
    from backend.db.communication_models import install_guards
    install_guards(op.get_bind())


def downgrade():
    raise RuntimeError("Communication originals must be retained; restore a complete pre-upgrade backup instead.")
