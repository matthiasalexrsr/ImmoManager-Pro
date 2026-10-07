"""Immutable document originals: version manifests and their bytes in 64 KiB blocks.

Ported from the earlier archive revision y1a2b3c4d5e6, whose parent chain this
branch does not have; the schema is the same. Databases that create_all()
already created the tables for keep them and only get the guards.

Revision ID: e5f1a7c3b9d2
Revises: d7a2f9c4e681
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f1a7c3b9d2"
down_revision = "d7a2f9c4e681"
branch_labels = None
depends_on = None

TABLES = ("document_versions", "document_version_chunks")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if TABLES[0] not in existing:
        op.create_table(
            TABLES[0],
            sa.Column("id", sa.String(), primary_key=True),
            *[sa.Column(field, sa.String(), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable)
              for field, table, nullable in (
                  ("document_id", "documents", False), ("portfolio_id", "portfolios", False),
                  ("property_id", "properties", False), ("unit_id", "units", True),
                  ("contract_id", "contracts", True), ("tenant_id", "tenants", True),
                  ("predecessor_id", TABLES[0], True), ("restored_from_id", TABLES[0], True))],
            sa.Column("number", sa.BigInteger(), nullable=False),
            sa.Column("actor_id", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(100), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("operation", sa.String(20), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("filename", sa.Text(), nullable=False),
            sa.Column("media_type", sa.String(200), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("metadata_snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("document_id", "number", name="uq_document_version_number"),
            sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_document_version_command"),
            sa.CheckConstraint("number > 0 AND size_bytes >= 0", name="ck_document_version_values"),
            sa.CheckConstraint("operation IN ('archive_original','upload','restore')",
                               name="ck_document_version_operation"),
        )
        op.create_index("ix_document_versions_subject", TABLES[0], ["tenant_id", "document_id", "number"])
        op.create_index("ix_document_versions_portfolio", TABLES[0], ["portfolio_id", "document_id", "number"])
        op.create_index("ix_document_versions_contract", TABLES[0], ["contract_id", "created_at"])
    if TABLES[1] not in existing:
        op.create_table(
            TABLES[1],
            sa.Column("version_id", sa.String(), sa.ForeignKey(f"{TABLES[0]}.id", ondelete="RESTRICT"),
                      primary_key=True),
            sa.Column("position", sa.BigInteger(), primary_key=True),
            sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"),
                      nullable=False),
            sa.Column("data", sa.LargeBinary(), nullable=False),
            sa.CheckConstraint("position >= 0 AND length(data) BETWEEN 1 AND 65536", name="ck_document_chunk_values"),
        )
    install_guards(bind)


# Frozen copy of backend.db.document_version_models.install_guards: a migration
# must not change with the application code.
def install_guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        for table in TABLES:
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS immo_{table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'document originals are immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_document_original_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'document originals are immutable'; END; $$ LANGUAGE plpgsql")
        for table in TABLES:
            trigger = f"immo_{table}_immutable"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION immo_document_original_immutable()")


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if bind.scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Document originals exist; a downgrade would destroy immutable evidence")
    op.drop_table(TABLES[1])
    op.drop_table(TABLES[0])
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("DROP FUNCTION IF EXISTS immo_document_original_immutable()")
