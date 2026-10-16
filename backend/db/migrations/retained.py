"""Downgrade preflight: refuse retained data before removing empty feature tables."""

from sqlalchemy import inspect


def require_empty(connection, names: tuple[str, ...], message: str) -> list[str]:
    tables = [name for name in names if inspect(connection).has_table(name)]
    if connection.dialect.name == 'postgresql' and tables:
        # Exclude a concurrent insertion between the emptiness check and DDL.
        connection.exec_driver_sql('LOCK TABLE ' + ', '.join('"' + name + '"' for name in sorted(tables))
                                   + ' IN ACCESS EXCLUSIVE MODE')
    elif connection.dialect.name == 'sqlite':
        driver = connection.connection.driver_connection
        if driver is not None and not driver.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
    if any(connection.exec_driver_sql('SELECT 1 FROM "' + name + '" LIMIT 1').first() for name in tables):
        raise RuntimeError(message)
    return tables
