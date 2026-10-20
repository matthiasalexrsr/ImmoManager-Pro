"""Document expiry: the day a document stops being valid and how early to be reminded.

New nullable columns ``documents.valid_until`` (with an index for the daily reminder
job) and ``documents.reminder_days``. Guarded like c6e8a0b2d4f3, so create_all databases
that already have the columns pass. A downgrade is refused while any document has an
expiry date or a reminder lead time; SQLite drops the columns in place.

Revision ID: d8a1c3e5f7b9
Revises: c6e8a0b2d4f3
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "d8a1c3e5f7b9"
down_revision: str | None = "c6e8a0b2d4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "idx_documents_valid_until"
COLUMNS = ("valid_until", "reminder_days")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("documents"):
        return
    existing = {column["name"] for column in inspector.get_columns("documents")}
    if "valid_until" not in existing:
        op.add_column("documents", sa.Column("valid_until", sa.Date(), nullable=True))
    if "reminder_days" not in existing:
        op.add_column("documents", sa.Column("reminder_days", sa.Integer(), nullable=True))
    if INDEX not in {index["name"] for index in inspector.get_indexes("documents")}:
        op.create_index(INDEX, "documents", ["valid_until"])


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("documents"):
        return
    present = [name for name in COLUMNS if name in {column["name"] for column in inspector.get_columns("documents")}]
    if present and bind.execute(sa.text("SELECT 1 FROM documents WHERE "
                                        + " OR ".join(f"{name} IS NOT NULL" for name in present) + " LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard document expiry dates or reminder lead times; keep this "
                           "version or clear those fields first.")
    if INDEX in {index["name"] for index in inspector.get_indexes("documents")}:
        op.drop_index(INDEX, table_name="documents")
    for name in present:
        # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
        if bind.dialect.name == "sqlite":
            op.execute(f"ALTER TABLE documents DROP COLUMN {name}")
        else:
            op.drop_column("documents", name)
