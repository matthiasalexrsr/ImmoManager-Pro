"""Document texts for the full-text search.

New table ``document_texts`` (one row per document, deleted with it): the text the
indexing job read from the document's file or archived original. It is derived data
that the job can always rebuild, so a downgrade simply drops it. Guarded like the
previous revisions: a create_all database that already has the table passes.

Revision ID: e2b4d6f8a0c1
Revises: d8a1c3e5f7b9
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "e2b4d6f8a0c1"
down_revision: str | None = "d8a1c3e5f7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("document_texts"):
        return
    op.create_table(
        "document_texts",
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("characters", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    guard_branch_downgrade()
    if sa.inspect(op.get_bind()).has_table("document_texts"):
        op.drop_table("document_texts")      # derived: the indexing job rebuilds it after an upgrade
