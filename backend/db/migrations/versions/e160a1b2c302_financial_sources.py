"""Canonical receivable settlement edges, service periods, saved definitions.

Revision ID: e160a1b2c302
Revises: d73f2b9a041c
No old amount/status/document bytes are rewritten; unknown legacy partials remain evidence.
"""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c302"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _table(name, *columns):
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(name):
        expected = {c.name for c in columns if isinstance(c, sa.Column)}
        existing = {c["name"] for c in inspector.get_columns(name)}
        if not expected.issubset(existing):
            raise RuntimeError("Unvollständige Finanztabelle: " + name)
        return
    op.create_table(name, *columns)


def _index(name, table, columns):
    existing = {i["name"]: i for i in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in existing:
        if existing[name]["column_names"] != columns:
            raise RuntimeError("Abweichender Finanzindex: " + name)
        return
    op.create_index(name, table, columns)


def upgrade():
    columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("invoices")}
    for name in ("performance_start", "performance_end"):
        if name not in columns:
            op.add_column("invoices", sa.Column(name, sa.Date(), nullable=True))
        elif not isinstance(columns[name]["type"], sa.Date):
            raise RuntimeError("Abweichender Datentyp: invoices." + name)
    _table("receivable_settlements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("receivable_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("booking_id", sa.String(), sa.ForeignKey("bookings.id", ondelete="RESTRICT")),
        sa.Column("credit_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="RESTRICT")),
        sa.Column("reverses_id", sa.String(64), sa.ForeignKey("receivable_settlements.id", ondelete="NO ACTION"), unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String()),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(amount > 0 AND reverses_id IS NULL) OR (amount < 0 AND reverses_id IS NOT NULL)", name="ck_settlement_direction"),
        sa.CheckConstraint("(booking_id IS NULL) <> (credit_id IS NULL)", name="ck_settlement_one_source"))
    _index("ix_receivable_settlement_claim", "receivable_settlements", ["receivable_id", "effective_date"])
    _index("ix_receivable_settlement_booking", "receivable_settlements", ["booking_id"])
    _index("ix_receivable_settlement_credit", "receivable_settlements", ["credit_id"])
    _table("saved_finance_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _index("ix_saved_finance_owner", "saved_finance_reports", ["owner_id", "created_at", "id"])


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    names = require_empty(connection, ('receivable_settlements', 'saved_finance_reports'),
                          'Finanznachweise werden nicht gelöscht. Gesicherten Programm-/Datenstand wiederherstellen.')
    if connection.exec_driver_sql('SELECT 1 FROM invoices WHERE performance_start IS NOT NULL OR performance_end IS NOT NULL LIMIT 1').first():
        raise RuntimeError('Erfasste Leistungszeiträume bleiben erhalten. Vollbackup wiederherstellen.')
    for name in names:
        op.drop_table(name)
    for name in ('performance_end', 'performance_start'):
        op.drop_column('invoices', name)
