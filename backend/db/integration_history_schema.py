"""Validate-only startup contract; only the migration creates this family."""

import sqlite3
from typing import Any, cast

from sqlalchemy import Table, UniqueConstraint, inspect

from ..services.integrations.history_types import HistoryError
from .integration_history_models import HISTORY_MODELS, TABLES


def ensure_history_schema(connection):
    if isinstance(connection, sqlite3.Connection):
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def columns(name):
            return {row[1] for row in connection.execute('PRAGMA table_info("' + name + '")')}

        def primary(name):
            return tuple(row[1] for row in sorted(connection.execute('PRAGMA table_info("' + name + '")'), key=lambda row: row[5]) if row[5])

        def uniques(name):
            result = set()
            for row in connection.execute('PRAGMA index_list("' + name + '")'):
                if row[2]:
                    result.add(tuple(item[2] for item in connection.execute('PRAGMA index_info("' + row[1] + '")')))
            return result

        def foreign(name):
            grouped: dict[int, list[Any]] = {}
            for row in connection.execute('PRAGMA foreign_key_list("' + name + '")'):
                grouped.setdefault(row[0], []).append(row)
            return {(tuple(row[3] for row in sorted(group, key=lambda row: row[1])), group[0][2],
                     tuple(row[4] for row in sorted(group, key=lambda row: row[1])), group[0][6].upper()) for group in grouped.values()}
    else:
        inspector = inspect(connection)
        names = set(inspector.get_table_names())
        def columns(name):
            return {row["name"] for row in inspector.get_columns(name)}

        def primary(name):
            return tuple(inspector.get_pk_constraint(name)["constrained_columns"])

        def uniques(name):
            return {tuple(row["column_names"]) for row in inspector.get_unique_constraints(name)}

        def foreign(name):
            return {(tuple(row["constrained_columns"]), row["referred_table"], tuple(row["referred_columns"]),
                     row.get("options", {}).get("ondelete", "NO ACTION").upper()) for row in inspector.get_foreign_keys(name)}
    if not names.intersection(TABLES):
        return False
    if not set(TABLES).issubset(names):
        raise HistoryError("HISTORY_CORRUPT")
    for model in HISTORY_MODELS:
        table = cast(Table, model.__table__)
        expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}
        expected_fk = {(tuple(element.parent.name for element in item.elements), item.referred_table.name,
                        tuple(element.column.name for element in item.elements), (item.ondelete or "NO ACTION").upper()) for item in table.foreign_key_constraints}
        if (not set(table.columns.keys()).issubset(columns(model.__tablename__))
                or primary(model.__tablename__) != tuple(column.name for column in table.primary_key.columns)
                or not expected_unique.issubset(uniques(model.__tablename__))
                or foreign(model.__tablename__) != expected_fk):
            raise HistoryError("HISTORY_CORRUPT")
    return True


def install_history_guards(connection):
    """Immutable values; explicit telemetry clear is the only service delete."""
    immutable = TABLES[1:]
    if connection.dialect.name == "sqlite":
        for table in immutable:
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS preserve_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'integration history is immutable'); END")
        connection.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS preserve_integration_history_clears_delete BEFORE DELETE ON integration_history_clears BEGIN SELECT RAISE(ABORT,'history clear audit is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE OR REPLACE FUNCTION immo_history_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'integration history is immutable'; END; $$ LANGUAGE plpgsql")
        for table in immutable:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS preserve_{table}_update ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER preserve_{table}_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION immo_history_immutable()")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS preserve_integration_history_clears_delete ON integration_history_clears")
        connection.exec_driver_sql("CREATE TRIGGER preserve_integration_history_clears_delete BEFORE DELETE ON integration_history_clears FOR EACH ROW EXECUTE FUNCTION immo_history_immutable()")
