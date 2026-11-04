"""Track the exact document revision independently of the index read clock."""
import sqlalchemy as sa
from alembic import op

revision = "b13c2e4f6a81"
down_revision = "b02a1d3e5f70"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("document_texts")}
    if "source_updated_at" not in columns:
        # A missing marker is intentionally not guessed from indexed_at: that
        # clock may have another timezone or precede an imported future stamp.
        # Old derived rows remain readable and are queued for a safe rebuild.
        op.add_column("document_texts", sa.Column("source_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("document_texts") as batch:
        batch.drop_column("source_updated_at")
