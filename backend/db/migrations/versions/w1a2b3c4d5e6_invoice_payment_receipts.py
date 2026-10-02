"""Extend the single receipt ledger to reviewed outgoing invoice payments.

Revision ID: w1a2b3c4d5e6
Revises: v1a2b3c4d5e6
"""
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from backend.db.sqlite_table_preservation import retained_sqlite_batch

revision = "w1a2b3c4d5e6"
down_revision = "v1a2b3c4d5e6"
branch_labels = None
depends_on = None

ONE_TARGET = """(CASE WHEN receivable_id IS NULL THEN 0 ELSE 1 END) +
(CASE WHEN rent_charge_id IS NULL THEN 0 ELSE 1 END) +
(CASE WHEN invoice_id IS NULL THEN 0 ELSE 1 END) = 1"""


@contextmanager
def _retained_sqlite_triggers(connection):
    # SQLite validates triggers on other tables during a batch table rename.
    # Temporarily hold their exact definitions in this offline DDL transaction,
    # then restore them unchanged; normal application writes never disable them.
    retained = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL").all() if connection.dialect.name == "sqlite" else []
    for name, _ in retained:
        quoted = '"' + name.replace('"', '""') + '"'
        connection.exec_driver_sql(f"DROP TRIGGER {quoted}")
    yield
    for _, sql in retained:
        connection.exec_driver_sql(sql)


def upgrade():
    connection = op.get_bind()
    invoice_fields = {column["name"] for column in sa.inspect(connection).get_columns("invoices")}
    payment_fields = {column["name"] for column in sa.inspect(connection).get_columns("payments")}
    with _retained_sqlite_triggers(connection):
        if "amount_paid" not in invoice_fields:
            op.add_column("invoices", sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False, server_default="0"))
            # Preserve explicit historical paid states without inventing bank receipts
            # or activating independent legacy business triggers during backfill.
            op.execute("UPDATE invoices SET amount_paid=gross_amount WHERE status='paid' AND gross_amount>0")
        with (
            retained_sqlite_batch(connection, "payments", naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
            }) as original_table,
            op.batch_alter_table("payments", copy_from=original_table, naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
            }) as batch,
        ):
            if "invoice_id" not in payment_fields:
                batch.add_column(sa.Column("invoice_id", sa.String(), nullable=True))
                batch.create_foreign_key("fk_payments_invoice_id_invoices", "invoices", ["invoice_id"], ["id"], ondelete="RESTRICT")
            else:
                # Additive SQLite read compatibility used an inline REFERENCES
                # clause. Reflection can omit its ON DELETE RESTRICT option;
                # retain the receipt link explicitly during table rebuilding.
                invoice_fk = next((fk for fk in sa.inspect(connection).get_foreign_keys("payments")
                                   if fk["constrained_columns"] == ["invoice_id"]), None)
                name = "fk_payments_invoice_id_invoices"
                options = {}
                if invoice_fk:
                    if invoice_fk["referred_table"] != "invoices" or invoice_fk["referred_columns"] != ["id"]:
                        raise RuntimeError("Unknown invoice receipt relationship; offline schema review required.")
                    name = invoice_fk["name"] or name
                    options = {key: value for key, value in invoice_fk.get("options", {}).items() if key != "ondelete"}
                    batch.drop_constraint(name, type_="foreignkey")
                batch.create_foreign_key(name, "invoices", ["invoice_id"], ["id"], ondelete="RESTRICT", **options)
            batch.drop_constraint("ck_payments_one_target", type_="check")
            batch.create_check_constraint("ck_payments_one_target", ONE_TARGET)
            if "idx_payments_invoice" not in {index["name"] for index in sa.inspect(connection).get_indexes("payments")}:
                batch.create_index("idx_payments_invoice", ["invoice_id"])
    from backend.services.invoice_payment_schema import ensure_invoice_payment_immutability
    ensure_invoice_payment_immutability(connection)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM payments WHERE invoice_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Invoice payment history exists; downgrade refused. Preserve a verified full recovery archive.")
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS preserve_invoice_payment_update")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS preserve_invoice_reversal_update")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS preserve_invoice_payment_update ON payments")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS preserve_invoice_reversal_update ON payment_reversals")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_guard_invoice_payment_update()")
    with _retained_sqlite_triggers(connection):
        with op.batch_alter_table("payments", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}) as batch:
            batch.drop_index("idx_payments_invoice")
            # Additive SQLite compatibility creates an unnamed FK. Alembic's
            # reflected naming convention gives it the same explicit name.
            batch.drop_constraint("fk_payments_invoice_id_invoices", type_="foreignkey")
            batch.drop_constraint("ck_payments_one_target", type_="check")
            batch.drop_column("invoice_id")
            batch.create_check_constraint("ck_payments_one_target", "(receivable_id IS NULL) != (rent_charge_id IS NULL)")
    op.drop_column("invoices", "amount_paid")
