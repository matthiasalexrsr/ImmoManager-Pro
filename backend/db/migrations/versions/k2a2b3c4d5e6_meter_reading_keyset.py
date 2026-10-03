"""Index bounded current meter readings without rewriting measurement originals."""

from alembic import op
import sqlalchemy as sa

revision = "k2a2b3c4d5e6"
down_revision = "j2a2b3c4d5e6"
branch_labels = depends_on = None

INDEX_NAME = "ix_meter_readings_latest"


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("Meter reading keyset supports SQLite and PostgreSQL")
    collation = '"BINARY"' if dialect == "sqlite" else '"C"'
    # Alembic owns this index. Do not attach an Index to global Python metadata:
    # repeated upgrade/create_all composition must not register duplicate names.
    op.create_index(INDEX_NAME, "standalone_meter_readings",
                    ["meter_id", sa.text("reading_date DESC"), sa.text(f"id COLLATE {collation} DESC")])


def downgrade():
    op.drop_index(INDEX_NAME, table_name="standalone_meter_readings")
