"""Immutable general document versions and chunked original bytes.

Revision ID: y1a2b3c4d5e6
Revises: x1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "y1a2b3c4d5e6"
down_revision = "x1a2b3c4d5e6"
branch_labels = depends_on = None
TABLES = ("document_versions", "document_version_chunks")


def upgrade():
    op.create_table(TABLES[0],
        sa.Column("id", sa.String(), primary_key=True),
        *[sa.Column(field, sa.String(), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable)
          for field, table, nullable in (("document_id", "documents", False), ("portfolio_id", "portfolios", False),
              ("property_id", "properties", False), ("unit_id", "units", True), ("contract_id", "contracts", True),
              ("tenant_id", "tenants", True), ("predecessor_id", TABLES[0], True), ("restored_from_id", TABLES[0], True))],
        sa.Column("number", sa.BigInteger(), nullable=False), sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False), sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False), sa.Column("media_type", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("metadata_snapshot", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "number", name="uq_document_version_number"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_document_version_command"),
        sa.CheckConstraint("number > 0 AND size_bytes >= 0", name="ck_document_version_values"),
        sa.CheckConstraint("operation IN ('archive_original','upload','restore')", name="ck_document_version_operation"))
    op.create_index("ix_document_versions_subject", TABLES[0], ["tenant_id", "document_id", "number"])
    op.create_index("ix_document_versions_portfolio", TABLES[0], ["portfolio_id", "document_id", "number"])
    op.create_table(TABLES[1],
        sa.Column("version_id", sa.String(), sa.ForeignKey("document_versions.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.BigInteger(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("position >= 0 AND length(data) BETWEEN 1 AND 65536", name="ck_document_chunk_values"))
    install_guards(op.get_bind())


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for table in TABLES:
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_{operation.lower()} "
                    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'document originals are immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_document_original_immutable() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'document originals are immutable'; END; $$ LANGUAGE plpgsql""")
        for table in TABLES:
            trigger = f"immo_{table}_immutable"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION immo_document_original_immutable()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Document originals exist; downgrade would destroy immutable evidence")
    for table in reversed(TABLES):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.get_bind().exec_driver_sql("DROP FUNCTION IF EXISTS immo_document_original_immutable()")
