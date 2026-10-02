"""Retain actual SQLite FK actions and explicit indexes during offline batch DDL.

SQLAlchemy reflection can miss an ALTER-added inline FK action, descending index
keys and expression indexes. Read these from SQLite itself; no row is read or
changed here. The caller's offline transaction owns publication and rollback.
"""

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import ForeignKeyConstraint, MetaData, Table
from sqlalchemy.engine import Connection, RowMapping


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _reflected_table(connection: Connection, name: str,
                     naming_convention: dict[str, str] | None) -> Table:
    table = Table(name, MetaData(naming_convention=naming_convention), autoload_with=connection)
    groups: dict[int, list[RowMapping]] = defaultdict(list)
    for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({_quoted(name)})"):
        groups[row.id].append(row._mapping)
    for rows in groups.values():
        ordered = sorted(rows, key=lambda row: row["seq"])
        local = tuple(row["from"] for row in ordered)
        references = tuple((row["table"], row["to"]) for row in ordered)
        constraints = [constraint for constraint in table.foreign_key_constraints
            if tuple(constraint.columns.keys()) == local
            and tuple((element.column.table.name, element.column.name)
                      for element in constraint.elements) == references]
        if len(constraints) != 1 or any((row["on_update"], row["on_delete"])
                != (ordered[0]["on_update"], ordered[0]["on_delete"]) for row in ordered):
            raise RuntimeError("SQLite relationship reflection is incomplete; offline schema review required.")
        constraint: ForeignKeyConstraint = constraints[0]
        constraint.onupdate = ordered[0]["on_update"]
        constraint.ondelete = ordered[0]["on_delete"]
        for element in constraint.elements:
            element.onupdate = constraint.onupdate
            element.ondelete = constraint.ondelete
    return table


@contextmanager
def retained_sqlite_batch(connection: Connection, table_name: str, *,
                          naming_convention: dict[str, str] | None = None) -> Iterator[Table | None]:
    if connection.dialect.name != "sqlite":
        yield None
        return
    indexes = list(connection.exec_driver_sql(
        "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table_name,)))
    yield _reflected_table(connection, table_name, naming_convention)
    # Explicit SQLite CREATE INDEX statements retain key directions, collations,
    # predicates, expression keys and uniqueness. Automatic constraint indexes
    # belong to the reflected table's unchanged PK/UNIQUE constraints instead.
    for name, sql in indexes:
        current = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).scalar()
        if current != sql:
            connection.exec_driver_sql(f"DROP INDEX IF EXISTS {_quoted(name)}")
            connection.exec_driver_sql(sql)
