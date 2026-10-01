"""Additive schema support for formerly unstamped local SQLite databases."""

from sqlalchemy import inspect, text


def ensure_account_encryption_schema(connection):
    columns = {column["name"] for column in inspect(connection).get_columns("accounts")}
    if "iban_fingerprint" not in columns:
        connection.execute(text("ALTER TABLE accounts ADD COLUMN iban_fingerprint VARCHAR(64)"))
    connection.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_iban_fingerprint ON accounts (iban_fingerprint)")
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_accounts_iban_unindexed ON accounts (iban_fingerprint, iban) "
            "WHERE iban IS NOT NULL AND iban != '' AND iban_fingerprint IS NULL"
        )
    )


def lock_account_writes(connection):
    """Arbitrate migration and account CRUD at the database, across processes."""
    if connection.dialect.name == "postgresql":
        connection.execute(text("LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE"))
    elif connection.dialect.name == "sqlite":
        # SQLAlchemy's implicit BEGIN following a SELECT is not necessarily an
        # actual SQLite transaction. Acquire the writer lock before reading.
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        from .iban_encryption import IBANEncryptionError

        raise IBANEncryptionError("ENCRYPTION_DATABASE_UNSUPPORTED")


def guard_account_write(connection, ring):
    from .iban_encryption import IBANEncryptionError

    lock_account_writes(connection)
    if connection.execute(
        text("SELECT 1 FROM accounts WHERE iban IS NOT NULL AND iban != '' AND iban_fingerprint IS NULL LIMIT 1")
    ).first():
        raise IBANEncryptionError("ENCRYPTION_MIGRATION_REQUIRED")
    evidence = connection.execute(
        text("SELECT iban, iban_fingerprint FROM accounts WHERE iban_fingerprint IS NOT NULL LIMIT 1")
    ).first()
    if evidence and ring.fingerprint(evidence[0]) != evidence[1]:
        raise IBANEncryptionError("ENCRYPTION_INDEX_KEY_MISMATCH")
