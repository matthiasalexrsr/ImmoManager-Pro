"""Add structured invoice originals and separate validation evidence.

Revision ID: f2a4c6e8b0d3
Revises: e1a3c5e7f9b2
"""
import sqlalchemy as sa
from alembic import op

revision = "f2a4c6e8b0d3"
down_revision = "e1a3c5e7f9b2"
branch_labels = None
depends_on = None
NAMES = ("e_invoice_intakes", "e_invoice_validations")


def tables():
    metadata = sa.MetaData()
    for name in ("properties", "invoices", "documents"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    intake = sa.Table(NAMES[0], metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("validation_actor_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False, index=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("original", sa.LargeBinary(), nullable=False),
        sa.Column("xml", sa.LargeBinary()),
        sa.Column("container", sa.String(8), nullable=False),
        sa.Column("format", sa.String(20)),
        sa.Column("reading", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, index=True),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("validation_number", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.String(), sa.ForeignKey("invoices.id", ondelete="RESTRICT"), unique=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
        sa.Column("accept_key", sa.String(100)),
        sa.Column("accept_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("created_by", "idempotency_key", name="uq_e_invoice_upload_key"))
    validation = sa.Table(NAMES[1], metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("intake_id", sa.String(36), sa.ForeignKey("e_invoice_intakes.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(30), nullable=False),
        sa.Column("engine_version", sa.String(80), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("intake_id", "number", name="uq_e_invoice_validation_run"))
    return intake, validation


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "rounding_amount" not in {c["name"] for c in inspector.get_columns("invoice_reviews")}:
        op.add_column("invoice_reviews", sa.Column("rounding_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial e-invoice schema; verify originals before upgrading")
    for table in tables():
        if existing:
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            if set(columns) != set(table.c.keys()) or any(
                    columns[c.name]["type"].compile(dialect=connection.dialect).upper() != c.type.compile(dialect=connection.dialect).upper()
                    or bool(columns[c.name]["nullable"]) != bool(c.nullable) for c in table.c):
                raise RuntimeError("E-invoice schema mismatch: " + table.name)
            indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
            if any(index.name not in indexes or indexes[index.name]["column_names"] != [c.name for c in index.columns]
                   for index in table.indexes):
                raise RuntimeError("E-invoice index mismatch: " + table.name)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    require_empty(op.get_bind(), NAMES, "Invoice originals and validation evidence must not be discarded; restore a verified pre-upgrade backup")
    if op.get_bind().execute(sa.text("SELECT 1 FROM invoice_reviews WHERE rounding_amount <> 0 LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard payable rounding; restore a verified pre-upgrade backup")
    for name in reversed(NAMES):
        op.drop_table(name)
    op.drop_column("invoice_reviews", "rounding_amount")
