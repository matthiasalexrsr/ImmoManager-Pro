"""Document retention: the class that decides how long a document must be kept.

New nullable column ``documents.retention_class`` (empty = decided by the document
type). Guarded like d8a1c3e5f7b9, so create_all databases that already have the
column pass. A downgrade is refused while any document has an explicit class; SQLite
drops the column in place.

Revision ID: f4c6e8a0b2d3
Revises: e2b4d6f8a0c1
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "f4c6e8a0b2d3"
down_revision: str | None = "e2b4d6f8a0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("documents"):
        return
    if "retention_class" not in {column["name"] for column in inspector.get_columns("documents")}:
        op.add_column("documents", sa.Column("retention_class", sa.String(20), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("documents"):
        return
    if "retention_class" not in {column["name"] for column in inspector.get_columns("documents")}:
        return
    if bind.execute(sa.text("SELECT 1 FROM documents WHERE retention_class IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the retention class chosen for documents; keep this "
                           "version or reset those documents to the automatic class first.")
    # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
    if bind.dialect.name == "sqlite":
        op.execute("ALTER TABLE documents DROP COLUMN retention_class")
    else:
        op.drop_column("documents", "retention_class")
