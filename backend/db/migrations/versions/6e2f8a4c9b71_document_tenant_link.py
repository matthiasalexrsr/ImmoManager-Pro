"""Allow documents to belong directly to a tenant, before a contract exists.

Revision ID: 6e2f8a4c9b71
Revises: a1d6c3f8e2b4
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6e2f8a4c9b71"
down_revision: str | None = "a1d6c3f8e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tenant_id" not in {column["name"] for column in inspector.get_columns("documents")}:
        if op.get_bind().dialect.name == "sqlite":
            # SQLite accepts a nullable REFERENCES column directly. Avoid
            # rebuilding documents, which other tables already reference.
            op.execute("ALTER TABLE documents ADD COLUMN tenant_id VARCHAR REFERENCES tenants(id) ON DELETE SET NULL")
        else:
            op.add_column("documents", sa.Column(
                "tenant_id", sa.String(), sa.ForeignKey("tenants.id", name="fk_documents_tenant", ondelete="SET NULL"),
                nullable=True,
            ))
    if "idx_documents_tenant" not in {index["name"] for index in inspector.get_indexes("documents")}:
        op.create_index("idx_documents_tenant", "documents", ["tenant_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("documents")}
    if "tenant_id" in existing:
        documents = sa.table("documents", sa.column("tenant_id"))
        assigned = op.get_bind().execute(sa.select(sa.func.count()).select_from(documents).where(
            documents.c.tenant_id.isnot(None),
        )).scalar_one()
        if assigned:
            raise RuntimeError("Cannot remove document tenant links while tenant-linked documents exist")
    if "idx_documents_tenant" in {index["name"] for index in inspector.get_indexes("documents")}:
        op.drop_index("idx_documents_tenant", table_name="documents")
    if "tenant_id" in existing:
        # Direct DROP COLUMN preserves documents and incoming invoice links.
        op.drop_column("documents", "tenant_id")
