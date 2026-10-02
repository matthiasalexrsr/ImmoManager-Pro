"""Additive legacy read compatibility; invoice receipt checks need an offline migration."""
from sqlalchemy import inspect


def ensure_invoice_payment_columns(connection):
    inspector = inspect(connection)
    if connection.dialect.name != "sqlite":
        return
    if inspector.has_table("invoices"):
        fields = {column["name"] for column in inspector.get_columns("invoices")}
        if {"id", "status", "gross_amount"} <= fields and "amount_paid" not in fields:
            connection.exec_driver_sql("ALTER TABLE invoices ADD COLUMN amount_paid NUMERIC(12,2) NOT NULL DEFAULT 0")
            connection.exec_driver_sql("UPDATE invoices SET amount_paid=gross_amount WHERE status='paid' AND gross_amount>0")
    if inspector.has_table("payments") and inspector.has_table("invoices"):
        fields = {column["name"] for column in inspector.get_columns("payments")}
        if {"id", "receivable_id", "rent_charge_id"} <= fields and "invoice_id" not in fields:
            connection.exec_driver_sql("ALTER TABLE payments ADD COLUMN invoice_id VARCHAR REFERENCES invoices(id) ON DELETE RESTRICT")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id)")


def require_invoice_payment_schema(connection):
    checks = inspect(connection).get_check_constraints("payments")
    if any(check.get("name") == "ck_payments_one_target" and "invoice_id" in check.get("sqltext", "") for check in checks):
        from .credit_schema import require_negative_allocation_schema
        require_negative_allocation_schema(connection)
        return
    from .payments import FinancialConsistencyError
    raise FinancialConsistencyError("Die Rechnungszahlungsstruktur benötigt das Offline-Upgrade. Anwendung und andere Schreiber stoppen und Dateien/Konfiguration separat sichern. Für unversionierte lokale SQLite-Bestände: python -m backend.invoice_schema_upgrade --database <Datenbank> --backup-output <neue-PREVIOUS-Datei> --offline. Versionierte Datenbanken über den regulären Alembic-Migrationsweg aktualisieren; keine Version raten. Die gespeicherte Bankbuchung bleibt erhalten.")


def ensure_invoice_payment_immutability(connection):
    """Protect invoice receipts against SQL updates, allowing explicit atomic restore."""
    inspector = inspect(connection)
    if not inspector.has_table("payments") or "invoice_id" not in {c["name"] for c in inspector.get_columns("payments")}:
        return
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS preserve_invoice_payment_update
            BEFORE UPDATE ON payments WHEN OLD.invoice_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'Invoice payment history is immutable'); END""")
        if inspector.has_table("payment_reversals"):
            connection.exec_driver_sql("""CREATE TRIGGER IF NOT EXISTS preserve_invoice_reversal_update
                BEFORE UPDATE ON payment_reversals WHEN EXISTS
                (SELECT 1 FROM payments WHERE id=OLD.payment_id AND invoice_id IS NOT NULL)
                BEGIN SELECT RAISE(ABORT, 'Invoice reversal history is immutable'); END""")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_guard_invoice_payment_update()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_TABLE_NAME = 'payments' THEN
                IF OLD.invoice_id IS NOT NULL THEN RAISE EXCEPTION 'Invoice payment history is immutable'; END IF;
            ELSE
                IF EXISTS (SELECT 1 FROM payments WHERE id=OLD.payment_id AND invoice_id IS NOT NULL)
                THEN RAISE EXCEPTION 'Invoice reversal history is immutable'; END IF;
            END IF;
            RETURN NEW; END; $$""")
        for table, trigger in (("payments", "preserve_invoice_payment_update"), ("payment_reversals", "preserve_invoice_reversal_update")):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION immo_guard_invoice_payment_update()")
