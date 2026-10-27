"""Private connections, immutable secret versions, mappings and durable action receipts.

Revision ID: d73f2b9a041c
Revises: c61e9a2f034b
"""

import sqlalchemy as sa
from alembic import op

revision = "d73f2b9a041c"
down_revision = "c61e9a2f034b"
branch_labels = None
depends_on = None


def _table(name, *columns):
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(name):
        required = {column.name for column in columns if isinstance(column, sa.Column)}
        if not required.issubset({column["name"] for column in inspector.get_columns(name)}):
            raise RuntimeError("Existing integration table does not match the declared migration")
        return
    op.create_table(name, *columns)


def _index(name, table, columns, **options):
    existing = {value["name"]: value for value in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in existing:
        if existing[name]["column_names"] != columns or bool(existing[name]["unique"]) != bool(options.get("unique")):
            raise RuntimeError("Existing integration index has an incompatible definition")
    else:
        op.create_index(name, table, columns, **options)


def upgrade():
    # These are frozen declarations, independent of future runtime ORM versions.
    _table("integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config_token", sa.Text(), nullable=False),
        sa.Column("secret_refs", sa.JSON(), nullable=False),
        sa.Column("legacy_source_hash", sa.String(64)),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    _index("ix_integration_connections_page", "integration_connections", ["created_at", "id"])
    _index("uq_integration_default_provider", "integration_connections", ["provider_id"], unique=True,
           sqlite_where=sa.text("is_default = 1"), postgresql_where=sa.text("is_default = true"))
    _table("integration_connection_secrets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(120), nullable=False),
        sa.Column("value_token", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("connection_id", "field_name", "revision", name="uq_integration_connection_secret"))
    _table("integration_connection_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_kind", sa.String(100), nullable=False),
        sa.Column("external_key_hash", sa.String(64), nullable=False),
        sa.Column("external_key_token", sa.Text(), nullable=False),
        sa.Column("target_kind", sa.String(60)),
        sa.Column("target_id", sa.String(120)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("observed_token", sa.Text(), nullable=False),
        sa.Column("manifest_token", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("confirmed_by", sa.String(36)),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("connection_id", "source_kind", "external_key_hash", name="uq_integration_external_mapping"))
    _index("ix_integration_mapping_page", "integration_connection_mappings", ["connection_id", "created_at", "id"])
    _table("integration_action_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("command_key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(60)),
        sa.Column("source_id", sa.String(120)),
        sa.Column("source_revision", sa.String(200)),
        sa.Column("config_snapshot_token", sa.Text(), nullable=False),
        sa.Column("action_manifest_token", sa.Text(), nullable=False),
        sa.Column("request_token", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("checkpoint_token", sa.Text()),
        sa.Column("result_token", sa.Text()),
        sa.Column("result_sha256", sa.String(64)),
        sa.Column("result_bytes", sa.Integer()),
        sa.Column("result_blocks", sa.Integer()),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("safe_summary", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "command_key", name="uq_integration_actor_command"))
    _index("ix_integration_run_page", "integration_action_runs", ["connection_id", "created_at", "id"])
    _index("ix_integration_run_state", "integration_action_runs", ["state", "lease_until", "id"])
    _table("integration_source_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "category", "sequence", name="uq_integration_source_block"))
    _index("ix_integration_source_hash", "integration_source_blocks", ["run_id", "category", "sha256"])
    _table("integration_connection_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("integration_action_runs.id", ondelete="RESTRICT")),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("detail_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    _index("ix_integration_event_page", "integration_connection_events", ["connection_id", "created_at", "id"])


def downgrade():
    for name in ("integration_connection_events", "integration_source_blocks", "integration_action_runs",
                 "integration_connection_mappings", "integration_connection_secrets", "integration_connections"):
        op.drop_table(name)
