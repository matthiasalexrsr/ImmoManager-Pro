"""Add durable communication, retaining all existing messages and manual dunning entries."""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c304"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _schema():
    """Frozen declarations; never infer an old migration from evolving ORM models."""
    metadata = sa.MetaData()
    # FK signatures only. These predecessor tables are never created here.
    for name in ("message_threads", "integration_connections", "documents"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    items = sa.Table("communication_items", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("thread_id", sa.String(), sa.ForeignKey('message_threads.id', ondelete='RESTRICT')),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey('integration_connections.id', ondelete='RESTRICT')),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_token", sa.Text(), nullable=False), sa.Column("message_id", sa.String(255)),
        sa.Column("dedupe_key", sa.String(64), unique=True), sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    sa.Index("ix_communication_page", items.c.kind, items.c.thread_id, items.c.created_at, items.c.id)
    sa.Index("ix_communication_work", items.c.state, items.c.lease_until, items.c.id)
    sa.Index("ix_communication_message_id", items.c.message_id)
    evidence = sa.Table("communication_evidence", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    blocks = sa.Table("communication_blocks", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey('communication_evidence.id', ondelete='RESTRICT'), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("evidence_id", "sequence", name="uq_communication_block"))
    attachments = sa.Table('communication_attachments', metadata, sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), sa.ForeignKey('communication_items.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version_id', sa.String(120), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    sa.Index('ix_communication_attachment_document', attachments.c.document_id, attachments.c.item_id)
    return items, evidence, blocks, attachments


def _incompatible(table, detail):
    # Diagnostic identifies schema objects, never private row values/tokens.
    raise RuntimeError(f"Existing communication schema is incompatible: {table}: {detail}. Verify the original database before upgrading.")


def _foreign_signature(columns, parent, remote, schema, options):
    def default_action(value):
        return (value or "NO ACTION").upper()
    return (tuple(columns), schema, parent, tuple(remote), (options.get("ondelete") or "").upper(),
            default_action(options.get("onupdate")), bool(options.get("deferrable")),
            (options.get("initially") or "IMMEDIATE").upper(), (options.get("match") or "SIMPLE").upper())


def _verify_table(connection, inspector, table):
    name = table.name
    actual = {column["name"]: column for column in inspector.get_columns(name)}
    if set(actual) != set(table.c.keys()):
        _incompatible(name, "column set")
    for column in table.c:
        value = actual[column.name]
        expected_type = str(column.type.compile(dialect=connection.dialect)).upper()
        actual_type = str(value["type"].compile(dialect=connection.dialect)).upper()
        accepted_types = {expected_type}
        # Two released FK declarations differ between ORM and migration:
        # thread_id is VARCHAR here / VARCHAR(36) in the ORM; document_id is
        # VARCHAR(36) here / unbounded VARCHAR in the ORM. Freeze BOTH known
        # signatures, without guessing compatibility for any other length/type.
        if (name, column.name) in {("communication_items", "thread_id"), ("communication_attachments", "document_id")}:
            accepted_types.update(str(kind.compile(dialect=connection.dialect)).upper() for kind in (sa.String(), sa.String(36)))
        if actual_type not in accepted_types or bool(value["nullable"]) != bool(column.nullable):
            _incompatible(name, f"column type/nullability {column.name}")
        if value.get("default") is not None or value.get("computed") or value.get("identity"):
            _incompatible(name, f"unexpected generated/default value {column.name}")
    if inspector.get_pk_constraint(name)["constrained_columns"] != [column.name for column in table.primary_key]:
        _incompatible(name, "primary key")
    unique = {tuple(value["column_names"]) for value in inspector.get_unique_constraints(name)}
    expected_unique = {tuple(column.name for column in constraint.columns) for constraint in table.constraints
                       if isinstance(constraint, sa.UniqueConstraint)}
    if unique != expected_unique:
        _incompatible(name, "unique constraints")
    if inspector.get_check_constraints(name):
        _incompatible(name, "unexpected check constraints")
    default_schema = inspector.default_schema_name
    foreign = {_foreign_signature(value["constrained_columns"], value["referred_table"], value["referred_columns"],
                                  value.get("referred_schema") or default_schema, value.get("options", {}))
               for value in inspector.get_foreign_keys(name)}
    expected_foreign = set()
    for constraint in table.foreign_key_constraints:
        target = constraint.referred_table
        expected_foreign.add(_foreign_signature([element.parent.name for element in constraint.elements], target.name,
            [element.column.name for element in constraint.elements], target.schema or default_schema,
            {"ondelete": constraint.ondelete, "onupdate": constraint.onupdate, "deferrable": constraint.deferrable,
             "initially": constraint.initially, "match": constraint.match}))
    if foreign != expected_foreign:
        _incompatible(name, "foreign keys/actions")
    # PostgreSQL reflects constraint-owned unique indexes as well. They were
    # checked above as constraints; only explicit indexes belong in this set.
    indexes = {value["name"]: value for value in inspector.get_indexes(name) if not value.get("duplicates_constraint")}
    if connection.dialect.name == "sqlite":
        quoted = connection.dialect.identifier_preparer.quote(name)
        explicit = {row[1] for row in connection.exec_driver_sql(f"PRAGMA index_list({quoted})") if row[3] == "c"}
        if explicit != indexes.keys():
            _incompatible(name, "unreflectable index definitions")
    expected_indexes = {value.name: value for value in table.indexes}
    if indexes.keys() != expected_indexes.keys():
        _incompatible(name, "index set")
    for index_name, expected in expected_indexes.items():
        value = indexes[index_name]
        if value["column_names"] != [column.name for column in expected.columns] or bool(value["unique"]) != bool(expected.unique):
            _incompatible(name, f"index columns/uniqueness {index_name}")
        if value.get("column_sorting"):
            _incompatible(name, f"index ordering {index_name}")
        for key, option in value.get("dialect_options", {}).items():
            if key == "postgresql_using" and option == "btree":
                continue
            if option is not None and option is not False and not (isinstance(option, (list, dict)) and not option):
                _incompatible(name, f"index options {index_name}")


def upgrade():
    connection = op.get_bind()
    tables = _schema()
    names = {table.name for table in tables}
    inspector = sa.inspect(connection)
    present = names & set(inspector.get_table_names())
    if names & set(inspector.get_view_names()):
        _incompatible("family", "a required table name is a view")
    if present and present != names:
        _incompatible("family", "partial table family")
    if present:
        # Validate ALL four tables before touching even a guard or index. An
        # altered/partial create_all database is never silently stamped/repaired.
        for table in tables:
            _verify_table(connection, inspector, table)
    else:
        for table in tables:
            table.create(connection)
    from backend.db.communication_models import install_guards
    if connection.dialect.name == "sqlite":
        # install_guards uses IF NOT EXISTS on SQLite. Reinstall its known
        # guards, including same-named ineffective legacy definitions.
        for table in tables[1:]:
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table.name}_{operation}_guard")
    install_guards(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    names = require_empty(connection, ('communication_attachments', 'communication_blocks', 'communication_evidence', 'communication_items'),
                          'Communication originals must be retained; restore a complete pre-upgrade backup instead.')
    for name in names:
        op.drop_table(name)
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('DROP FUNCTION IF EXISTS communication_evidence_guard()')
