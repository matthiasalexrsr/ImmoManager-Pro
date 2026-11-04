"""Resumable text indexing; old bounded samples are rebuilt, never called complete."""
import sqlalchemy as sa
from alembic import op

revision = "b02a1d3e5f70"
down_revision = "a9c1e3f5b7d2"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("document_texts")}
    additions = [sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
                 sa.Column("cursor", sa.JSON(), nullable=False, server_default="{}"),
                 sa.Column("source_sha256", sa.String(64)),
                 sa.Column("indexed_units", sa.Integer(), nullable=False, server_default="0"),
                 sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
                 sa.Column("warning", sa.Text())]
    for column in additions:
        if column.name not in columns:
            op.add_column("document_texts", column)


def downgrade():
    # Derived data can always be rebuilt from the retained original bytes.
    with op.batch_alter_table("document_texts") as batch:
        for name in ["warning", "total_units", "indexed_units", "source_sha256", "cursor", "complete"]:
            batch.drop_column(name)
